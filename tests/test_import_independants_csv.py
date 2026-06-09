import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

from import_independants_csv import (
    INDEPENDANT_COLUMNS,
    create_independants_table,
    import_independants_csv,
)


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=INDEPENDANT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


class ImportIndependantsCsvTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = Path(self.temp_dir.name) / "companies.db"
        self.csv_path = Path(self.temp_dir.name) / "independants.csv"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.addCleanup(self.conn.close)

    def test_creates_table_and_imports_csv_rows(self) -> None:
        write_csv(
            self.csv_path,
            [
                {
                    **{column: "" for column in INDEPENDANT_COLUMNS},
                    "siren": "111111111",
                    "siret": "11111111100011",
                    "nom_ou_denomination": "ALPHA",
                    "est_entrepreneur_individuel": "True",
                    "est_micro_entrepreneur_probable": "False",
                    "age_etablissement_annees": "16",
                    "score_priorisation": "8",
                }
            ],
        )

        imported_count = import_independants_csv(self.conn, self.csv_path)
        row = self.conn.execute(
            "SELECT * FROM independants WHERE siret = ?",
            ("11111111100011",),
        ).fetchone()

        self.assertEqual(1, imported_count)
        self.assertEqual("ALPHA", row["nom_ou_denomination"])
        self.assertEqual(1, row["est_entrepreneur_individuel"])
        self.assertEqual(0, row["est_micro_entrepreneur_probable"])
        self.assertEqual(16, row["age_etablissement_annees"])
        self.assertEqual(8, row["score_priorisation"])
        self.assertEqual("", row["telephone"])

    def test_import_replaces_existing_rows_by_default(self) -> None:
        create_independants_table(self.conn)
        self.conn.execute(
            """
            INSERT INTO independants (
                siren,
                siret,
                nom_ou_denomination,
                score_priorisation
            )
            VALUES (?, ?, ?, ?)
            """,
            ("999999999", "99999999900099", "OLD", 1),
        )
        self.conn.commit()
        write_csv(
            self.csv_path,
            [
                {
                    **{column: "" for column in INDEPENDANT_COLUMNS},
                    "siren": "111111111",
                    "siret": "11111111100011",
                    "nom_ou_denomination": "NEW",
                }
            ],
        )

        import_independants_csv(self.conn, self.csv_path)
        rows = self.conn.execute("SELECT siret FROM independants").fetchall()

        self.assertEqual(["11111111100011"], [row["siret"] for row in rows])

    def test_rejects_missing_csv_columns(self) -> None:
        with self.csv_path.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=["siren", "siret"])
            writer.writeheader()
            writer.writerow({"siren": "111111111", "siret": "11111111100011"})

        with self.assertRaisesRegex(ValueError, "Colonnes CSV manquantes"):
            import_independants_csv(self.conn, self.csv_path)


if __name__ == "__main__":
    unittest.main()
