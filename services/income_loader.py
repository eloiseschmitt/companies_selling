"""Load INSEE Filosofi IRIS median disposable income data."""

from __future__ import annotations

import csv
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas

SOURCE_NAME = "INSEE Filosofi IRIS"

IRIS_CODE_CANDIDATES = (
    "iris_code",
    "code_iris",
    "codeiris",
    "iris",
    "cod_iris",
    "depcomiris",
)
IRIS_LABEL_CANDIDATES = (
    "iris_label",
    "libelle_iris",
    "lib_iris",
    "libiris",
    "nom_iris",
)
COMMUNE_CODE_CANDIDATES = (
    "commune_code",
    "code_commune",
    "com",
    "depcom",
    "codgeo",
)
MEDIAN_INCOME_CANDIDATES = (
    "median_disposable_income",
    "mediane_revenu_disponible_uc",
    "mediane_niveau_vie",
    "revenu_disponible_median_uc",
    "dec_med",
    "dec_med21",
    "dec_med20",
    "dec_med19",
    "dec_med18",
    "dec_med17",
    "disp_med",
    "disp_med21",
    "disp_med20",
    "disp_med19",
    "disp_med18",
    "disp_med17",
    "q2_disp",
    "med_disp",
    "mediane_disp",
    "niveau_vie_median",
)


@dataclass(frozen=True)
class ColumnDetection:
    iris_code: str
    median_income: str
    iris_label: str | None
    commune_code: str | None
    source_year: str | None


class FilosofiColumnError(RuntimeError):
    """Raised when a required Filosofi column cannot be detected."""


class UnsupportedFilosofiFormatError(RuntimeError):
    """Raised when a Filosofi source file format is not supported."""


def load_filosofi_iris(file_path: Path) -> pandas.DataFrame:
    """Load a Filosofi IRIS source file into a pandas DataFrame."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Filosofi source file not found: {path}")

    suffix = path.suffix.lower()
    if suffix == ".csv":
        df = read_csv(path)
    elif suffix == ".zip":
        df = read_rows_from_zip(path)
    elif suffix in {".xlsx", ".xls"}:
        df = read_excel_with_detected_header(path)
    elif suffix == ".parquet":
        df = pandas.read_parquet(path)
    else:
        raise UnsupportedFilosofiFormatError(
            f"Unsupported Filosofi file format: {suffix or '<none>'}"
        )

    df.attrs["source_name"] = SOURCE_NAME
    df.attrs["source_year"] = detect_source_year(path.name, df.columns)
    return df


def extract_median_income_by_iris(df: pandas.DataFrame) -> pandas.DataFrame:
    """Extract median disposable income by IRIS from a Filosofi DataFrame."""
    detection = detect_columns(df)
    output = pandas.DataFrame(
        {
            "iris_code": df[detection.iris_code].map(normalize_text),
            "median_disposable_income": df[detection.median_income].map(parse_number),
            "source_name": df.attrs.get("source_name", SOURCE_NAME),
            "source_year": df.attrs.get("source_year") or detection.source_year,
        }
    )

    if detection.iris_label:
        output.insert(1, "iris_label", df[detection.iris_label].map(normalize_text))
    else:
        output.insert(1, "iris_label", None)

    if detection.commune_code:
        output.insert(2, "commune_code", df[detection.commune_code].map(normalize_text))
    else:
        output.insert(2, "commune_code", None)

    output = output.dropna(subset=["iris_code", "median_disposable_income"])
    return output.reset_index(drop=True)


def detect_columns(df: pandas.DataFrame) -> ColumnDetection:
    columns_by_normalized_name = build_column_lookup(df.columns)
    iris_code = find_column(columns_by_normalized_name, IRIS_CODE_CANDIDATES)
    if iris_code is None:
        raise missing_column_error("IRIS code", IRIS_CODE_CANDIDATES, df.columns)

    median_income = find_column(columns_by_normalized_name, MEDIAN_INCOME_CANDIDATES)
    if median_income is None:
        raise missing_column_error(
            "median disposable income",
            MEDIAN_INCOME_CANDIDATES,
            df.columns,
        )

    return ColumnDetection(
        iris_code=iris_code,
        median_income=median_income,
        iris_label=find_column(columns_by_normalized_name, IRIS_LABEL_CANDIDATES),
        commune_code=find_column(columns_by_normalized_name, COMMUNE_CODE_CANDIDATES),
        source_year=detect_source_year("", df.columns),
    )


def read_csv(path: Path) -> pandas.DataFrame:
    separator = detect_csv_separator(path)
    return pandas.read_csv(path, sep=separator, dtype=str, encoding="utf-8-sig")


def read_rows_from_zip(path: Path) -> pandas.DataFrame:
    with zipfile.ZipFile(path) as archive:
        csv_names = [
            name for name in archive.namelist() if name.lower().endswith(".csv")
        ]
        if csv_names:
            with archive.open(csv_names[0]) as csv_file:
                return pandas.read_csv(csv_file, sep=None, engine="python", dtype=str)

        excel_names = [
            name
            for name in archive.namelist()
            if name.lower().endswith((".xlsx", ".xls"))
        ]
        if excel_names:
            with archive.open(excel_names[0]) as excel_file:
                return read_excel_with_detected_header(excel_file)

    raise UnsupportedFilosofiFormatError(
        f"No CSV or Excel file found in ZIP archive: {path}"
    )


def read_excel_with_detected_header(source: object) -> pandas.DataFrame:
    raw_df = pandas.read_excel(source, header=None, dtype=str)
    header_index = find_excel_header_index(raw_df)
    if header_index is None:
        raise UnsupportedFilosofiFormatError(
            "Unable to detect Filosofi header row in Excel file."
        )

    df = raw_df.iloc[header_index + 1 :].copy()
    df.columns = [str(value).strip() for value in raw_df.iloc[header_index]]
    df = df.dropna(how="all")
    return df


def find_excel_header_index(df: pandas.DataFrame) -> int | None:
    iris_candidates = {normalize_column_name(column) for column in IRIS_CODE_CANDIDATES}
    income_candidates = {
        normalize_column_name(column) for column in MEDIAN_INCOME_CANDIDATES
    }
    for index, row in df.iterrows():
        values = {normalize_column_name(str(value)) for value in row.dropna()}
        if values & iris_candidates and values & income_candidates:
            return int(index)
    return None


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
) -> FilosofiColumnError:
    available_columns = [str(column) for column in columns]
    return FilosofiColumnError(
        f"Unable to detect Filosofi {label} column. "
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
