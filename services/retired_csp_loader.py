"""Load conservative retired and CSP+ marginal indicators from INSEE IRIS sources."""

from __future__ import annotations

import csv
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas

SOURCE_NAME = "INSEE Recensement de la population IRIS"
QUALITY_BOTH_AVAILABLE = "retired_and_csp_plus_available"
QUALITY_RETIRED_ONLY = "retired_count_available"
QUALITY_CSP_PLUS_ONLY = "csp_plus_15_plus_count_available"
QUALITY_NOT_AVAILABLE = "not_available_directly_at_iris_level"

METRIC_DEFINITION = (
    "separate marginal indicators: retired people count and CSP+ population aged "
    "15+ count"
)
QUALITY_NOTE = (
    "retired_count and csp_plus_15_plus_count are separate indicators; they are "
    "not equivalent to retired formerly CSP+ people"
)
CSP_PLUS_UNAVAILABLE_NOTE = (
    "csp_plus_15_plus_count unavailable because no GSEC metadata label explicitly "
    "mentions cadres or professions intellectuelles supérieures"
)
GSEC_METADATA_ATTR = "gsec_metadata"

IRIS_CODE_CANDIDATES = (
    "iris_code",
    "code_iris",
    "codeiris",
    "iris",
    "cod_iris",
    "depcomiris",
)
RETIRED_COUNT_CANDIDATES = (
    "retired_count",
    "c22_pop15p_stat_gsec32",
    "retraites",
    "retraites_count",
    "pop15p_retraites",
    "population_15_plus_retired",
    "p22_pop15p_retraites",
    "c22_pop15p_retraites",
    "p21_pop15p_retraites",
    "c21_pop15p_retraites",
    "p20_pop15p_retraites",
    "p19_pop15p_retraites",
)
CSP_PLUS_15_PLUS_COUNT_CANDIDATES = (
    "csp_plus_15_plus_count",
    "c22_pop15p_stat_gsec13_23",
    "cadres_professions_intellectuelles_superieures_15_plus",
    "cadres_15_plus",
    "cs3_15_plus",
    "pop15p_cs3",
    "p22_pop15p_cs3",
    "c22_pop15p_cs3",
    "p21_pop15p_cs3",
    "c21_pop15p_cs3",
    "p20_pop15p_cs3",
    "p19_pop15p_cs3",
)


@dataclass(frozen=True)
class RetiredCspDetection:
    iris_code: str
    retired_count_column: str | None
    csp_plus_15_plus_count_column: str | None
    metric_definition: str
    quality_flag: str
    quality_note: str
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
        df.attrs[GSEC_METADATA_ATTR] = read_gsec_metadata_from_zip(path)
    elif suffix in {".xlsx", ".xls"}:
        df = pandas.read_excel(path, dtype=str)
    elif suffix == ".parquet":
        df = pandas.read_parquet(path)
    else:
        raise UnsupportedRetiredCspFormatError(
            f"Unsupported retired CSP+ file format: {suffix or '<none>'}"
        )

    df.attrs["source_path"] = str(path)
    df.attrs["source_name"] = SOURCE_NAME
    df.attrs["source_year"] = detect_source_year(path.name, df.columns)
    return df


