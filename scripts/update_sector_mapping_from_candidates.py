"""Update sector_iris_mapping.yml from a reviewed iris_candidates.csv file."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from services.geography import update_sector_mapping_from_candidates

DEFAULT_CANDIDATES = Path("data") / "output" / "iris_candidates.csv"
DEFAULT_MAPPING = Path("config") / "sector_iris_mapping.yml"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Populate sector_iris_mapping.yml from iris_candidates.csv. "
            "Use only after human review of candidate sectors."
        )
    )
    parser.add_argument(
        "--candidates",
        type=Path,
        default=DEFAULT_CANDIDATES,
        help="Path to iris_candidates.csv.",
    )
    parser.add_argument(
        "--mapping",
        type=Path,
        default=DEFAULT_MAPPING,
        help="Path to sector_iris_mapping.yml.",
    )
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(levelname)s %(name)s: %(message)s",
    )
    mapping = update_sector_mapping_from_candidates(args.candidates, args.mapping)
    updated_codes = sum(len(iris_codes) for iris_codes in mapping.values())
    logging.getLogger(__name__).info(
        "Updated %s with %s sector/IRIS assignments from %s.",
        args.mapping,
        updated_codes,
        args.candidates,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
