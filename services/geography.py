"""Geographic helpers for manually mapping INSEE IRIS to business sectors."""

from __future__ import annotations

import csv
import logging
import unicodedata
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import pandas

logger = logging.getLogger(__name__)

SECTOR_NAMES = (
    "Bordeaux Caudéran",
    "Bordeaux Fondaudège",
    "Bordeaux Chartrons",
    "Le Bouscat",
    "Bruges",
    "Mérignac centre",
    "Saint-Médard-en-Jalles",
    "Talence",
    "Pessac centre",
    "Bègles secteur résidentiel",
)

COMMUNE_CODES_BY_SECTOR = {
    "Bordeaux Caudéran": "33063",
    "Bordeaux Fondaudège": "33063",
    "Bordeaux Chartrons": "33063",
    "Le Bouscat": "33069",
    "Bruges": "33075",
    "Mérignac centre": "33281",
    "Saint-Médard-en-Jalles": "33449",
    "Talence": "33522",
    "Pessac centre": "33318",
    "Bègles secteur résidentiel": "33039",
}

IRIS_CODE_COLUMNS = ("iris", "code_iris", "codeiris", "iris_code", "cod_iris")
IRIS_LABEL_COLUMNS = ("libiris", "lib_iris", "iris_label", "nom_iris", "libelle_iris")
COMMUNE_CODE_COLUMNS = (
    "com",
    "code_commune",
    "commune_code",
    "depcom",
    "codgeo",
    "code_departement_commune",
)
COMMUNE_NAME_COLUMNS = (
    "libcom",
    "nom_commune",
    "commune_name",
    "libelle_commune",
    "libelle_de_commune",
)


@dataclass(frozen=True)
class IrisArea:
    """Minimum IRIS geography row needed for manual sector mapping."""

    iris_code: str
    iris_label: str
    commune_code: str
    commune_name: str


@dataclass(frozen=True)
class IrisCandidate:
    """Candidate IRIS row exported for human review."""

    iris: IrisArea
    candidate_sectors: tuple[str, ...]


class GeographyTableError(RuntimeError):
    """Raised when an IRIS geography table is missing required columns."""


class SectorMappingError(RuntimeError):
    """Raised when manual sector mapping is invalid."""


def load_iris_table(path: Path) -> list[IrisArea]:
    """Load an IRIS geography table from CSV."""
    rows = read_csv_rows(path)
    if not rows:
        return []

    column_lookup = build_column_lookup(rows[0].keys())
    iris_code_column = require_column(column_lookup, IRIS_CODE_COLUMNS, "IRIS code")
    iris_label_column = require_column(column_lookup, IRIS_LABEL_COLUMNS, "IRIS label")
    commune_code_column = require_column(
        column_lookup, COMMUNE_CODE_COLUMNS, "commune code"
    )
    commune_name_column = require_column(
        column_lookup, COMMUNE_NAME_COLUMNS, "commune name"
    )

    iris_areas: list[IrisArea] = []
    for row in rows:
        iris_code = normalize_code(row.get(iris_code_column))
        commune_code = normalize_code(row.get(commune_code_column))
        if normalize_column_name(iris_code) == normalize_column_name(
            iris_code_column
        ) or normalize_column_name(commune_code) == normalize_column_name(
            commune_code_column
        ):
            continue
        if not iris_code or not commune_code:
            continue
        iris_areas.append(
            IrisArea(
                iris_code=iris_code,
                iris_label=str(row.get(iris_label_column) or "").strip(),
                commune_code=commune_code,
                commune_name=str(row.get(commune_name_column) or "").strip(),
            )
        )

    logger.info("Loaded %s IRIS geography rows from %s.", len(iris_areas), path)
    return iris_areas


def load_sector_iris_mapping(path: Path) -> dict[str, tuple[str, ...]]:
    """Load the manual YAML mapping without guessing any IRIS."""
    mapping = parse_sector_mapping_yaml(path.read_text(encoding="utf-8"))
    validate_sector_names(mapping)
    return mapping


