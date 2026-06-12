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
QUALITY_AVAILABLE_PROXIES = "available_direct_proxies"
QUALITY_NOT_AVAILABLE = "not_available_directly_at_iris_level"

PERSONS_75_PLUS_LIVING_ALONE_DEFINITION = "persons aged 75+ living alone"
HOUSEHOLDS_REFERENCE_75_PLUS_DEFINITION = (
    "one-person households whose reference person is aged 75+"
)
AVAILABLE_PROXY_DEFINITION = (
    "directly available IRIS indicators: people 80+ living alone, people 55-79 "
    "living alone, and one-person households all ages"
)
DIRECT_PROXY_QUALITY_NOTE = (
    "75+ living alone unavailable at IRIS level; using 80+ living alone as closest "
    "direct indicator."
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
    "p22_pop75p_seul",
    "p22_pop_75p_seul",
    "c22_pop75p_seul",
    "c22_pop_75p_seul",
    "p21_pop75p_seul",
    "p20_pop75p_seul",
    "p19_pop75p_seul",
    "p18_pop75p_seul",
    "p17_pop75p_seul",
    "p22_pop75p_vivseul",
    "c22_pop75p_vivseul",
    "p21_pop75p_vivseul",
    "p20_pop75p_vivseul",
    "p19_pop75p_vivseul",
)
ONE_PERSON_HOUSEHOLDS_REFERENCE_75_PLUS_CANDIDATES = (
    "one_person_households_reference_75_plus",
    "households_one_person_reference_75_plus",
    "menages_1_personne_reference_75_plus",
    "menages_1pers_pr_75p",
    "men_pseul75p",
    "men_pseul_75p",
    "menpseul75p",
    "menpseul_75p",
    "men1p_75p",
    "p22_men1p_75p",
    "p22_men_1p_75p",
    "p22_men_pseul75p",
    "p22_men_pseul_75p",
    "p22_menpseul75p",
    "p22_menpseul_75p",
    "c22_men1p_75p",
    "c22_men_1p_75p",
    "c22_men_pseul75p",
    "c22_men_pseul_75p",
    "c22_menpseul75p",
    "c22_menpseul_75p",
    "p21_men1p_75p",
    "p20_men1p_75p",
    "p19_men1p_75p",
    "p18_men1p_75p",
    "p17_men1p_75p",
    "p21_men_pseul_75p",
    "p20_men_pseul_75p",
    "p19_men_pseul_75p",
)
PEOPLE_80_PLUS_LIVING_ALONE_CANDIDATES = (
    "people_80_plus_living_alone",
    "pop80p_pseul",
    "pop_80p_pseul",
    "p22_pop80p_pseul",
    "p21_pop80p_pseul",
    "p20_pop80p_pseul",
    "p19_pop80p_pseul",
)
PEOPLE_55_79_LIVING_ALONE_CANDIDATES = (
    "people_55_79_living_alone",
    "pop5579_pseul",
    "pop_5579_pseul",
    "p22_pop5579_pseul",
    "p21_pop5579_pseul",
    "p20_pop5579_pseul",
    "p19_pop5579_pseul",
)
ONE_PERSON_HOUSEHOLDS_ALL_AGES_CANDIDATES = (
    "one_person_households_all_ages",
    "menpseul",
    "men_pseul",
    "c22_menpseul",
    "c21_menpseul",
    "c20_menpseul",
    "c19_menpseul",
)

@dataclass(frozen=True)
class HouseholdMetricDetection:
    iris_code: str
    single_75_plus_column: str | None
    single_75_plus_definition: str | None
    people_80_plus_living_alone_column: str | None
    people_55_79_living_alone_column: str | None
    one_person_households_all_ages_column: str | None
    source_year: str | None


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

    df.attrs["source_path"] = str(path)
    df.attrs["source_name"] = SOURCE_NAME
    df.attrs["source_year"] = detect_source_year(path.name, df.columns)
    return df


