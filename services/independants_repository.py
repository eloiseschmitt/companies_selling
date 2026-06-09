"""Lecture filtrée des indépendants depuis la table SQLite `independants`."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal, TypedDict

DEFAULT_DATABASE_PATH = Path("companies.db")
TABLE_NAME = "independants"

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
    "telephone",
    "adresse_complete",
)

ALLOWED_SORT_COLUMNS = frozenset(RETURN_FIELDS)
DEFAULT_LIMIT = 50
MAX_LIMIT = 500
TEXT_SEARCH_FIELDS = (
    "siren",
    "siret",
    "nom_ou_denomination",
    "commune",
    "code_postal",
    "code_naf_retenu",
    "adresse_complete",
)


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
    database_path: Path = DEFAULT_DATABASE_PATH,
) -> IndependantsPage:
    """Liste les indépendants depuis SQLite avec filtres, tri et pagination."""
    limit, offset = _parse_pagination(pagination)
    if not database_path.exists():
        return _empty_page(limit, offset)

    where_clause, params = _build_where_clause(filters or {})
    sort_column, sort_direction = _parse_sort(sort)
    order_clause = _build_order_clause(sort_column, sort_direction)
    columns = ", ".join(RETURN_FIELDS)

    with sqlite3.connect(database_path) as conn:
        conn.row_factory = sqlite3.Row
        if not _table_exists(conn):
            return _empty_page(limit, offset)
        _ensure_telephone_column(conn)

        total = conn.execute(
            f"SELECT COUNT(*) FROM {TABLE_NAME}{where_clause}",
            params,
        ).fetchone()[0]
        rows = conn.execute(
            f"""
            SELECT {columns}
            FROM {TABLE_NAME}
            {where_clause}
            {order_clause}
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()

    return {
        "data": [_project_row(row) for row in rows],
        "total": int(total),
        "limit": limit,
        "offset": offset,
    }


def _build_where_clause(filters: Mapping[str, Any]) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    commune = _clean(filters.get("commune"))
    if commune:
        clauses.append("UPPER(commune) = UPPER(?)")
        params.append(commune)

    code_postal = _clean(filters.get("code_postal"))
    if code_postal:
        clauses.append("code_postal = ?")
        params.append(code_postal)

    code_naf = _normalize_naf(filters.get("code_naf"))
    if code_naf:
        clauses.append("REPLACE(UPPER(code_naf_retenu), '.', '') = ?")
        params.append(code_naf)

    score_min = _clean(filters.get("score_min"))
    if score_min:
        try:
            parsed_score_min = int(score_min)
        except ValueError:
            raise ValueError("Le filtre score_min doit être un entier.") from None
        clauses.append("score_priorisation >= ?")
        params.append(parsed_score_min)

    employeur = filters.get("employeur")
    if employeur is not None and employeur != "":
        if _parse_filter_bool(employeur):
            clauses.append("UPPER(caractere_employeur_unite_legale) = 'O'")
        else:
            clauses.append(
                """
                (
                    caractere_employeur_unite_legale IS NULL
                    OR UPPER(caractere_employeur_unite_legale) != 'O'
                )
                """
            )

    text = _clean(filters.get("texte") or filters.get("q"))
    if text:
        escaped_text = f"%{_escape_like(text.casefold())}%"
        clauses.append(
            "("
            + " OR ".join(
                f"LOWER(COALESCE({field}, '')) LIKE ? ESCAPE '\\'"
                for field in TEXT_SEARCH_FIELDS
            )
            + ")"
        )
        params.extend([escaped_text] * len(TEXT_SEARCH_FIELDS))

    if not clauses:
        return "", []
    return f" WHERE {' AND '.join(clauses)}", params


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


def _build_order_clause(column: str | None, direction: SortDirection) -> str:
    if column is None:
        return "ORDER BY nom_ou_denomination COLLATE NOCASE ASC, siret ASC"
    sql_direction = direction.upper()
    return f"ORDER BY {column} IS NULL ASC, {column} COLLATE NOCASE {sql_direction}"


def _parse_pagination(pagination: Mapping[str, Any] | None) -> tuple[int, int]:
    pagination = pagination or {}
    limit = _parse_int(pagination.get("limit"), default=DEFAULT_LIMIT)
    offset = _parse_int(pagination.get("offset"), default=0)
    if limit < 0:
        raise ValueError("limit doit être positif.")
    if offset < 0:
        raise ValueError("offset doit être positif.")
    return min(limit, MAX_LIMIT), offset


def _project_row(row: sqlite3.Row) -> dict[str, Any]:
    projected = {field: row[field] for field in RETURN_FIELDS}
    projected["age_etablissement_annees"] = _parse_optional_int(
        projected["age_etablissement_annees"]
    )
    projected["score_priorisation"] = _parse_int(projected["score_priorisation"])
    projected["est_entrepreneur_individuel"] = _parse_sqlite_bool(
        projected["est_entrepreneur_individuel"]
    )
    projected["est_micro_entrepreneur_probable"] = _parse_sqlite_bool(
        projected["est_micro_entrepreneur_probable"]
    )
    return projected


def _table_exists(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
        """,
        (TABLE_NAME,),
    ).fetchone()
    return row is not None


def _ensure_telephone_column(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({TABLE_NAME})")}
    if "telephone" in columns:
        return
    conn.execute(
        f"ALTER TABLE {TABLE_NAME} ADD COLUMN telephone TEXT NOT NULL DEFAULT ''"
    )
    conn.commit()


def _empty_page(limit: int, offset: int) -> IndependantsPage:
    return {"data": [], "total": 0, "limit": limit, "offset": offset}


def _parse_filter_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value

    normalized = _clean(value).casefold()
    if normalized in {"true", "1", "yes", "oui", "o"}:
        return True
    if normalized in {"false", "0", "no", "non", "n"}:
        return False
    raise ValueError("Le filtre employeur doit être un booléen ou oui/non.")


def _parse_sqlite_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value == 1
    return _clean(value).casefold() in {"true", "1", "yes", "oui", "o"}


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


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()
