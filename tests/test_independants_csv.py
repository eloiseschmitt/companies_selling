import csv
import tempfile
import unittest
from pathlib import Path

from services.independants_csv import RETURN_FIELDS, list_independants


def write_independants_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames = [
        "siren",
        "siret",
        "nom_ou_denomination",
        "commune",
        "code_postal",
        "code_naf_retenu",
        "date_creation_etablissement",
        "age_etablissement_annees",
        "categorie_juridique_unite_legale",
        "est_entrepreneur_individuel",
        "est_micro_entrepreneur_probable",
        "caractere_employeur_unite_legale",
        "score_priorisation",
        "adresse_complete",
        "extra_column",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


class IndependantsCsvTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.csv_path = Path(self.temp_dir.name) / "independants.csv"
        write_independants_csv(
            self.csv_path,
            [
                {
                    "siren": "111111111",
                    "siret": "11111111100011",
                    "nom_ou_denomination": "ALPHA CLEAN",
                    "commune": "BORDEAUX",
                    "code_postal": "33000",
                    "code_naf_retenu": "81.21Z",
                    "date_creation_etablissement": "2010-01-01",
                    "age_etablissement_annees": "16",
                    "categorie_juridique_unite_legale": "1000",
                    "est_entrepreneur_individuel": "True",
                    "est_micro_entrepreneur_probable": "False",
                    "caractere_employeur_unite_legale": "O",
                    "score_priorisation": "10",
                    "adresse_complete": "1 RUE A, 33000 BORDEAUX",
                    "extra_column": "ignored",
                },
                {
                    "siren": "222222222",
                    "siret": "22222222200022",
                    "nom_ou_denomination": "BETA JARDIN",
                    "commune": "MERIGNAC",
                    "code_postal": "33700",
                    "code_naf_retenu": "8130Z",
                    "date_creation_etablissement": "2024-01-01",
                    "age_etablissement_annees": "2",
                    "categorie_juridique_unite_legale": "1000",
                    "est_entrepreneur_individuel": "True",
                    "est_micro_entrepreneur_probable": "True",
                    "caractere_employeur_unite_legale": "N",
                    "score_priorisation": "3",
                    "adresse_complete": "2 RUE B, 33700 MERIGNAC",
                    "extra_column": "ignored",
                },
                {
                    "siren": "333333333",
                    "siret": "33333333300033",
                    "nom_ou_denomination": "GAMMA AIDE",
                    "commune": "BORDEAUX",
                    "code_postal": "33800",
                    "code_naf_retenu": "8810A",
                    "date_creation_etablissement": "2025-09-01",
                    "age_etablissement_annees": "0",
                    "categorie_juridique_unite_legale": "1000",
                    "est_entrepreneur_individuel": "True",
                    "est_micro_entrepreneur_probable": "True",
                    "caractere_employeur_unite_legale": "",
                    "score_priorisation": "1",
                    "adresse_complete": "3 RUE C, 33800 BORDEAUX",
                    "extra_column": "ignored",
                },
            ],
        )

    def test_lists_projected_rows_with_typed_values(self) -> None:
        page = list_independants(
            filters={},
            sort={"column": "siren", "direction": "asc"},
            pagination={"limit": 10, "offset": 0},
            csv_path=self.csv_path,
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
            csv_path=self.csv_path,
        )

        self.assertEqual(1, page["total"])
        self.assertEqual("111111111", page["data"][0]["siren"])

    def test_sort_and_pagination(self) -> None:
        page = list_independants(
            filters={},
            sort={"column": "score_priorisation", "direction": "desc"},
            pagination={"limit": 2, "offset": 1},
            csv_path=self.csv_path,
        )

        self.assertEqual(3, page["total"])
        self.assertEqual(["222222222", "333333333"], [r["siren"] for r in page["data"]])

    def test_rejects_unknown_sort_column(self) -> None:
        with self.assertRaisesRegex(ValueError, "Tri non autorisé"):
            list_independants(
                filters={},
                sort={"column": "score_priorisation; DROP TABLE companies"},
                pagination={},
                csv_path=self.csv_path,
            )

    def test_rejects_invalid_filters_and_pagination(self) -> None:
        with self.assertRaisesRegex(ValueError, "score_min"):
            list_independants(
                filters={"score_min": "high"},
                sort={},
                pagination={},
                csv_path=self.csv_path,
            )

        with self.assertRaisesRegex(ValueError, "limit"):
            list_independants(
                filters={},
                sort={},
                pagination={"limit": -1},
                csv_path=self.csv_path,
            )

    def test_missing_csv_returns_empty_page(self) -> None:
        page = list_independants(
            filters={},
            sort={},
            pagination={"limit": 5, "offset": 0},
            csv_path=Path(self.temp_dir.name) / "missing.csv",
        )

        self.assertEqual({"data": [], "total": 0, "limit": 5, "offset": 0}, page)


if __name__ == "__main__":
    unittest.main()
