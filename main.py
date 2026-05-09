from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import sqlite3

app = FastAPI()

templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
def home(request: Request):

    conn = sqlite3.connect("companies.db")
    conn.row_factory = sqlite3.Row

    companies = conn.execute("""
        SELECT *
        FROM companies
        LIMIT 50
    """).fetchall()

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "companies": companies
        }
    )