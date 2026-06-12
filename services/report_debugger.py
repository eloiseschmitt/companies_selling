"""Debug source coverage against the configured sector IRIS mapping."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas

from services.geography import load_sector_iris_mapping
from services.household_loader import load_household_iris
from services.income_loader import load_filosofi_iris
from services.population_loader import load_population_iris
from services.retired_csp_loader import load_retired_csp_iris

IRIS_COLUMN_CANDIDATES = (
    "iris_code",
    "code_iris",
    "codeiris",
    "iris",
    "cod_iris",
    "depcomiris",
)
SAMPLE_SIZE = 20


@dataclass(frozen=True)
class DebugSource:
    label: str
    path: Path | None
    loader: Callable[[Path], pandas.DataFrame]


@dataclass(frozen=True)
class SourceDebugSummary:
    label: str
    path: Path | None
    error: str | None
    rows: int
    iris_distinct: int
    iris_column: str | None
    sample_iris: tuple[str, ...]
    sectors: tuple[SectorCoverage, ...]


@dataclass(frozen=True)
class SectorCoverage:
    sector_name: str
    configured_count: int
    found_count: int
    missing_count: int
    configured_iris: tuple[str, ...]
    source_sample_iris: tuple[str, ...]
    missing_iris: tuple[str, ...]


def build_debug_report(
    sector_mapping_path: Path,
    income_path: Path | None,
    population_path: Path | None,
    household_path: Path | None,
    retired_csp_path: Path | None,
) -> str:
    """Build a human-readable debug report for source/mapping coverage."""
    mapping = load_sector_iris_mapping(sector_mapping_path)
    sources = (
        DebugSource("Income source", income_path, load_filosofi_iris),
        DebugSource("Population source", population_path, load_population_iris),
        DebugSource("Household source", household_path, load_household_iris),
        DebugSource("Retired/CSP source", retired_csp_path, load_retired_csp_iris),
    )
    summaries = tuple(debug_source(source, mapping) for source in sources)
    return format_debug_report(summaries)


def debug_source(
    source: DebugSource,
    mapping: dict[str, tuple[str, ...]],
) -> SourceDebugSummary:
    if source.path is None:
        return SourceDebugSummary(
            label=source.label,
            path=None,
            error="source file not resolved",
            rows=0,
            iris_distinct=0,
            iris_column=None,
            sample_iris=(),
            sectors=build_empty_sector_coverages(mapping),
        )

    try:
        df = source.loader(source.path)
    except Exception as exc:
        return SourceDebugSummary(
            label=source.label,
            path=source.path,
            error=str(exc),
            rows=0,
            iris_distinct=0,
            iris_column=None,
            sample_iris=(),
            sectors=build_empty_sector_coverages(mapping),
        )

    iris_column = find_iris_column(df.columns)
    if iris_column is None:
        return SourceDebugSummary(
            label=source.label,
            path=source.path,
            error="IRIS column not detected",
            rows=len(df),
            iris_distinct=0,
            iris_column=None,
            sample_iris=(),
            sectors=build_empty_sector_coverages(mapping),
        )

    source_iris = tuple(
        sorted(
            {
                code
                for code in df[iris_column].map(normalize_iris_code).dropna()
                if code
            }
        )
    )
    source_iris_set = set(source_iris)
    sample_iris = source_iris[:SAMPLE_SIZE]
    sectors = tuple(
        build_sector_coverage(sector, codes, source_iris_set, sample_iris)
        for sector, codes in mapping.items()
    )
    return SourceDebugSummary(
        label=source.label,
        path=source.path,
        error=None,
        rows=len(df),
        iris_distinct=len(source_iris),
        iris_column=iris_column,
        sample_iris=sample_iris,
        sectors=sectors,
    )


def build_sector_coverage(
    sector_name: str,
    configured_codes: tuple[str, ...],
    source_iris: set[str],
    source_sample_iris: tuple[str, ...],
) -> SectorCoverage:
    configured_iris = tuple(normalize_iris_code(code) for code in configured_codes)
    found = tuple(code for code in configured_iris if code in source_iris)
    missing = tuple(code for code in configured_iris if code not in source_iris)
    return SectorCoverage(
        sector_name=sector_name,
        configured_count=len(configured_iris),
        found_count=len(found),
        missing_count=len(missing),
        configured_iris=configured_iris,
        source_sample_iris=source_sample_iris,
        missing_iris=missing,
    )


def build_empty_sector_coverages(
    mapping: dict[str, tuple[str, ...]],
) -> tuple[SectorCoverage, ...]:
    return tuple(
        SectorCoverage(
            sector_name=sector,
            configured_count=len(codes),
            found_count=0,
            missing_count=len(codes),
            configured_iris=tuple(normalize_iris_code(code) for code in codes),
            source_sample_iris=(),
            missing_iris=tuple(normalize_iris_code(code) for code in codes),
        )
        for sector, codes in mapping.items()
    )


def format_debug_report(summaries: tuple[SourceDebugSummary, ...]) -> str:
    lines: list[str] = []
    for summary in summaries:
        lines.append(f"{summary.label}:")
        lines.append(f"- file: {summary.path or 'not resolved'}")
        if summary.error:
            lines.append(f"- error: {summary.error}")
        lines.append(f"- rows: {summary.rows}")
        lines.append(f"- iris distinct: {summary.iris_distinct}")
        lines.append(f"- iris column: {summary.iris_column or 'not detected'}")
        lines.append("- sample iris:")
        lines.extend(format_indented_values(summary.sample_iris))
        lines.append("")
        for sector in summary.sectors:
            lines.append("Configured sector:")
            lines.append(sector.sector_name)
            lines.append(f"- configured iris: {sector.configured_count}")
            lines.append(f"- found: {sector.found_count}")
            lines.append(f"- missing: {sector.missing_count}")
            if sector.found_count == 0:
                lines.append("- compared configured iris:")
                lines.extend(format_indented_values(sector.configured_iris))
                lines.append("- compared source sample iris:")
                lines.extend(format_indented_values(sector.source_sample_iris))
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def format_indented_values(values: tuple[str, ...]) -> list[str]:
    if not values:
        return ["  none"]
    return [f"  {value}" for value in values]


def find_iris_column(columns: Any) -> str | None:
    columns_by_normalized_name = {
        normalize_column_name(str(column)): str(column) for column in columns
    }
    for candidate in IRIS_COLUMN_CANDIDATES:
        column = columns_by_normalized_name.get(normalize_column_name(candidate))
        if column:
            return column
    return None


def normalize_column_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def normalize_iris_code(value: Any) -> str:
    if value is None or pandas.isna(value):
        return ""
    return str(value).strip().upper()
