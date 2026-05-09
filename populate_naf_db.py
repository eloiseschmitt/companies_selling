"""
Script pour remplir la table naf_code dans la base de données SQLite
avec les données du fichier int_courts_naf_rev_2.xls
"""

import sqlite3
import pandas as pd
import os

# Chemin vers les fichiers
DB_PATH = "companies.db"
XLS_PATH = "int_courts_naf_rev_2.xls"

# Nom des colonnes dans le fichier Excel
CODE_COL = "Code"
NAME_COL = "Intitulés NAF rév. 2, \nen 40 caractères"


def create_naf_table():
    """Crée la table naf_code dans la base de données."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Créer la table si elle n'existe pas
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS naf_code (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()
    print("✓ Table naf_code créée (ou déjà existante)")


def populate_naf_table():
    """Remplit la table naf_code avec les données du fichier Excel."""
    # Vérifier que les fichiers existent
    if not os.path.exists(XLS_PATH):
        print(f"❌ Erreur: fichier {XLS_PATH} non trouvé")
        return False

    if not os.path.exists(DB_PATH):
        print(f"❌ Erreur: base de données {DB_PATH} non trouvée")
        return False

    # Lire le fichier Excel
    print(f"📖 Lecture du fichier {XLS_PATH}...")
    df = pd.read_excel(XLS_PATH, sheet_name="NAF rév. 2")

    # Filtrer les données: garder seulement les lignes avec code et name
    df_filtered = df[[CODE_COL, NAME_COL]].copy()
    df_filtered = df_filtered.dropna(subset=[CODE_COL, NAME_COL])
    df_filtered[CODE_COL] = df_filtered[CODE_COL].astype(str).str.strip()
    df_filtered[NAME_COL] = df_filtered[NAME_COL].astype(str).str.strip()

    print(f"✓ {len(df_filtered)} enregistrements trouvés dans le fichier Excel")

    # Insérer les données dans la base de données
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Vider la table existante (optionnel)
    cursor.execute("DELETE FROM naf_code")

    inserted = 0
    skipped = 0

    for _, row in df_filtered.iterrows():
        code = row[CODE_COL]
        name = row[NAME_COL]

        try:
            cursor.execute(
                "INSERT INTO naf_code (code, name) VALUES (?, ?)", (code, name)
            )
            inserted += 1
        except sqlite3.IntegrityError:
            skipped += 1

    conn.commit()
    conn.close()

    print(f"✓ {inserted} enregistrements insérés")
    if skipped > 0:
        print(f"⚠️  {skipped} enregistrements ignorés (doublons)")

    return True


def verify_naf_table():
    """Vérifie que la table a bien été remplie."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    count = cursor.execute("SELECT COUNT(*) FROM naf_code").fetchone()[0]
    conn.close()

    print(f"\n📊 Vérification: {count} codes NAF en base de données")

    # Afficher quelques exemples
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    examples = cursor.execute("SELECT code, name FROM naf_code LIMIT 5").fetchall()
    conn.close()

    print("\n📝 Exemples de codes NAF:")
    for code, name in examples:
        print(f"  - {code}: {name}")


def main():
    """Fonction principale."""
    print("🔧 Remplissage de la table NAF...\n")

    create_naf_table()
    if populate_naf_table():
        verify_naf_table()
        print("\n✅ Opération terminée avec succès!")
    else:
        print("\n❌ L'opération a échoué")


if __name__ == "__main__":
    main()
