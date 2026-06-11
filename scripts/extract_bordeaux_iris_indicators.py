"""Extract INSEE IRIS indicators for Bordeaux Metropole business sectors."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from services.insee_iris_indicators import (
    DataSource,
    build_indicators,
    load_sector_config,
    load_source_rows,
    save_results,
    write_results_csv,
)

DEFAULT_CONFIG = Path("config") / "bordeaux_iris_sectors.example.json"
DEFAULT_CACHE_DIR = Path(".cache") / "insee_iris"
DEFAULT_DB_PATH = Path("companies.db")
DEFAULT_OUTPUT = Path("bordeaux_iris_indicators.csv")


def extract_bordeaux_iris_indicators(
    config_path: Path,
    income_source: DataSource,
    population_source: DataSource,
    household_source: DataSource | None,
    cache_dir: Path,
    db_path: Path,
    output_path: Path,
) -> int:
    sectors = load_sector_config(config_path)
    income_rows = load_source_rows(income_source, cache_dir)
    population_rows = load_source_rows(population_source, cache_dir)
    household_rows = (
        load_source_rows(household_source, cache_dir) if household_source else None
    )
    results = build_indicators(
        sectors=sectors,
        income_rows=income_rows,
        population_rows=population_rows,
        household_rows=household_rows,
    )
    save_results(db_path, results)
    write_results_csv(output_path, results)
    return len(results)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build INSEE IRIS indicators for configured Bordeaux Metropole sectors. "
            "Sector IRIS codes must be explicit in the JSON config."
        )
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--income-source", required=True, help="Filosofi IRIS CSV/ZIP URL or path."
    )
    parser.add_argument(
        "--income-vintage", required=True, help="Filosofi source vintage, e.g. 2021."
    )
    parser.add_argument(
        "--population-source",
        required=True,
        help="INSEE RP IRIS population CSV/ZIP URL or path.",
    )
    parser.add_argument(
        "--population-vintage", required=True, help="RP source vintage, e.g. 2021."
    )
    parser.add_argument(
        "--household-source",
        default=None,
        help=(
            "Optional INSEE RP household CSV/ZIP URL or path if separate "
            "from population."
        ),
    )
    parser.add_argument(
        "--household-vintage",
        default=None,
        help="Household source vintage. Defaults to population vintage.",
    )
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(levelname)s %(name)s: %(message)s",
    )
    household_source = None
    if args.household_source:
        household_source = DataSource(
            name="INSEE Recensement de la population IRIS - ménages",
            location=args.household_source,
            vintage=args.household_vintage or args.population_vintage,
        )

    count = extract_bordeaux_iris_indicators(
        config_path=args.config,
        income_source=DataSource(
            name="INSEE Filosofi IRIS",
            location=args.income_source,
            vintage=args.income_vintage,
        ),
        population_source=DataSource(
            name="INSEE Recensement de la population IRIS",
            location=args.population_source,
            vintage=args.population_vintage,
        ),
        household_source=household_source,
        cache_dir=args.cache_dir,
        db_path=args.db,
        output_path=args.output,
    )
    logging.getLogger(__name__).info(
        "Extraction complete: %s indicator rows written to %s and %s.",
        count,
        args.output,
        args.db,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
