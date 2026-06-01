"""Service de connexion au SFTP INPI."""

from __future__ import annotations

import argparse
import logging
import os
import posixpath
import re
from dataclasses import dataclass
from pathlib import Path
from stat import S_ISDIR

import paramiko
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = BASE_DIR / ".env"
REQUIRED_ENV_VARS = ("SFTP_HOST", "SFTP_USER", "SFTP_PASSWORD")
INPI_FINANCIAL_ROOT_DIR = "Bilans_PDF"

logger = logging.getLogger(__name__)


class MissingSFTPCredentialsError(RuntimeError):
    """Erreur levée quand la configuration SFTP est incomplète."""


@dataclass
class FinancialPdfSearchResult:
    selected_path: str | None
    years_inspected: list[str]
    candidates_found: int


def load_env_file(env_file: Path = DEFAULT_ENV_FILE) -> None:
    """Charge les variables d'un fichier .env sans écraser l'environnement."""
    load_dotenv(env_file)


def get_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        logger.error("Variable d'environnement SFTP manquante: %s", name)
        raise MissingSFTPCredentialsError(
            f"Variable d'environnement SFTP manquante: {name}"
        )
    return value


def get_sftp_port() -> int:
    raw_port = os.getenv("SFTP_PORT")
    if not raw_port:
        return 22

    try:
        return int(raw_port)
    except ValueError as exc:
        raise MissingSFTPCredentialsError(
            "Variable d'environnement SFTP invalide: SFTP_PORT"
        ) from exc


class InpiSFTPClient:
    """Client SFTP minimal pour lister les fichiers disponibles sur l'INPI."""

    def __init__(self, host: str, username: str, password: str, port: int = 22):
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self._transport: paramiko.Transport | None = None
        self._sftp: paramiko.SFTPClient | None = None

    @classmethod
    def from_environment(cls) -> InpiSFTPClient:
        load_env_file()
        client = cls(
            host=get_required_env("SFTP_HOST"),
            username=get_required_env("SFTP_USER"),
            password=get_required_env("SFTP_PASSWORD"),
            port=get_sftp_port(),
        )
        logger.info(
            "Configuration SFTP INPI chargée: hôte=%s, port=%s, utilisateur=%s",
            client.host,
            client.port,
            client.username,
        )
        return client

    def connect(self) -> None:
        try:
            self._transport = paramiko.Transport((self.host, self.port))
            self._transport.connect(
                username=self.username,
                password=self.password,
            )
            self._sftp = paramiko.SFTPClient.from_transport(self._transport)
            logger.info(
                "Connexion SFTP INPI ouverte pour %s@%s",
                self.username,
                self.host,
            )
        except Exception:
            logger.exception(
                "Erreur lors de la connexion SFTP INPI pour %s@%s",
                self.username,
                self.host,
            )
            self.close()
            raise

    def list_files(self, remote_path: str = ".") -> list[str]:
        if self._sftp is None:
            raise RuntimeError("La connexion SFTP INPI n'est pas ouverte.")

        try:
            return self._sftp.listdir(remote_path)
        except Exception:
            logger.exception(
                "Erreur lors du listage SFTP INPI du dossier %s pour %s@%s",
                remote_path,
                self.username,
                self.host,
            )
            raise

    def list_entries(self, remote_path: str = ".") -> list[paramiko.SFTPAttributes]:
        if self._sftp is None:
            raise RuntimeError("La connexion SFTP INPI n'est pas ouverte.")

        try:
            return self._sftp.listdir_attr(remote_path)
        except Exception:
            logger.exception(
                "Erreur lors du listage SFTP INPI du dossier %s pour %s@%s",
                remote_path,
                self.username,
                self.host,
            )
            raise

    def read_text_file(
        self,
        remote_path: str,
        max_bytes: int = 10_000_000,
        encoding: str = "utf-8",
    ) -> str:
        if self._sftp is None:
            raise RuntimeError("La connexion SFTP INPI n'est pas ouverte.")

        try:
            with self._sftp.open(remote_path, "rb") as remote_file:
                content = remote_file.read(max_bytes + 1)
        except Exception:
            logger.exception(
                "Erreur lors de la lecture SFTP INPI du fichier %s pour %s@%s",
                remote_path,
                self.username,
                self.host,
            )
            raise

        if len(content) > max_bytes:
            raise ValueError(f"Fichier distant trop volumineux: {remote_path}")

        return content.decode(encoding, errors="replace")

    def read_binary_file(
        self,
        remote_path: str,
        max_bytes: int = 50_000_000,
    ) -> bytes:
        if self._sftp is None:
            raise RuntimeError("La connexion SFTP INPI n'est pas ouverte.")

        try:
            with self._sftp.open(remote_path, "rb") as remote_file:
                content = remote_file.read(max_bytes + 1)
        except Exception:
            logger.exception(
                "Erreur lors de la lecture SFTP INPI du fichier %s pour %s@%s",
                remote_path,
                self.username,
                self.host,
            )
            raise

        if len(content) > max_bytes:
            raise ValueError(f"Fichier distant trop volumineux: {remote_path}")

        return content

    def download_file(
        self,
        remote_path: str,
        local_path: Path,
        force: bool = False,
    ) -> Path:
        if self._sftp is None:
            raise RuntimeError("La connexion SFTP INPI n'est pas ouverte.")

        local_path.parent.mkdir(parents=True, exist_ok=True)
        if local_path.exists() and not force:
            logger.info("Fichier déjà présent localement: %s", local_path)
            return local_path

        try:
            self._sftp.get(remote_path, str(local_path))
        except Exception:
            logger.exception(
                "Erreur lors du téléchargement SFTP INPI du fichier %s pour %s@%s",
                remote_path,
                self.username,
                self.host,
            )
            raise

        return local_path

    def download_latest_financial_pdf_for_siren(
        self,
        siren: str,
        destination_dir: Path,
        force: bool = False,
    ) -> Path | None:
        """Télécharge le PDF financier INPI le plus récent pour un SIREN."""
        validate_siren(siren)
        logger.info(
            "Hôte SFTP utilisé: %s:%s, utilisateur=%s",
            self.host,
            self.port,
            self.username,
        )
        search_result = search_latest_financial_pdf_for_siren(self, siren)
        selected_path = search_result.selected_path
        logger.info("Années inspectées: %s", ", ".join(search_result.years_inspected))
        logger.info(
            "Nombre de fichiers candidats trouvés: %s",
            search_result.candidates_found,
        )
        if selected_path is None:
            logger.error("Aucun PDF de comptes annuels trouvé pour le SIREN %s.", siren)
            return None

        logger.info("Chemin distant sélectionné: %s", selected_path)
        local_path = destination_dir / posixpath.basename(selected_path)
        downloaded_path = self.download_file(selected_path, local_path, force=force)
        logger.info("Chemin local final: %s", downloaded_path)
        logger.info(
            "PDF financier INPI disponible pour le SIREN %s: %s",
            siren,
            downloaded_path,
        )
        return downloaded_path

    def close(self) -> None:
        if self._sftp is not None:
            self._sftp.close()
            self._sftp = None

        if self._transport is not None:
            self._transport.close()
            self._transport = None

    def __enter__(self) -> InpiSFTPClient:
        self.connect()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()


