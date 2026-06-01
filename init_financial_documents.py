"""Crée la table financial_documents dans la base SQLite locale."""

import argparse
import logging
import posixpath
import re
import sqlite3
from dataclasses import dataclass
from time import perf_counter

from services.inpi_sftp import InpiSFTPClient, is_directory


DATABASE_FILE = "companies.db"
INPI_ROOT_DIR = "Bilans_PDF"

logger = logging.getLogger(__name__)


@dataclass
class SirenSearchStats:
    years_inspected: int = 0
    files_examined: int = 0
    duration_seconds: float = 0.0


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
    stats: SirenSearchStats,
) -> list[str]:
    candidates = []
    prefix = f"CA_{siren}_"
    year_path = remote_join(INPI_ROOT_DIR, year)

    for month_entry in reversed(list_sorted_entries(client, year_path)):
        stats.files_examined += 1
        if not is_directory(month_entry):
            continue

        month_path = remote_join(year_path, month_entry.filename)
        for day_entry in reversed(list_sorted_entries(client, month_path)):
            stats.files_examined += 1
            if not is_directory(day_entry):
                continue

            day_path = remote_join(month_path, day_entry.filename)
            for document_entry in reversed(list_sorted_entries(client, day_path)):
                stats.files_examined += 1
                document_path = remote_join(day_path, document_entry.filename)
                if not document_entry.filename.startswith(prefix):
                    continue

                if not is_directory(document_entry):
                    if document_entry.filename.endswith(".pdf"):
                        candidates.append(document_path)
                    continue

                for file_entry in list_sorted_entries(client, document_path):
                    stats.files_examined += 1
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


def find_latest_ca_pdf_for_siren(
    siren: str,
) -> tuple[str | None, SirenSearchStats]:
    stats = SirenSearchStats()
    started_at = perf_counter()
    with InpiSFTPClient.from_environment() as client:
        for year in get_available_years(client):
            stats.years_inspected += 1
            logger.info(
                "Recherche des PDF CA_%s_ dans %s/%s",
                siren,
                INPI_ROOT_DIR,
                year,
            )
            candidates = find_ca_pdf_candidates_for_year(client, year, siren, stats)
            if not candidates:
                continue

            selected_path = select_latest_ca_pdf(candidates, siren)
            stats.duration_seconds = perf_counter() - started_at
            logger.info("PDF INPI trouvé pour le SIREN %s: %s", siren, selected_path)
            logger.info(
                "Recherche SIREN terminée: années inspectées=%s, "
                "fichiers examinés=%s, durée=%.2fs",
                stats.years_inspected,
                stats.files_examined,
                stats.duration_seconds,
            )
            return selected_path, stats

    stats.duration_seconds = perf_counter() - started_at
    logger.info(
        "Recherche SIREN terminée sans résultat: années inspectées=%s, "
        "fichiers examinés=%s, durée=%.2fs",
        stats.years_inspected,
        stats.files_examined,
        stats.duration_seconds,
    )
    return None, stats


def get_siret_for_siren(conn: sqlite3.Connection, siren: str) -> str | None:
    try:
        row = conn.execute(
            """
            SELECT siret
            FROM companies
            WHERE siret IS NOT NULL AND SUBSTR(siret, 1, 9) = ?
            ORDER BY siret
            LIMIT 1
            """,
            (siren,),
        ).fetchone()
    except sqlite3.OperationalError:
        return None

    if row is None:
        return None
    return row[0]


def process_latest_pdf_for_siren(siren: str) -> dict[str, object]:
    from import_financial_documents import (
        INPI_DOCUMENT_TYPE,
        FinancialDocumentMetadata,
        extract_closing_date_from_pdf_filename,
        extract_filing_date_from_path,
        extract_revenue_from_text,
        extract_text_from_pdf_bytes,
        upsert_financial_document,
    )

    selected_path, search_stats = find_latest_ca_pdf_for_siren(siren)
    if not selected_path:
        raise SystemExit(f"Aucun PDF CA_{siren}_ trouvé dans {INPI_ROOT_DIR}.")

    closing_date = extract_closing_date_from_pdf_filename(selected_path)
    if not closing_date:
        raise SystemExit(
            f"Date de clôture introuvable dans le nom du PDF: {selected_path}"
        )

    with InpiSFTPClient.from_environment() as client:
        pdf_content = client.read_binary_file(selected_path)

    text = extract_text_from_pdf_bytes(pdf_content)
    revenue = extract_revenue_from_text(text)

    conn = sqlite3.connect(DATABASE_FILE)
    try:
        create_financial_documents_table(conn)
        document = FinancialDocumentMetadata(
            siren=siren,
            siret=get_siret_for_siren(conn, siren),
            closing_date=closing_date,
            filing_date=extract_filing_date_from_path(selected_path),
            document_path=selected_path,
            document_type=INPI_DOCUMENT_TYPE,
            revenue=revenue,
        )
        status = upsert_financial_document(conn, document)
        conn.commit()
    finally:
        conn.close()

    logger.info("PDF INPI traité pour le SIREN %s: %s", siren, selected_path)
    return {
        "siren": siren,
        "document_path": selected_path,
        "closing_date": closing_date,
        "revenue": revenue,
        "status": status,
        "years_inspected": search_stats.years_inspected,
        "files_examined": search_stats.files_examined,
        "search_duration_seconds": search_stats.duration_seconds,
    }


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
        summary = process_latest_pdf_for_siren(args.siren)
        print("Résumé import PDF INPI")
        print(f"siren: {summary['siren']}")
        print(f"fichier utilisé: {summary['document_path']}")
        print(f"date de clôture: {summary['closing_date']}")
        print(f"chiffre d'affaires détecté: {summary['revenue']}")
        print(f"statut: {summary['status']}")
        print(f"années inspectées: {summary['years_inspected']}")
        print(f"fichiers examinés: {summary['files_examined']}")
        print(f"durée recherche: {summary['search_duration_seconds']:.2f}s")
        return

    conn = sqlite3.connect(DATABASE_FILE)
    try:
        create_financial_documents_table(conn)
    finally:
        conn.close()

    print("Table financial_documents créée ou déjà existante.")


if __name__ == "__main__":
    main()
