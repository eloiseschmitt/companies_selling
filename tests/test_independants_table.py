import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app


class IndependantsTableTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_table_renders_filters_rows_and_pagination_links(self) -> None:
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
                        "commentaires": "",
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
        self.assertIn("80 résultats trouvés", body)
        self.assertIn("Filtres actifs", body)
        self.assertIn("Recherche : alpha", body)
        self.assertIn("Commune : BORDEAUX", body)
        self.assertIn("Ménage / nettoyage courant", body)
        self.assertIn("Profil intéressant", body)
        self.assertIn("Téléphone", body)
        self.assertIn("Contacté", body)
        self.assertIn("Commentaires", body)
        self.assertIn("Action", body)
        self.assertIn("profile-badge profile-yes", body)
        self.assertIn("interesting-row", body)
        self.assertIn("Google Maps", body)
        self.assertIn("telephone-cell", body)
        self.assertIn('data-siret="11111111100011"', body)
        self.assertIn("Double-cliquer pour modifier", body)
        self.assertIn("delete-button", body)
        self.assertIn("Supprimer", body)
        self.assertIn("Non", body)
        self.assertIn("contacte-cell", body)
        self.assertIn('data-original-contacte="false"', body)
        self.assertIn("commentaires-cell", body)
        self.assertIn('data-original-commentaires=""', body)
        self.assertIn("https://www.google.com/maps/search/?api=1", body)
        self.assertIn('value="alpha"', body)
        self.assertIn('value="BORDEAUX"', body)
        self.assertIn("q=alpha", body)
        self.assertIn("commune=BORDEAUX", body)
        self.assertIn('id="independants-table"', body)
        self.assertIn("cdn.datatables.net", body)
        self.assertIn("Recherche instantanée", body)
        self.assertIn("filtres serveur", body)
        self.assertIn("La page ne charge jamais plus de", body)
        self.assertIn("500 lignes", body)
        self.assertIn('data-column-name="nom_ou_denomination"', body)
        self.assertIn('data-column-name="score_priorisation"', body)
        self.assertIn('indicator.textContent = order[1] === "asc" ? "↑" : "↓"', body)
        self.assertIn("targets: [6, 7, 9, 10, 11, 12, 13]", body)
        self.assertIn("saveTelephone", body)
        self.assertIn("editTelephoneCell", body)
        self.assertIn("editContacteCell", body)
        self.assertIn("saveContacte", body)
        self.assertIn("editCommentairesCell", body)
        self.assertIn("saveCommentaires", body)
        self.assertIn('tableElement.addEventListener("dblclick"', body)
        self.assertIn("window.DataTable", body)
        self.assertIn("/independants/${cell.dataset.siret}/telephone", body)
        self.assertIn("/independants/${cell.dataset.siret}/contacte", body)
        self.assertIn("/independants/${cell.dataset.siret}/commentaires", body)
        self.assertIn('method: "PATCH"', body)
        self.assertIn('method: "DELETE"', body)
        self.assertIn("Suppression impossible", body)
        self.assertIn("Mise à jour impossible", body)
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
                "supprime": False,
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

    def test_table_accepts_limit_up_to_500(self) -> None:
        with patch("main.list_db_independants") as list_independants:
            list_independants.return_value = {
                "data": [],
                "total": 0,
                "limit": 500,
                "offset": 0,
            }

            response = self.client.get(
                "/independants/table",
                params={
                    "commune": "BORDEAUX",
                    "limit": 500,
                },
            )

        self.assertEqual(200, response.status_code)
        list_independants.assert_called_once()

    def test_table_rejects_limit_over_500(self) -> None:
        response = self.client.get("/independants/table", params={"limit": 501})

        self.assertEqual(400, response.status_code)
        self.assertIn("limit doit être compris entre 1 et 500", response.text)


if __name__ == "__main__":
    unittest.main()
