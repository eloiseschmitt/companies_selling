import csv
import io
import os
import re
import sqlite3
from datetime import date, datetime
from urllib.parse import quote_plus, urlencode

from dotenv import load_dotenv
from fastapi import HTTPException, Request
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app import app
from constants import MAPPING_HEADCOUNT
from services.independants_repository import (
    ALLOWED_SORT_COLUMNS,
    count_deleted_independants,
    mark_independant_deleted,
    update_independant_commentaires,
    update_independant_contacte,
    update_independant_telephone,
)
from services.independants_repository import list_independants as list_db_independants

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

import admin  # noqa: E402,F401

templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
MAX_INDEPENDANTS_LIMIT = 200
MAX_INDEPENDANTS_TABLE_LIMIT = 500
INTERESTING_PROFILE_MIN_SCORE = 6
NAF_BADGES = {
    "8121Z": "Ménage / nettoyage courant",
    "8129B": "Nettoyage divers",
    "8130Z": "Jardinage",
    "8810A": "Aide à domicile",
    "8810B": "Accompagnement social",
}
INDEPENDANTS_TABLE_SORT_COLUMNS = (
    "nom_ou_denomination",
    "commune",
    "code_postal",
    "code_naf_retenu",
    "date_creation_etablissement",
    "age_etablissement_annees",
    "score_priorisation",
)
COMPANY_EXPORT_COLUMNS = [
    "siren",
    "siret",
    "nic",
    "denomination_legale",
    "prenom",
    "nom",
    "dateCreationEtablissement",
    "trancheEffectifsEtablissement",
    "activitePrincipaleEtablissement",
    "libelle",
    "score",
]


class IndependantItem(BaseModel):
    siren: str
    siret: str
    nom_ou_denomination: str
    commune: str
    code_postal: str
    code_naf_retenu: str
    date_creation_etablissement: str
    age_etablissement_annees: int | None
    categorie_juridique_unite_legale: str
    est_entrepreneur_individuel: bool
    est_micro_entrepreneur_probable: bool
    caractere_employeur_unite_legale: str
    score_priorisation: int
    contacte: bool = False
    telephone: str = ""
    commentaires: str = ""
    adresse_complete: str


class IndependantsResponse(BaseModel):
    items: list[IndependantItem]
    total: int
    limit: int
    offset: int


class IndependantTelephoneUpdate(BaseModel):
    telephone: str = ""


class IndependantTelephoneResponse(BaseModel):
    siret: str
    telephone: str


class IndependantContacteUpdate(BaseModel):
    contacte: bool


class IndependantContacteResponse(BaseModel):
    siret: str
    contacte: bool


class IndependantCommentairesUpdate(BaseModel):
    commentaires: str = ""


class IndependantCommentairesResponse(BaseModel):
    siret: str
    commentaires: str


class IndependantDeleteResponse(BaseModel):
    siret: str
    supprime: bool


