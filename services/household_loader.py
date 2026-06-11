"""Load INSEE IRIS household data for older people living alone indicators."""

from __future__ import annotations

import csv
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas

SOURCE_NAME = "INSEE Recensement de la population IRIS"
QUALITY_EXACT_PERSONS = "exact_persons_75_plus_living_alone"
QUALITY_EXACT_HOUSEHOLDS = "exact_households_reference_75_plus"
QUALITY_ESTIMATED = "estimated"

PERSONS_75_PLUS_LIVING_ALONE_DEFINITION = "persons aged 75+ living alone"
HOUSEHOLDS_REFERENCE_75_PLUS_DEFINITION = (
    "one-person households whose reference person is aged 75+"
)
ESTIMATED_DEFINITION = (
    "estimated persons aged 75+ living alone from available 75+ population and "
    "living-alone rate/count variables"
)

IRIS_CODE_CANDIDATES = (
    "iris_code",
    "code_iris",
    "codeiris",
    "iris",
    "cod_iris",
    "depcomiris",
)
PERSONS_75_PLUS_LIVING_ALONE_CANDIDATES = (
    "single_75_plus_count",
    "persons_75_plus_living_alone",
    "population_75_plus_living_alone",
    "pop75p_seul",
    "pop_75p_seul",
    "p21_pop75p_seul",
    "p20_pop75p_seul",
    "p19_pop75p_seul",
    "p18_pop75p_seul",
    "p17_pop75p_seul",
    "p21_pop75p_vivseul",
    "p20_pop75p_vivseul",
    "p19_pop75p_vivseul",
)
ONE_PERSON_HOUSEHOLDS_REFERENCE_75_PLUS_CANDIDATES = (
    "one_person_households_reference_75_plus",
    "households_one_person_reference_75_plus",
    "menages_1_personne_reference_75_plus",
    "menages_1pers_pr_75p",
    "men1p_75p",
    "p21_men1p_75p",
    "p20_men1p_75p",
    "p19_men1p_75p",
    "p18_men1p_75p",
    "p17_men1p_75p",
    "p21_men_pseul_75p",
    "p20_men_pseul_75p",
    "p19_men_pseul_75p",
)
POPULATION_75_PLUS_CANDIDATES = (
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
LIVING_ALONE_RATE_75_PLUS_CANDIDATES = (
    "living_alone_rate_75_plus",
    "single_rate_75_plus",
    "share_75_plus_living_alone",
    "tx_pop75p_seul",
    "pct_pop75p_seul",
    "p21_tx_pop75p_seul",
    "p20_tx_pop75p_seul",
    "p19_tx_pop75p_seul",
)
POPULATION_LIVING_ALONE_CANDIDATES = (
    "population_living_alone",
    "persons_living_alone",
    "pop_seul",
    "pop_vivseul",
    "p21_pop_seul",
    "p20_pop_seul",
    "p19_pop_seul",
)
POPULATION_TOTAL_CANDIDATES = (
    "population_total",
    "population",
    "pop_total",
    "p21_pop",
    "p20_pop",
    "p19_pop",
)


@dataclass(frozen=True)
class HouseholdMetricDetection:
    iris_code: str
    value_columns: tuple[str, ...]
    metric_definition: str
    quality_flag: str
    source_year: str | None
    estimation_denominator: str | None = None


class HouseholdColumnError(RuntimeError):
    """Raised when household single-75+ indicators cannot be detected."""


class UnsupportedHouseholdFormatError(RuntimeError):
    """Raised when a household source file format is not supported."""


def load_household_iris(file_path: Path) -> pandas.DataFrame:
    """Load an INSEE IRIS household source file into a pandas DataFrame."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Household source file not found: {path}")

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
        raise UnsupportedHouseholdFormatError(
            f"Unsupported household file format: {suffix or '<none>'}"
        )

    df.attrs["source_name"] = SOURCE_NAME
    df.attrs["source_year"] = detect_source_year(path.name, df.columns)
    return df


def extract_single_75_plus_by_iris(df: pandas.DataFrame) -> pandas.DataFrame:
    """Extract or estimate older people living alone indicators by IRIS."""
    detection = detect_metric_columns(df)
    count = compute_single_75_plus_count(df, detection)
    output = pandas.DataFrame(
        {
            "iris_code": df[detection.iris_code].map(normalize_text),
            "single_75_plus_count": count,
            "metric_definition": detection.metric_definition,
            "quality_flag": detection.quality_flag,
            "source_name": df.attrs.get("source_name", SOURCE_NAME),
            "source_year": df.attrs.get("source_year") or detection.source_year,
        }
    )
    output = output.dropna(subset=["iris_code"])
    return output.reset_index(drop=True)


def detect_metric_columns(df: pandas.DataFrame) -> HouseholdMetricDetection:
    columns_by_normalized_name = build_column_lookup(df.columns)
    iris_code = find_column(columns_by_normalized_name, IRIS_CODE_CANDIDATES)
    if iris_code is None:
        raise missing_column_error("IRIS code", IRIS_CODE_CANDIDATES, df.columns)

    direct_persons_column = find_column(
        columns_by_normalized_name,
        PERSONS_75_PLUS_LIVING_ALONE_CANDIDATES,
    )
    if direct_persons_column:
        return HouseholdMetricDetection(
            iris_code=iris_code,
            value_columns=(direct_persons_column,),
            metric_definition=PERSONS_75_PLUS_LIVING_ALONE_DEFINITION,
            quality_flag=QUALITY_EXACT_PERSONS,
            source_year=detect_source_year("", df.columns),
        )

    household_column = find_column(
        columns_by_normalized_name,
        ONE_PERSON_HOUSEHOLDS_REFERENCE_75_PLUS_CANDIDATES,
    )
    if household_column:
        return HouseholdMetricDetection(
            iris_code=iris_code,
            value_columns=(household_column,),
            metric_definition=HOUSEHOLDS_REFERENCE_75_PLUS_DEFINITION,
            quality_flag=QUALITY_EXACT_HOUSEHOLDS,
            source_year=detect_source_year("", df.columns),
        )

    population_75_plus_column = find_column(
        columns_by_normalized_name,
        POPULATION_75_PLUS_CANDIDATES,
    )
    living_alone_rate_column = find_column(
        columns_by_normalized_name,
        LIVING_ALONE_RATE_75_PLUS_CANDIDATES,
    )
    if population_75_plus_column and living_alone_rate_column:
        return HouseholdMetricDetection(
            iris_code=iris_code,
            value_columns=(population_75_plus_column, living_alone_rate_column),
            metric_definition=ESTIMATED_DEFINITION,
            quality_flag=QUALITY_ESTIMATED,
            source_year=detect_source_year("", df.columns),
            estimation_denominator="rate_75_plus",
        )

    living_alone_column = find_column(
        columns_by_normalized_name,
        POPULATION_LIVING_ALONE_CANDIDATES,
    )
    population_total_column = find_column(
        columns_by_normalized_name,
        POPULATION_TOTAL_CANDIDATES,
    )
    if population_75_plus_column and living_alone_column and population_total_column:
        return HouseholdMetricDetection(
            iris_code=iris_code,
            value_columns=(
                population_75_plus_column,
                living_alone_column,
                population_total_column,
            ),
            metric_definition=ESTIMATED_DEFINITION,
            quality_flag=QUALITY_ESTIMATED,
            source_year=detect_source_year("", df.columns),
            estimation_denominator="overall_living_alone_share",
        )

    raise household_metric_error(df.columns)


def compute_single_75_plus_count(
    df: pandas.DataFrame,
    detection: HouseholdMetricDetection,
) -> pandas.Series:
    if detection.quality_flag in {QUALITY_EXACT_PERSONS, QUALITY_EXACT_HOUSEHOLDS}:
        return df[detection.value_columns[0]].map(parse_number)

    if detection.estimation_denominator == "rate_75_plus":
        population_75_plus = df[detection.value_columns[0]].map(parse_number)
        rate = df[detection.value_columns[1]].map(parse_number).map(normalize_rate)
        return population_75_plus * rate

    if detection.estimation_denominator == "overall_living_alone_share":
        population_75_plus = df[detection.value_columns[0]].map(parse_number)
        living_alone = df[detection.value_columns[1]].map(parse_number)
        population_total = df[detection.value_columns[2]].map(parse_number)
        share = living_alone / population_total.replace(0, pandas.NA)
        return population_75_plus * share

    return pandas.Series([pandas.NA] * len(df), index=df.index)


def read_csv(path: Path) -> pandas.DataFrame:
    separator = detect_csv_separator(path)
    return pandas.read_csv(path, sep=separator, dtype=str, encoding="utf-8-sig")


def read_csv_from_zip(path: Path) -> pandas.DataFrame:
    with zipfile.ZipFile(path) as archive:
        csv_names = [
            name for name in archive.namelist() if name.lower().endswith(".csv")
        ]
        if not csv_names:
            raise UnsupportedHouseholdFormatError(
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
) -> HouseholdColumnError:
    available_columns = [str(column) for column in columns]
    return HouseholdColumnError(
        f"Unable to detect household {label} column. "
        f"Candidate columns: {', '.join(candidates)}. "
        f"Available columns: {', '.join(available_columns)}"
    )


def household_metric_error(columns: Any) -> HouseholdColumnError:
    available_columns = [str(column) for column in columns]
    candidate_groups = (
        "persons 75+ living alone: "
        + ", ".join(PERSONS_75_PLUS_LIVING_ALONE_CANDIDATES),
        "one-person households reference 75+: "
        + ", ".join(ONE_PERSON_HOUSEHOLDS_REFERENCE_75_PLUS_CANDIDATES),
        "estimation: population 75+ + living-alone rate 75+",
        "estimation: population 75+ + population living alone + population total",
    )
    return HouseholdColumnError(
        "Unable to detect a household indicator for people aged 75+ living alone. "
        f"Candidate groups: {'; '.join(candidate_groups)}. "
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


def normalize_rate(value: float | None) -> float | None:
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
