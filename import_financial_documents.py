"""Importe les métadonnées de documents financiers depuis le SFTP INPI."""

from __future__ import annotations

import argparse
import csv
import io
import logging
import posixpath
import re
import sqlite3
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from init_financial_documents import create_financial_documents_table
from services.inpi_sftp import InpiSFTPClient, is_directory


DATABASE_FILE = "companies.db"
DOCUMENT_SOURCE = "INPI_SFTP"
INDEX_EXTENSIONS = {".csv", ".txt", ".tsv", ".xml"}
DOCUMENT_EXTENSIONS = {".pdf", ".xml", ".zip", ".json", ".html", ".txt"}
INDEX_NAME_HINTS = ("index", "manifest", "metadata", "metadonnees", "liste")

logger = logging.getLogger(__name__)


@dataclass
class FinancialDocumentMetadata:
    siren: str
    siret: str | None
    closing_date: str
    filing_date: str | None
    document_path: str
    document_type: str | None
    source: str = DOCUMENT_SOURCE


@dataclass
class ImportStats:
    files_scanned: int = 0
    documents_ignored: int = 0
    documents_inserted: int = 0
    documents_updated: int = 0
    documents_without_metadata: int = 0


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def get_table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row["name"] for row in rows}


def get_existing_company_identifiers(
    conn: sqlite3.Connection,
) -> tuple[set[str], dict[str, set[str]]]:
    columns = get_table_columns(conn, "companies")
    if "siren" in columns:
        rows = conn.execute(
            """
            SELECT DISTINCT siren, siret
            FROM companies
            WHERE siren IS NOT NULL AND siren != ''
            """
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT DISTINCT SUBSTR(siret, 1, 9) AS siren, siret
            FROM companies
            WHERE siret IS NOT NULL AND LENGTH(siret) >= 9
            """
        ).fetchall()

    sirens = set()
    sirets_by_siren: dict[str, set[str]] = {}
    for row in rows:
        siren = normalize_digits(row["siren"], 9)
        if not siren:
            continue

        sirens.add(siren)
        siret = normalize_digits(row["siret"], 14)
        if siret:
            sirets_by_siren.setdefault(siren, set()).add(siret)

    return sirens, sirets_by_siren


def normalize_digits(value: object, expected_length: int) -> str | None:
    if value is None:
        return None

    digits = re.sub(r"\D", "", str(value))
    if len(digits) == expected_length:
        return digits
    return None


def normalize_date(value: object) -> str | None:
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    iso_match = re.search(r"(\d{4})[-_/](\d{2})[-_/](\d{2})", text)
    if iso_match:
        return "-".join(iso_match.groups())

    french_match = re.search(r"(\d{2})[-_/](\d{2})[-_/](\d{4})", text)
    if french_match:
        day, month, year = french_match.groups()
        return f"{year}-{month}-{day}"

    compact_match = re.search(r"(?<!\d)(20\d{2}|19\d{2})(\d{2})(\d{2})(?!\d)", text)
    if compact_match:
        year, month, day = compact_match.groups()
        return f"{year}-{month}-{day}"

    return None


def remote_join(parent: str, child: str) -> str:
    if parent in {"", "."}:
        return child
    return posixpath.join(parent, child)


def get_extension(path: str) -> str:
    return posixpath.splitext(path.lower())[1]


def is_index_file(path: str) -> bool:
    extension = get_extension(path)
    if extension in {".csv", ".tsv"}:
        return True
    if extension in INDEX_EXTENSIONS:
        basename = posixpath.basename(path).lower()
        return any(hint in basename for hint in INDEX_NAME_HINTS)
    return False


def infer_document_type(path: str, explicit_type: str | None = None) -> str | None:
    if explicit_type:
        return explicit_type.strip() or None

    lower_path = path.lower()
    if "bilan" in lower_path:
        return "bilan"
    if "compte" in lower_path or "annual" in lower_path:
        return "comptes_annuels"
    if "rapport" in lower_path:
        return "rapport"

    extension = get_extension(path)
    if extension:
        return extension.lstrip(".")
    return None


def extract_metadata_from_path(path: str) -> FinancialDocumentMetadata | None:
    basename = posixpath.basename(path)
    siret_matches = re.findall(r"(?<!\d)\d{14}(?!\d)", basename)
    siret = normalize_digits(next(iter(siret_matches), None), 14)
    siren = siret[:9] if siret else None

    if siren is None:
        siren = normalize_digits(
            next(iter(re.findall(r"(?<!\d)\d{9}(?!\d)", basename)), None),
            9,
        )

    dates = []
    for match in re.finditer(
        r"(?<!\d)(?:\d{4}[-_/]?\d{2}[-_/]?\d{2}|\d{2}[-_/]\d{2}[-_/]\d{4})(?!\d)",
        basename,
    ):
        normalized = normalize_date(match.group(0))
        if normalized:
            dates.append(normalized)

    if not siren or not dates:
        return None

    closing_date = dates[0]
    filing_date = dates[1] if len(dates) > 1 else None
    return FinancialDocumentMetadata(
        siren=siren,
        siret=siret,
        closing_date=closing_date,
        filing_date=filing_date,
        document_path=path,
        document_type=infer_document_type(path),
    )


def first_value(row: dict[str, str], candidates: tuple[str, ...]) -> str | None:
    normalized_row = {key.lower().strip(): value for key, value in row.items()}
    for candidate in candidates:
        value = normalized_row.get(candidate)
        if value:
            return value
    return None


def metadata_from_index_row(
    row: dict[str, str],
    index_path: str,
) -> FinancialDocumentMetadata | None:
    document_path = first_value(
        row,
        (
            "document_path",
            "path",
            "chemin",
            "chemin_document",
            "filename",
            "file",
            "fichier",
            "nom_fichier",
        ),
    )
    if document_path:
        document_path = remote_join(posixpath.dirname(index_path), document_path)
    else:
        document_path = index_path

    siret = normalize_digits(first_value(row, ("siret", "numero_siret")), 14)
    siren = normalize_digits(first_value(row, ("siren", "numero_siren")), 9)
    if siren is None and siret:
        siren = siret[:9]

    closing_date = normalize_date(
        first_value(
            row,
            (
                "closing_date",
                "date_cloture",
                "datecloture",
                "date_cloture_exercice",
                "cloture",
            ),
        )
    )
    filing_date = normalize_date(
        first_value(
            row,
            (
                "filing_date",
                "date_depot",
                "datedepot",
                "date_depot_document",
                "depot",
            ),
        )
    )
    document_type = infer_document_type(
        document_path,
        first_value(row, ("document_type", "type", "type_document", "nature")),
    )

    if not siren or not closing_date:
        return extract_metadata_from_path(document_path)

    return FinancialDocumentMetadata(
        siren=siren,
        siret=siret,
        closing_date=closing_date,
        filing_date=filing_date,
        document_path=document_path,
        document_type=document_type,
    )


def parse_delimited_index(
    content: str,
    index_path: str,
) -> list[FinancialDocumentMetadata]:
    first_line = content.splitlines()[0] if content.splitlines() else ""
    delimiter = "\t" if "\t" in first_line else ";"
    if "," in first_line and first_line.count(",") > first_line.count(delimiter):
        delimiter = ","

    reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)
    documents = []
    for row in reader:
        metadata = metadata_from_index_row(row, index_path)
        if metadata:
            documents.append(metadata)
    return documents


def parse_xml_index(content: str, index_path: str) -> list[FinancialDocumentMetadata]:
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return []

    documents = []
    for element in root.iter():
        values = {
            child.tag.split("}")[-1].lower(): (child.text or "").strip()
            for child in list(element)
            if child.text
        }
        if not values:
            continue

        metadata = metadata_from_index_row(values, index_path)
        if metadata:
            documents.append(metadata)

    return documents


def parse_index_file(content: str, index_path: str) -> list[FinancialDocumentMetadata]:
    if get_extension(index_path) == ".xml":
        return parse_xml_index(content, index_path)
    return parse_delimited_index(content, index_path)


def iter_remote_files(
    client: InpiSFTPClient,
    remote_path: str,
    recursive: bool,
    max_depth: int,
) -> list[str]:
    files = []

    def visit(path: str, depth: int) -> None:
        for entry in client.list_entries(path):
            entry_path = remote_join(path, entry.filename)
            if is_directory(entry):
                if recursive and depth < max_depth:
                    visit(entry_path, depth + 1)
                continue
            files.append(entry_path)

    visit(remote_path, 0)
    return files


def upsert_financial_document(
    conn: sqlite3.Connection,
    document: FinancialDocumentMetadata,
) -> str:
    existing = conn.execute(
        """
        SELECT siret, filing_date, document_type, source
        FROM financial_documents
        WHERE siren = ? AND closing_date = ? AND document_path = ?
        """,
        (document.siren, document.closing_date, document.document_path),
    ).fetchone()

    if existing is None:
        conn.execute(
            """
            INSERT INTO financial_documents (
                siren,
                siret,
                closing_date,
                filing_date,
                document_path,
                document_type,
                source
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document.siren,
                document.siret,
                document.closing_date,
                document.filing_date,
                document.document_path,
                document.document_type,
                document.source,
            ),
        )
        return "inserted"

    new_values = {
        "siret": document.siret,
        "filing_date": document.filing_date,
        "document_type": document.document_type,
        "source": document.source,
    }
    changed = any(existing[key] != value for key, value in new_values.items())
    if not changed:
        return "unchanged"

    conn.execute(
        """
        UPDATE financial_documents
        SET siret = ?,
            filing_date = ?,
            document_type = ?,
            source = ?,
            updated_at = datetime('now')
        WHERE siren = ? AND closing_date = ? AND document_path = ?
        """,
        (
            document.siret,
            document.filing_date,
            document.document_type,
            document.source,
            document.siren,
            document.closing_date,
            document.document_path,
        ),
    )
    return "updated"


