from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from fastapi import FastAPI

from services.data_sources import (
    SourceReference,
    download_sources,
    load_manifest,
    source_from_url,
)
from services.geography import (
    build_iris_candidates,
    export_iris_candidates,
    load_iris_table,
    load_sector_iris_mapping,
    validate_sector_mapping,
)
from services.report_builder import DEFAULT_OUTPUT_DIR, build_sector_report
from services.source_inspector import format_inspection, inspect_source

app = FastAPI()

DEFAULT_SECTOR_MAPPING = Path("config") / "sector_iris_mapping.yml"
DEFAULT_RAW_DIR = Path("data") / "raw"
DEFAULT_SOURCE_MANIFEST = Path("data") / "source_manifest.json"
DEFAULT_IRIS_CANDIDATES_OUTPUT = Path("data") / "output" / "iris_candidates.csv"

SOURCE_KEYS = {
    "income": "insee_filosofi_iris",
    "population": "insee_rp_iris_population",
    "household": "insee_rp_iris_households",
    "retired_csp": "insee_rp_iris_retired_csp",
    "iris_geography": "insee_iris_geography",
}


class CliSourceError(RuntimeError):
    """Raised when a CLI command cannot resolve a required source file."""


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging(args.verbose)
    try:
        return run_command(args)
    except Exception as exc:
        logging.getLogger(__name__).error("%s", exc)
        return 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="INSEE IRIS sector reporting CLI.")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logs.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_download_sources_parser(subparsers)
    add_export_iris_candidates_parser(subparsers)
    add_build_report_parser(subparsers)
    add_validate_mapping_parser(subparsers)
    add_inspect_source_parser(subparsers)
    return parser.parse_args(argv)


def add_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Enable verbose logs.",
    )
    parser.add_argument(
        "--sector-mapping",
        type=Path,
        default=DEFAULT_SECTOR_MAPPING,
        help="Manual sector to IRIS mapping YAML path.",
    )
    parser.add_argument(
        "--output-format",
        choices=("csv", "xlsx"),
        default="csv",
        help="Preferred output format. build-report still writes CSV and XLSX.",
    )


def add_manifest_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_SOURCE_MANIFEST)


def add_download_sources_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("download-sources", help="Download source files.")
    parser.add_argument("--force-refresh", action="store_true")
    add_manifest_options(parser)
    add_source_url_options(parser)
    add_common_options(parser)


def add_export_iris_candidates_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "export-iris-candidates",
        help="Export IRIS rows from communes concerned by the sectors.",
    )
    parser.add_argument("--iris-source", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_IRIS_CANDIDATES_OUTPUT)
    parser.add_argument("--force-refresh", action="store_true")
    add_manifest_options(parser)
    add_common_options(parser)


def add_build_report_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("build-report", help="Build sector report files.")
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    add_manifest_options(parser)
    parser.add_argument("--income-file", type=Path)
    parser.add_argument("--population-file", type=Path)
    parser.add_argument("--household-file", type=Path)
    parser.add_argument("--retired-csp-file", type=Path)
    add_common_options(parser)


def add_validate_mapping_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "validate-mapping",
        help="Validate manual sector to IRIS mapping against an IRIS table.",
    )
    parser.add_argument("--iris-source", type=Path)
    parser.add_argument("--force-refresh", action="store_true")
    add_manifest_options(parser)
    add_common_options(parser)


def add_inspect_source_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "inspect-source",
        help="Inspect columns and preview rows from a local INSEE source file.",
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Enable verbose logs.",
    )


def add_source_url_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--income-source", help="Filosofi IRIS source URL or path.")
    parser.add_argument(
        "--population-source", help="Population IRIS source URL or path."
    )
    parser.add_argument("--household-source", help="Household IRIS source URL or path.")
    parser.add_argument("--retired-csp-source", help="Retired CSP+ source URL or path.")
    parser.add_argument("--iris-source", help="IRIS geography source URL or path.")


def configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )


def run_command(args: argparse.Namespace) -> int:
    if args.command == "download-sources":
        return command_download_sources(args)
    if args.command == "export-iris-candidates":
        return command_export_iris_candidates(args)
    if args.command == "build-report":
        return command_build_report(args)
    if args.command == "validate-mapping":
        return command_validate_mapping(args)
    if args.command == "inspect-source":
        return command_inspect_source(args)
    raise ValueError(f"Unsupported command: {args.command}")


def command_download_sources(args: argparse.Namespace) -> int:
    references = build_source_references(args)
    if not references:
        logging.getLogger(__name__).warning(
            "No sources provided to download. Pass source URLs once, or use files "
            "already recorded in data/source_manifest.json for later commands."
        )
        return 0
    paths = download_sources(
        references,
        raw_dir=args.raw_dir,
        manifest_path=args.manifest,
        force_refresh=args.force_refresh,
    )
    for key, path in paths.items():
        logging.getLogger(__name__).info("%s -> %s", key, path)
    return 0


def command_export_iris_candidates(args: argparse.Namespace) -> int:
    iris_source = resolve_source_path(
        explicit_path=args.iris_source,
        manifest_path=args.manifest,
        raw_dir=args.raw_dir,
        source_key=SOURCE_KEYS["iris_geography"],
        label="IRIS geography",
    )
    iris_areas = load_iris_table(iris_source)
    candidates = build_iris_candidates(iris_areas)
    export_iris_candidates(args.output, candidates)
    logging.getLogger(__name__).info(
        "Exported %s candidate IRIS rows to %s.", len(candidates), args.output
    )
    return 0


