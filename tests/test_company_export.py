import csv
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main


class CompanyExportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db.close()
        self.addCleanup(self.cleanup_temp_db)
        self.create_database()

    def cleanup_temp_db(self) -> None:
        Path(self.temp_db.name).unlink(missing_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.temp_db.name)
        conn.row_factory = sqlite3.Row
        return conn

    def create_database(self) -> None:
        conn = self.connect()
        try:
            conn.execute(
                """
                CREATE TABLE companies (
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
            conn.execute(
                """
                CREATE TABLE naf_code (
                    code TEXT,
                    name TEXT
                )
                """
            )
            conn.executemany(
                """
                INSERT INTO companies (
                    siret,
                    nic,
                    dateCreationEtablissement,
                    trancheEffectifsEtablissement,
                    activitePrincipaleEtablissement,
                    denomination_legale,
                    prenom,
                    nom
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        "12345678900012",
                        "00012",
                        "1980-01-01",
                        "03",
                        "68.20B",
                        "Alpha",
                        "",
                        "",
                    ),
                    (
                        "98765432100034",
                        "00034",
                        "2020-01-01",
                        "NN",
                        "81.10Z",
                        "Beta",
                        "",
                        "",
                    ),
                ],
            )
            conn.executemany(
                "INSERT INTO naf_code (code, name) VALUES (?, ?)",
                [
                    ("68.20B", "Location de terrains"),
                    ("81.10Z", "Activités combinées de soutien"),
                ],
            )
            conn.commit()
        finally:
            conn.close()

    def test_export_companies_csv_uses_active_naf_filter(self) -> None:
        with patch.object(main, "get_db_connection", side_effect=self.connect):
            response = main.export_companies_csv(naf_code="68.20B")

        rows = list(csv.DictReader(io.StringIO(response.body.decode("utf-8"))))

        self.assertEqual("text/csv; charset=utf-8", response.media_type)
        self.assertEqual(1, len(rows))
        self.assertEqual("123456789", rows[0]["siren"])
        self.assertEqual("12345678900012", rows[0]["siret"])
        self.assertEqual("Alpha", rows[0]["denomination_legale"])
        self.assertEqual("68.20B", rows[0]["activitePrincipaleEtablissement"])
        self.assertEqual("Location de terrains", rows[0]["libelle"])
        self.assertEqual("5", rows[0]["score"])

    def test_export_query_string_preserves_filters(self) -> None:
        query_string = main.build_export_query_string(
            section="68",
            naf_code="68.20B,81.10Z",
            sort_score="asc",
        )

        self.assertEqual(
            "section=68&naf_code=68.20B%2C81.10Z&sort_score=asc",
            query_string,
        )


if __name__ == "__main__":
    unittest.main()
