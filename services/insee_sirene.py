"""Client HTTP pour l'API SIRENE INSEE v3.11."""

from __future__ import annotations

import logging
import os
import re
import time
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import requests
from dotenv import load_dotenv

API_BASE_URL = "https://api.insee.fr/api-sirene/3.11"
API_KEY_ENV_VAR = "INSEE_API_KEY"
API_KEY_HEADER = "X-INSEE-Api-Key-Integration"
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_RETRY_ATTEMPTS = 6
DEFAULT_RETRY_DELAY_SECONDS = 2.0
DEFAULT_MAX_RETRY_DELAY_SECONDS = 120.0
DEFAULT_PAGE_SIZE = 1000
DEFAULT_PAGE_DELAY_SECONDS = 1.0

BORDEAUX_METROPOLE_POSTAL_CODES = (
    "33000",
    "33100",
    "33110",
    "33127",
    "33130",
    "33140",
    "33150",
    "33160",
    "33170",
    "33185",
    "33200",
    "33270",
    "33290",
    "33300",
    "33310",
    "33320",
    "33360",
    "33370",
    "33400",
    "33440",
    "33520",
    "33530",
    "33560",
    "33600",
    "33700",
    "33800",
    "33810",
    "33950",
)
TARGET_NAF_CODES = ("8121Z", "8129B", "8130Z", "8810A", "8810B")

logger = logging.getLogger(__name__)


class MissingInseeApiKeyError(RuntimeError):
    """Erreur levée quand la clé API INSEE est absente."""


class InseeSireneApiError(RuntimeError):
    """Erreur levée quand l'API SIRENE INSEE retourne une réponse HTTP en erreur."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class InseeSireneRequestError(RuntimeError):
    """Erreur levée quand la requête HTTP vers l'API SIRENE échoue."""


HTTP_ERROR_MESSAGES = {
    400: "Requête SIRENE INSEE invalide.",
    401: "Authentification SIRENE INSEE refusée.",
    403: "Accès SIRENE INSEE interdit.",
    404: "Ressource SIRENE INSEE introuvable.",
    429: "Limite de requêtes SIRENE INSEE atteinte.",
    500: "Erreur interne de l'API SIRENE INSEE.",
    503: "API SIRENE INSEE indisponible.",
}


def validate_siren(siren: str) -> None:
    if not re.fullmatch(r"\d{9}", siren):
        raise ValueError("siren doit contenir exactement 9 chiffres.")


def validate_siret(siret: str) -> None:
    if not re.fullmatch(r"\d{14}", siret):
        raise ValueError("siret doit contenir exactement 14 chiffres.")


