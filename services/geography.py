"""Geographic helpers for manually mapping INSEE IRIS to business sectors."""

from __future__ import annotations

import csv
import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

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
COMMUNE_CODE_COLUMNS = ("com", "code_commune", "commune_code", "depcom", "codgeo")
COMMUNE_NAME_COLUMNS = ("libcom", "nom_commune", "commune_name", "libelle_commune")


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
    content = path.read_text(encoding="utf-8-sig")
    sample = content[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(content.splitlines(), dialect=dialect)
    return [dict(row) for row in reader]


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
    return name.strip().lower().replace(" ", "_").replace("-", "_")


def normalize_code(value: str | None) -> str:
    return "" if value is None else str(value).strip().upper()


def strip_yaml_comment(line: str) -> str:
    return line.split("#", 1)[0]