def validate_sector_mapping(
    mapping: Mapping[str, Sequence[str]],
    iris_areas: Sequence[IrisArea],
) -> None:
    """Validate that mapped IRIS codes exist and belong to expected communes."""
    validate_sector_names(mapping)
    iris_by_code = {area.iris_code: area for area in iris_areas}
    errors: list[str] = []

    for sector, iris_codes in mapping.items():
        expected_commune_code = COMMUNE_CODES_BY_SECTOR[sector]
        for iris_code in iris_codes:
            area = iris_by_code.get(iris_code)
            if area is None:
                errors.append(f"{sector}: unknown IRIS {iris_code}")
            elif area.commune_code != expected_commune_code:
                errors.append(
                    f"{sector}: IRIS {iris_code} belongs to commune "
                    f"{area.commune_code}, expected {expected_commune_code}"
                )

    if errors:
        raise SectorMappingError("Invalid sector IRIS mapping: " + "; ".join(errors))


def build_iris_candidates(iris_areas: Sequence[IrisArea]) -> list[IrisCandidate]:
    """Return all IRIS in concerned communes, without assigning neighborhoods."""
    sectors_by_commune = build_sectors_by_commune()
    concerned_commune_codes = set(sectors_by_commune)
    candidates = [
        IrisCandidate(
            iris=area,
            candidate_sectors=sectors_by_commune.get(area.commune_code, ()),
        )
        for area in iris_areas
        if area.commune_code in concerned_commune_codes
    ]
    return sorted(
        candidates,
        key=lambda candidate: (
            candidate.iris.commune_name,
            candidate.iris.iris_code,
        ),
    )


def search_iris_areas(
    iris_areas: Sequence[IrisArea],
    commune: str | None = None,
    query: str | None = None,
) -> list[IrisArea]:
    """Search IRIS rows by commune and IRIS label."""
    normalized_commune = normalize_search_text(commune) if commune else None
    normalized_query = normalize_search_text(query) if query else None
    matches: list[IrisArea] = []
    for area in iris_areas:
        if normalized_commune and normalized_commune not in normalize_search_text(
            area.commune_name
        ):
            continue
        if normalized_query and normalized_query not in normalize_search_text(
            area.iris_label
        ):
            continue
        matches.append(area)
    return sorted(matches, key=lambda area: (area.commune_name, area.iris_code))


def filter_iris_candidates(
    candidates: Sequence[IrisCandidate],
    commune: str | None = None,
    query: str | None = None,
) -> list[IrisCandidate]:
    """Filter candidate rows by commune and IRIS label."""
    matching_codes = {
        area.iris_code
        for area in search_iris_areas(
            [candidate.iris for candidate in candidates],
            commune=commune,
            query=query,
        )
    }
    return [
        candidate
        for candidate in candidates
        if candidate.iris.iris_code in matching_codes
    ]


