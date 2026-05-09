from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
import sqlite3
import os
from constants import MAPPING_HEADCOUNT

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI()

templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


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


def build_display_rows(companies_list: list[dict], code_to_name: dict[str, str]) -> list[dict]:
    """Construit les lignes à afficher en insérant les sections NAF avant les entreprises."""
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


@app.get("/")
def home(request: Request, page: int = 1, limit: int = 50):
    """Affiche la page HTML avec les données des entreprises."""
    conn = get_db_connection()
    total_count = conn.execute("SELECT COUNT(*) as count FROM companies").fetchone()[
        "count"
    ]
    offset = (page - 1) * limit

    companies = conn.execute(
        """
        SELECT siret, nic, dateCreationEtablissement, 
               trancheEffectifsEtablissement, activitePrincipaleEtablissement
        FROM companies
        ORDER BY SUBSTR(activitePrincipaleEtablissement, 1, 2),
                 SUBSTR(activitePrincipaleEtablissement, 1, 4),
                 activitePrincipaleEtablissement,
                 dateCreationEtablissement DESC,
                 siret
        LIMIT ? OFFSET ?
    """,
        (limit, offset),
    ).fetchall()

    naf_codes = conn.execute(
        """
        SELECT code, name from naf_code
        """,
    ).fetchall()

    conn.close()

    companies_list = [
        {
            **dict(row),
            "trancheEffectifsEtablissement": MAPPING_HEADCOUNT.get(
                dict(row).get("trancheEffectifsEtablissement"),
                dict(row).get("trancheEffectifsEtablissement"),
            ),
        } for row in companies
    ]
    naf_code_list = [dict(row) for row in naf_codes]

    code_to_name = {item["code"]: item["name"] for item in naf_code_list}

    for company in companies_list:
        code = company.get("activitePrincipaleEtablissement")
        if code in code_to_name:
            company["libelle"] = code_to_name[code]

    display_rows = build_display_rows(companies_list, code_to_name)
    total_pages = (total_count + limit - 1) // limit

    context = {
        "request": request,
        "companies": display_rows,
        "page": page,
        "total_pages": total_pages,
        "total_count": total_count,
        "limit": limit,
    }

    return templates.TemplateResponse(request, "index.html", context)


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
def get_companies_api(page: int = 1, limit: int = 50, filter_activity: str = None):
    """API pour récupérer les entreprises en JSON."""
    conn = get_db_connection()

    # Requête de base
    query = "SELECT * FROM companies"
    params = []

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
def get_naf_sections_api(page: int = 1, limit: int = 50, filter_activity: str = None):
    """API pour récupérer les sections naf en JSON."""
    conn = get_db_connection()

    # Requête de base
    query = "SELECT * FROM naf_code"
    params = []

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
