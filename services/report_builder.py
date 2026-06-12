"""Build sector reports from normalized INSEE IRIS loaders."""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

import pandas

from services.geography import load_sector_iris_mapping
from services.household_loader import (
    extract_single_75_plus_by_iris,
    load_household_iris,
)
from services.income_loader import extract_median_income_by_iris, load_filosofi_iris
from services.population_loader import (
    extract_population_75_plus_by_iris,
    load_population_iris,
)
from services.retired_csp_loader import (
    extract_retired_csp_plus_by_iris,
    load_retired_csp_iris,
)
from services.sector_aggregator import aggregate_sector_indicators

DEFAULT_OUTPUT_DIR = Path("data") / "output"
DEFAULT_SOURCE_MANIFEST = Path("data") / "source_manifest.json"
logger = logging.getLogger(__name__)


class ReportBuildError(RuntimeError):
    """Raised when a sector report cannot be built."""


def build_sector_report(
    sector_mapping_path: Path,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    source_manifest_path: Path = DEFAULT_SOURCE_MANIFEST,
    income_path: Path | None = None,
    population_path: Path | None = None,
    household_path: Path | None = None,
    retired_csp_path: Path | None = None,
    output_format: str = "csv",
) -> pandas.DataFrame:
    """Build sector report files and return the report DataFrame."""
    output_dir.mkdir(parents=True, exist_ok=True)
    mapping = load_sector_iris_mapping(sector_mapping_path)

    income_df = load_optional_income(income_path)
    population_df = load_optional_population(population_path)
    household_df = load_optional_household(household_path)
    retired_csp_df = load_optional_retired_csp(retired_csp_path)

    report = aggregate_sector_indicators(
        mapping,
        income_df=income_df,
        population_df=population_df,
        household_df=household_df,
        retired_csp_df=retired_csp_df,
    )
    csv_path = output_dir / "sector_report.csv"
    xlsx_path = output_dir / "sector_report.xlsx"
    ranking_xlsx_path = output_dir / "sector_ranking.xlsx"
    report.to_csv(csv_path, index=False, encoding="utf-8-sig")
    if output_format in {"xlsx", "all"}:
        write_xlsx(report, xlsx_path)
    elif output_format == "csv":
        # The business requirement asks build-report to generate both files.
        write_xlsx(report, xlsx_path)
    else:
        raise ReportBuildError(f"Unsupported output format: {output_format}")
    write_xlsx(report, ranking_xlsx_path)

    write_output_manifest(source_manifest_path, output_dir / "source_manifest.json")
    write_quality_report(report, output_dir / "quality_report.md")
    return report


def load_optional_income(path: Path | None) -> pandas.DataFrame | None:
    if path is None:
        return None
    try:
        return extract_median_income_by_iris(load_filosofi_iris(path))
    except Exception as exc:
        raise ReportBuildError(
            f"Income source could not be loaded from {path}: {exc}"
        ) from exc


def load_optional_population(path: Path | None) -> pandas.DataFrame | None:
    if path is None:
        return None
    try:
        return extract_population_75_plus_by_iris(load_population_iris(path))
    except Exception as exc:
        raise ReportBuildError(
            f"Population source could not be loaded from {path}: {exc}"
        ) from exc


def load_optional_household(path: Path | None) -> pandas.DataFrame | None:
    if path is None:
        return None
    try:
        return extract_single_75_plus_by_iris(load_household_iris(path))
    except Exception as exc:
        raise ReportBuildError(
            f"Household source could not be loaded from {path}: {exc}"
        ) from exc


def load_optional_retired_csp(path: Path | None) -> pandas.DataFrame | None:
    if path is None:
        return None
    try:
        return extract_retired_csp_plus_by_iris(load_retired_csp_iris(path))
    except Exception as exc:
        raise ReportBuildError(
            f"Retired/CSP source could not be loaded from {path}: {exc}"
        ) from exc


def write_xlsx(report: pandas.DataFrame, output_path: Path) -> None:
    try:
        report.to_excel(output_path, index=False)
    except ImportError as exc:
        raise ReportBuildError(
            "XLSX output requires openpyxl or xlsxwriter. "
            "Install project dependencies from requirements.txt."
        ) from exc


def write_output_manifest(source_manifest_path: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if source_manifest_path.exists():
        shutil.copyfile(source_manifest_path, output_path)
        return
    output_path.write_text(
        json.dumps({"sources": {}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_quality_report(report: pandas.DataFrame, output_path: Path) -> None:
    lines = ["# Quality report", ""]
    if report.empty:
        lines.append("No sector rows were generated.")
    for row in report.to_dict(orient="records"):
        sector_name = row.get("sector_name", "")
        notes = str(row.get("quality_notes") or "No quality notes.")
        source_years = str(row.get("source_years") or "No source years.")
        lines.extend(
            [
                f"## {sector_name}",
                "",
                f"- IRIS: {row.get('iris_codes', '')}",
                f"- Source years: {source_years}",
                f"- Quality notes: {notes}",
                "",
            ]
        )
    output_path.write_text("\n".join(lines), encoding="utf-8")
