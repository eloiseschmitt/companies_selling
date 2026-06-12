"""Export candidate INSEE IRIS rows for manual sector mapping."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from services.geography import (
    build_iris_candidates,
    export_iris_candidates,
    load_iris_table,
)

DEFAULT_OUTPUT = Path("data") / "output" / "iris_candidates.csv"


def export_candidates(iris_source: Path, output_path: Path = DEFAULT_OUTPUT) -> int:
    iris_areas = load_iris_table(iris_source)
    candidates = build_iris_candidates(iris_areas)
    export_iris_candidates(output_path, candidates)
    return len(candidates)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Export all IRIS from communes concerned by the business sectors. "
            "This does not assign IRIS to neighborhoods."
        )
    )
    parser.add_argument(
        "--iris-source",
        type=Path,
        required=True,
        help=(
            "CSV table containing IRIS code, IRIS label, commune code and commune name."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="CSV output path for candidate IRIS rows.",
    )
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(levelname)s %(name)s: %(message)s",
    )
    count = export_candidates(args.iris_source, args.output)
    logging.getLogger(__name__).info(
        "Exported %s candidate IRIS rows to %s.",
        count,
        args.output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
