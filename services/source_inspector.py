"""Inspect local INSEE source files for debugging column mappings."""

from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

import pandas

SEARCH_PATTERNS = (
    "AGE",
    "AGED",
    "75",
    "SEUL",
    "MEN",
    "MENAGE",
    "FAM",
    "CS",
    "CSP",
    "RETR",
    "P15",
    "P20",
    "P22",
)
IRIS_COLUMN_CANDIDATES = ("IRIS", "CODE_IRIS", "CODEIRIS", "DEPcomIRIS", "iris")


@dataclass(frozen=True)
class InspectedTable:
    name: str
    columns: list[str]
    row_count: int
    distinct_iris_count: int | None
    matching_columns: list[str]
    preview: pandas.DataFrame


def inspect_source(path: Path) -> list[InspectedTable]:
    """Return table summaries for a CSV, Excel, Parquet, or ZIP source."""
    source_path = Path(path)
    if not source_path.exists():
        raise FileNotFoundError(f"Source file not found: {source_path}")

    suffix = source_path.suffix.lower()
    if suffix == ".zip":
        return inspect_zip(source_path)
    return [inspect_table(source_path.name, read_table(source_path))]


def inspect_zip(path: Path) -> list[InspectedTable]:
    tables: list[InspectedTable] = []
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if not name.lower().endswith((".csv", ".xlsx", ".xls", ".parquet")):
                continue
            with archive.open(name) as file_obj:
                df = read_table_from_file_obj(name, file_obj)
            tables.append(inspect_table(name, df))
    if not tables:
        raise ValueError(f"No supported table found in ZIP archive: {path}")
    return tables


def read_table(path: Path) -> pandas.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return read_csv_bytes(path.read_bytes())
    if suffix in {".xlsx", ".xls"}:
        return read_excel_detect_header(path)
    if suffix == ".parquet":
        return pandas.read_parquet(path)
    raise ValueError(f"Unsupported source format: {suffix or '<none>'}")


def read_table_from_file_obj(name: str, file_obj: IO[bytes]) -> pandas.DataFrame:
    suffix = Path(name).suffix.lower()
    content = file_obj.read()
    if suffix == ".csv":
        return read_csv_bytes(content)
    if suffix in {".xlsx", ".xls"}:
        return read_excel_detect_header(content)
    if suffix == ".parquet":
        return pandas.read_parquet(io.BytesIO(content))
    raise ValueError(f"Unsupported internal file format: {name}")


def read_csv_bytes(content: bytes) -> pandas.DataFrame:
    text = decode_text(content)
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
        separator = dialect.delimiter
    except csv.Error:
        separator = None
    return pandas.read_csv(
        io.StringIO(text),
        sep=separator,
        engine="python" if separator is None else "c",
        dtype=str,
    )


def read_excel_detect_header(source: object) -> pandas.DataFrame:
    excel_source = make_seekable(source)
    raw_df = pandas.read_excel(excel_source, header=None, dtype=str)
    header_index = find_header_index(raw_df)
    if header_index is None:
        excel_source.seek(0)
        return pandas.read_excel(excel_source, dtype=str)
    df = raw_df.iloc[header_index + 1 :].copy()
    df.columns = [str(value).strip() for value in raw_df.iloc[header_index]]
    return df.dropna(how="all")


def make_seekable(source: object) -> Any:
    if isinstance(source, bytes):
        return io.BytesIO(source)
    if isinstance(source, Path):
        return source.open("rb")
    return source


def find_header_index(df: pandas.DataFrame) -> int | None:
    for row_index, (_, row) in enumerate(df.iterrows()):
        values = {str(value).strip().upper() for value in row.dropna()}
        if values & {candidate.upper() for candidate in IRIS_COLUMN_CANDIDATES}:
            return row_index
    return None


def inspect_table(name: str, df: pandas.DataFrame) -> InspectedTable:
    columns = [str(column) for column in df.columns]
    iris_column = find_iris_column(columns)
    distinct_iris_count = None
    if iris_column is not None:
        distinct_iris_count = int(df[iris_column].dropna().astype(str).nunique())
    return InspectedTable(
        name=name,
        columns=columns,
        row_count=int(len(df)),
        distinct_iris_count=distinct_iris_count,
        matching_columns=find_matching_columns(columns),
        preview=df.head(5),
    )


def find_iris_column(columns: list[str]) -> str | None:
    normalized = {normalize_column(column): column for column in columns}
    for candidate in IRIS_COLUMN_CANDIDATES:
        column = normalized.get(normalize_column(candidate))
        if column:
            return column
    return None


def find_matching_columns(columns: list[str]) -> list[str]:
    matches: list[str] = []
    for column in columns:
        upper_column = column.upper()
        if any(pattern in upper_column for pattern in SEARCH_PATTERNS):
            matches.append(column)
    return matches


def format_inspection(tables: list[InspectedTable]) -> str:
    lines: list[str] = []
    for table in tables:
        lines.extend(
            [
                f"# {table.name}",
                f"Rows: {table.row_count}",
                "Distinct IRIS: "
                + (
                    "unknown"
                    if table.distinct_iris_count is None
                    else str(table.distinct_iris_count)
                ),
                "Columns:",
                ", ".join(table.columns),
                "Matching columns:",
                ", ".join(table.matching_columns) if table.matching_columns else "None",
                "Preview:",
                table.preview.to_string(index=False),
                "",
            ]
        )
    return "\n".join(lines)


def decode_text(content: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("utf-8", content, 0, 1, "unsupported encoding")


def normalize_column(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())