def export_iris_candidates(
    output_path: Path, candidates: Sequence[IrisCandidate]
) -> None:
    """Export candidate IRIS rows for manual sector mapping."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8-sig") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=(
                "commune_code",
                "commune_name",
                "iris_code",
                "iris_label",
                "candidate_sectors",
            ),
        )
        writer.writeheader()
        for candidate in candidates:
            writer.writerow(
                {
                    "commune_code": candidate.iris.commune_code,
                    "commune_name": candidate.iris.commune_name,
                    "iris_code": candidate.iris.iris_code,
                    "iris_label": candidate.iris.iris_label,
                    "candidate_sectors": "; ".join(candidate.candidate_sectors),
                }
            )


def update_sector_mapping_from_candidates(
    candidates_path: Path,
    mapping_path: Path,
) -> dict[str, tuple[str, ...]]:
    """Update sector mapping YAML from a reviewed iris_candidates.csv file."""
    mapping = {
        sector: list(codes)
        for sector, codes in load_sector_iris_mapping(mapping_path).items()
    }
    rows = read_csv_file_rows(candidates_path)

    for row in rows:
        iris_code = normalize_code(row.get("iris_code"))
        if not iris_code:
            continue
        for sector in parse_candidate_sectors(row.get("candidate_sectors", "")):
            if sector not in mapping:
                raise SectorMappingError(
                    f"Unknown sector {sector!r} in {candidates_path}."
                )
            if iris_code not in mapping[sector]:
                mapping[sector].append(iris_code)

    normalized_mapping = {
        sector: tuple(sorted(codes)) for sector, codes in mapping.items()
    }
    write_sector_iris_mapping(mapping_path, normalized_mapping)
    return normalized_mapping


def parse_candidate_sectors(value: str) -> list[str]:
    return [sector.strip() for sector in value.split(";") if sector.strip()]


def write_sector_iris_mapping(
    mapping_path: Path,
    mapping: Mapping[str, Sequence[str]],
) -> None:
    validate_sector_names(mapping)
    lines = [
        "# Manual mapping from business sectors to validated INSEE IRIS codes.",
        "# Generated or updated from data/output/iris_candidates.csv.",
        "# Review the mapping before using it for statistical reporting.",
        "sectors:",
    ]
    for sector in SECTOR_NAMES:
        iris_codes = tuple(mapping.get(sector, ()))
        if not iris_codes:
            lines.append(f"  {sector}: []")
            continue
        lines.append(f"  {sector}:")
        lines.extend(f"    - {iris_code}" for iris_code in iris_codes)
    mapping_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_sectors_by_commune() -> dict[str, tuple[str, ...]]:
    sectors_by_commune: dict[str, list[str]] = {}
    for sector, commune_code in COMMUNE_CODES_BY_SECTOR.items():
        sectors_by_commune.setdefault(commune_code, []).append(sector)
    return {
        commune_code: tuple(sectors)
        for commune_code, sectors in sectors_by_commune.items()
    }


def parse_sector_mapping_yaml(content: str) -> dict[str, tuple[str, ...]]:
    """Parse the limited YAML shape used by config/sector_iris_mapping.yml."""
    mapping: dict[str, list[str]] = {}
    current_sector: str | None = None
    in_sectors_block = False

    for raw_line in content.splitlines():
        line = strip_yaml_comment(raw_line).rstrip()
        if not line.strip():
            continue
        if line.strip() == "sectors:":
            in_sectors_block = True
            current_sector = None
            continue
        if not in_sectors_block:
            continue

        stripped = line.strip()
        if stripped.startswith("-"):
            if current_sector is None:
                raise SectorMappingError("IRIS list item found before any sector.")
            iris_code = normalize_code(stripped[1:].strip().strip("\"'"))
            if iris_code:
                mapping[current_sector].append(iris_code)
            continue

        if ":" not in stripped:
            raise SectorMappingError(f"Invalid mapping line: {raw_line}")
        key, value = stripped.split(":", 1)
        sector = key.strip().strip("\"'")
        current_sector = sector
        mapping.setdefault(sector, [])
        value = value.strip()
        if value == "[]" or not value:
            continue
        if value.startswith("[") and value.endswith("]"):
            items = [item.strip().strip("\"'") for item in value[1:-1].split(",")]
            mapping[sector].extend(normalize_code(item) for item in items if item)
            continue
        raise SectorMappingError(f"Unsupported mapping value for {sector}: {value}")

    return {sector: tuple(iris_codes) for sector, iris_codes in mapping.items()}


def validate_sector_names(mapping: Mapping[str, Sequence[str]]) -> None:
    expected = set(SECTOR_NAMES)
    actual = set(mapping)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing or unknown:
        details = []
        if missing:
            details.append("missing sectors: " + ", ".join(missing))
        if unknown:
            details.append("unknown sectors: " + ", ".join(unknown))
        raise SectorMappingError("Invalid sector list: " + "; ".join(details))


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    suffix = path.suffix.lower()
    if suffix == ".zip":
        return read_rows_from_zip(path)
    if suffix in {".xlsx", ".xls"}:
        return read_excel_rows(path)
    return read_csv_file_rows(path)


def read_rows_from_zip(path: Path) -> list[dict[str, str]]:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        csv_names = [name for name in names if name.lower().endswith(".csv")]
        if csv_names:
            content = decode_text(archive.read(csv_names[0]))
            return parse_csv_content(content)

        excel_names = [
            name for name in names if name.lower().endswith((".xlsx", ".xls"))
        ]
        if excel_names:
            with archive.open(excel_names[0]) as excel_file:
                return dataframe_to_rows(read_excel_with_detected_header(excel_file))

    raise GeographyTableError(f"No CSV or Excel file found in ZIP archive: {path}")


def read_excel_rows(path: Path) -> list[dict[str, str]]:
    return dataframe_to_rows(read_excel_with_detected_header(path))


def read_excel_with_detected_header(source: object) -> pandas.DataFrame:
    raw_df = pandas.read_excel(source, header=None, dtype=str)
    header_index = find_excel_header_index(raw_df)
    if header_index is None:
        raise GeographyTableError("Unable to detect IRIS header row in Excel file.")

    df = raw_df.iloc[header_index + 1 :].copy()
    df.columns = [str(value).strip() for value in raw_df.iloc[header_index]]
    df = df.dropna(how="all")
    return df


def find_excel_header_index(df: pandas.DataFrame) -> int | None:
    iris_candidates = {normalize_column_name(column) for column in IRIS_CODE_COLUMNS}
    commune_candidates = {
        normalize_column_name(column) for column in COMMUNE_CODE_COLUMNS
    }
    for row_index, (_, row) in enumerate(df.iterrows()):
        values = {normalize_column_name(str(value)) for value in row.dropna()}
        if values & iris_candidates and values & commune_candidates:
            return row_index
    return None


def read_csv_file_rows(path: Path) -> list[dict[str, str]]:
    content = decode_text(path.read_bytes())
    return parse_csv_content(content)


def decode_text(content: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise GeographyTableError("Unable to decode CSV content with supported encodings.")


def parse_csv_content(content: str) -> list[dict[str, str]]:
    sample = content[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(content.splitlines(), dialect=dialect)
    return [dict(row) for row in reader]


def dataframe_to_rows(df: pandas.DataFrame) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for row in df.to_dict(orient="records"):
        rows.append(
            {
                str(key): "" if pandas.isna(value) else str(value)
                for key, value in row.items()
            }
        )
    return rows


def build_column_lookup(columns: Iterable[str]) -> dict[str, str]:
    return {normalize_column_name(column): column for column in columns}


def require_column(
    column_lookup: Mapping[str, str],
    candidates: Sequence[str],
    label: str,
) -> str:
    for candidate in candidates:
        column = column_lookup.get(normalize_column_name(candidate))
        if column:
            return column
    raise GeographyTableError(f"Missing {label} column. Tried: {', '.join(candidates)}")


def normalize_column_name(name: str) -> str:
    without_accents = "".join(
        character
        for character in unicodedata.normalize("NFKD", name)
        if not unicodedata.combining(character)
    )
    return without_accents.strip().lower().replace(" ", "_").replace("-", "_")


def normalize_code(value: str | None) -> str:
    return "" if value is None else str(value).strip().upper()


def normalize_search_text(value: str | None) -> str:
    if value is None:
        return ""
    without_accents = "".join(
        character
        for character in unicodedata.normalize("NFKD", str(value))
        if not unicodedata.combining(character)
    )
    return without_accents.strip().lower()


def strip_yaml_comment(line: str) -> str:
    return line.split("#", 1)[0]
