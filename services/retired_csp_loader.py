"""Load conservative retired CSP+ indicators from INSEE IRIS sources."""

from __future__ import annotations

import csv
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas

SOURCE_NAME = "INSEE Recensement de la population IRIS"
QUALITY_DIRECT_COUNT = "direct_count"
QUALITY_DIRECT_SHARE = "direct_share"
QUALITY_DIRECT_COUNT_AND_SHARE = "direct_count_and_share"
QUALITY_NOT_AVAILABLE = "not_available_directly_at_iris_level"

DIRECT_METRIC_DEFINITION = (
    "retired people formerly executives or higher intellectual professions"
)
UNAVAILABLE_METRIC_DEFINITION = (
    "retired formerly CSP+ indicator is not directly available in configured "
    "INSEE IRIS columns"
)

IRIS_CODE_CANDIDATES = (
    "iris_code",
    "code_iris",
    "codeiris",
    "iris",
    "cod_iris",
    "depcomiris",
)
DIRECT_COUNT_CANDIDATES = (
    "retired_csp_plus_count",
    "retired_former_cadres_count",
    "retired_former_executives_count",
    "retraites_anciens_cadres",
    "retraites_anciens_cadres_pis",
    "retraites_csp_plus",
    "anciens_cadres_retraites",
    "p21_retraites_anciens_cadres",
    "p20_retraites_anciens_cadres",
    "p19_retraites_anciens_cadres",
    "p18_retraites_anciens_cadres",
    "p17_retraites_anciens_cadres",
)
DIRECT_SHARE_CANDIDATES = (
    "retired_csp_plus_share",
    "share_retired_former_cadres",
    "share_retired_former_executives",
    "part_retraites_anciens_cadres",
    "tx_retraites_anciens_cadres",
    "pct_retraites_anciens_cadres",
    "p21_tx_retraites_anciens_cadres",
    "p20_tx_retraites_anciens_cadres",
    "p19_tx_retraites_anciens_cadres",
)


@dataclass(frozen=True)
class RetiredCspDetection:
    iris_code: str
    count_column: str | None
    share_column: str | None
    metric_definition: str
    quality_flag: str
    source_year: str | None


class RetiredCspColumnError(RuntimeError):
    """Raised when a required structural column cannot be detected."""


class UnsupportedRetiredCspFormatError(RuntimeError):
    """Raised when a retired CSP+ source file format is not supported."""


def load_retired_csp_iris(file_path: Path) -> pandas.DataFrame:
    """Load an INSEE IRIS source file into a pandas DataFrame."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Retired CSP+ source file not found: {path}")

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
        raise UnsupportedRetiredCspFormatError(
            f"Unsupported retired CSP+ file format: {suffix or '<none>'}"
        )

    df.attrs["source_name"] = SOURCE_NAME
    df.attrs["source_year"] = detect_source_year(path.name, df.columns)
    return df


def extract_retired_csp_plus_by_iris(df: pandas.DataFrame) -> pandas.DataFrame:
    """Extract a direct retired CSP+ indicator, or mark it unavailable."""
    detection = detect_metric_columns(df)
    if detection.count_column:
        count = df[detection.count_column].map(parse_number)
    else:
        count = pandas.Series([None] * len(df), index=df.index, dtype="object")

    if detection.share_column:
        share = df[detection.share_column].map(parse_number).map(normalize_share)
    else:
        share = pandas.Series([None] * len(df), index=df.index, dtype="object")

    output = pandas.DataFrame(
        {
            "iris_code": df[detection.iris_code].map(normalize_text),
            "retired_csp_plus_count": count,
            "retired_csp_plus_share": share,
            "metric_definition": detection.metric_definition,
            "quality_flag": detection.quality_flag,
            "source_name": df.attrs.get("source_name", SOURCE_NAME),
            "source_year": df.attrs.get("source_year") or detection.source_year,
        }
    )
    output = output.dropna(subset=["iris_code"])
    return output.reset_index(drop=True)


def detect_metric_columns(df: pandas.DataFrame) -> RetiredCspDetection:
    columns_by_normalized_name = build_column_lookup(df.columns)
    iris_code = find_column(columns_by_normalized_name, IRIS_CODE_CANDIDATES)
    if iris_code is None:
        raise missing_column_error("IRIS code", IRIS_CODE_CANDIDATES, df.columns)

    count_column = find_column(columns_by_normalized_name, DIRECT_COUNT_CANDIDATES)
    share_column = find_column(columns_by_normalized_name, DIRECT_SHARE_CANDIDATES)
    if count_column and share_column:
        quality_flag = QUALITY_DIRECT_COUNT_AND_SHARE
        metric_definition = DIRECT_METRIC_DEFINITION
    elif count_column:
        quality_flag = QUALITY_DIRECT_COUNT
        metric_definition = DIRECT_METRIC_DEFINITION
    elif share_column:
        quality_flag = QUALITY_DIRECT_SHARE
        metric_definition = DIRECT_METRIC_DEFINITION
    else:
        quality_flag = QUALITY_NOT_AVAILABLE
        metric_definition = UNAVAILABLE_METRIC_DEFINITION

    return RetiredCspDetection(
        iris_code=iris_code,
        count_column=count_column,
        share_column=share_column,
        metric_definition=metric_definition,
        quality_flag=quality_flag,
        source_year=detect_source_year("", df.columns),
    )


def read_csv(path: Path) -> pandas.DataFrame:
    separator = detect_csv_separator(path)
    return pandas.read_csv(path, sep=separator, dtype=str, encoding="utf-8-sig")


def read_csv_from_zip(path: Path) -> pandas.DataFrame:
    with zipfile.ZipFile(path) as archive:
        csv_names = [
            name for name in archive.namelist() if name.lower().endswith(".csv")
        ]
        if not csv_names:
            raise UnsupportedRetiredCspFormatError(
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
    return None


def missing_column_error(
    label: str,
    candidates: tuple[str, ...],
    columns: Any,
) -> RetiredCspColumnError:
    available_columns = [str(column) for column in columns]
    return RetiredCspColumnError(
        f"Unable to detect retired CSP+ {label} column. "
        f"Candidate columns: {', '.join(candidates)}. "
        f"Available columns: {', '.join(available_columns)}"
    )


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


def normalize_share(value: float | None) -> float | None:
    if value is None:
        return None
    if value > 1:
        return value / 100
    return value


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