def list_available_files(remote_path: str = ".") -> list[str]:
    """Retourne les fichiers disponibles sur le SFTP INPI."""
    client = InpiSFTPClient.from_environment()
    with client:
        return client.list_files(remote_path)


def is_directory(entry: paramiko.SFTPAttributes) -> bool:
    """Retourne True si l'entrée SFTP est un dossier."""
    return entry.st_mode is not None and S_ISDIR(entry.st_mode)


def validate_siren(siren: str) -> None:
    if not re.fullmatch(r"\d{9}", siren):
        logger.error("SIREN invalide: %s", siren)
        raise ValueError("siren doit contenir exactement 9 chiffres.")


def parse_cli_siren(siren: str) -> str:
    try:
        validate_siren(siren)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return siren


def remote_join(parent: str, child: str) -> str:
    if parent in {"", "."}:
        return child
    return posixpath.join(parent, child)


def list_sorted_entries(
    client: InpiSFTPClient,
    remote_path: str,
) -> list[paramiko.SFTPAttributes]:
    return sorted(client.list_entries(remote_path), key=lambda entry: entry.filename)


def get_available_financial_years(client: InpiSFTPClient) -> list[str]:
    logger.info("Dossier racine consulté: %s", INPI_FINANCIAL_ROOT_DIR)
    entries = list_sorted_entries(client, INPI_FINANCIAL_ROOT_DIR)
    years = [
        entry.filename
        for entry in entries
        if is_directory(entry) and re.fullmatch(r"\d{4}", entry.filename)
    ]
    return sorted(years, reverse=True)