def extract_retired_csp_plus_by_iris(df: pandas.DataFrame) -> pandas.DataFrame:
    """Extract safer marginal retired and CSP+ indicators by IRIS."""
    detection = detect_metric_columns(df)
    if detection.retired_count_column:
        retired_count = df[detection.retired_count_column].map(parse_number)
    else:
        retired_count = pandas.Series([None] * len(df), index=df.index, dtype="object")

    if detection.csp_plus_15_plus_count_column:
        csp_plus_count = df[detection.csp_plus_15_plus_count_column].map(parse_number)
    else:
        csp_plus_count = pandas.Series([None] * len(df), index=df.index, dtype="object")

    output = pandas.DataFrame(
        {
            "iris_code": df[detection.iris_code].map(normalize_text),
            "retired_count": retired_count,
            "csp_plus_15_plus_count": csp_plus_count,
            "metric_definition": detection.metric_definition,
            "quality_flag": detection.quality_flag,
            "quality_note": detection.quality_note,
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
        raise missing_column_error("IRIS code", IRIS_CODE_CANDIDATES, df)

    retired_count_column = find_column(
        columns_by_normalized_name,
        RETIRED_COUNT_CANDIDATES,
    )
    csp_plus_15_plus_count_column = find_column(
        columns_by_normalized_name,
        CSP_PLUS_15_PLUS_COUNT_CANDIDATES,
    )
    csp_plus_15_plus_count_column = validate_csp_plus_column(
        csp_plus_15_plus_count_column,
        df,
    )
    if retired_count_column and csp_plus_15_plus_count_column:
        quality_flag = QUALITY_BOTH_AVAILABLE
    elif retired_count_column:
        quality_flag = QUALITY_RETIRED_ONLY
    elif csp_plus_15_plus_count_column:
        quality_flag = QUALITY_CSP_PLUS_ONLY
    else:
        raise retired_csp_metric_error(df)

    return RetiredCspDetection(
        iris_code=iris_code,
        retired_count_column=retired_count_column,
        csp_plus_15_plus_count_column=csp_plus_15_plus_count_column,
        metric_definition=METRIC_DEFINITION,
        quality_flag=quality_flag,
        quality_note=build_quality_note(csp_plus_15_plus_count_column, df),
        source_year=detect_source_year("", df.columns),
    )


def read_csv(path: Path) -> pandas.DataFrame:
    separator = detect_csv_separator(path)
    return pandas.read_csv(path, sep=separator, dtype=str, encoding="utf-8-sig")


def read_csv_from_zip(path: Path) -> pandas.DataFrame:
    with zipfile.ZipFile(path) as archive:
        csv_names = [
            name
            for name in archive.namelist()
            if name.lower().endswith(".csv") and "meta" not in name.lower()
        ]
        if not csv_names:
            raise UnsupportedRetiredCspFormatError(
                f"No CSV found in ZIP archive: {path}"
            )
        with archive.open(csv_names[0]) as csv_file:
            return pandas.read_csv(csv_file, sep=None, engine="python", dtype=str)


def read_gsec_metadata_from_zip(path: Path) -> dict[str, str]:
    with zipfile.ZipFile(path) as archive:
        meta_names = [
            name
            for name in archive.namelist()
            if name.lower().endswith(".csv") and "meta" in name.lower()
        ]
        if not meta_names:
            return {}
        content = archive.read(meta_names[0]).decode("utf-8-sig", errors="ignore")
    rows = csv.DictReader(content.splitlines(), delimiter=";")
    metadata: dict[str, str] = {}
    for row in rows:
        code = str(row.get("COD_VAR") or "").strip()
        if not code.startswith("C22_POP15P_STAT_GSEC"):
            continue
        label = " ".join(
            part.strip()
            for part in (
                str(row.get("LIB_VAR") or ""),
                str(row.get("LIB_VAR_LONG") or ""),
            )
            if part
        )
        metadata[code] = label
    return metadata


def format_gsec_metadata(metadata: dict[str, str]) -> str:
    if not metadata:
        return "No C22_POP15P_STAT_GSEC metadata found."
    return "\n".join(
        f"{column}: {label}" for column, label in sorted(metadata.items())
    )


def validate_csp_plus_column(
    column: str | None,
    df: pandas.DataFrame,
) -> str | None:
    if column is None:
        return None
    metadata = df.attrs.get(GSEC_METADATA_ATTR) or {}
    if not metadata:
        return column
    label = metadata.get(column)
    if label and is_csp_plus_label(label):
        return column
    return None


def is_csp_plus_label(label: str) -> bool:
    normalized = normalize_column_name(label)
    return (
        "cadre" in normalized
        or "professions_intellectuelles_superieures" in normalized
    )


def build_quality_note(
    csp_plus_15_plus_count_column: str | None,
    df: pandas.DataFrame,
) -> str:
    if csp_plus_15_plus_count_column:
        return QUALITY_NOTE
    metadata = df.attrs.get(GSEC_METADATA_ATTR) or {}
    if metadata:
        return QUALITY_NOTE + ". " + CSP_PLUS_UNAVAILABLE_NOTE
    return QUALITY_NOTE


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
        strip_year_prefix(strip_year_suffix(normalize_column_name(item)))
        for item in candidates
    }
    for normalized_name, original_name in columns_by_normalized_name.items():
        comparable_name = strip_year_prefix(strip_year_suffix(normalized_name))
        if comparable_name in candidate_roots:
            return original_name
    return None


def missing_column_error(
    label: str,
    candidates: tuple[str, ...],
    df: pandas.DataFrame,
) -> RetiredCspColumnError:
    available_columns = [str(column) for column in df.columns]
    found_candidates = find_candidate_columns(available_columns)
    return RetiredCspColumnError(
        f"Unable to detect retired/CSP marginal {label} column. "
        f"File read: {df.attrs.get('source_path', '<dataframe>')}. "
        "Searched motifs: IRIS, RETR, RETRAITE, CS, CSP, CADRE, POP15P, P22, C22. "
        f"Candidate columns: {', '.join(candidates)}. "
        f"Candidate columns found: {', '.join(found_candidates) or 'none'}. "
        f"Available columns: {', '.join(available_columns)}"
    )


def retired_csp_metric_error(df: pandas.DataFrame) -> RetiredCspColumnError:
    available_columns = [str(column) for column in df.columns]
    found_candidates = find_candidate_columns(available_columns)
    return RetiredCspColumnError(
        "Unable to detect retired_count or csp_plus_15_plus_count proxy columns. "
        f"File read: {df.attrs.get('source_path', '<dataframe>')}. "
        "Searched motifs: IRIS, RETR, RETRAITE, CS, CSP, CADRE, POP15P, P22, C22. "
        "Retired count candidates: "
        f"{', '.join(RETIRED_COUNT_CANDIDATES)}. "
        "CSP+ 15+ count candidates: "
        f"{', '.join(CSP_PLUS_15_PLUS_COUNT_CANDIDATES)}. "
        f"Candidate columns found: {', '.join(found_candidates) or 'none'}. "
        f"Available columns: {', '.join(available_columns)}"
    )


def find_candidate_columns(columns: list[str]) -> list[str]:
    motifs = ("iris", "retr", "retraite", "cs", "csp", "cadre", "pop15p", "p22", "c22")
    return [
        column
        for column in columns
        if any(motif in normalize_column_name(column) for motif in motifs)
    ]


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