def command_build_report(args: argparse.Namespace) -> int:
    report = build_sector_report(
        sector_mapping_path=args.sector_mapping,
        output_dir=args.output_dir,
        source_manifest_path=args.manifest,
        income_path=resolve_optional_report_source(
            args.income_file,
            args.manifest,
            args.raw_dir,
            SOURCE_KEYS["income"],
            "Filosofi income",
        ),
        population_path=resolve_optional_report_source(
            args.population_file,
            args.manifest,
            args.raw_dir,
            SOURCE_KEYS["population"],
            "population",
        ),
        household_path=resolve_optional_report_source(
            args.household_file,
            args.manifest,
            args.raw_dir,
            SOURCE_KEYS["household"],
            "household",
        ),
        retired_csp_path=resolve_optional_report_source(
            args.retired_csp_file,
            args.manifest,
            args.raw_dir,
            SOURCE_KEYS["retired_csp"],
            "retired CSP+",
        ),
        output_format=args.output_format,
    )
    logging.getLogger(__name__).info(
        "Built sector report with %s rows in %s.", len(report), args.output_dir
    )
    return 0


def command_validate_mapping(args: argparse.Namespace) -> int:
    iris_source = resolve_source_path(
        explicit_path=args.iris_source,
        manifest_path=args.manifest,
        raw_dir=args.raw_dir,
        source_key=SOURCE_KEYS["iris_geography"],
        label="IRIS geography",
    )
    mapping = load_sector_iris_mapping(args.sector_mapping)
    iris_areas = load_iris_table(iris_source)
    validate_sector_mapping(mapping, iris_areas)
    logging.getLogger(__name__).info("Sector mapping is valid.")
    return 0


def command_inspect_source(args: argparse.Namespace) -> int:
    print(format_inspection(inspect_source(args.source)))
    return 0


def resolve_optional_report_source(
    explicit_path: Path | None,
    manifest_path: Path,
    raw_dir: Path,
    source_key: str,
    label: str,
) -> Path | None:
    try:
        return resolve_source_path(
            explicit_path, manifest_path, raw_dir, source_key, label
        )
    except CliSourceError as exc:
        logging.getLogger(__name__).warning("%s", exc)
        return None


def resolve_source_path(
    explicit_path: Path | None,
    manifest_path: Path,
    raw_dir: Path,
    source_key: str,
    label: str,
) -> Path:
    if explicit_path is not None:
        if not explicit_path.exists():
            raise CliSourceError(f"{label} source file not found: {explicit_path}")
        return explicit_path

    manifest_path = Path(manifest_path)
    if not manifest_path.exists():
        raise CliSourceError(
            f"No {label} source provided and manifest not found: {manifest_path}. "
            "Run download-sources with source URLs first, or pass the source file "
            "explicitly."
        )

    manifest = load_manifest(manifest_path)
    candidates: list[Path] = []
    for entry in manifest.values():
        local_filename = str(entry.get("local_filename") or "")
        manifest_source_key = str(entry.get("source_key") or "")
        if manifest_source_key and manifest_source_key != source_key:
            continue
        if not manifest_source_key and not local_filename.startswith(source_key):
            continue
        local_path = resolve_manifest_local_path(
            local_filename=local_filename,
            manifest_path=manifest_path,
            raw_dir=raw_dir,
        )
        if local_path.exists():
            candidates.append(local_path)

    if not candidates:
        candidates = find_raw_source_candidates(raw_dir, source_key)

    if not candidates:
        raise CliSourceError(
            f"No {label} source found in {manifest_path} for key {source_key}. "
            "Run download-sources with the corresponding URL, or pass the source "
            "file explicitly."
        )
    return sorted(candidates)[-1]


def find_raw_source_candidates(raw_dir: Path, source_key: str) -> list[Path]:
    if not raw_dir.exists():
        return []
    supported_suffixes = {".csv", ".zip", ".xlsx", ".xls", ".parquet"}
    return sorted(
        path
        for path in raw_dir.iterdir()
        if path.is_file()
        and path.name.startswith(source_key)
        and path.suffix.lower() in supported_suffixes
    )


def resolve_manifest_local_path(
    local_filename: str,
    manifest_path: Path,
    raw_dir: Path,
) -> Path:
    local_path = Path(local_filename)
    if local_path.is_absolute():
        return local_path
    if raw_dir != DEFAULT_RAW_DIR:
        return raw_dir / local_filename
    return manifest_path.parent / "raw" / local_filename


def build_source_references(args: argparse.Namespace) -> list[SourceReference]:
    source_specs = (
        (SOURCE_KEYS["income"], "INSEE Filosofi IRIS", args.income_source),
        (
            SOURCE_KEYS["population"],
            "INSEE Recensement de la population IRIS",
            args.population_source,
        ),
        (
            SOURCE_KEYS["household"],
            "INSEE Recensement de la population IRIS - ménages",
            args.household_source,
        ),
        (
            SOURCE_KEYS["retired_csp"],
            "INSEE Recensement de la population IRIS - retraités CSP+",
            args.retired_csp_source,
        ),
        (SOURCE_KEYS["iris_geography"], "INSEE Géographie IRIS", args.iris_source),
    )
    return [
        source_from_url(key=key, name=name, url=url)
        for key, name, url in source_specs
        if url
    ]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