def parse_financial_pdf_filename(filename: str) -> dict[str, str] | None:
    match = re.match(
        r"^CA_(?P<siren>\d{9})_(?P<greffe>[^_]+)_(?P<gestion>[^_]+)_"
        r"(?P<closing_year>\d{4})_(?P<chrono>[^.]+)\.pdf$",
        filename,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    return match.groupdict()


def parse_financial_pdf_sort_key(filename: str) -> tuple[int, tuple]:
    parsed = parse_financial_pdf_filename(filename)
    if parsed is None:
        return 0, ()

    chrono_key = tuple(
        (1, int(part)) if part.isdigit() else (0, part)
        for part in re.split(r"(\d+)", parsed["chrono"])
        if part
    )
    return int(parsed["closing_year"]), chrono_key


def select_latest_financial_pdf_filename(filenames: list[str]) -> str | None:
    valid_filenames = [
        filename for filename in filenames if parse_financial_pdf_filename(filename)
    ]
    if not valid_filenames:
        return None
    return max(valid_filenames, key=parse_financial_pdf_sort_key)


def find_financial_pdf_candidates_in_year(
    client: InpiSFTPClient,
    year: str,
    siren: str,
) -> list[str]:
    candidates = []
    prefix = f"CA_{siren}_"
    stack = [remote_join(INPI_FINANCIAL_ROOT_DIR, year)]

    while stack:
        current_path = stack.pop(0)
        for entry in list_sorted_entries(client, current_path):
            entry_path = remote_join(current_path, entry.filename)
            if is_directory(entry):
                stack.append(entry_path)
                continue
            is_matching_pdf = (
                entry.filename.startswith(prefix)
                and posixpath.splitext(entry.filename.lower())[1] == ".pdf"
            )
            if is_matching_pdf:
                candidates.append(entry_path)

    return candidates


def find_latest_financial_pdf_path_for_siren(
    client: InpiSFTPClient,
    siren: str,
) -> str | None:
    return search_latest_financial_pdf_for_siren(client, siren).selected_path


def search_latest_financial_pdf_for_siren(
    client: InpiSFTPClient,
    siren: str,
) -> FinancialPdfSearchResult:
    validate_siren(siren)
    years_inspected = []
    candidates_found = 0
    for year in get_available_financial_years(client):
        years_inspected.append(year)
        candidates = find_financial_pdf_candidates_in_year(client, year, siren)
        candidates_found += len(candidates)
        logger.info(
            "Année inspectée: %s, fichiers candidats trouvés: %s",
            year,
            len(candidates),
        )
        if candidates:
            candidates_by_filename = {
                posixpath.basename(path): path for path in candidates
            }
            selected_filename = select_latest_financial_pdf_filename(
                list(candidates_by_filename)
            )
            if selected_filename is not None:
                return FinancialPdfSearchResult(
                    selected_path=candidates_by_filename[selected_filename],
                    years_inspected=years_inspected,
                    candidates_found=candidates_found,
                )
    return FinancialPdfSearchResult(
        selected_path=None,
        years_inspected=years_inspected,
        candidates_found=candidates_found,
    )


def download_latest_financial_pdf_for_siren(
    siren: str,
    destination_dir: Path,
    force: bool = False,
) -> Path | None:
    """Ouvre le SFTP INPI et télécharge le dernier PDF financier du SIREN."""
    client = InpiSFTPClient.from_environment()
    with client:
        return client.download_latest_financial_pdf_for_siren(
            siren,
            destination_dir,
            force=force,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Télécharge le dernier PDF de comptes annuels INPI d'un SIREN."
    )
    parser.add_argument(
        "--siren",
        required=True,
        type=parse_cli_siren,
        help="SIREN à 9 chiffres.",
    )
    parser.add_argument(
        "--destination",
        type=Path,
        default=Path("downloads"),
        help="Dossier local de destination. Par défaut: ./downloads.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Retélécharge le PDF même s'il existe déjà localement.",
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    args = parse_args()
    destination_dir = args.destination
    destination_dir.mkdir(parents=True, exist_ok=True)
    downloaded_path = download_latest_financial_pdf_for_siren(
        args.siren,
        destination_dir,
        force=args.force,
    )
    if downloaded_path is None:
        print(f"Aucun PDF de comptes annuels trouvé pour le SIREN {args.siren}.")
        return

    print(f"PDF téléchargé: {downloaded_path}")


if __name__ == "__main__":
    main()
