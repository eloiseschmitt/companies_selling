from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import sqlite3
import os
from typing import List, Dict

# Obtenir le chemin absolu du répertoire courant
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI()

templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


def get_db_connection():
    """Crée une connexion à la base de données SQLite."""
    db_path = os.path.join(BASE_DIR, "companies.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


@app.get("/")
def home(request: Request, page: int = 1, limit: int = 50):
    """Affiche la page HTML avec les données des entreprises."""
    conn = get_db_connection()

    # Récupérer le nombre total d'enregistrements
    total_count = conn.execute("SELECT COUNT(*) as count FROM companies").fetchone()[
        "count"
    ]

    # Calculer les offsets pour la pagination
    offset = (page - 1) * limit

    # Récupérer les données paginées
    companies = conn.execute(
        """
        SELECT siret, nic, dateCreationEtablissement, 
               trancheEffectifsEtablissement, activitePrincipaleEtablissement
        FROM companies
        ORDER BY dateCreationEtablissement DESC
        LIMIT ? OFFSET ?
    """,
        (limit, offset),
    ).fetchall()

    conn.close()

    # Convertir les Row en dict pour le template
    companies_list = [dict(row) for row in companies]

    total_pages = (total_count + limit - 1) // limit

    context = {
        "request": request,
        "companies": companies_list,
        "page": page,
        "total_pages": total_pages,
        "total_count": total_count,
        "limit": limit,
    }

    return templates.TemplateResponse(request, "index.html", context)


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
    query += " ORDER BY dateCreationEtablissement DESC LIMIT ? OFFSET ?"
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
