import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app


class IndependantsTableTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_table_renders_filters_rows_and_pagination_links(self) -> None:
        with patch("main.list_csv_independants") as list_independants:
            list_independants.return_value = {
                "data": [
                    {
                        "siren": "111111111",
                        "siret": "11111111100011",
                        "nom_ou_denomination": "ALPHA CLEAN",
                        "commune": "BORDEAUX",
                        "code_postal": "33000",
                        "code_naf_retenu": "81.21Z",
                        "date_creation_etablissement": "2010-01-01",
                        "age_etablissement_annees": 16,
                        "categorie_juridique_unite_legale": "1000",
                        "est_entrepreneur_individuel": True,
                        "est_micro_entrepreneur_probable": False,
                        "caractere_employeur_unite_legale": "O",
                        "score_priorisation": 10,
                        "adresse_complete": "1 RUE A, 33000 BORDEAUX",
                    }
                ],
                "total": 80,
                "limit": 25,
                "offset": 25,
            }

            response = self.client.get(
                "/independants/table",
                params={
                    "q": "alpha",
                    "commune": "BORDEAUX",
                    "code_postal": "33000",
                    "code_naf": "8121Z",
                    "score_min": "5",
                    "employeur": "oui",
                    "sort_by": "score_priorisation",
                    "sort_order": "desc",
                    "limit": 25,
                    "offset": 25,
                },
            )

        self.assertEqual(200, response.status_code)
        body = response.text
        self.assertIn("Indépendants Bordeaux Métropole", body)
        self.assertIn("ALPHA CLEAN", body)
        self.assertIn("1 RUE A, 33000 BORDEAUX", body)
        self.assertIn('value="alpha"', body)
        self.assertIn('value="BORDEAUX"', body)
        self.assertIn("q=alpha", body)
        self.assertIn("commune=BORDEAUX", body)
        self.assertIn("sort_by=score_priorisation", body)
        self.assertIn("sort_order=asc", body)
        self.assertIn('<span class="sort-indicator">↓</span>', body)
        self.assertIn("sort_by=nom_ou_denomination", body)
        self.assertIn("offset=0", body)
        self.assertIn("offset=50", body)
        list_independants.assert_called_once_with(
            filters={
                "q": "alpha",
                "commune": "BORDEAUX",
                "code_postal": "33000",
                "code_naf": "8121Z",
                "score_min": "5",
                "employeur": "oui",
            },
            sort={"column": "score_priorisation", "direction": "desc"},
            pagination={"limit": 25, "offset": 25},
        )

    def test_table_rejects_invalid_sort_column(self) -> None:
        response = self.client.get(
            "/independants/table",
            params={"sort_by": "score_priorisation; DROP TABLE companies"},
        )

        self.assertEqual(400, response.status_code)
        self.assertIn("Tri non autorisé", response.text)

    def test_table_second_click_switches_current_column_to_desc(self) -> None:
        with patch("main.list_csv_independants") as list_independants:
            list_independants.return_value = {
                "data": [],
                "total": 0,
                "limit": 50,
                "offset": 0,
            }

            response = self.client.get(
                "/independants/table",
                params={
                    "commune": "BORDEAUX",
                    "sort_by": "commune",
                    "sort_order": "asc",
                },
            )

        self.assertEqual(200, response.status_code)
        body = response.text
        self.assertIn("sort_by=commune", body)
        self.assertIn("sort_order=desc", body)
        self.assertIn("commune=BORDEAUX", body)
        self.assertIn('<span class="sort-indicator">↑</span>', body)


if __name__ == "__main__":
    unittest.main()
