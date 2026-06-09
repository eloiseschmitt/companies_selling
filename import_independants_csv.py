"""Importe le CSV des indépendants Bordeaux Métropole dans SQLite."""

from __future__ import annotations

import argparse
import csv
import sqlite3
from collections.abc import Sequence
from pathlib import Path

DATABASE_FILE = "companies.db"
CSV_FILE = "independants_bordeaux_metropole.csv"
TABLE_NAME = "independants"

TEXT_COLUMNS = [
    "siren",
    "siret",
    "nic",
    "nom_ou_denomination",
    "denomination_unite_legale",
    "nom_unite_legale",
    "prenom_usuel_unite_legale",
    "categorie_juridique_unite_legale",
    "activite_principale_unite_legale",
    "activite_principale_etablissement",
    "code_naf_retenu",
    "date_creation_unite_legale",
    "date_creation_etablissement",
    "etat_administratif_unite_legale",
    "etat_administratif_etablissement",
    "tranche_effectifs_unite_legale",
    "tranche_effectifs_etablissement",
    "caractere_employeur_unite_legale",
    "caractere_employeur_etablissement",
    "enseigne_1",
    "enseigne_2",
    "enseigne_3",
    "denomination_usuelle_etablissement",
    "numero_voie",
    "type_voie",
    "libelle_voie",
    "complement_adresse",
    "code_postal",
    "commune",
    "code_commune",
    "telephone",
    "adresse_complete",
    "raison_score",
]
BOOLEAN_COLUMNS = [
    "est_entrepreneur_individuel",
    "est_micro_entrepreneur_probable",
]
INTEGER_COLUMNS = [
    "age_etablissement_annees",
    "score_priorisation",
]
INDEPENDANT_COLUMNS = [
    "siren",
    "siret",
    "nic",
    "nom_ou_denomination",
    "denomination_unite_legale",
    "nom_unite_legale",
    "prenom_usuel_unite_legale",
    "categorie_juridique_unite_legale",
    "est_entrepreneur_individuel",
    "est_micro_entrepreneur_probable",
    "activite_principale_unite_legale",
    "activite_principale_etablissement",
    "code_naf_retenu",
    "date_creation_unite_legale",
    "date_creation_etablissement",
    "etat_administratif_unite_legale",
    "etat_administratif_etablissement",
    "tranche_effectifs_unite_legale",
    "tranche_effectifs_etablissement",
    "caractere_employeur_unite_legale",
    "caractere_employeur_etablissement",
    "enseigne_1",
    "enseigne_2",
    "enseigne_3",
    "denomination_usuelle_etablissement",
    "numero_voie",
    "type_voie",
    "libelle_voie",
    "complement_adresse",
    "code_postal",
    "commune",
    "code_commune",
    "telephone",
    "adresse_complete",
    "age_etablissement_annees",
    "score_priorisation",
    "raison_score",
]
OPTIONAL_CSV_COLUMNS = frozenset({"telephone"})


def create_independants_table(conn: sqlite3.Connection) -> None:
    """Crée la table des indépendants et ses index."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS independants (
            siren TEXT NOT NULL,
            siret TEXT PRIMARY KEY,
            nic TEXT,
            nom_ou_denomination TEXT,
            denomination_unite_legale TEXT,
            nom_unite_legale TEXT,
            prenom_usuel_unite_legale TEXT,
            categorie_juridique_unite_legale TEXT,
            est_entrepreneur_individuel INTEGER NOT NULL DEFAULT 0,
            est_micro_entrepreneur_probable INTEGER NOT NULL DEFAULT 0,
            activite_principale_unite_legale TEXT,
            activite_principale_etablissement TEXT,
            code_naf_retenu TEXT,
            date_creation_unite_legale TEXT,
            date_creation_etablissement TEXT,
            etat_administratif_unite_legale TEXT,
            etat_administratif_etablissement TEXT,
            tranche_effectifs_unite_legale TEXT,
            tranche_effectifs_etablissement TEXT,
            caractere_employeur_unite_legale TEXT,
            caractere_employeur_etablissement TEXT,
            enseigne_1 TEXT,
            enseigne_2 TEXT,
            enseigne_3 TEXT,
            denomination_usuelle_etablissement TEXT,
            numero_voie TEXT,
            type_voie TEXT,
            libelle_voie TEXT,
            complement_adresse TEXT,
            code_postal TEXT,
            commune TEXT,
            code_commune TEXT,
            telephone TEXT NOT NULL DEFAULT '',
            adresse_complete TEXT,
            age_etablissement_annees INTEGER,
            score_priorisation INTEGER NOT NULL DEFAULT 0,
            raison_score TEXT
        )
        """
    )
    ensure_independants_columns(conn)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_independants_siren ON independants (siren)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_independants_commune ON independants (commune)"
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_independants_code_postal
        ON independants (code_postal)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_independants_code_naf_retenu
        ON independants (code_naf_retenu)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_independants_score_priorisation
        ON independants (score_priorisation)
        """
    )
    conn.commit()


def ensure_independants_columns(conn: sqlite3.Connection) -> None:
    """Ajoute les colonnes manquantes sur une base déjà existante."""
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({TABLE_NAME})")}
    if "telephone" not in columns:
        conn.execute(
            f"ALTER TABLE {TABLE_NAME} ADD COLUMN telephone TEXT NOT NULL DEFAULT ''"
        )


def import_independants_csv(
    conn: sqlite3.Connection,
    csv_path: Path,
    replace: bool = True,
) -> int:
    """Importe le CSV dans la table `independants`."""
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV introuvable: {csv_path}")

    create_independants_table(conn)
    if replace:
        conn.execute("DELETE FROM independants")

    placeholders = ", ".join("?" for _ in INDEPENDANT_COLUMNS)
    rows = []
    with csv_path.open(newline="", encoding="utf-8-sig") as csv_file:
        reader = csv.DictReader(csv_file)
        validate_csv_columns(reader.fieldnames)
        for row in reader:
            rows.append(
                tuple(
                    normalize_value(row.get(column), column)
                    for column in INDEPENDANT_COLUMNS
                )
            )

    conn.executemany(
        f"""
        INSERT OR REPLACE INTO independants ({", ".join(INDEPENDANT_COLUMNS)})
        VALUES ({placeholders})
        """,
        rows,
    )
    conn.commit()
    return len(rows)


def validate_csv_columns(fieldnames: Sequence[str] | None) -> None:
    missing_columns = (
        set(INDEPENDANT_COLUMNS) - OPTIONAL_CSV_COLUMNS - set(fieldnames or [])
    )
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"Colonnes CSV manquantes: {missing}")


def normalize_value(value: str | None, column: str) -> str | int | None:
    cleaned = (value or "").strip()
    if column in BOOLEAN_COLUMNS:
        return 1 if cleaned.lower() == "true" else 0
    if column in INTEGER_COLUMNS:
        return int(cleaned) if cleaned else None
    return cleaned


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Importe independants_bordeaux_metropole.csv dans companies.db."
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=Path(DATABASE_FILE),
        help="Chemin de la base SQLite.",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=Path(CSV_FILE),
        help="Chemin du CSV des indépendants.",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="N'efface pas la table avant import.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    conn = sqlite3.connect(args.database)
    try:
        imported_count = import_independants_csv(
            conn,
            args.csv,
            replace=not args.append,
        )
    finally:
        conn.close()

    print(f"Table {TABLE_NAME} alimentée: {imported_count} ligne(s) importée(s).")


if __name__ == "__main__":
    main()
