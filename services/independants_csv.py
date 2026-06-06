"""Lecture filtrée du CSV consolidé des indépendants Bordeaux Métropole."""

from __future__ import annotations

import csv
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal, TypedDict

DEFAULT_CSV_PATH = Path("independants_bordeaux_metropole.csv")

RETURN_FIELDS = (
    "siren",
    "siret",
    "nom_ou_denomination",
    "commune",
    "code_postal",
    "code_naf_retenu",
    "date_creation_etablissement",
    "age_etablissement_annees",
    "categorie_juridique_unite_legale",
    "est_entrepreneur_individuel",
    "est_micro_entrepreneur_probable",
    "caractere_employeur_unite_legale",
    "score_priorisation",
    "adresse_complete",
)

ALLOWED_SORT_COLUMNS = frozenset(RETURN_FIELDS)
DEFAULT_LIMIT = 50
MAX_LIMIT = 500


class IndependantsPage(TypedDict):
    data: list[dict[str, Any]]
    total: int
    limit: int
    offset: int


SortDirection = Literal["asc", "desc"]


def list_independants(
    filters: Mapping[str, Any] | None = None,
    sort: Mapping[str, Any] | None = None,
    pagination: Mapping[str, Any] | None = None,
    csv_path: Path = DEFAULT_CSV_PATH,
) -> IndependantsPage:
    """Liste les indépendants depuis le CSV avec filtres, tri et pagination.

    La lecture se fait en mémoire depuis le CSV, sans construction SQL. Le tri est
    limité à une liste blanche de colonnes pour éviter les entrées arbitraires.
    """
    normalized_filters = dict(filters or {})
    rows = [
        _project_row(row)
        for row in _read_csv_rows(csv_path)
        if _matches_filters(row, normalized_filters)
    ]

    sort_column, sort_direction = _parse_sort(sort)
    if sort_column is not None:
        rows.sort(
            key=lambda row: _sort_value(row, sort_column),
            reverse=sort_direction == "desc",
        )

    limit, offset = _parse_pagination(pagination)
    total = len(rows)
    return {
        "data": rows[offset : offset + limit],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def _read_csv_rows(csv_path: Path) -> list[dict[str, str]]:
    if not csv_path.exists():
        return []

    with csv_path.open(newline="", encoding="utf-8-sig") as csv_file:
        return list(csv.DictReader(csv_file))


def _project_row(row: Mapping[str, Any]) -> dict[str, Any]:
    projected: dict[str, Any] = {
        field: _clean(row.get(field)) for field in RETURN_FIELDS
    }
    projected["age_etablissement_annees"] = _parse_optional_int(
        projected["age_etablissement_annees"]
    )
    projected["score_priorisation"] = _parse_int(projected["score_priorisation"])
    projected["est_entrepreneur_individuel"] = _parse_bool(
        projected["est_entrepreneur_individuel"]
    )
    projected["est_micro_entrepreneur_probable"] = _parse_bool(
        projected["est_micro_entrepreneur_probable"]
    )
    return projected


def _matches_filters(row: Mapping[str, Any], filters: Mapping[str, Any]) -> bool:
    if not _matches_text(row, "commune", filters.get("commune")):
        return False
    if not _matches_exact(row, "code_postal", filters.get("code_postal")):
        return False
    if not _matches_naf(row, filters.get("code_naf")):
        return False
    if not _matches_score_min(row, filters.get("score_min")):
        return False
    if not _matches_employeur(row, filters.get("employeur")):
        return False
    return _matches_free_text(row, filters.get("texte") or filters.get("q"))


def _matches_text(row: Mapping[str, Any], field: str, expected: Any) -> bool:
    expected_text = _clean(expected)
    if not expected_text:
        return True
    return _clean(row.get(field)).casefold() == expected_text.casefold()


def _matches_exact(row: Mapping[str, Any], field: str, expected: Any) -> bool:
    expected_text = _clean(expected)
    if not expected_text:
        return True
    return _clean(row.get(field)) == expected_text


def _matches_naf(row: Mapping[str, Any], expected: Any) -> bool:
    expected_text = _clean(expected)
    if not expected_text:
        return True
    return _normalize_naf(row.get("code_naf_retenu")) == _normalize_naf(expected_text)


def _matches_score_min(row: Mapping[str, Any], expected: Any) -> bool:
    expected_text = _clean(expected)
    if not expected_text:
        return True
    try:
        score_min = int(expected_text)
    except ValueError:
        raise ValueError("Le filtre score_min doit être un entier.") from None
    return _parse_int(row.get("score_priorisation")) >= score_min


def _matches_employeur(row: Mapping[str, Any], expected: Any) -> bool:
    if expected is None or expected == "":
        return True
    expected_bool = _parse_filter_bool(expected)
    is_employeur = _clean(row.get("caractere_employeur_unite_legale")).upper() == "O"
    return is_employeur is expected_bool


def _matches_free_text(row: Mapping[str, Any], expected: Any) -> bool:
    expected_text = _clean(expected).casefold()
    if not expected_text:
        return True
    haystack = " ".join(
        _clean(row.get(field))
        for field in (
            "siren",
            "siret",
            "nom_ou_denomination",
            "commune",
            "code_postal",
            "code_naf_retenu",
            "adresse_complete",
        )
    ).casefold()
    return expected_text in haystack


def _parse_sort(sort: Mapping[str, Any] | None) -> tuple[str | None, SortDirection]:
    if not sort:
        return None, "asc"

    column = _clean(sort.get("column") or sort.get("field"))
    if not column:
        return None, "asc"
    if column not in ALLOWED_SORT_COLUMNS:
        raise ValueError(f"Tri non autorisé: {column}")

    direction = _clean(sort.get("direction") or "asc").lower()
    if direction not in {"asc", "desc"}:
        raise ValueError("La direction de tri doit être 'asc' ou 'desc'.")
    if direction == "desc":
        return column, "desc"
    return column, "asc"


def _parse_pagination(pagination: Mapping[str, Any] | None) -> tuple[int, int]:
    pagination = pagination or {}
    limit = _parse_int(pagination.get("limit"), default=DEFAULT_LIMIT)
    offset = _parse_int(pagination.get("offset"), default=0)
    if limit < 0:
        raise ValueError("limit doit être positif.")
    if offset < 0:
        raise ValueError("offset doit être positif.")
    return min(limit, MAX_LIMIT), offset


def _sort_value(row: Mapping[str, Any], column: str) -> tuple[bool, Any]:
    value = row.get(column)
    return value in ("", None), value


def _parse_filter_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value

    normalized = _clean(value).casefold()
    if normalized in {"true", "1", "yes", "oui", "o"}:
        return True
    if normalized in {"false", "0", "no", "non", "n"}:
        return False
    raise ValueError("Le filtre employeur doit être un booléen ou oui/non.")


def _parse_bool(value: Any) -> bool:
    return _clean(value).casefold() == "true"


def _parse_optional_int(value: Any) -> int | None:
    cleaned = _clean(value)
    if not cleaned:
        return None
    return _parse_int(cleaned)


def _parse_int(value: Any, default: int = 0) -> int:
    cleaned = _clean(value)
    if not cleaned:
        return default
    try:
        return int(cleaned)
    except ValueError:
        return default


def _normalize_naf(value: Any) -> str:
    return _clean(value).replace(".", "").upper()


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()
