import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app


class IndependantsEndpointTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_get_independants_returns_items_and_pagination(self) -> None:
        with patch("main.list_db_independants") as list_independants:
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
                        "contacte": False,
                        "telephone": "",
                        "adresse_complete": "1 RUE A, 33000 BORDEAUX",
                    }
                ],
                "total": 1,
                "limit": 25,
                "offset": 5,
            }

            response = self.client.get(
                "/independants",
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
                    "offset": 5,
                },
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            {
                "items": [
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
                        "contacte": False,
                        "telephone": "",
                        "adresse_complete": "1 RUE A, 33000 BORDEAUX",
                    }
                ],
                "total": 1,
                "limit": 25,
                "offset": 5,
            },
            response.json(),
        )
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
            pagination={"limit": 25, "offset": 5},
        )

    def test_updates_independant_telephone(self) -> None:
        with patch("main.update_independant_telephone") as update_telephone:
            update_telephone.return_value = "06 12 34 56 78"

            response = self.client.patch(
                "/independants/11111111100011/telephone",
                json={"telephone": "+33 6 12 34 56 78"},
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            {"siret": "11111111100011", "telephone": "06 12 34 56 78"},
            response.json(),
        )
        update_telephone.assert_called_once_with("11111111100011", "+33 6 12 34 56 78")

    def test_update_independant_telephone_rejects_invalid_number(self) -> None:
        with patch("main.update_independant_telephone") as update_telephone:
            update_telephone.side_effect = ValueError(
                "Le numéro de téléphone doit être un numéro français valide."
            )

            response = self.client.patch(
                "/independants/11111111100011/telephone",
                json={"telephone": "12345"},
            )

        self.assertEqual(400, response.status_code)
        self.assertIn("numéro français valide", response.json()["detail"])

    def test_update_independant_telephone_returns_404_for_unknown_siret(self) -> None:
        with patch("main.update_independant_telephone") as update_telephone:
            update_telephone.return_value = None

            response = self.client.patch(
                "/independants/99999999900099/telephone",
                json={"telephone": "06 12 34 56 78"},
            )

        self.assertEqual(404, response.status_code)
        self.assertEqual("Indépendant introuvable.", response.json()["detail"])

    def test_deletes_independant(self) -> None:
        with patch("main.mark_independant_deleted") as mark_deleted:
            mark_deleted.return_value = True

            response = self.client.delete("/independants/11111111100011")

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            {"siret": "11111111100011", "supprime": True},
            response.json(),
        )
        mark_deleted.assert_called_once_with("11111111100011")

    def test_delete_independant_returns_404_for_unknown_siret(self) -> None:
        with patch("main.mark_independant_deleted") as mark_deleted:
            mark_deleted.return_value = False

            response = self.client.delete("/independants/99999999900099")

        self.assertEqual(404, response.status_code)
        self.assertEqual("Indépendant introuvable.", response.json()["detail"])

    def test_get_independants_rejects_invalid_sort_column(self) -> None:
        response = self.client.get(
            "/independants",
            params={"sort_by": "score_priorisation; DROP TABLE companies"},
        )

        self.assertEqual(400, response.status_code)
        self.assertIn("Tri non autorisé", response.json()["detail"])

    def test_get_independants_rejects_invalid_sort_order(self) -> None:
        response = self.client.get(
            "/independants",
            params={"sort_by": "score_priorisation", "sort_order": "sideways"},
        )

        self.assertEqual(400, response.status_code)
        self.assertEqual(
            "sort_order doit valoir 'asc' ou 'desc'.",
            response.json()["detail"],
        )

    def test_get_independants_rejects_limit_over_max(self) -> None:
        response = self.client.get("/independants", params={"limit": 201})

        self.assertEqual(400, response.status_code)
        self.assertIn("limit doit être compris", response.json()["detail"])

    def test_get_independants_rejects_service_validation_error(self) -> None:
        with patch("main.list_db_independants") as list_independants:
            list_independants.side_effect = ValueError(
                "Le filtre score_min doit être un entier."
            )

            response = self.client.get(
                "/independants",
                params={"score_min": "not-an-int"},
            )

        self.assertEqual(400, response.status_code)
        self.assertEqual(
            "Le filtre score_min doit être un entier.",
            response.json()["detail"],
        )


if __name__ == "__main__":
    unittest.main()