class InseeSireneClient:
    """Client minimal pour consulter les unités légales et établissements SIRENE."""

    def __init__(
        self,
        session: requests.Session | None = None,
        base_url: str = API_BASE_URL,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
        retry_attempts: int = DEFAULT_RETRY_ATTEMPTS,
        retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
        max_retry_delay_seconds: float = DEFAULT_MAX_RETRY_DELAY_SECONDS,
    ) -> None:
        self.session = session or requests.Session()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retry_attempts = retry_attempts
        self.retry_delay_seconds = retry_delay_seconds
        self.max_retry_delay_seconds = max_retry_delay_seconds
        self._api_key: str | None = None

    def get_siren(self, siren: str) -> dict[str, Any]:
        """Retourne les informations SIRENE d'une unité légale."""
        validate_siren(siren)
        return self._get(f"/siren/{siren}")

    def get_siret(self, siret: str) -> dict[str, Any]:
        """Retourne les informations SIRENE d'un établissement."""
        validate_siret(siret)
        return self._get(f"/siret/{siret}")

    def search_etablissements(
        self,
        limit: int | None = None,
        postal_codes: Sequence[str] = BORDEAUX_METROPOLE_POSTAL_CODES,
        naf_codes: Sequence[str] = TARGET_NAF_CODES,
        active: bool = True,
        head_offices: bool = True,
        page_size: int = DEFAULT_PAGE_SIZE,
        page_delay_seconds: float = DEFAULT_PAGE_DELAY_SECONDS,
    ) -> list[dict[str, Any]]:
        """Recherche les établissements bruts correspondant aux filtres ciblés."""
        if limit is not None and limit < 0:
            raise ValueError("limit doit être positif ou None.")
        if limit == 0:
            return []
        if page_size <= 0 or page_size > DEFAULT_PAGE_SIZE:
            raise ValueError(
                f"page_size doit être compris entre 1 et {DEFAULT_PAGE_SIZE}."
            )

        query = build_etablissements_query(
            postal_codes=postal_codes,
            naf_codes=naf_codes,
            active=active,
            head_offices=head_offices,
        )
        etablissements: list[dict[str, Any]] = []
        cursor = "*"

        while True:
            remaining = None if limit is None else limit - len(etablissements)
            if remaining is not None and remaining <= 0:
                return etablissements

            params = {
                "q": query,
                "nombre": min(page_size, remaining)
                if remaining is not None
                else page_size,
                "curseur": cursor,
            }
            payload = self._get("/siret", params=params)
            page = payload.get("etablissements") or []
            if not isinstance(page, list):
                message = (
                    "Réponse JSON SIRENE INSEE invalide: liste etablissements attendue."
                )
                raise InseeSireneApiError(
                    200,
                    message,
                )

            etablissements.extend(
                etablissement
                for etablissement in page
                if isinstance(etablissement, dict)
            )
            if limit is not None and len(etablissements) >= limit:
                return etablissements[:limit]

            header = payload.get("header") or {}
            next_cursor = (
                header.get("curseurSuivant") if isinstance(header, dict) else None
            )
            if not page or not next_cursor or next_cursor == cursor:
                return etablissements[:limit] if limit is not None else etablissements

            cursor = str(next_cursor)
            if page_delay_seconds > 0:
                time.sleep(page_delay_seconds)

    def _get(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        headers = {API_KEY_HEADER: self._get_api_key()}
        attempts = max(1, self.retry_attempts)
        request_kwargs: dict[str, Any] = {
            "headers": headers,
            "timeout": self.timeout,
        }
        if params is not None:
            request_kwargs["params"] = dict(params)

        for attempt in range(1, attempts + 1):
            try:
                response = self.session.get(url, **request_kwargs)
            except requests.RequestException as exc:
                raise InseeSireneRequestError(
                    f"Requête SIRENE INSEE impossible pour GET {url}: {exc}"
                ) from exc

            if response.status_code != 429 or attempt >= attempts:
                self._raise_for_http_error(response, "GET", url)
                return self._json_payload(response)

            delay = self._retry_delay_seconds(response, attempt)
            logger.warning(
                "Réponse SIRENE INSEE 429 pour GET %s, retry %s/%s dans %.2fs.",
                url,
                attempt + 1,
                attempts,
                delay,
            )
            time.sleep(delay)

        raise InseeSireneRequestError(f"Requête SIRENE INSEE inachevée pour GET {url}.")

    def _retry_delay_seconds(
        self,
        response: requests.Response,
        attempt: int,
    ) -> float:
        headers = getattr(response, "headers", {}) or {}
        retry_after_header = (
            headers.get("Retry-After") if isinstance(headers, Mapping) else None
        )
        retry_after = _parse_retry_after(retry_after_header)
        if retry_after is not None:
            return min(retry_after, self.max_retry_delay_seconds)

        delay = self.retry_delay_seconds * (2 ** (attempt - 1))
        return min(delay, self.max_retry_delay_seconds)

    def _get_api_key(self) -> str:
        if self._api_key is not None:
            return self._api_key

        load_dotenv()
        api_key = os.getenv(API_KEY_ENV_VAR)
        if not api_key:
            raise MissingInseeApiKeyError(
                f"Variable d'environnement {API_KEY_ENV_VAR} requise."
            )

        self._api_key = api_key
        return self._api_key

    def _raise_for_http_error(
        self,
        response: requests.Response,
        method: str,
        url: str,
    ) -> None:
        if response.status_code < 400:
            return

        detail = HTTP_ERROR_MESSAGES.get(
            response.status_code,
            f"Erreur HTTP SIRENE INSEE {response.status_code}.",
        )
        message = f"{detail} Méthode: {method}. URL: {url}."
        logger.error(
            "Erreur SIRENE INSEE HTTP %s pour %s %s.",
            response.status_code,
            method,
            url,
        )
        raise InseeSireneApiError(response.status_code, message)

    def _json_payload(self, response: requests.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise InseeSireneApiError(
                response.status_code,
                "Réponse JSON SIRENE INSEE invalide.",
            ) from exc

        if not isinstance(payload, dict):
            raise InseeSireneApiError(
                response.status_code,
                "Réponse JSON SIRENE INSEE invalide: objet attendu.",
            )
        return payload


def build_etablissements_query(
    postal_codes: Sequence[str],
    naf_codes: Sequence[str],
    active: bool = True,
    head_offices: bool = True,
) -> str:
    """Construit la requête multicritères SIRENE pour les établissements ciblés."""
    clauses: list[str] = []
    if head_offices:
        clauses.append("etablissementSiege:true")

    clauses.append(_or_clause("codePostalEtablissement", postal_codes))
    periode_clauses: list[str] = []
    if active:
        clauses.append("etatAdministratifUniteLegale:A")
        periode_clauses.append("etatAdministratifEtablissement:A")
    periode_clauses.append(
        _or_clause(
            "activitePrincipaleEtablissement",
            [format_sirene_naf_code(code) for code in naf_codes],
        )
    )
    clauses.append(f"periode({' AND '.join(periode_clauses)})")
    return " AND ".join(clauses)


def _or_clause(field_name: str, values: Sequence[str]) -> str:
    cleaned_values = [value.strip() for value in values if value.strip()]
    if not cleaned_values:
        raise ValueError(f"Au moins une valeur est requise pour {field_name}.")
    if len(cleaned_values) == 1:
        return f"{field_name}:{cleaned_values[0]}"
    return "(" + " OR ".join(f"{field_name}:{value}" for value in cleaned_values) + ")"


def format_sirene_naf_code(naf_code: str) -> str:
    """Convertit un code NAF métier `8121Z` vers le format SIRENE `81.21Z`."""
    cleaned_code = naf_code.strip().upper().replace(".", "")
    if len(cleaned_code) == 5:
        return f"{cleaned_code[:2]}.{cleaned_code[2:]}"
    return naf_code.strip().upper()


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None

    cleaned_value = value.strip()
    if cleaned_value.isdigit():
        return float(cleaned_value)

    try:
        retry_at = parsedate_to_datetime(cleaned_value)
    except (TypeError, ValueError):
        return None

    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    delay = (retry_at - datetime.now(timezone.utc)).total_seconds()
    return max(0.0, delay)