def import_financial_documents(
    remote_path: str = ".",
    recursive: bool = False,
    max_depth: int = 2,
    dry_run: bool = False,
) -> ImportStats:
    stats = ImportStats()
    conn = get_connection()
    try:
        create_financial_documents_table(conn)
        company_sirens, _ = get_existing_company_identifiers(conn)
        logger.info(
            "%s SIREN entreprises chargés depuis companies",
            len(company_sirens),
        )

        with InpiSFTPClient.from_environment() as client:
            files = iter_remote_files(client, remote_path, recursive, max_depth)
            stats.files_scanned = len(files)

            for remote_file in files:
                extension = get_extension(remote_file)
                documents = []

                if is_index_file(remote_file):
                    try:
                        content = client.read_text_file(remote_file)
                    except ValueError:
                        logger.warning(
                            "Index ignoré car trop volumineux: %s",
                            remote_file,
                        )
                        content = ""
                    if content:
                        documents = parse_index_file(content, remote_file)

                if not documents and extension in DOCUMENT_EXTENSIONS:
                    metadata = extract_metadata_from_path(remote_file)
                    if metadata:
                        documents = [metadata]

                if not documents:
                    stats.documents_without_metadata += 1
                    continue

                for document in documents:
                    if document.siren not in company_sirens:
                        stats.documents_ignored += 1
                        continue

                    if dry_run:
                        continue

                    result = upsert_financial_document(conn, document)
                    if result == "inserted":
                        stats.documents_inserted += 1
                    elif result == "updated":
                        stats.documents_updated += 1

            if not dry_run:
                conn.commit()
    finally:
        conn.close()

    logger.info("Fichiers parcourus: %s", stats.files_scanned)
    logger.info("Documents ignorés: %s", stats.documents_ignored)
    logger.info("Documents insérés: %s", stats.documents_inserted)
    logger.info("Documents mis à jour: %s", stats.documents_updated)
    if stats.documents_without_metadata:
        logger.info(
            "Fichiers sans métadonnées exploitables: %s",
            stats.documents_without_metadata,
        )

    return stats


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Importe les métadonnées des documents financiers depuis le SFTP INPI."
        )
    )
    parser.add_argument(
        "--remote-path",
        default=".",
        help="Dossier distant à parcourir sur le SFTP.",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Parcourt récursivement les sous-dossiers.",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=2,
        help="Profondeur maximale si --recursive est activé.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parcourt le SFTP sans écrire dans la base.",
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    args = parse_args()
    import_financial_documents(
        remote_path=args.remote_path,
        recursive=args.recursive,
        max_depth=args.max_depth,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
