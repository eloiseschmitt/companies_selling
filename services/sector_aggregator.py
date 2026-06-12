"""Aggregate normalized IRIS indicators to manually defined business sectors."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pandas

SUMMABLE_SINGLE_75_PLUS_FLAGS = {
    "exact_persons_75_plus_living_alone",
    "exact_households_reference_75_plus",
}


def aggregate_sector_indicators(
    sector_iris_mapping: Mapping[str, Sequence[str]],
    income_df: pandas.DataFrame | None = None,
    population_df: pandas.DataFrame | None = None,
    household_df: pandas.DataFrame | None = None,
    retired_csp_df: pandas.DataFrame | None = None,
    income_weight_column: str | None = None,
    retired_weight_column: str | None = None,
) -> pandas.DataFrame:
    """Aggregate normalized IRIS-level indicators to sector level."""
    rows: list[dict[str, Any]] = []
    indexed_income = index_by_iris(income_df)
    indexed_population = index_by_iris(population_df)
    indexed_household = index_by_iris(household_df)
    indexed_retired = index_by_iris(retired_csp_df)

    for sector_name, iris_codes in sector_iris_mapping.items():
        normalized_iris_codes = tuple(normalize_iris_code(code) for code in iris_codes)
        quality_notes: list[str] = []
        source_years: set[str] = set()

        income_rows = select_iris_rows(indexed_income, normalized_iris_codes)
        population_rows = select_iris_rows(indexed_population, normalized_iris_codes)
        household_rows = select_iris_rows(indexed_household, normalized_iris_codes)
        retired_rows = select_iris_rows(indexed_retired, normalized_iris_codes)

        median_min, median_max, median_weighted, median_values = aggregate_income(
            income_rows,
            income_weight_column,
            quality_notes,
        )
        taxable_min, taxable_max, taxable_mean = aggregate_taxable_households_share(
            income_rows
        )
        population_75_plus = sum_column(
            population_rows,
            "population_75_plus",
            quality_notes,
            "population_75_plus",
        )
        single_75_plus_count = aggregate_single_75_plus(
            household_rows,
            quality_notes,
        )
        people_80_plus_living_alone = sum_column(
            household_rows,
            "people_80_plus_living_alone",
            quality_notes,
            "people_80_plus_living_alone",
        )
        people_55_79_living_alone = sum_column(
            household_rows,
            "people_55_79_living_alone",
            quality_notes,
            "people_55_79_living_alone",
        )
        one_person_households_all_ages = sum_column(
            household_rows,
            "one_person_households_all_ages",
            quality_notes,
            "one_person_households_all_ages",
        )
        append_household_quality_notes(household_rows, quality_notes)
        retired_count, csp_plus_15_plus_count = aggregate_retired_and_csp(
            retired_rows,
            quality_notes,
        )

        collect_source_years(source_years, income_rows)
        collect_source_years(source_years, population_rows)
        collect_source_years(source_years, household_rows)
        collect_source_years(source_years, retired_rows)

        rows.append(
            {
                "sector_name": sector_name,
                "iris_codes": ",".join(normalized_iris_codes),
                "median_income_min": median_min,
                "median_income_max": median_max,
                "median_income_weighted": median_weighted,
                "median_income_iris_values": median_values,
                "taxable_households_share_min": taxable_min,
                "taxable_households_share_max": taxable_max,
                "taxable_households_share_mean": taxable_mean,
                "population_75_plus": population_75_plus,
                "population_75_plus_rounded": round_optional(population_75_plus),
                "single_75_plus_count": single_75_plus_count,
                "people_80_plus_living_alone": people_80_plus_living_alone,
                "people_80_plus_living_alone_rounded": round_optional(
                    people_80_plus_living_alone
                ),
                "people_55_79_living_alone": people_55_79_living_alone,
                "one_person_households_all_ages": one_person_households_all_ages,
                "retired_count": retired_count,
                "retired_count_rounded": round_optional(retired_count),
                "csp_plus_15_plus_count": csp_plus_15_plus_count,
                "csp_plus_15_plus_count_rounded": round_optional(
                    csp_plus_15_plus_count
                ),
                "living_alone_ratio_80_plus": compute_ratio(
                    people_80_plus_living_alone,
                    population_75_plus,
                ),
                "quality_notes": " | ".join(quality_notes),
                "source_years": ",".join(sorted(source_years)),
            }
        )

    report = pandas.DataFrame(
        rows,
        columns=(
            "sector_name",
            "iris_codes",
            "median_income_min",
            "median_income_max",
            "median_income_weighted",
            "median_income_iris_values",
            "taxable_households_share_min",
            "taxable_households_share_max",
            "taxable_households_share_mean",
            "population_75_plus",
            "population_75_plus_rounded",
            "single_75_plus_count",
            "people_80_plus_living_alone",
            "people_80_plus_living_alone_rounded",
            "people_55_79_living_alone",
            "one_person_households_all_ages",
            "retired_count",
            "retired_count_rounded",
            "csp_plus_15_plus_count",
            "csp_plus_15_plus_count_rounded",
            "living_alone_ratio_80_plus",
            "quality_notes",
            "source_years",
        ),
    )
    return sort_sector_report(report)


def aggregate_income(
    rows: pandas.DataFrame,
    income_weight_column: str | None,
    quality_notes: list[str],
) -> tuple[float | None, float | None, float | None, str | None]:
    if rows.empty or "median_disposable_income" not in rows.columns:
        quality_notes.append("median income unavailable for configured IRIS")
        return None, None, None, None

    incomes = rows["median_disposable_income"].map(parse_number).dropna()
    if incomes.empty:
        quality_notes.append("median income values are empty for configured IRIS")
        return None, None, None, None

    median_min = float(incomes.min())
    median_max = float(incomes.max())
    median_values = format_income_iris_values(rows)
    weighted_income = None
    if income_weight_column and income_weight_column in rows.columns:
        weighted_income = weighted_average(
            rows,
            value_column="median_disposable_income",
            weight_column=income_weight_column,
        )
        if weighted_income is None:
            quality_notes.append(
                "median income weighted average not calculable with provided weights"
            )
        else:
            quality_notes.append(
                "median income weighted average is an approximation from IRIS medians"
            )
    else:
        quality_notes.append(
            "median income is not averaged; IRIS median range is reported because no "
            "reliable weight column was provided"
        )
    return median_min, median_max, weighted_income, median_values


def aggregate_taxable_households_share(
    rows: pandas.DataFrame,
) -> tuple[float | None, float | None, float | None]:
    if rows.empty or "taxable_households_share" not in rows.columns:
        return None, None, None
    values = rows["taxable_households_share"].map(parse_number).dropna()
    if values.empty:
        return None, None, None
    return float(values.min()), float(values.max()), float(values.mean())


def sort_sector_report(report: pandas.DataFrame) -> pandas.DataFrame:
    if report.empty:
        return report
    sorted_report = report.sort_values(
        by=["population_75_plus", "median_income_max"],
        ascending=[False, False],
        na_position="last",
        kind="mergesort",
    )
    return sorted_report.reset_index(drop=True)


def round_optional(value: float | None) -> int | None:
    if value is None or pandas.isna(value):
        return None
    return int(round(float(value)))


def compute_ratio(
    numerator: float | None,
    denominator: float | None,
) -> float | None:
    if numerator is None or denominator is None:
        return None
    if pandas.isna(numerator) or pandas.isna(denominator):
        return None
    denominator_float = float(denominator)
    if denominator_float == 0:
        return None
    return float(numerator) / denominator_float


def aggregate_single_75_plus(
    rows: pandas.DataFrame,
    quality_notes: list[str],
) -> float | None:
    if rows.empty or "single_75_plus_count" not in rows.columns:
        quality_notes.append("single_75_plus_count unavailable for configured IRIS")
        return None

    values = rows["single_75_plus_count"].map(parse_number).dropna()
    if values.empty:
        return None

    if "quality_flag" not in rows.columns:
        quality_notes.append("single_75_plus_count not summed: missing quality_flag")
        return None

    quality_flags = {str(value) for value in rows["quality_flag"].dropna().unique()}
    unsupported = quality_flags - SUMMABLE_SINGLE_75_PLUS_FLAGS
    if unsupported:
        quality_notes.append(
            "single_75_plus_count not summed due to non-summable quality flags: "
            + ",".join(sorted(unsupported))
        )
        return None

    if "exact_households_reference_75_plus" in quality_flags:
        quality_notes.append(
            "single_75_plus_count includes one-person households by reference person, "
            "not persons living alone"
        )
    return float(values.sum())


def append_household_quality_notes(
    rows: pandas.DataFrame,
    quality_notes: list[str],
) -> None:
    if rows.empty or "quality_notes" not in rows.columns:
        return
    for note in rows["quality_notes"].dropna().unique():
        text = str(note).strip()
        if text and text not in quality_notes:
            quality_notes.append(text)


def aggregate_retired_and_csp(
    rows: pandas.DataFrame,
    quality_notes: list[str],
) -> tuple[float | None, float | None]:
    if rows.empty:
        quality_notes.append(
            "retired/CSP marginal indicators unavailable for configured IRIS"
        )
        return None, None

    retired_count = (
        sum_numeric_series(rows["retired_count"])
        if "retired_count" in rows
        else None
    )
    csp_plus_count = (
        sum_numeric_series(rows["csp_plus_15_plus_count"])
        if "csp_plus_15_plus_count" in rows
        else None
    )
    quality_notes.append(
        "retired_count and csp_plus_15_plus_count are aggregated separately; this "
        "is not equivalent to retired formerly CSP+ people"
    )
    if retired_count is None:
        quality_notes.append("retired_count unavailable for configured IRIS")
    if csp_plus_count is None:
        quality_notes.append("csp_plus_15_plus_count unavailable for configured IRIS")
    return retired_count, csp_plus_count


def format_income_iris_values(rows: pandas.DataFrame) -> str | None:
    values: list[str] = []
    for _, row in rows.iterrows():
        income = parse_number(row.get("median_disposable_income"))
        if income is None:
            continue
        iris_code = normalize_iris_code(row.get("iris_code"))
        values.append(f"{iris_code}:{income:g}")
    return "; ".join(values) if values else None


def sum_column(
    rows: pandas.DataFrame,
    column: str,
    quality_notes: list[str],
    label: str,
) -> float | None:
    if rows.empty or column not in rows.columns:
        quality_notes.append(f"{label} unavailable for configured IRIS")
        return None
    value = sum_numeric_series(rows[column])
    if value is None:
        quality_notes.append(f"{label} values are empty for configured IRIS")
    return value


def weighted_average(
    rows: pandas.DataFrame,
    value_column: str,
    weight_column: str,
) -> float | None:
    values = rows[value_column].map(parse_number)
    weights = rows[weight_column].map(parse_number)
    usable = pandas.DataFrame({"value": values, "weight": weights}).dropna()
    usable = usable[usable["weight"] > 0]
    if usable.empty:
        return None
    return float((usable["value"] * usable["weight"]).sum() / usable["weight"].sum())


def weighted_count_from_share(
    rows: pandas.DataFrame,
    share_column: str,
    weight_column: str,
) -> float | None:
    shares = rows[share_column].map(parse_number)
    weights = rows[weight_column].map(parse_number)
    usable = pandas.DataFrame({"share": shares, "weight": weights}).dropna()
    usable = usable[usable["weight"] > 0]
    if usable.empty:
        return None
    return float((usable["share"].map(normalize_share) * usable["weight"]).sum())


def sum_numeric_series(series: pandas.Series) -> float | None:
    values = series.map(parse_number).dropna()
    if values.empty:
        return None
    return float(values.sum())


def index_by_iris(df: pandas.DataFrame | None) -> pandas.DataFrame:
    if df is None or df.empty or "iris_code" not in df.columns:
        return pandas.DataFrame()
    indexed = df.copy()
    indexed["iris_code"] = indexed["iris_code"].map(normalize_iris_code)
    return indexed.set_index("iris_code", drop=False)


def select_iris_rows(
    indexed_df: pandas.DataFrame,
    iris_codes: Sequence[str],
) -> pandas.DataFrame:
    if indexed_df.empty:
        return pandas.DataFrame()
    present_codes = [code for code in iris_codes if code in indexed_df.index]
    if not present_codes:
        return pandas.DataFrame(columns=indexed_df.columns)
    return indexed_df.loc[present_codes]


def collect_source_years(source_years: set[str], rows: pandas.DataFrame) -> None:
    if rows.empty or "source_year" not in rows.columns:
        return
    for value in rows["source_year"].dropna().unique():
        text = str(value).strip()
        if text:
            source_years.add(text)


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


def normalize_iris_code(value: Any) -> str:
    return "" if value is None else str(value).strip().upper()
