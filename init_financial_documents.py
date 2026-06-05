"""Crée la table financial_documents dans la base SQLite locale."""

import sqlite3

DATABASE_FILE = "companies.db"


def create_financial_documents_table(conn: sqlite3.Connection) -> None:
    """Crée la table et les index des documents financiers."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS financial_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            siren TEXT NOT NULL,
            siret TEXT,
            closing_date TEXT NOT NULL,
            filing_date TEXT,
            document_path TEXT NOT NULL,
            document_type TEXT,
            source TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            CONSTRAINT uq_financial_documents_siren_closing_date_document_path
                UNIQUE (siren, closing_date, document_path)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_financial_documents_siren
        ON financial_documents (siren)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_financial_documents_siret
        ON financial_documents (siret)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_financial_documents_closing_date
        ON financial_documents (closing_date)
        """
    )
    ensure_financial_documents_columns(conn)
    conn.commit()


def ensure_financial_documents_columns(conn: sqlite3.Connection) -> None:
    existing_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(financial_documents)")
    }

    if "revenue" not in existing_columns:
        conn.execute("ALTER TABLE financial_documents ADD COLUMN revenue NUMERIC")


def main() -> None:
    conn = sqlite3.connect(DATABASE_FILE)
    try:
        create_financial_documents_table(conn)
    finally:
        conn.close()

    print("Table financial_documents créée ou déjà existante.")


if __name__ == "__main__":
    main()
