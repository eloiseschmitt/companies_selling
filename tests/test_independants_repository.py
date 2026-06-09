import sqlite3
import tempfile
import unittest
from pathlib import Path

from import_independants_csv import create_independants_table
from services.independants_repository import RETURN_FIELDS, list_independants


class IndependantsRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.database_path = Path(self.temp_dir.name) / "companies.db"

        conn = sqlite3.connect(self.database_path)
        try:
            create_independants_table(conn)
            conn.executemany(
                """
                INSERT INTO independants (
                    siren,
                    siret,
                    nom_ou_denomination,
                    commune,
                    code_postal,
                    code_naf_retenu,
                    date_creation_etablissement,
                    age_etablissement_annees,
                    categorie_juridique_unite_legale,
                    est_entrepreneur_individuel,
                    est_micro_entrepreneur_probable,
                    caractere_employeur_unite_legale,
                    score_priorisation,
                    adresse_complete
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        "111111111",
                        "11111111100011",
                        "ALPHA CLEAN",
                        "BORDEAUX",
                        "33000",
                        "81.21Z",
                        "2010-01-01",
                        16,
                        "1000",
                        1,
                        0,
                        "O",
                        10,
                        "1 RUE A, 33000 BORDEAUX",
                    ),
                    (
                        "222222222",
                        "22222222200022",
                        "BETA JARDIN",
                        "MERIGNAC",
                        "33700",
                        "8130Z",
                        "2024-01-01",
                        2,
                        "1000",
                        1,
                        1,
                        "N",
                        3,
                        "2 RUE B, 33700 MERIGNAC",
                    ),
                    (
                        "333333333",
                        "33333333300033",
                        "GAMMA AIDE",
                        "BORDEAUX",
                        "33800",
                        "8810A",
                        "2025-09-01",
                        0,
                        "1000",
                        1,
                        1,
                        None,
                        1,
                        "3 RUE C, 33800 BORDEAUX",
                    ),
                ],
            )
            conn.commit()
        finally:
            conn.close()

    def test_lists_projected_rows_with_typed_values(self) -> None:
        page = list_independants(
            filters={},
            sort={"column": "siren", "direction": "asc"},
            pagination={"limit": 10, "offset": 0},
            database_path=self.database_path,
        )

        self.assertEqual(3, page["total"])
        self.assertEqual(10, page["limit"])
        self.assertEqual(0, page["offset"])
        self.assertEqual(set(RETURN_FIELDS), set(page["data"][0]))
        self.assertEqual(16, page["data"][0]["age_etablissement_annees"])
        self.assertEqual(10, page["data"][0]["score_priorisation"])
        self.assertIs(page["data"][0]["est_entrepreneur_individuel"], True)
        self.assertIs(page["data"][0]["est_micro_entrepreneur_probable"], False)

    def test_filters_by_commune_postal_code_naf_score_employeur_and_text(self) -> None:
        page = list_independants(
            filters={
                "commune": "bordeaux",
                "code_postal": "33000",
                "code_naf": "8121Z",
                "score_min": 5,
                "employeur": "oui",
                "texte": "alpha",
            },
            sort={},
            pagination={"limit": 10, "offset": 0},
            database_path=self.database_path,
        )

        self.assertEqual(1, page["total"])
        self.assertEqual("111111111", page["data"][0]["siren"])

    def test_filters_non_employeurs(self) -> None:
        page = list_independants(
            filters={"employeur": "non"},
            sort={"column": "siren", "direction": "asc"},
            pagination={"limit": 10, "offset": 0},
            database_path=self.database_path,
        )

        self.assertEqual(["222222222", "333333333"], [r["siren"] for r in page["data"]])

    def test_sort_and_pagination(self) -> None:
        page = list_independants(
            filters={},
            sort={"column": "score_priorisation", "direction": "desc"},
            pagination={"limit": 2, "offset": 1},
            database_path=self.database_path,
        )

        self.assertEqual(3, page["total"])
        self.assertEqual(["222222222", "333333333"], [r["siren"] for r in page["data"]])

    def test_rejects_unknown_sort_column(self) -> None:
        with self.assertRaisesRegex(ValueError, "Tri non autorisé"):
            list_independants(
                filters={},
                sort={"column": "score_priorisation; DROP TABLE companies"},
                pagination={},
                database_path=self.database_path,
            )

    def test_rejects_invalid_filters_and_pagination(self) -> None:
        with self.assertRaisesRegex(ValueError, "score_min"):
            list_independants(
                filters={"score_min": "high"},
                sort={},
                pagination={},
                database_path=self.database_path,
            )

        with self.assertRaisesRegex(ValueError, "limit"):
            list_independants(
                filters={},
                sort={},
                pagination={"limit": -1},
                database_path=self.database_path,
            )

    def test_missing_database_returns_empty_page(self) -> None:
        page = list_independants(
            filters={},
            sort={},
            pagination={"limit": 5, "offset": 0},
            database_path=Path(self.temp_dir.name) / "missing.db",
        )

        self.assertEqual({"data": [], "total": 0, "limit": 5, "offset": 0}, page)


if __name__ == "__main__":
    unittest.main()
