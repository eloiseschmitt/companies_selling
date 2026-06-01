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
from decimal import Decimal, InvalidOperation
from stat import S_ISDIR

from pypdf import PdfReader

from init_financial_documents import create_financial_documents_table
from services.inpi_sftp import InpiSFTPClient, is_directory


DATABASE_FILE = "companies.db"
DOCUMENT_SOURCE = "inpi_sftp"
INPI_DOCUMENT_TYPE = "comptes_annuels_pdf"
INPI_ROOT_DIR = "Bilans_PDF"
INDEX_EXTENSIONS = {".csv", ".txt", ".tsv", ".xml"}
DOCUMENT_EXTENSIONS = {".pdf", ".xml", ".zip", ".json", ".html", ".txt"}
INDEX_NAME_HINTS = ("index", "manifest", "metadata", "metadonnees", "liste")
REVENUE_LABELS = (
    "CHIFFRES D'AFFAIRES NETS",
    "Chiffres d'affaires nets",
    "chiffre d'affaires",
    "chiffre d'affaires nets",
)
AMOUNT_PATTERN = re.compile(
    r"(?<!\w)-?(?:\d{1,3}(?:[ .\u00a0]\d{3})+|\d+)(?:,\d+)?"
)

logger = logging.getLogger(__name__)


@dataclass
class FinancialDocumentMetadata:
    siren: str
    siret: str | None
    closing_date: str
    filing_date: str | None
    document_path: str
    document_type: str | None
    revenue: Decimal | None = None
    source: str = DOCUMENT_SOURCE


@dataclass
class ImportStats:
    files_scanned: int = 0
    documents_ignored: int = 0
    documents_inserted: int = 0
    documents_updated: int = 0
    documents_without_metadata: int = 0
    matching_sirens: int = 0
    pdfs_read: int = 0
    revenues_found: int = 0
    pdfs_without_revenue: int = 0


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


def entry_is_directory(entry) -> bool:
    return entry.st_mode is not None and S_ISDIR(entry.st_mode)


def get_first_siret_for_siren(
    sirets_by_siren: dict[str, set[str]],
    siren: str,
) -> str | None:
    sirets = sirets_by_siren.get(siren)
    if not sirets:
        return None
    return sorted(sirets)[0]


def parse_ca_pdf_filename(path: str) -> dict[str, str] | None:
    filename = posixpath.basename(path)
    match = re.match(
        r"^CA_(?P<siren>\d{9})_(?P<greffe>[^_]+)_(?P<gestion>[^_]+)_"
        r"(?P<anneecloture>\d{4})_(?P<numchrono>[^.]+)\.pdf$",
        filename,
        flags=re.IGNORECASE,
    )
    if match:
        return match.groupdict()

    gu_match = re.match(
        r"^GU_CA_(?P<siren>\d{9})_(?P<datecloture>\d{8})_"
        r"(?P<numchrono>[^.]+)\.pdf$",
        filename,
        flags=re.IGNORECASE,
    )
    if gu_match:
        return gu_match.groupdict()

    return None


def extract_siren_from_pdf_filename(path: str) -> str | None:
    parsed = parse_ca_pdf_filename(path)
    if parsed:
        return parsed["siren"]
    return None


def extract_closing_date_from_pdf_filename(path: str) -> str | None:
    parsed = parse_ca_pdf_filename(path)
    if not parsed:
        return None

    if parsed.get("datecloture"):
        return normalize_date(parsed["datecloture"])
    return parsed.get("anneecloture")


def extract_filing_date_from_path(path: str) -> str | None:
    match = re.search(r"Bilans_PDF/(\d{4})/(\d{2})/(\d{2})/", path)
    if not match:
        return None
    year, month, day = match.groups()
    return f"{year}-{month}-{day}"


def normalize_amount(value: str) -> Decimal | None:
    compact = value.replace("\u00a0", " ").strip()
    compact = re.sub(r"\s+", "", compact)

    if "," in compact:
        compact = compact.replace(".", "").replace(",", ".")
    else:
        compact = compact.replace(".", "")

    try:
        return Decimal(compact)
    except InvalidOperation:
        return None


def extract_amounts_from_line(line: str) -> list[tuple[int, Decimal]]:
    amounts = []
    for match in AMOUNT_PATTERN.finditer(line):
        amount = normalize_amount(match.group(0))
        if amount is not None:
            amounts.append((match.start(), amount))
    return amounts


def line_contains_revenue_label(line: str) -> bool:
    normalized_line = line.casefold()
    return any(label.casefold() in normalized_line for label in REVENUE_LABELS)


def extract_revenue_from_text(text: str) -> Decimal | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        if not line_contains_revenue_label(line):
            continue

        amounts = extract_amounts_from_line(line)
        if not amounts and index + 1 < len(lines):
            amounts = extract_amounts_from_line(lines[index + 1])
        if not amounts:
            continue

        header = " ".join(lines[max(0, index - 3):index]).casefold()
        total_position = header.rfind("total")
        if total_position >= 0:
            right_side_amounts = [
                amount for position, amount in amounts if position >= total_position
            ]
            if right_side_amounts:
                return right_side_amounts[-1]

        return amounts[-1][1]

    return None


def extract_text_from_pdf_bytes(content: bytes) -> str:
    reader = PdfReader(io.BytesIO(content))
    page_texts = []
    for page in reader.pages:
        page_texts.append(page.extract_text() or "")
    return "\n".join(page_texts)