def extract_single_75_plus_by_iris(df: pandas.DataFrame) -> pandas.DataFrame:
    """Extract direct available older people living-alone indicators by IRIS."""
    detection = detect_metric_columns(df)
    single_75_plus_count = (
        df[detection.single_75_plus_column].map(parse_number)
        if detection.single_75_plus_column
        else pandas.Series([None] * len(df), index=df.index, dtype="object")
    )
    people_80_plus_living_alone = map_optional_number(
        df,
        detection.people_80_plus_living_alone_column,
    )
    people_55_79_living_alone = map_optional_number(
        df,
        detection.people_55_79_living_alone_column,
    )
    one_person_households_all_ages = map_optional_number(
        df,
        detection.one_person_households_all_ages_column,
    )
    quality_notes = (
        ""
        if detection.single_75_plus_column
        else DIRECT_PROXY_QUALITY_NOTE
    )
    output = pandas.DataFrame(
        {
            "iris_code": df[detection.iris_code].map(normalize_text),
            "single_75_plus_count": single_75_plus_count,
            "people_80_plus_living_alone": people_80_plus_living_alone,
            "people_55_79_living_alone": people_55_79_living_alone,
            "one_person_households_all_ages": one_person_households_all_ages,
            "metric_definition": detection.single_75_plus_definition
            or AVAILABLE_PROXY_DEFINITION,
            "quality_flag": build_quality_flag(detection),
            "quality_notes": quality_notes,
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
        raise missing_column_error("IRIS code", IRIS_CODE_CANDIDATES, df)

    direct_persons_column = find_column(
        columns_by_normalized_name,
        PERSONS_75_PLUS_LIVING_ALONE_CANDIDATES,
    )
    if direct_persons_column:
        single_75_plus_column = direct_persons_column
        single_75_plus_definition = PERSONS_75_PLUS_LIVING_ALONE_DEFINITION
    else:
        single_75_plus_column = None
        single_75_plus_definition = None

    household_column = find_column(
        columns_by_normalized_name,
        ONE_PERSON_HOUSEHOLDS_REFERENCE_75_PLUS_CANDIDATES,
    )
    if household_column and single_75_plus_column is None:
        single_75_plus_column = household_column
        single_75_plus_definition = HOUSEHOLDS_REFERENCE_75_PLUS_DEFINITION

    people_80_plus_column = find_column(
        columns_by_normalized_name,
        PEOPLE_80_PLUS_LIVING_ALONE_CANDIDATES,
    )
    people_55_79_column = find_column(
        columns_by_normalized_name,
        PEOPLE_55_79_LIVING_ALONE_CANDIDATES,
    )
    one_person_households_column = find_column(
        columns_by_normalized_name,
        ONE_PERSON_HOUSEHOLDS_ALL_AGES_CANDIDATES,
    )
    if not any(
        (
            single_75_plus_column,
            people_80_plus_column,
            people_55_79_column,
            one_person_households_column,
        )
    ):
        raise household_metric_error(df)

    return HouseholdMetricDetection(
        iris_code=iris_code,
        single_75_plus_column=single_75_plus_column,
        single_75_plus_definition=single_75_plus_definition,
        people_80_plus_living_alone_column=people_80_plus_column,
        people_55_79_living_alone_column=people_55_79_column,
        one_person_households_all_ages_column=one_person_households_column,
        source_year=detect_source_year("", df.columns),
    )


def map_optional_number(
    df: pandas.DataFrame,
    column: str | None,
) -> pandas.Series:
    if column is None:
        return pandas.Series([None] * len(df), index=df.index, dtype="object")
    return df[column].map(parse_number)


def build_quality_flag(detection: HouseholdMetricDetection) -> str:
    if detection.single_75_plus_column:
        if (
            detection.single_75_plus_definition
            == HOUSEHOLDS_REFERENCE_75_PLUS_DEFINITION
        ):
            return QUALITY_EXACT_HOUSEHOLDS
        return QUALITY_EXACT_PERSONS
    if any(
        (
            detection.people_80_plus_living_alone_column,
            detection.people_55_79_living_alone_column,
            detection.one_person_households_all_ages_column,
        )
    ):
        return QUALITY_AVAILABLE_PROXIES
    return QUALITY_NOT_AVAILABLE


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
) -> HouseholdColumnError:
    available_columns = [str(column) for column in df.columns]
    found_candidates = find_candidate_columns(available_columns)
    return HouseholdColumnError(
        f"Unable to detect household {label} column. "
        f"File read: {df.attrs.get('source_path', '<dataframe>')}. "
        "Searched motifs: IRIS, 75, SEUL, MEN, MENAGE, P22, C22. "
        f"Candidate columns: {', '.join(candidates)}. "
        f"Candidate columns found: {', '.join(found_candidates) or 'none'}. "
        f"Available columns: {', '.join(available_columns)}"
    )


def household_metric_error(df: pandas.DataFrame) -> HouseholdColumnError:
    available_columns = [str(column) for column in df.columns]
    found_candidates = find_candidate_columns(available_columns)
    candidate_groups = (
        "persons 75+ living alone: "
        + ", ".join(PERSONS_75_PLUS_LIVING_ALONE_CANDIDATES),
        "one-person households reference 75+: "
        + ", ".join(ONE_PERSON_HOUSEHOLDS_REFERENCE_75_PLUS_CANDIDATES),
        "people 80+ living alone: "
        + ", ".join(PEOPLE_80_PLUS_LIVING_ALONE_CANDIDATES),
        "people 55-79 living alone: "
        + ", ".join(PEOPLE_55_79_LIVING_ALONE_CANDIDATES),
        "one-person households all ages: "
        + ", ".join(ONE_PERSON_HOUSEHOLDS_ALL_AGES_CANDIDATES),
    )
    return HouseholdColumnError(
        "Unable to detect a direct household indicator for people living alone or "
        "one-person households. "
        f"File read: {df.attrs.get('source_path', '<dataframe>')}. "
        "Searched motifs: IRIS, 75, SEUL, MEN, MENAGE, P22, C22. "
        f"Candidate groups: {'; '.join(candidate_groups)}. "
        f"Candidate columns found: {', '.join(found_candidates) or 'none'}. "
        f"Available columns: {', '.join(available_columns)}"
    )


def find_candidate_columns(columns: list[str]) -> list[str]:
    motifs = ("iris", "75", "seul", "men", "menage", "p22", "c22")
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
