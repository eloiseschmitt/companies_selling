"""Build a premium opportunity ranking from the sector report."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas

DEFAULT_INPUT = Path("data") / "output" / "sector_report.csv"
DEFAULT_OUTPUT_CSV = Path("data") / "output" / "sector_ranking.csv"
DEFAULT_OUTPUT_XLSX = Path("data") / "output" / "sector_ranking.xlsx"

FINAL_COLUMNS = (
    "sector_name",
    "premium_rank",
    "premium_opportunity_score",
    "income_score",
    "taxable_households_score",
    "population_75_plus_score",
    "people_80_plus_living_alone_score",
    "population_75_plus",
    "people_80_plus_living_alone",
    "median_income_max",
    "taxable_households_share_mean",
)

SCORE_INPUT_COLUMNS = {
    "income_score": "median_income_max",
    "taxable_households_score": "taxable_households_share_mean",
    "population_75_plus_score": "population_75_plus",
    "people_80_plus_living_alone_score": "people_80_plus_living_alone",
}

SCORE_WEIGHTS = {
    "income_score": 0.35,
    "taxable_households_score": 0.25,
    "population_75_plus_score": 0.25,
    "people_80_plus_living_alone_score": 0.15,
}


class RankingError(RuntimeError):
    """Raised when the ranking cannot be built."""


def build_ranking(sector_report: pandas.DataFrame) -> pandas.DataFrame:
    """Compute normalized scores and premium rank from a sector report."""
    validate_columns(sector_report)
    ranking = sector_report.copy()
    for score_column, source_column in SCORE_INPUT_COLUMNS.items():
        ranking[score_column] = min_max_score(ranking[source_column])

    ranking["premium_opportunity_score"] = sum(
        ranking[score_column] * weight for score_column, weight in SCORE_WEIGHTS.items()
    )
    ranking = ranking.sort_values(
        by="premium_opportunity_score",
        ascending=False,
        na_position="last",
        kind="mergesort",
    ).reset_index(drop=True)
    ranking["premium_rank"] = range(1, len(ranking) + 1)
    return ranking.loc[:, FINAL_COLUMNS]


def build_ranking_files(
    input_path: Path = DEFAULT_INPUT,
    output_csv_path: Path = DEFAULT_OUTPUT_CSV,
    output_xlsx_path: Path = DEFAULT_OUTPUT_XLSX,
) -> pandas.DataFrame:
    """Read sector_report.csv and write ranking CSV/XLSX outputs."""
    sector_report = pandas.read_csv(input_path)
    ranking = build_ranking(sector_report)
    output_csv_path.parent.mkdir(parents=True, exist_ok=True)
    ranking.to_csv(output_csv_path, index=False, encoding="utf-8-sig")
    ranking.to_excel(output_xlsx_path, index=False)
    return ranking


def min_max_score(series: pandas.Series) -> pandas.Series:
    values = pandas.to_numeric(series, errors="coerce")
    minimum = values.min(skipna=True)
    maximum = values.max(skipna=True)
    if pandas.isna(minimum) or pandas.isna(maximum):
        return pandas.Series([pandas.NA] * len(values), index=values.index)
    if maximum == minimum:
        return pandas.Series([100.0] * len(values), index=values.index)
    return ((values - minimum) / (maximum - minimum)) * 100


def validate_columns(df: pandas.DataFrame) -> None:
    missing = [
        column
        for column in {"sector_name", *SCORE_INPUT_COLUMNS.values()}
        if column not in df.columns
    ]
    if missing:
        raise RankingError("Missing ranking input columns: " + ", ".join(missing))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build sector premium ranking.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--output-xlsx", type=Path, default=DEFAULT_OUTPUT_XLSX)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    build_ranking_files(args.input, args.output_csv, args.output_xlsx)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
