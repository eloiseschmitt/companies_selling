"""Build INSEE IRIS indicators for configured business sectors."""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import sqlite3
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 60
INDICATOR_MEDIAN_INCOME = "median_disposable_income_per_consumption_unit"
INDICATOR_POPULATION_75_PLUS = "population_75_plus"
INDICATOR_75_PLUS_LIVING_ALONE = "population_75_plus_living_alone"
INDICATOR_UPPER_SOCIO_PROFESSIONAL_RETIRED = "upper_socio_professional_retired"

IRIS_CODE_COLUMNS = (
    "iris",
    "code_iris",
    "codeiris",
    "iris_code",
    "cod_iris",
    "depcomiris",
)
IRIS_LABEL_COLUMNS = ("libiris", "lib_iris", "iris_label", "nom_iris")
INCOME_MEDIAN_COLUMNS = (
    "disp_med21",
    "disp_med20",
    "disp_med19",
    "q2_disp",
    "median_income",
    "median_disposable_income",
    "mediane_niveau_vie",
)
INCOME_WEIGHT_COLUMNS = (
    "nbpersmenfisc21",
    "nbpersmenfisc20",
    "nbpersmenfisc19",
    "population",
    "pop",
)
POPULATION_75_PLUS_COLUMNS = (
    "p21_pop75p",
    "p20_pop75p",
    "p19_pop75p",
    "population_75_plus",
    "pop75p",
)
LIVING_ALONE_75_PLUS_COLUMNS = (
    "p21_pop75p_seul",
    "p20_pop75p_seul",
    "p19_pop75p_seul",
    "population_75_plus_living_alone",
    "pop75p_seul",
)
RETIRED_COLUMNS = (
    "p21_pop15p_retraites",
    "p20_pop15p_retraites",
    "p19_pop15p_retraites",
    "retired_population",
    "retraites",
)
UPPER_SOCIO_PROFESSIONAL_COLUMNS = (
    "p21_pop15p_cs3",
    "p21_pop15p_cs4",
    "p20_pop15p_cs3",
    "p20_pop15p_cs4",
    "p19_pop15p_cs3",
    "p19_pop15p_cs4",
    "upper_socio_professional_population",
)


@dataclass(frozen=True)
class DataSource:
    """A local or remote source file plus provenance metadata."""

    name: str
    location: str
    vintage: str


@dataclass(frozen=True)
class SectorConfig:
    """Explicit business-sector perimeter."""

    name: str
    iris_codes: tuple[str, ...]


@dataclass(frozen=True)
class IndicatorResult:
    sector: str
    indicator: str
    value: float | None
    unit: str
    source: str
    vintage: str
    method: str
    iris_codes: tuple[str, ...]
    quality: str
    note: str


@dataclass(frozen=True)
class SourceRows:
    source: DataSource
    rows_by_iris: dict[str, dict[str, str]]
    columns_by_normalized_name: dict[str, str]


class MissingColumnError(RuntimeError):
    """Raised when a required source column cannot be found."""


class InvalidSectorConfigError(RuntimeError):
    """Raised when sector configuration cannot be used safely."""