def get_latest_inpi_year(client: InpiSFTPClient) -> str:
    entries = client.list_entries(INPI_ROOT_DIR)
    years = [
        entry.filename
        for entry in entries
        if entry_is_directory(entry) and re.fullmatch(r"\d{4}", entry.filename)
    ]
    if not years:
        raise RuntimeError(f"Aucune année disponible dans {INPI_ROOT_DIR}")
    return sorted(years)[-1]


def iter_pdf_files(client: InpiSFTPClient, remote_path: str):
    stack = [remote_path]
    while stack:
        current_path = stack.pop(0)
        entries = sorted(
            client.list_entries(current_path),
            key=lambda item: item.filename,
        )
        for entry in entries:
            entry_path = remote_join(current_path, entry.filename)
            if entry_is_directory(entry):
                stack.append(entry_path)
                continue
            if get_extension(entry_path) == ".pdf":
                yield entry_path


def read_pdf_text(client: InpiSFTPClient, remote_path: str) -> str:
    content = client.read_binary_file(remote_path)
    return extract_text_from_pdf_bytes(content)


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
        SELECT siret, filing_date, document_type, source, revenue
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
                source,
                revenue
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document.siren,
                document.siret,
                document.closing_date,
                document.filing_date,
                document.document_path,
                document.document_type,
                document.source,
                str(document.revenue) if document.revenue is not None else None,
            ),
        )
        return "inserted"

    new_values = {
        "siret": document.siret,
        "filing_date": document.filing_date,
        "document_type": document.document_type,
        "source": document.source,
        "revenue": document.revenue,
    }
    changed = any(
        str(existing[key]) != str(value)
        if value is not None and existing[key] is not None
        else existing[key] != value
        for key, value in new_values.items()
    )
    if not changed:
        return "unchanged"

    conn.execute(
        """
        UPDATE financial_documents
        SET siret = ?,
            filing_date = ?,
            document_type = ?,
            source = ?,
            revenue = ?,
            updated_at = datetime('now')
        WHERE siren = ? AND closing_date = ? AND document_path = ?
        """,
        (
            document.siret,
            document.filing_date,
            document.document_type,
            document.source,
            str(document.revenue) if document.revenue is not None else None,
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
    max_pdfs: int | None = None,
    limit: int | None = None,
) -> ImportStats:
    stats = ImportStats()
    conn = get_connection()
    try:
        create_financial_documents_table(conn)
        company_sirens, sirets_by_siren = get_existing_company_identifiers(conn)
        logger.info(
            "%s SIREN entreprises chargés depuis companies",
            len(company_sirens),
        )

        with InpiSFTPClient.from_environment() as client:
            year = remote_path
            if remote_path == ".":
                year = get_latest_inpi_year(client)
                year_path = f"{INPI_ROOT_DIR}/{year}"
            elif re.fullmatch(r"\d{4}", remote_path):
                year_path = f"{INPI_ROOT_DIR}/{remote_path}"
            else:
                year_path = remote_path

            logger.info("Import des PDF INPI depuis %s", year_path)

            for remote_file in iter_pdf_files(client, year_path):
                stats.files_scanned += 1
                if max_pdfs is not None and stats.files_scanned > max_pdfs:
                    break

                siren = extract_siren_from_pdf_filename(remote_file)
                closing_date = extract_closing_date_from_pdf_filename(remote_file)
                if not siren or not closing_date:
                    stats.documents_without_metadata += 1
                    continue

                if siren not in company_sirens:
                    stats.documents_ignored += 1
                    continue

                if limit is not None and stats.matching_sirens >= limit:
                    break

                stats.matching_sirens += 1
                siret = get_first_siret_for_siren(sirets_by_siren, siren)
                text = read_pdf_text(client, remote_file)
                stats.pdfs_read += 1
                revenue = extract_revenue_from_text(text)
                if revenue is None:
                    stats.pdfs_without_revenue += 1
                else:
                    stats.revenues_found += 1

                if dry_run:
                    continue

                document = FinancialDocumentMetadata(
                    siren=siren,
                    siret=siret,
                    closing_date=closing_date,
                    filing_date=extract_filing_date_from_path(remote_file),
                    document_path=remote_file,
                    document_type=INPI_DOCUMENT_TYPE,
                    revenue=revenue,
                )
                result = upsert_financial_document(conn, document)
                if result == "inserted":
                    stats.documents_inserted += 1
                elif result == "updated":
                    stats.documents_updated += 1

            if not dry_run:
                conn.commit()
    finally:
        conn.close()

    logger.info("Fichiers PDF listés: %s", stats.files_scanned)
    logger.info("SIREN correspondants: %s", stats.matching_sirens)
    logger.info("PDF lus: %s", stats.pdfs_read)
    logger.info("Chiffres d'affaires trouvés: %s", stats.revenues_found)
    logger.info("PDF sans chiffre d'affaires détecté: %s", stats.pdfs_without_revenue)
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
        help="Année ou dossier distant à parcourir sur le SFTP.",
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
    parser.add_argument(
        "--max-pdfs",
        type=int,
        default=None,
        help="Nombre maximal de PDF à lister pendant un import de test.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Nombre maximal de PDF correspondant à companies à traiter.",
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
        max_pdfs=args.max_pdfs,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
