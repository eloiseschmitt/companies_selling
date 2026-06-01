"""Service de connexion au SFTP INPI."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import paramiko


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = BASE_DIR / ".env"
REQUIRED_ENV_VARS = ("SFTP_HOST", "SFTP_USER", "SFTP_PASSWORD")

logger = logging.getLogger(__name__)


class MissingSFTPCredentialsError(RuntimeError):
    """Erreur levée quand la configuration SFTP est incomplète."""


def load_env_file(env_file: Path = DEFAULT_ENV_FILE) -> None:
    """Charge les variables d'un fichier .env sans écraser l'environnement."""
    if not env_file.exists():
        return

    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key:
            os.environ.setdefault(key, value)


def get_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise MissingSFTPCredentialsError(
            f"Variable d'environnement SFTP manquante: {name}"
        )
    return value


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
        return cls(
            host=get_required_env("SFTP_HOST"),
            username=get_required_env("SFTP_USER"),
            password=get_required_env("SFTP_PASSWORD"),
        )

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