def get_db_connection():
    """Crée une connexion à la base de données SQLite."""
    db_path = os.path.join(BASE_DIR, "companies.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def get_naf_parent_codes(code: str | None) -> tuple[str | None, str | None]:
    """Retourne les codes NAF parents de niveau 2 et 3 caractères."""
    if not code:
        return None, None

    normalized_code = str(code).strip()
    if len(normalized_code) < 2:
        return None, None

    level_2_code = normalized_code[:2]
    level_3_code = normalized_code[:4] if len(normalized_code) >= 4 else None
    return level_2_code, level_3_code


def build_display_rows(
    companies_list: list[dict], code_to_name: dict[str, str]
) -> list[dict]:
    """Construit les lignes à afficher avec les sections NAF."""
    display_rows = []
    current_level_2 = None
    current_level_3 = None

    for company in companies_list:
        level_2_code, level_3_code = get_naf_parent_codes(
            company.get("activitePrincipaleEtablissement")
        )
        level_2_name = code_to_name.get(level_2_code, "") if level_2_code else ""
        level_3_name = code_to_name.get(level_3_code, "") if level_3_code else ""

        if level_2_code and level_2_name and level_2_code != current_level_2:
            display_rows.append(
                {
                    "row_type": "section",
                    "section_level": 2,
                    "section_code": level_2_code,
                    "section_name": level_2_name,
                }
            )
            current_level_2 = level_2_code
            current_level_3 = None

        if level_3_code and level_3_name and level_3_code != current_level_3:
            display_rows.append(
                {
                    "row_type": "section",
                    "section_level": 3,
                    "section_code": level_3_code,
                    "section_name": level_3_name,
                }
            )
            current_level_3 = level_3_code

        display_rows.append(
            {
                **company,
                "row_type": "company",
            }
        )

    return display_rows


def build_naf_sections_tree(naf_rows: list[sqlite3.Row]) -> list[dict]:
    """Construit l'arbre des sections NAF de niveau 2 et 4 caractères."""
    sections_level_2 = []
    code_to_section: dict[str, dict] = {}

    for row in naf_rows:
        code = row["code"]
        if len(code) == 2:
            section = {
                "code": code,
                "name": row["name"],
                "children": [],
            }
            sections_level_2.append(section)
            code_to_section[code] = section

    for row in naf_rows:
        code = row["code"]
        if len(code) != 4:
            continue
        parent_code = code[:2]
        parent_section = code_to_section.get(parent_code)
        if not parent_section:
            continue
        parent_section["children"].append(
            {
                "code": code,
                "name": row["name"],
            }
        )

    return sections_level_2


def normalize_naf_code(code: str | None) -> str:
    """Normalise un code NAF fourni par l'utilisateur."""
    if not code:
        return ""
    compact_code = code.strip().replace(".", "").upper()
    if len(compact_code) <= 2:
        return compact_code
    return f"{compact_code[:2]}.{compact_code[2:]}"


def parse_naf_codes(codes: str | None) -> list[str]:
    """Retourne les codes NAF normalisés depuis une saisie libre."""
    if not codes:
        return []

    normalized_codes = []
    seen_codes = set()
    for raw_code in re.split(r"[\s,;]+", codes):
        normalized_code = normalize_naf_code(raw_code)
        if not normalized_code or normalized_code in seen_codes:
            continue
        normalized_codes.append(normalized_code)
        seen_codes.add(normalized_code)

    return normalized_codes


def build_company_filter_clause(
    section_code: str | None,
    naf_codes: list[str],
) -> tuple[str, list[str]]:
    """Construit les filtres SQL applicables à la liste des entreprises."""
    clauses = []
    params = []

    normalized_section = normalize_naf_code(section_code)
    if normalized_section:
        clauses.append("activitePrincipaleEtablissement LIKE ?")
        params.append(f"{normalized_section}%")

    if naf_codes:
        placeholders = ", ".join("?" for _ in naf_codes)
        clauses.append(f"activitePrincipaleEtablissement IN ({placeholders})")
        params.extend(naf_codes)

    if not clauses:
        return "", []

    return f" WHERE {' AND '.join(clauses)}", params


def get_score_sort_direction(sort_score: str | None) -> str:
    """Normalise la direction de tri du score."""
    if sort_score == "asc":
        return "ASC"
    return "DESC"


def get_company_score_sql() -> str:
    """Retourne l'expression SQL du score métier."""
    return """
        (
            CASE
                WHEN dateCreationEtablissement IS NOT NULL
                     AND dateCreationEtablissement != ''
                     AND dateCreationEtablissement < date('now', '-30 years')
                THEN 3
                ELSE 0
            END
            +
            CASE
                WHEN trancheEffectifsEtablissement IN ('03', '11')
                THEN 2
                ELSE 0
            END
        )
    """


def build_company_query(
    where_clause: str,
    score_sort_direction: str,
    paginated: bool = False,
) -> str:
    pagination_sql = "LIMIT ? OFFSET ?" if paginated else ""
    score_sql = get_company_score_sql()
    return f"""
        SELECT SUBSTR(siret, 1, 9) AS siren,
               siret, nic, dateCreationEtablissement,
               trancheEffectifsEtablissement, activitePrincipaleEtablissement,
               denomination_legale, prenom, nom,
               {score_sql} AS score
        FROM companies
        {where_clause}
        ORDER BY SUBSTR(activitePrincipaleEtablissement, 1, 2),
                 SUBSTR(activitePrincipaleEtablissement, 1, 4),
                 activitePrincipaleEtablissement,
                 score {score_sort_direction},
                 dateCreationEtablissement DESC,
                 siret
        {pagination_sql}
    """


def get_naf_code_map(conn: sqlite3.Connection) -> dict[str, str]:
    naf_codes = conn.execute(
        """
        SELECT code, name from naf_code
        """,
    ).fetchall()
    return {row["code"]: row["name"] for row in naf_codes}


def format_company_row(row: sqlite3.Row, code_to_name: dict[str, str]) -> dict:
    company = dict(row)
    headcount_code = company.get("trancheEffectifsEtablissement")
    naf_code = company.get("activitePrincipaleEtablissement")
    company["trancheEffectifsEtablissement"] = MAPPING_HEADCOUNT.get(
        str(headcount_code) if headcount_code is not None else "",
        headcount_code,
    )
    company["libelle"] = code_to_name.get(
        str(naf_code) if naf_code is not None else "",
        "",
    )
    return company


def build_export_query_string(
    section: str | None,
    naf_code: str | None,
    sort_score: str | None,
) -> str:
    params = {}
    if section:
        params["section"] = section
    if naf_code:
        params["naf_code"] = naf_code
    if sort_score:
        params["sort_score"] = sort_score
    return urlencode(params)


def build_independants_query_string(
    q: str | None = None,
    commune: str | None = None,
    code_postal: str | None = None,
    code_naf: str | None = None,
    score_min: str | None = None,
    annee_creation: str | None = None,
    telephone_renseigne: str | None = None,
    employeur: str | None = None,
    sort_by: str | None = None,
    sort_order: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> str:
    params = {}
    for key, value in (
        ("q", q),
        ("commune", commune),
        ("code_postal", code_postal),
        ("code_naf", code_naf),
        ("score_min", score_min),
        ("annee_creation", annee_creation),
        ("telephone_renseigne", telephone_renseigne),
        ("employeur", employeur),
        ("sort_by", sort_by),
        ("sort_order", sort_order),
        ("limit", limit),
        ("offset", offset),
    ):
        if value not in (None, ""):
            params[key] = value
    return urlencode(params)


def build_active_independants_filters(
    q: str | None,
    commune: str | None,
    code_postal: str | None,
    code_naf: str | None,
    score_min: str | None,
    annee_creation: str | None,
    telephone_renseigne: str | None,
    employeur: str | None,
) -> list[dict[str, str]]:
    filters = []
    for label, value in (
        ("Recherche", q),
        ("Commune", commune),
        ("Code postal", code_postal),
        ("Code NAF", code_naf),
        ("Score minimum", score_min),
        ("Année création", annee_creation),
        ("Téléphone renseigné", telephone_renseigne),
        ("Employeur", employeur),
    ):
        if value not in (None, ""):
            filters.append({"label": label, "value": str(value)})
    return filters


def enrich_independants_table_rows(rows: list[dict]) -> list[dict]:
    return [enrich_independant_table_row(row) for row in rows]


def enrich_independant_table_row(row: dict) -> dict:
    code_naf = normalize_independant_naf_code(row.get("code_naf_retenu"))
    score = int(row.get("score_priorisation") or 0)
    maps_query = " ".join(
        str(part)
        for part in (
            row.get("adresse_complete"),
            row.get("code_postal"),
            row.get("commune"),
        )
        if part
    )
    return {
        **row,
        "code_naf_normalise": code_naf,
        "code_naf_label": NAF_BADGES.get(code_naf, code_naf or "Activité inconnue"),
        "profil_interessant": score >= INTERESTING_PROFILE_MIN_SCORE,
        "row_class": (
            "interesting-row" if score >= INTERESTING_PROFILE_MIN_SCORE else ""
        ),
        "google_maps_url": (
            f"https://www.google.com/maps/search/?api=1&query={quote_plus(maps_query)}"
            if maps_query
            else ""
        ),
    }


def normalize_independant_naf_code(value: object) -> str:
    return str(value or "").replace(".", "").strip().upper()


def build_companies_csv(companies: list[dict]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=COMPANY_EXPORT_COLUMNS)
    writer.writeheader()
    for company in companies:
        writer.writerow(
            {column: company.get(column, "") for column in COMPANY_EXPORT_COLUMNS}
        )
    return output.getvalue()


def company_is_older_than_30_years(creation_date: str | None) -> bool:
    """Retourne True si la date de création a plus de 30 ans."""
    if not creation_date:
        return False

    try:
        parsed_date = datetime.strptime(creation_date, "%Y-%m-%d").date()
    except ValueError:
        return False

    today = date.today()
    age = (
        today.year
        - parsed_date.year
        - ((today.month, today.day) < (parsed_date.month, parsed_date.day))
    )
    return age > 30


def company_headcount_is_between_6_and_19(headcount_code: str | None) -> bool:
    """Retourne True si le nombre de salariés est > 5 et < 20."""
    return headcount_code in {"03", "11"}


def compute_company_score(company: dict) -> int:
    """Calcule le score métier affiché dans le tableau."""
    score = 0

    if company_is_older_than_30_years(company.get("dateCreationEtablissement")):
        score += 3

    if company_headcount_is_between_6_and_19(
        company.get("trancheEffectifsEtablissement")
    ):
        score += 2

    return score


@app.get("/")
def home(
    request: Request,
    page: int = 1,
    limit: int = 50,
    section: str | None = None,
    naf_code: str | None = None,
    sort_score: str | None = None,
):
    """Affiche la page HTML avec les données des entreprises."""
    conn = get_db_connection()
    selected_section = normalize_naf_code(section)
    selected_naf_codes = parse_naf_codes(naf_code)
    selected_naf_codes_query = ",".join(selected_naf_codes)
    where_clause, where_params = build_company_filter_clause(
        selected_section,
        selected_naf_codes,
    )
    score_sort_direction = get_score_sort_direction(sort_score)
    total_count = conn.execute(
        f"SELECT COUNT(*) as count FROM companies{where_clause}",
        where_params,
    ).fetchone()["count"]
    offset = (page - 1) * limit

    companies = conn.execute(
        build_company_query(where_clause, score_sort_direction, paginated=True),
        [*where_params, limit, offset],
    ).fetchall()

    code_to_name = get_naf_code_map(conn)

    conn.close()

    companies_list = [format_company_row(row, code_to_name) for row in companies]

    display_rows = build_display_rows(companies_list, code_to_name)
    total_pages = (total_count + limit - 1) // limit
    selected_section_name = (
        code_to_name.get(selected_section, "") if selected_section else ""
    )
    selected_naf_code_names = [
        {"code": code, "name": code_to_name.get(code, "")}
        for code in selected_naf_codes
    ]

    context = {
        "request": request,
        "companies": display_rows,
        "page": page,
        "total_pages": total_pages,
        "total_count": total_count,
        "limit": limit,
        "selected_section": selected_section,
        "selected_section_name": selected_section_name,
        "selected_naf_code": selected_naf_codes_query,
        "selected_naf_codes": selected_naf_code_names,
        "sort_score": sort_score or "desc",
        "next_sort_score": "asc" if (sort_score or "desc") == "desc" else "desc",
        "export_query": build_export_query_string(
            selected_section,
            selected_naf_codes_query,
            sort_score or "desc",
        ),
    }

    return templates.TemplateResponse(request, "index.html", context)


@app.get("/companies.csv")
def export_companies_csv(
    section: str | None = None,
    naf_code: str | None = None,
    sort_score: str | None = None,
):
    """Exporte en CSV les entreprises correspondant aux filtres de la page home."""
    conn = get_db_connection()
    selected_section = normalize_naf_code(section)
    selected_naf_codes = parse_naf_codes(naf_code)
    where_clause, where_params = build_company_filter_clause(
        selected_section,
        selected_naf_codes,
    )
    score_sort_direction = get_score_sort_direction(sort_score)
    companies = conn.execute(
        build_company_query(where_clause, score_sort_direction),
        where_params,
    ).fetchall()
    code_to_name = get_naf_code_map(conn)
    conn.close()

    companies_list = [format_company_row(row, code_to_name) for row in companies]
    csv_content = build_companies_csv(companies_list)
    headers = {
        "Content-Disposition": 'attachment; filename="companies_export.csv"',
    }
    return Response(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers=headers,
    )


@app.get("/independants", response_model=IndependantsResponse)
def get_independants(
    q: str | None = None,
    commune: str | None = None,
    code_postal: str | None = None,
    code_naf: str | None = None,
    score_min: str | None = None,
    employeur: str | None = None,
    sort_by: str | None = None,
    sort_order: str = "asc",
    limit: int = 50,
    offset: int = 0,
) -> IndependantsResponse:
    """Retourne les indépendants depuis la table SQLite consolidée."""
    if limit < 1 or limit > MAX_INDEPENDANTS_LIMIT:
        raise HTTPException(
            status_code=400,
            detail=f"limit doit être compris entre 1 et {MAX_INDEPENDANTS_LIMIT}.",
        )
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset doit être positif.")
    if sort_by and sort_by not in ALLOWED_SORT_COLUMNS:
        raise HTTPException(status_code=400, detail=f"Tri non autorisé: {sort_by}")
    if sort_order not in {"asc", "desc"}:
        raise HTTPException(
            status_code=400,
            detail="sort_order doit valoir 'asc' ou 'desc'.",
        )

    filters = {
        "q": q,
        "commune": commune,
        "code_postal": code_postal,
        "code_naf": code_naf,
        "score_min": score_min,
        "employeur": employeur,
    }
    sort = {"column": sort_by, "direction": sort_order} if sort_by else {}

    try:
        page = list_db_independants(
            filters=filters,
            sort=sort,
            pagination={"limit": limit, "offset": offset},
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return IndependantsResponse(
        items=[IndependantItem.model_validate(item) for item in page["data"]],
        total=page["total"],
        limit=page["limit"],
        offset=page["offset"],
    )


@app.patch(
    "/independants/{siret}/telephone",
    response_model=IndependantTelephoneResponse,
)
def update_independant_telephone_endpoint(
    siret: str,
    payload: IndependantTelephoneUpdate,
) -> IndependantTelephoneResponse:
    """Met à jour le téléphone d'un indépendant depuis la table HTML."""
    try:
        telephone = update_independant_telephone(siret, payload.telephone)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if telephone is None:
        raise HTTPException(status_code=404, detail="Indépendant introuvable.")

    return IndependantTelephoneResponse(siret=siret, telephone=telephone)


@app.patch(
    "/independants/{siret}/contacte",
    response_model=IndependantContacteResponse,
)
def update_independant_contacte_endpoint(
    siret: str,
    payload: IndependantContacteUpdate,
) -> IndependantContacteResponse:
    """Met à jour le statut contacté d'un indépendant depuis la table HTML."""
    contacte = update_independant_contacte(siret, payload.contacte)
    if contacte is None:
        raise HTTPException(status_code=404, detail="Indépendant introuvable.")
    return IndependantContacteResponse(siret=siret, contacte=contacte)


@app.patch(
    "/independants/{siret}/commentaires",
    response_model=IndependantCommentairesResponse,
)
def update_independant_commentaires_endpoint(
    siret: str,
    payload: IndependantCommentairesUpdate,
) -> IndependantCommentairesResponse:
    """Met à jour les commentaires d'un indépendant depuis la table HTML."""
    commentaires = update_independant_commentaires(siret, payload.commentaires)
    if commentaires is None:
        raise HTTPException(status_code=404, detail="Indépendant introuvable.")
    return IndependantCommentairesResponse(siret=siret, commentaires=commentaires)


@app.delete(
    "/independants/{siret}",
    response_model=IndependantDeleteResponse,
)
def delete_independant_endpoint(siret: str) -> IndependantDeleteResponse:
    """Masque un indépendant de la table en le marquant comme supprimé."""
    deleted = mark_independant_deleted(siret)
    if not deleted:
        raise HTTPException(status_code=404, detail="Indépendant introuvable.")
    return IndependantDeleteResponse(siret=siret, supprime=True)


@app.get("/independants/table")
def independants_table(
    request: Request,
    q: str | None = None,
    commune: str | None = None,
    code_postal: str | None = None,
    code_naf: str | None = None,
    score_min: str | None = None,
    annee_creation: str | None = None,
    telephone_renseigne: str | None = None,
    employeur: str | None = None,
    sort_by: str | None = "score_priorisation",
    sort_order: str = "desc",
    limit: int = 50,
    offset: int = 0,
):
    """Affiche les indépendants depuis la table SQLite sous forme de tableau HTML."""
    if limit < 1 or limit > MAX_INDEPENDANTS_TABLE_LIMIT:
        raise HTTPException(
            status_code=400,
            detail=(
                f"limit doit être compris entre 1 et {MAX_INDEPENDANTS_TABLE_LIMIT}."
            ),
        )
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset doit être positif.")
    if sort_by and sort_by not in INDEPENDANTS_TABLE_SORT_COLUMNS:
        raise HTTPException(status_code=400, detail=f"Tri non autorisé: {sort_by}")
    if sort_order not in {"asc", "desc"}:
        raise HTTPException(
            status_code=400,
            detail="sort_order doit valoir 'asc' ou 'desc'.",
        )

    filters = {
        "q": q,
        "commune": commune,
        "code_postal": code_postal,
        "code_naf": code_naf,
        "score_min": score_min,
        "annee_creation": annee_creation,
        "telephone_renseigne": telephone_renseigne,
        "employeur": employeur,
        "supprime": False,
    }
    sort = {"column": sort_by, "direction": sort_order} if sort_by else {}

    try:
        page = list_db_independants(
            filters=filters,
            sort=sort,
            pagination={"limit": limit, "offset": offset},
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    deleted_total = count_deleted_independants()
    previous_offset = max(0, offset - limit)
    next_offset = offset + limit
    has_previous = offset > 0
    has_next = next_offset < page["total"]
    previous_query = build_independants_query_string(
        q=q,
        commune=commune,
        code_postal=code_postal,
        code_naf=code_naf,
        score_min=score_min,
        annee_creation=annee_creation,
        telephone_renseigne=telephone_renseigne,
        employeur=employeur,
        sort_by=sort_by,
        sort_order=sort_order,
        limit=limit,
        offset=previous_offset,
    )
    next_query = build_independants_query_string(
        q=q,
        commune=commune,
        code_postal=code_postal,
        code_naf=code_naf,
        score_min=score_min,
        annee_creation=annee_creation,
        telephone_renseigne=telephone_renseigne,
        employeur=employeur,
        sort_by=sort_by,
        sort_order=sort_order,
        limit=limit,
        offset=next_offset,
    )

    return templates.TemplateResponse(
        request,
        "independants_table.html",
        {
            "request": request,
            "items": enrich_independants_table_rows(page["data"]),
            "total": page["total"],
            "deleted_total": deleted_total,
            "limit": limit,
            "max_limit": MAX_INDEPENDANTS_TABLE_LIMIT,
            "offset": offset,
            "q": q or "",
            "commune": commune or "",
            "code_postal": code_postal or "",
            "code_naf": code_naf or "",
            "score_min": score_min or "",
            "annee_creation": annee_creation or "",
            "telephone_renseigne": telephone_renseigne or "",
            "employeur": employeur or "",
            "sort_by": sort_by or "",
            "sort_order": sort_order,
            "active_filters": build_active_independants_filters(
                q=q,
                commune=commune,
                code_postal=code_postal,
                code_naf=code_naf,
                score_min=score_min,
                annee_creation=annee_creation,
                telephone_renseigne=telephone_renseigne,
                employeur=employeur,
            ),
            "has_previous": has_previous,
            "has_next": has_next,
            "previous_url": f"/independants/table?{previous_query}",
            "next_url": f"/independants/table?{next_query}",
            "start_index": 0 if page["total"] == 0 else offset + 1,
            "end_index": min(offset + limit, page["total"]),
        },
    )


@app.get("/naf_sections")
def naf_sections_page(request: Request):
    """Affiche la liste des sections NAF de niveau 2 et de leurs sous-sections."""
    conn = get_db_connection()
    naf_rows = conn.execute(
        """
        SELECT code, name
        FROM naf_code
        WHERE LENGTH(code) IN (2, 4)
        ORDER BY code
        """
    ).fetchall()
    conn.close()

    sections = build_naf_sections_tree(naf_rows)

    return templates.TemplateResponse(
        request,
        "naf_sections.html",
        {
            "request": request,
            "sections": sections,
            "total_sections": len(sections),
        },
    )


@app.get("/api/companies")
def get_companies_api(
    page: int = 1, limit: int = 50, filter_activity: str | None = None
):
    """API pour récupérer les entreprises en JSON."""
    conn = get_db_connection()

    # Requête de base
    query = "SELECT * FROM companies"
    params: list[str | int] = []

    # Ajouter le filtre d'activité si fourni
    if filter_activity:
        query += " WHERE activitePrincipaleEtablissement = ?"
        params.append(filter_activity)

    # Compter le total
    count_query = f"SELECT COUNT(*) as count FROM ({query})"
    total_count = conn.execute(count_query, params).fetchone()["count"]

    # Pagination
    offset = (page - 1) * limit
    query += """
        ORDER BY SUBSTR(activitePrincipaleEtablissement, 1, 2),
                 SUBSTR(activitePrincipaleEtablissement, 1, 4),
                 activitePrincipaleEtablissement,
                 dateCreationEtablissement DESC,
                 siret
        LIMIT ? OFFSET ?
    """
    params.extend([limit, offset])

    companies = conn.execute(query, params).fetchall()
    conn.close()

    companies_list = [dict(row) for row in companies]
    total_pages = (total_count + limit - 1) // limit

    return {
        "data": companies_list,
        "page": page,
        "total_pages": total_pages,
        "total_count": total_count,
        "limit": limit,
    }


@app.get("/api/naf_sections")
def get_naf_sections_api(
    page: int = 1, limit: int = 50, filter_activity: str | None = None
):
    """API pour récupérer les sections naf en JSON."""
    conn = get_db_connection()

    # Requête de base
    query = "SELECT * FROM naf_code"
    params: list[str | int] = []

    # Ajouter le filtre d'activité si fourni
    if filter_activity:
        query += " WHERE LENGTH(code) < 5"
        params.append(filter_activity)

    # Compter le total
    count_query = f"SELECT COUNT(*) as count FROM ({query})"
    total_count = conn.execute(count_query, params).fetchone()["count"]

    # Pagination
    offset = (page - 1) * limit
    params.extend([limit, offset])

    sections = conn.execute(query, params).fetchall()
    conn.close()

    section_list = [dict(row) for row in sections]
    total_pages = (total_count + limit - 1) // limit

    return {
        "data": section_list,
        "page": page,
        "total_pages": total_pages,
        "total_count": total_count,
        "limit": limit,
    }