def load_sector_config(path: Path) -> list[SectorConfig]:
    """Load sector definitions from JSON."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("sectors"), list):
        raise InvalidSectorConfigError("Sector config must contain a sectors list.")

    sectors: list[SectorConfig] = []
    for item in payload["sectors"]:
        if not isinstance(item, dict):
            raise InvalidSectorConfigError("Each sector entry must be an object.")
        name = str(item.get("name") or "").strip()
        raw_iris_codes = item.get("iris_codes")
        if not name:
            raise InvalidSectorConfigError("Each sector needs a non-empty name.")
        if not isinstance(raw_iris_codes, list):
            raise InvalidSectorConfigError(
                f"Sector {name!r} must define iris_codes as a list."
            )
        iris_codes = tuple(
            normalize_iris_code(str(code))
            for code in raw_iris_codes
            if str(code).strip()
        )
        sectors.append(SectorConfig(name=name, iris_codes=iris_codes))
    return sectors


def load_source_rows(source: DataSource, cache_dir: Path) -> SourceRows:
    """Download/cache and parse one CSV or ZIP source."""
    source_path = resolve_source_path(source.location, cache_dir)
    rows = read_tabular_rows(source_path)
    if not rows:
        logger.warning("No rows found in %s.", source.location)
        return SourceRows(source, {}, {})

    columns_by_normalized_name = build_column_lookup(rows[0].keys())
    iris_column = find_column(columns_by_normalized_name, IRIS_CODE_COLUMNS)
    if iris_column is None:
        raise MissingColumnError(
            f"No IRIS code column found in {source.location}. "
            f"Tried: {', '.join(IRIS_CODE_COLUMNS)}"
        )

    rows_by_iris: dict[str, dict[str, str]] = {}
    for row in rows:
        iris_code = normalize_iris_code(row.get(iris_column, ""))
        if iris_code:
            rows_by_iris[iris_code] = row

    logger.info(
        "Loaded %s IRIS rows from %s (%s).",
        len(rows_by_iris),
        source.name,
        source.vintage,
    )
    return SourceRows(source, rows_by_iris, columns_by_normalized_name)


def build_indicators(
    sectors: Sequence[SectorConfig],
    income_rows: SourceRows,
    population_rows: SourceRows,
    household_rows: SourceRows | None = None,
) -> list[IndicatorResult]:
    """Compute all requested indicators for the configured sectors."""
    household_source = household_rows or population_rows
    results: list[IndicatorResult] = []
    for sector in sectors:
        if not sector.iris_codes:
            raise InvalidSectorConfigError(
                f"Sector {sector.name!r} has no iris_codes. Fill the config before "
                "running the extraction to avoid inventing a perimeter."
            )
        results.extend(
            [
                compute_median_income(sector, income_rows),
                compute_population_75_plus(sector, population_rows),
                compute_75_plus_living_alone(sector, household_source),
                compute_upper_socio_professional_retired(sector, population_rows),
            ]
        )
    return results


def compute_median_income(
    sector: SectorConfig, source_rows: SourceRows
) -> IndicatorResult:
    value_column = require_column(source_rows, INCOME_MEDIAN_COLUMNS, "median income")
    weight_column = find_column(
        source_rows.columns_by_normalized_name, INCOME_WEIGHT_COLUMNS
    )
    values: list[tuple[float, float]] = []
    missing_iris: list[str] = []

    for iris_code in sector.iris_codes:
        row = source_rows.rows_by_iris.get(iris_code)
        if row is None:
            missing_iris.append(iris_code)
            continue
        value = parse_number(row.get(value_column))
        if value is None:
            missing_iris.append(iris_code)
            continue
        weight = parse_number(row.get(weight_column)) if weight_column else None
        values.append((value, weight if weight and weight > 0 else 1.0))

    if not values:
        return unavailable_result(
            sector,
            INDICATOR_MEDIAN_INCOME,
            "EUR",
            source_rows.source,
            "No usable median-income value found for configured IRIS.",
        )

    if len(values) == 1:
        method = f"Direct IRIS value from column {value_column}."
        quality = "source"
        value = values[0][0]
    else:
        value = weighted_median(values)
        if weight_column:
            method = (
                "Weighted median approximation from IRIS medians using "
                f"{weight_column}."
            )
        else:
            method = "Median of IRIS medians; no population weight column was found."
        quality = "approximation"

    return IndicatorResult(
        sector=sector.name,
        indicator=INDICATOR_MEDIAN_INCOME,
        value=value,
        unit="EUR",
        source=source_rows.source.name,
        vintage=source_rows.source.vintage,
        method=method,
        iris_codes=sector.iris_codes,
        quality=quality,
        note=missing_note(missing_iris),
    )


def compute_population_75_plus(
    sector: SectorConfig,
    source_rows: SourceRows,
) -> IndicatorResult:
    value_column = require_column(
        source_rows, POPULATION_75_PLUS_COLUMNS, "75+ population"
    )
    return sum_column_indicator(
        sector,
        source_rows,
        INDICATOR_POPULATION_75_PLUS,
        value_column,
        "persons",
        f"Sum of IRIS values from column {value_column}.",
        "source",
    )


def compute_75_plus_living_alone(
    sector: SectorConfig,
    source_rows: SourceRows,
) -> IndicatorResult:
    value_column = find_column(
        source_rows.columns_by_normalized_name,
        LIVING_ALONE_75_PLUS_COLUMNS,
    )
    if value_column is None:
        return unavailable_result(
            sector,
            INDICATOR_75_PLUS_LIVING_ALONE,
            "persons_or_households",
            source_rows.source,
            "No exact or explicit 75+ living-alone column was found in the source.",
        )
    return sum_column_indicator(
        sector,
        source_rows,
        INDICATOR_75_PLUS_LIVING_ALONE,
        value_column,
        "persons_or_households",
        f"Sum of IRIS values from column {value_column}.",
        "source",
    )


def compute_upper_socio_professional_retired(
    sector: SectorConfig,
    source_rows: SourceRows,
) -> IndicatorResult:
    retired_column = find_column(
        source_rows.columns_by_normalized_name, RETIRED_COLUMNS
    )
    csp_columns = find_columns(
        source_rows.columns_by_normalized_name,
        UPPER_SOCIO_PROFESSIONAL_COLUMNS,
    )
    if retired_column is None or not csp_columns:
        return unavailable_result(
            sector,
            INDICATOR_UPPER_SOCIO_PROFESSIONAL_RETIRED,
            "persons",
            source_rows.source,
            "INSEE IRIS files do not expose a directly reliable retired-CSP+ indicator "
            "through the configured columns; leave null rather than inventing it.",
        )

    retired = sum_numeric_values(
        sector.iris_codes, source_rows.rows_by_iris, retired_column
    )
    csp_plus = sum(
        sum_numeric_values(sector.iris_codes, source_rows.rows_by_iris, column)
        for column in csp_columns
    )
    if retired is None or csp_plus is None:
        return unavailable_result(
            sector,
            INDICATOR_UPPER_SOCIO_PROFESSIONAL_RETIRED,
            "persons",
            source_rows.source,
            "Configured columns were present but no usable numeric values were found.",
        )

    return IndicatorResult(
        sector=sector.name,
        indicator=INDICATOR_UPPER_SOCIO_PROFESSIONAL_RETIRED,
        value=min(retired, csp_plus),
        unit="persons",
        source=source_rows.source.name,
        vintage=source_rows.source.vintage,
        method=(
            f"Approximation: min(sum retired {retired_column}, "
            f"sum CSP+ columns {', '.join(csp_columns)})."
        ),
        iris_codes=sector.iris_codes,
        quality="approximation",
        note=(
            "Approximation only; retired status and former CSP+ are not "
            "cross-tabulated."
        ),
    )


def sum_column_indicator(
    sector: SectorConfig,
    source_rows: SourceRows,
    indicator: str,
    column: str,
    unit: str,
    method: str,
    quality: str,
) -> IndicatorResult:
    missing_iris: list[str] = []
    total = 0.0
    usable_count = 0
    for iris_code in sector.iris_codes:
        row = source_rows.rows_by_iris.get(iris_code)
        value = parse_number(row.get(column)) if row else None
        if value is None:
            missing_iris.append(iris_code)
            continue
        total += value
        usable_count += 1

    if usable_count == 0:
        return unavailable_result(
            sector,
            indicator,
            unit,
            source_rows.source,
            f"No usable values found for column {column}.",
        )

    return IndicatorResult(
        sector=sector.name,
        indicator=indicator,
        value=total,
        unit=unit,
        source=source_rows.source.name,
        vintage=source_rows.source.vintage,
        method=method,
        iris_codes=sector.iris_codes,
        quality=quality,
        note=missing_note(missing_iris),
    )


def save_results(db_path: Path, results: Sequence[IndicatorResult]) -> None:
    """Persist indicator results to SQLite."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS insee_iris_indicators (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sector TEXT NOT NULL,
                indicator TEXT NOT NULL,
                value REAL,
                unit TEXT NOT NULL,
                source TEXT NOT NULL,
                vintage TEXT NOT NULL,
                method TEXT NOT NULL,
                iris_codes TEXT NOT NULL,
                quality TEXT NOT NULL,
                note TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(sector, indicator, source, vintage)
            )
            """
        )
        now = datetime.now(timezone.utc).isoformat()
        connection.executemany(
            """
            INSERT INTO insee_iris_indicators (
                sector, indicator, value, unit, source, vintage, method,
                iris_codes, quality, note, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(sector, indicator, source, vintage) DO UPDATE SET
                value = excluded.value,
                unit = excluded.unit,
                method = excluded.method,
                iris_codes = excluded.iris_codes,
                quality = excluded.quality,
                note = excluded.note,
                created_at = excluded.created_at
            """,
            [
                (
                    result.sector,
                    result.indicator,
                    result.value,
                    result.unit,
                    result.source,
                    result.vintage,
                    result.method,
                    json.dumps(list(result.iris_codes), ensure_ascii=False),
                    result.quality,
                    result.note,
                    now,
                )
                for result in results
            ],
        )
        connection.commit()


def write_results_csv(output_path: Path, results: Sequence[IndicatorResult]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8-sig") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=(
                "sector",
                "indicator",
                "value",
                "unit",
                "source",
                "vintage",
                "quality",
                "method",
                "iris_codes",
                "note",
            ),
        )
        writer.writeheader()
        for result in results:
            writer.writerow(
                {
                    "sector": result.sector,
                    "indicator": result.indicator,
                    "value": "" if result.value is None else result.value,
                    "unit": result.unit,
                    "source": result.source,
                    "vintage": result.vintage,
                    "quality": result.quality,
                    "method": result.method,
                    "iris_codes": ",".join(result.iris_codes),
                    "note": result.note,
                }
            )


def resolve_source_path(location: str, cache_dir: Path) -> Path:
    parsed = urlparse(location)
    if parsed.scheme in {"http", "https"}:
        return download_to_cache(location, cache_dir)
    path = Path(location)
    if not path.exists():
        raise FileNotFoundError(f"Source file not found: {path}")
    return path


def download_to_cache(url: str, cache_dir: Path) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    parsed = urlparse(url)
    suffix = Path(parsed.path).suffix or ".data"
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    target = cache_dir / f"{digest}{suffix}"
    if target.exists() and target.stat().st_size > 0:
        logger.info("Using cached source %s for %s.", target, url)
        return target

    logger.info("Downloading %s to %s.", url, target)
    response = requests.get(url, timeout=DEFAULT_TIMEOUT_SECONDS)
    response.raise_for_status()
    target.write_bytes(response.content)
    return target


def read_tabular_rows(path: Path) -> list[dict[str, str]]:
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            csv_names = [
                name for name in archive.namelist() if name.lower().endswith(".csv")
            ]
            if not csv_names:
                raise ValueError(f"No CSV file found in ZIP archive: {path}")
            with archive.open(csv_names[0]) as raw_file:
                content = raw_file.read().decode("utf-8-sig")
        return parse_csv_text(content)
    return parse_csv_text(path.read_text(encoding="utf-8-sig"))


def parse_csv_text(content: str) -> list[dict[str, str]]:
    sample = content[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(content.splitlines(), dialect=dialect)
    return [dict(row) for row in reader]


def normalize_column_name(name: str) -> str:
    return name.strip().lower().replace(" ", "_").replace("-", "_").replace(".", "_")


def normalize_iris_code(value: str | None) -> str:
    return "" if value is None else str(value).strip().upper()


def build_column_lookup(columns: Iterable[str]) -> dict[str, str]:
    return {normalize_column_name(column): column for column in columns}


def find_column(
    columns_by_normalized_name: Mapping[str, str],
    candidates: Sequence[str],
) -> str | None:
    for candidate in candidates:
        column = columns_by_normalized_name.get(normalize_column_name(candidate))
        if column:
            return column
    return None


def find_columns(
    columns_by_normalized_name: Mapping[str, str],
    candidates: Sequence[str],
) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        column = columns_by_normalized_name.get(normalize_column_name(candidate))
        if column and column not in seen:
            found.append(column)
            seen.add(column)
    return found


def require_column(
    source_rows: SourceRows,
    candidates: Sequence[str],
    label: str,
) -> str:
    column = find_column(source_rows.columns_by_normalized_name, candidates)
    if column is None:
        raise MissingColumnError(
            f"No {label} column found in {source_rows.source.location}. "
            f"Tried: {', '.join(candidates)}"
        )
    return column


def parse_number(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace("\u00a0", "")
    if not text or text.lower() in {"na", "nd", "n.d.", "secret", "s"}:
        return None
    text = text.replace(" ", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def weighted_median(values: Sequence[tuple[float, float]]) -> float:
    ordered = sorted(values, key=lambda item: item[0])
    total_weight = sum(weight for _, weight in ordered)
    threshold = total_weight / 2
    cumulative = 0.0
    for value, weight in ordered:
        cumulative += weight
        if cumulative >= threshold:
            return value
    return ordered[-1][0]


def sum_numeric_values(
    iris_codes: Sequence[str],
    rows_by_iris: Mapping[str, Mapping[str, str]],
    column: str,
) -> float | None:
    total = 0.0
    usable_count = 0
    for iris_code in iris_codes:
        row = rows_by_iris.get(iris_code)
        value = parse_number(row.get(column)) if row else None
        if value is None:
            continue
        total += value
        usable_count += 1
    return total if usable_count else None


def missing_note(missing_iris: Sequence[str]) -> str:
    if not missing_iris:
        return ""
    return "Missing or unusable values for IRIS: " + ", ".join(missing_iris)


def unavailable_result(
    sector: SectorConfig,
    indicator: str,
    unit: str,
    source: DataSource,
    note: str,
) -> IndicatorResult:
    return IndicatorResult(
        sector=sector.name,
        indicator=indicator,
        value=None,
        unit=unit,
        source=source.name,
        vintage=source.vintage,
        method="Unavailable from configured source columns.",
        iris_codes=sector.iris_codes,
        quality="unavailable",
        note=note,
    )
