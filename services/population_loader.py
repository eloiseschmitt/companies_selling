"""Load INSEE census IRIS population data and compute 75+ population."""

from __future__ import annotations

import csv
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas

SOURCE_NAME = "INSEE Recensement de la population IRIS"
QUALITY_EXACT = "exact"
QUALITY_APPROXIMATE = "approximate_age_bands"
QUALITY_UNAVAILABLE = "unavailable_age_bands"

IRIS_CODE_CANDIDATES = (
    "iris_code",
    "code_iris",
    "codeiris",
    "iris",
    "cod_iris",
    "depcomiris",
)
POPULATION_TOTAL_CANDIDATES = (
    "population_total",
    "population",
    "pop_total",
    "p21_pop",
    "p20_pop",
    "p19_pop",
    "p18_pop",
    "p17_pop",
)
DIRECT_75_PLUS_CANDIDATES = (
    "population_75_plus",
    "pop75p",
    "pop_75p",
    "pop_75_plus",
    "p21_pop75p",
    "p20_pop75p",
    "p19_pop75p",
    "p18_pop75p",
    "p17_pop75p",
)
EXACT_AGE_BAND_CANDIDATE_GROUPS = (
    ("75_79", "80_84", "85_89", "90_plus"),
    ("75_79", "80_84", "85_plus"),
    ("75_84", "85_plus"),
)
APPROXIMATE_AGE_BAND_CANDIDATE_GROUPS = (
    ("60_74", "75_plus"),
    ("65_79", "80_plus"),
    ("70_79", "80_plus"),
)
AGE_BAND_ALIASES = {
    "75_79": (
        "population_75_79",
        "pop75_79",
        "pop_75_79",
        "p21_pop7579",
        "p20_pop7579",
        "p19_pop7579",
        "p18_pop7579",
        "p17_pop7579",
    ),
    "80_84": (
        "population_80_84",
        "pop80_84",
        "pop_80_84",
        "p21_pop8084",
        "p20_pop8084",
        "p19_pop8084",
        "p18_pop8084",
        "p17_pop8084",
    ),
    "85_89": (
        "population_85_89",
        "pop85_89",
        "pop_85_89",
        "p21_pop8589",
        "p20_pop8589",
        "p19_pop8589",
        "p18_pop8589",
        "p17_pop8589",
    ),
    "90_plus": (
        "population_90_plus",
        "population_90p",
        "pop90p",
        "pop_90_plus",
        "p21_pop90p",
        "p20_pop90p",
        "p19_pop90p",
        "p18_pop90p",
        "p17_pop90p",
    ),
    "85_plus": (
        "population_85_plus",
        "population_85p",
        "pop85p",
        "pop_85_plus",
        "p21_pop85p",
        "p20_pop85p",
        "p19_pop85p",
        "p18_pop85p",
        "p17_pop85p",
    ),
    "75_84": (
        "population_75_84",
        "pop75_84",
        "pop_75_84",
        "p21_pop7584",
        "p20_pop7584",
        "p19_pop7584",
        "p18_pop7584",
        "p17_pop7584",
    ),
    "75_plus": DIRECT_75_PLUS_CANDIDATES,
    "60_74": (
        "population_60_74",
        "pop60_74",
        "pop_60_74",
        "p21_pop6074",
        "p20_pop6074",
        "p19_pop6074",
    ),
    "65_79": (
        "population_65_79",
        "pop65_79",
        "pop_65_79",
        "p21_pop6579",
        "p20_pop6579",
        "p19_pop6579",
    ),
    "70_79": (
        "population_70_79",
        "pop70_79",
        "pop_70_79",
        "p21_pop7079",
        "p20_pop7079",
        "p19_pop7079",
    ),
    "80_plus": (
        "population_80_plus",
        "population_80p",
        "pop80p",
        "pop_80_plus",
        "p21_pop80p",
        "p20_pop80p",
        "p19_pop80p",
    ),
}


@dataclass(frozen=True)
class PopulationColumnDetection:
    iris_code: str
    population_total: str | None
    population_75_plus_columns: tuple[str, ...]
    quality_flag: str
    source_year: str | None


