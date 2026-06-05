import argparse
import csv
import os
import sqlite3

DATABASE_FILE = "companies.db"
ESTABLISHMENT_FILE = "StockEtablissement_utf8.csv"
LEGAL_UNIT_FILE = "StockUniteLegale_utf8.csv"
CHUNK_SIZE = 10_000

COMPANY_COLUMNS = [
    "siret",
    "nic",
    "dateCreationEtablissement",
    "trancheEffectifsEtablissement",
    "activitePrincipaleEtablissement",
]

LEGAL_UNIT_COLUMNS = {
    "denomination_legale": "denominationUniteLegale",
    "prenom": "prenomUsuelUniteLegale",
    "nom": "nomUsageUniteLegale",
}


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_legal_unit_columns(conn: sqlite3.Connection) -> None:
    """Ajoute les colonnes d'identité légale sans toucher aux données existantes."""
    existing_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(companies)").fetchall()
    }

    for column_name in LEGAL_UNIT_COLUMNS:
        if column_name not in existing_columns:
            conn.execute(f"ALTER TABLE companies ADD COLUMN {column_name} TEXT")

    conn.commit()


def create_companies_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS companies (
            siret TEXT,
            nic TEXT,
            dateCreationEtablissement TEXT,
            trancheEffectifsEtablissement TEXT,
            activitePrincipaleEtablissement TEXT,
            denomination_legale TEXT,
            prenom TEXT,
            nom TEXT
        )
        """
    )
    conn.commit()


def should_keep_establishment(row: dict[str, str]) -> bool:
    return (
        row.get("etablissementSiege") == "true"
        and row.get("etatAdministratifEtablissement") == "A"
        and row.get("dateCreationEtablissement", "") <= "2000-01-01"
        and row.get("trancheEffectifsEtablissement") in {"01", "02", "03", "11", "12"}
    )


def insert_companies(conn: sqlite3.Connection, rows: list[tuple[str, ...]]) -> None:
    placeholders = ", ".join("?" for _ in COMPANY_COLUMNS)
    conn.executemany(
        f"""
        INSERT INTO companies ({", ".join(COMPANY_COLUMNS)})
        VALUES ({placeholders})
        """,
        rows,
    )
    conn.commit()


def load_companies_from_establishments(conn: sqlite3.Connection) -> None:
    """Remplit la table companies depuis le fichier StockEtablissement."""
    if not os.path.exists(ESTABLISHMENT_FILE):
        raise FileNotFoundError(
            f"{ESTABLISHMENT_FILE} est introuvable, impossible de remplir companies."
        )

    create_companies_table(conn)
    pending_rows = []

    with open(ESTABLISHMENT_FILE, newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            if not should_keep_establishment(row):
                continue

            pending_rows.append(
                tuple(row.get(column, "") for column in COMPANY_COLUMNS)
            )
            if len(pending_rows) >= CHUNK_SIZE:
                insert_companies(conn, pending_rows)
                pending_rows = []

    if pending_rows:
        insert_companies(conn, pending_rows)


def get_company_sirens(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT SUBSTR(siret, 1, 9) AS siren
        FROM companies
        WHERE siret IS NOT NULL AND LENGTH(siret) >= 9
        """
    ).fetchall()
    return {row["siren"] for row in rows if row["siren"]}


def create_legal_unit_updates_table(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS temp.legal_unit_updates")
    conn.execute(
        """
        CREATE TEMP TABLE legal_unit_updates (
            siren TEXT PRIMARY KEY,
            denomination_legale TEXT,
            prenom TEXT,
            nom TEXT
        )
        """
    )


def insert_legal_unit_updates(
    conn: sqlite3.Connection,
    rows: list[tuple[str, str, str, str]],
) -> None:
    conn.executemany(
        """
        INSERT OR REPLACE INTO legal_unit_updates (
            siren,
            denomination_legale,
            prenom,
            nom
        )
        VALUES (?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()


def apply_legal_unit_updates(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        UPDATE companies
        SET denomination_legale = (
                SELECT legal_unit_updates.denomination_legale
                FROM legal_unit_updates
                WHERE legal_unit_updates.siren = SUBSTR(companies.siret, 1, 9)
            ),
            prenom = (
                SELECT legal_unit_updates.prenom
                FROM legal_unit_updates
                WHERE legal_unit_updates.siren = SUBSTR(companies.siret, 1, 9)
            ),
            nom = (
                SELECT legal_unit_updates.nom
                FROM legal_unit_updates
                WHERE legal_unit_updates.siren = SUBSTR(companies.siret, 1, 9)
            )
        WHERE EXISTS (
            SELECT 1
            FROM legal_unit_updates
            WHERE legal_unit_updates.siren = SUBSTR(companies.siret, 1, 9)
        )
        """
    )
    conn.commit()


def enrich_companies_from_legal_units(conn: sqlite3.Connection) -> None:
    """Alimente les informations d'unité légale par correspondance SIREN."""
    if not os.path.exists(LEGAL_UNIT_FILE):
        raise FileNotFoundError(
            f"{LEGAL_UNIT_FILE} est introuvable, impossible d'enrichir companies."
        )

    ensure_legal_unit_columns(conn)
    company_sirens = get_company_sirens(conn)
    create_legal_unit_updates_table(conn)
    pending_updates = []
    scanned_rows = 0
    matched_rows = 0

    with open(LEGAL_UNIT_FILE, newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            scanned_rows += 1
            if scanned_rows % 1_000_000 == 0:
                progress = (
                    f"{scanned_rows} unités légales lues, "
                    f"{matched_rows} correspondances trouvées"
                )
                print(
                    progress,
                    flush=True,
                )

            siren = row.get("siren", "")
            if siren not in company_sirens:
                continue

            matched_rows += 1
            pending_updates.append(
                (
                    siren,
                    row.get(LEGAL_UNIT_COLUMNS["denomination_legale"], ""),
                    row.get(LEGAL_UNIT_COLUMNS["prenom"], ""),
                    row.get(LEGAL_UNIT_COLUMNS["nom"], ""),
                )
            )
            if len(pending_updates) >= CHUNK_SIZE:
                insert_legal_unit_updates(conn, pending_updates)
                pending_updates = []

    if pending_updates:
        insert_legal_unit_updates(conn, pending_updates)

    print(
        f"Application de {matched_rows} correspondances aux entreprises existantes",
        flush=True,
    )
    apply_legal_unit_updates(conn)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Remplit puis enrichit companies.db depuis les fichiers SIRENE."
    )
    parser.add_argument(
        "--enrich-only",
        action="store_true",
        help="Ajoute et alimente uniquement les colonnes d'unité légale.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    conn = get_connection()
    try:
        if not args.enrich_only and os.path.exists(ESTABLISHMENT_FILE):
            load_companies_from_establishments(conn)
        elif not args.enrich_only:
            message = (
                f"{ESTABLISHMENT_FILE} introuvable, "
                "enrichissement de la base existante uniquement"
            )
            print(
                message,
                flush=True,
            )
        enrich_companies_from_legal_units(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
