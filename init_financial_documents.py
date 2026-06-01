"""Crée la table financial_documents dans la base SQLite locale."""

import argparse
import logging
import posixpath
import re
import sqlite3

from services.inpi_sftp import InpiSFTPClient, is_directory


DATABASE_FILE = "companies.db"
INPI_ROOT_DIR = "Bilans_PDF"

logger = logging.getLogger(__name__)


def validate_siren(value: str) -> str:
    if not re.fullmatch(r"\d{9}", value):
        raise argparse.ArgumentTypeError(
            "--siren doit contenir exactement 9 chiffres."
        )
    return value


def remote_join(parent: str, child: str) -> str:
    return posixpath.join(parent, child)


def list_sorted_entries(client: InpiSFTPClient, remote_path: str):
    return sorted(client.list_entries(remote_path), key=lambda entry: entry.filename)


def get_available_years(client: InpiSFTPClient) -> list[str]:
    entries = list_sorted_entries(client, INPI_ROOT_DIR)
    years = [
        entry.filename
        for entry in entries
        if is_directory(entry) and re.fullmatch(r"\d{4}", entry.filename)
    ]
    return sorted(years, reverse=True)


def parse_ca_pdf_sort_key(filename: str, siren: str) -> tuple[int, tuple]:
    stem = filename.removesuffix(".pdf")
    parts = stem.split("_")
    if len(parts) < 6 or parts[0] != "CA" or parts[1] != siren:
        return 0, ()

    closing_digits = re.sub(r"\D", "", parts[4])
    closing_key = int(closing_digits) if closing_digits else 0
    chrono = "_".join(parts[5:])
    chrono_key = tuple(
        (1, int(part)) if part.isdigit() else (0, part)
        for part in re.split(r"(\d+)", chrono)
        if part
    )
    return closing_key, chrono_key


def find_ca_pdf_candidates_for_year(
    client: InpiSFTPClient,
    year: str,
    siren: str,
) -> list[str]:
    candidates = []
    prefix = f"CA_{siren}_"
    year_path = remote_join(INPI_ROOT_DIR, year)

    for month_entry in reversed(list_sorted_entries(client, year_path)):
        if not is_directory(month_entry):
            continue

        month_path = remote_join(year_path, month_entry.filename)
        for day_entry in reversed(list_sorted_entries(client, month_path)):
            if not is_directory(day_entry):
                continue

            day_path = remote_join(month_path, day_entry.filename)
            for document_entry in list_sorted_entries(client, day_path):
                document_path = remote_join(day_path, document_entry.filename)
                if not document_entry.filename.startswith(prefix):
                    continue

                if not is_directory(document_entry):
                    if document_entry.filename.endswith(".pdf"):
                        candidates.append(document_path)
                    continue

                for file_entry in list_sorted_entries(client, document_path):
                    is_matching_pdf = (
                        file_entry.filename.startswith(prefix)
                        and file_entry.filename.endswith(".pdf")
                    )
                    if is_matching_pdf:
                        candidates.append(
                            remote_join(document_path, file_entry.filename)
                        )

    return candidates


def select_latest_ca_pdf(paths: list[str], siren: str) -> str:
    return max(
        paths,
        key=lambda path: parse_ca_pdf_sort_key(posixpath.basename(path), siren),
    )


def find_latest_ca_pdf_for_siren(siren: str) -> str | None:
    with InpiSFTPClient.from_environment() as client:
        for year in get_available_years(client):
            logger.info(
                "Recherche des PDF CA_%s_ dans %s/%s",
                siren,
                INPI_ROOT_DIR,
                year,
            )
            candidates = find_ca_pdf_candidates_for_year(client, year, siren)
            if not candidates:
                continue

            selected_path = select_latest_ca_pdf(candidates, siren)
            logger.info("PDF INPI trouvé pour le SIREN %s: %s", siren, selected_path)
            return selected_path

    return None


def create_financial_documents_table(conn: sqlite3.Connection) -> None:
    """Crée la table et les index des documents financiers."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS financial_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            siren TEXT NOT NULL,
            siret TEXT,
            closing_date TEXT NOT NULL,
            filing_date TEXT,
            document_path TEXT NOT NULL,
            document_type TEXT,
            source TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            CONSTRAINT uq_financial_documents_siren_closing_date_document_path
                UNIQUE (siren, closing_date, document_path)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_financial_documents_siren
        ON financial_documents (siren)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_financial_documents_siret
        ON financial_documents (siret)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_financial_documents_closing_date
        ON financial_documents (closing_date)
        """
    )
    ensure_financial_documents_columns(conn)
    conn.commit()


def ensure_financial_documents_columns(conn: sqlite3.Connection) -> None:
    existing_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(financial_documents)")
    }

    if "revenue" not in existing_columns:
        conn.execute("ALTER TABLE financial_documents ADD COLUMN revenue NUMERIC")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Crée la table financial_documents dans la base SQLite locale."
    )
    parser.add_argument(
        "--siren",
        type=validate_siren,
        help="SIREN optionnel à 9 chiffres.",
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    args = parse_args()
    if args.siren:
        selected_path = find_latest_ca_pdf_for_siren(args.siren)
        if not selected_path:
            raise SystemExit(
                f"Aucun PDF CA_{args.siren}_ trouvé dans {INPI_ROOT_DIR}."
            )
        print(selected_path)
        return

    conn = sqlite3.connect(DATABASE_FILE)
    try:
        create_financial_documents_table(conn)
    finally:
        conn.close()

    print("Table financial_documents créée ou déjà existante.")


if __name__ == "__main__":
    main()
