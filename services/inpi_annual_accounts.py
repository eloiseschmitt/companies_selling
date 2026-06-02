"""Client HTTP pour l'API INPI des comptes annuels."""

from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv


LOGIN_URL = "https://registre-national-entreprises.inpi.fr/api/sso/login"
API_BASE_URL = "https://registre-national-entreprises.inpi.fr/api"
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_RETRY_ATTEMPTS = 3
DEFAULT_BACKOFF_SECONDS = 0.5
RETRYABLE_STATUS_CODES = {429, 500}

logger = logging.getLogger(__name__)


class MissingInpiCredentialsError(RuntimeError):
    """Erreur levée quand les identifiants INPI sont absents."""


class InpiApiError(RuntimeError):
    """Erreur levée quand l'API INPI retourne une réponse HTTP en erreur."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class InpiAuthenticationError(RuntimeError):
    """Erreur levée quand l'authentification INPI échoue."""


class InpiDownloadError(RuntimeError):
    """Erreur levée quand le fichier téléchargé depuis l'INPI est invalide."""


HTTP_ERROR_MESSAGES = {
    400: "Requête INPI invalide.",
    401: "Authentification INPI refusée.",
    403: "Accès INPI interdit.",
    429: "Limite de requêtes INPI atteinte.",
    500: "Erreur interne de l'API INPI.",
}


def validate_siren(siren: str) -> None:
    if not re.fullmatch(r"\d{9}", siren):
        raise ValueError("siren doit contenir exactement 9 chiffres.")


def select_best_bilan_pdf(
    attachments: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    """Sélectionne le meilleur bilan public disponible dans la réponse INPI."""
    bilans = attachments.get("bilans") or []
    if not bilans:
        return None, "no_bilan"

    active_bilans = [
        bilan
        for bilan in bilans
        if isinstance(bilan, dict) and not bilan.get("deleted")
    ]
    if not active_bilans:
        return None, "only_deleted"

    public_bilans = [
        bilan
        for bilan in active_bilans
        if bilan.get("confidentiality") == "Public"
    ]
    if not public_bilans:
        return None, "only_confidential"

    return max(public_bilans, key=_bilan_sort_date), None


def _bilan_sort_date(bilan: dict[str, Any]) -> str:
    return str(bilan.get("dateCloture") or bilan.get("dateDepot") or "")


class InpiAnnualAccountsClient:
    """Client minimal pour consulter les pièces jointes d'une entreprise INPI."""

    def __init__(
        self,
        session: requests.Session | None = None,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
        retry_attempts: int = DEFAULT_RETRY_ATTEMPTS,
        backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
    ) -> None:
        self.session = session or requests.Session()
        self.timeout = timeout
        self.retry_attempts = retry_attempts
        self.backoff_seconds = backoff_seconds
        self.token: str | None = None

    def authenticate(self) -> str:
        """Authentifie le client et retourne le token INPI."""
        load_dotenv()
        username = os.getenv("SFTP_USER")
        password = os.getenv("SFTP_PASSWORD")
        if not username or not password:
            raise MissingInpiCredentialsError(
                "Variables d'environnement SFTP_USER et SFTP_PASSWORD requises."
            )

        response = self._request(
            "post",
            LOGIN_URL,
            json={"username": username, "password": password},
            authenticated=False,
        )
        self._raise_for_known_http_error(response)

        payload = self._json_payload(response)
        token = payload.get("token")
        if not token:
            raise InpiAuthenticationError("Token INPI absent de la réponse de login.")

        self.token = str(token)
        return self.token

    def get_company_attachments(self, siren: str) -> dict[str, Any] | list[Any]:
        """Retourne les pièces jointes INPI associées au SIREN."""
        validate_siren(siren)
        response = self._request(
            "get",
            f"{API_BASE_URL}/companies/{siren}/attachments",
        )
        self._raise_for_known_http_error(response)
        return self._json_payload(response)

    def download_bilan_pdf(self, bilan_id: str, output_path: Path) -> Path:
        """Télécharge un bilan PDF INPI vers le chemin local demandé."""
        response = self._request(
            "get",
            f"{API_BASE_URL}/bilans/{bilan_id}/download",
        )
        self._raise_for_known_http_error(response)

        content = response.content
        if not content:
            raise InpiDownloadError("Le bilan PDF INPI téléchargé est vide.")
        if not content.startswith(b"%PDF"):
            raise InpiDownloadError(
                "Le bilan INPI téléchargé n'est pas un PDF valide."
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(content)
        return output_path

    def _request(
        self,
        method: str,
        url: str,
        authenticated: bool = True,
        allow_reauth: bool = True,
        **kwargs,
    ) -> requests.Response:
        if authenticated and self.token is None:
            self.authenticate()

        request_kwargs = dict(kwargs)
        request_kwargs["timeout"] = self.timeout
        if authenticated:
            headers = dict(request_kwargs.get("headers") or {})
            headers["Authorization"] = f"Bearer {self.token}"
            request_kwargs["headers"] = headers

        attempts = max(1, self.retry_attempts)
        for attempt in range(1, attempts + 1):
            response = getattr(self.session, method)(url, **request_kwargs)
            if response.status_code == 401 and authenticated and allow_reauth:
                logger.warning(
                    "Authentification INPI expirée pour %s %s, nouvelle tentative.",
                    method.upper(),
                    url,
                )
                self.authenticate()
                return self._request(
                    method,
                    url,
                    authenticated=authenticated,
                    allow_reauth=False,
                    **kwargs,
                )

            should_retry = (
                response.status_code in RETRYABLE_STATUS_CODES
                and attempt < attempts
            )
            if not should_retry:
                return response

            delay = self.backoff_seconds * (2 ** (attempt - 1))
            logger.warning(
                "Réponse INPI %s pour %s %s, retry %s/%s dans %.2fs.",
                response.status_code,
                method.upper(),
                url,
                attempt + 1,
                attempts,
                delay,
            )
            time.sleep(delay)

        return response

    def _raise_for_known_http_error(self, response: requests.Response) -> None:
        if response.status_code < 400:
            return

        message = HTTP_ERROR_MESSAGES.get(
            response.status_code,
            f"Erreur HTTP INPI {response.status_code}.",
        )
        logger.error("%s Statut HTTP: %s", message, response.status_code)
        raise InpiApiError(response.status_code, message)

    def _json_payload(self, response: requests.Response) -> dict[str, Any] | list[Any]:
        try:
            return response.json()
        except ValueError as exc:
            raise InpiApiError(
                response.status_code,
                "Réponse JSON INPI invalide.",
            ) from exc