class PopulationColumnError(RuntimeError):
    """Raised when required population columns cannot be detected."""


class UnsupportedPopulationFormatError(RuntimeError):
    """Raised when a population source file format is not supported."""


def load_population_iris(file_path: Path) -> pandas.DataFrame:
    """Load an INSEE IRIS census source file into a pandas DataFrame."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Population source file not found: {path}")

    suffix = path.suffix.lower()
    if suffix == ".csv":
        df = read_csv(path)
    elif suffix == ".zip":
        df = read_csv_from_zip(path)
    elif suffix in {".xlsx", ".xls"}:
        df = pandas.read_excel(path, dtype=str)
    elif suffix == ".parquet":
        df = pandas.read_parquet(path)
    else:
        raise UnsupportedPopulationFormatError(
            f"Unsupported population file format: {suffix or '<none>'}"
        )

    df.attrs["source_name"] = SOURCE_NAME
    df.attrs["source_year"] = detect_source_year(path.name, df.columns)
    return df


def extract_population_75_plus_by_iris(df: pandas.DataFrame) -> pandas.DataFrame:
    """Compute population aged 75+ by IRIS."""
    detection = detect_columns(df)
    population_75_plus = sum_numeric_columns(df, detection.population_75_plus_columns)
    output = pandas.DataFrame(
        {
            "iris_code": df[detection.iris_code].map(normalize_text),
            "population_75_plus": population_75_plus,
            "source_name": df.attrs.get("source_name", SOURCE_NAME),
            "source_year": df.attrs.get("source_year") or detection.source_year,
            "quality_flag": detection.quality_flag,
        }
    )

    if detection.population_total:
        output.insert(
            1,
            "population_total",
            df[detection.population_total].map(parse_number),
        )
    else:
        output.insert(1, "population_total", None)

    output = output.dropna(subset=["iris_code"])
    return output.reset_index(drop=True)


def detect_columns(df: pandas.DataFrame) -> PopulationColumnDetection:
    columns_by_normalized_name = build_column_lookup(df.columns)
    iris_code = find_column(columns_by_normalized_name, IRIS_CODE_CANDIDATES)
    if iris_code is None:
        raise missing_column_error("IRIS code", IRIS_CODE_CANDIDATES, df.columns)

    population_total = find_column(
        columns_by_normalized_name,
        POPULATION_TOTAL_CANDIDATES,
    )
    age_columns, quality_flag = detect_age_columns(columns_by_normalized_name)
    return PopulationColumnDetection(
        iris_code=iris_code,
        population_total=population_total,
        population_75_plus_columns=age_columns,
        quality_flag=quality_flag,
        source_year=detect_source_year("", df.columns),
    )


def detect_age_columns(
    columns_by_normalized_name: dict[str, str],
) -> tuple[tuple[str, ...], str]:
    direct_column = find_column(columns_by_normalized_name, DIRECT_75_PLUS_CANDIDATES)
    if direct_column:
        return (direct_column,), QUALITY_EXACT

    for group in EXACT_AGE_BAND_CANDIDATE_GROUPS:
        columns = find_age_band_group(columns_by_normalized_name, group)
        if columns:
            return columns, QUALITY_EXACT

    for group in APPROXIMATE_AGE_BAND_CANDIDATE_GROUPS:
        columns = find_age_band_group(columns_by_normalized_name, group)
        if columns:
            return columns, QUALITY_APPROXIMATE

    available_columns = ", ".join(columns_by_normalized_name.values())
    candidate_groups = [
        "+".join(group)
        for group in [
            *EXACT_AGE_BAND_CANDIDATE_GROUPS,
            *APPROXIMATE_AGE_BAND_CANDIDATE_GROUPS,
        ]
    ]
    raise PopulationColumnError(
        "Unable to detect age columns for population 75+. "
        f"Candidate groups: {', '.join(candidate_groups)}. "
        f"Available columns: {available_columns}"
    )


def find_age_band_group(
    columns_by_normalized_name: dict[str, str],
    group: tuple[str, ...],
) -> tuple[str, ...] | None:
    columns: list[str] = []
    for age_band in group:
        column = find_column(columns_by_normalized_name, AGE_BAND_ALIASES[age_band])
        if column is None:
            return None
        columns.append(column)
    return tuple(columns)


def read_csv(path: Path) -> pandas.DataFrame:
    separator = detect_csv_separator(path)
    return pandas.read_csv(path, sep=separator, dtype=str, encoding="utf-8-sig")


def read_csv_from_zip(path: Path) -> pandas.DataFrame:
    with zipfile.ZipFile(path) as archive:
        csv_names = [
            name for name in archive.namelist() if name.lower().endswith(".csv")
        ]
        if not csv_names:
            raise UnsupportedPopulationFormatError(
                f"No CSV found in ZIP archive: {path}"
            )
        with archive.open(csv_names[0]) as csv_file:
            return pandas.read_csv(csv_file, sep=None, engine="python", dtype=str)


def detect_csv_separator(path: Path) -> str | None:
    sample = path.read_text(encoding="utf-8-sig", errors="ignore")[:4096]
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
    except csv.Error:
        return None


def build_column_lookup(columns: Any) -> dict[str, str]:
    return {normalize_column_name(str(column)): str(column) for column in columns}


def find_column(
    columns_by_normalized_name: dict[str, str],
    candidates: tuple[str, ...],
) -> str | None:
    for candidate in candidates:
        exact = columns_by_normalized_name.get(normalize_column_name(candidate))
        if exact:
            return exact

    candidate_roots = {
        strip_year_suffix(normalize_column_name(item)) for item in candidates
    }
    for normalized_name, original_name in columns_by_normalized_name.items():
        if strip_year_suffix(normalized_name) in candidate_roots:
            return original_name
        if strip_year_prefix(normalized_name) in {
            strip_year_prefix(candidate_root) for candidate_root in candidate_roots
        }:
            return original_name
    return None


def missing_column_error(
    label: str,
    candidates: tuple[str, ...],
    columns: Any,
) -> PopulationColumnError:
    available_columns = [str(column) for column in columns]
    return PopulationColumnError(
        f"Unable to detect population {label} column. "
        f"Candidate columns: {', '.join(candidates)}. "
        f"Available columns: {', '.join(available_columns)}"
    )


def sum_numeric_columns(
    df: pandas.DataFrame,
    columns: tuple[str, ...],
) -> pandas.Series:
    values = pandas.DataFrame(
        {column: df[column].map(parse_number) for column in columns}
    )
    return values.sum(axis=1, min_count=1)


def normalize_column_name(name: str) -> str:
    return (
        name.strip()
        .lower()
        .replace("\ufeff", "")
        .replace(" ", "_")
        .replace("-", "_")
        .replace(".", "_")
    )


def normalize_text(value: Any) -> str | None:
    if value is None or pandas.isna(value):
        return None
    text = str(value).strip()
    return text or None


def parse_number(value: Any) -> float | None:
    if value is None or pandas.isna(value):
        return None
    text = str(value).strip().replace("\u00a0", "")
    if not text or text.lower() in {"na", "nd", "n.d.", "secret", "s"}:
        return None
    text = text.replace(" ", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def detect_source_year(filename: str, columns: Any) -> str | None:
    values = [filename, *(str(column) for column in columns)]
    for value in values:
        match = re.search(r"(?<!\d)(20\d{2})(?!\d)", value)
        if match:
            return match.group(1)
        short_match = re.search(r"(?:^|_)(\d{2})(?:$|_)", normalize_column_name(value))
        if short_match:
            year = int(short_match.group(1))
            if 10 <= year <= 99:
                return f"20{year:02d}"
    return None


def strip_year_suffix(value: str) -> str:
    without_four_digit_year = re.sub(r"_?20\d{2}$", "", value)
    return re.sub(r"_?\d{2}$", "", without_four_digit_year)


def strip_year_prefix(value: str) -> str:
    return re.sub(r"^[pc]\d{2}_", "", value)
