import unittest
from datetime import date
from typing import Any

from services.insee_sirene_mapping import (
    CSV_COLUMNS,
    build_adresse_complete,
    build_consolidated_etablissement_row,
    build_consolidated_etablissement_rows,
    compute_age_years,
    compute_prioritization_score,
    map_etablissement_to_csv_row,
)


class FakeSireneClient:
    def __init__(self, payloads_by_siren: dict[str, dict[str, Any]]) -> None:
        self.payloads_by_siren = payloads_by_siren
        self.calls: list[str] = []

    def get_siren(self, siren: str) -> dict[str, Any]:
        self.calls.append(siren)
        return self.payloads_by_siren[siren]


class InseeSireneMappingTest(unittest.TestCase):
    def test_maps_full_etablissement_and_unite_legale_to_csv_row(self) -> None:
        etablissement = {
            "siren": "123456789",
            "siret": "12345678900012",
            "nic": "00012",
            "activitePrincipaleEtablissement": "8121Z",
            "dateCreationEtablissement": "2020-01-02",
            "etatAdministratifEtablissement": "A",
            "trancheEffectifsEtablissement": "01",
            "caractereEmployeurEtablissement": "N",
            "enseigne1Etablissement": "ENSEIGNE A",
            "enseigne2Etablissement": "ENSEIGNE B",
            "enseigne3Etablissement": "ENSEIGNE C",
            "denominationUsuelleEtablissement": "NOM USUEL ETAB",
            "numeroVoieEtablissement": "12",
            "typeVoieEtablissement": "RUE",
            "libelleVoieEtablissement": "DES LILAS",
            "complementAdresseEtablissement": "BAT A",
            "codePostalEtablissement": "33000",
            "libelleCommuneEtablissement": "BORDEAUX",
            "codeCommuneEtablissement": "33063",
        }
        unite_legale = {
            "siren": "123456789",
            "denominationUniteLegale": "DENOMINATION UL",
            "nomUniteLegale": "DUPONT",
            "prenomUsuelUniteLegale": "JEAN",
            "categorieJuridiqueUniteLegale": "5710",
            "activitePrincipaleUniteLegale": "8130Z",
            "dateCreationUniteLegale": "2019-12-01",
            "etatAdministratifUniteLegale": "A",
            "trancheEffectifsUniteLegale": "03",
            "caractereEmployeurUniteLegale": "O",
        }

        row = map_etablissement_to_csv_row(etablissement, unite_legale)

        self.assertEqual(set(CSV_COLUMNS), set(row))
        self.assertEqual("123456789", row["siren"])
        self.assertEqual("12345678900012", row["siret"])
        self.assertEqual("00012", row["nic"])
        self.assertEqual("NOM USUEL ETAB", row["nom_ou_denomination"])
        self.assertEqual("DENOMINATION UL", row["denomination_unite_legale"])
        self.assertEqual("DUPONT", row["nom_unite_legale"])
        self.assertEqual("JEAN", row["prenom_usuel_unite_legale"])
        self.assertEqual("5710", row["categorie_juridique_unite_legale"])
        self.assertFalse(row["est_entrepreneur_individuel"])
        self.assertFalse(row["est_micro_entrepreneur_probable"])
        self.assertEqual("8130Z", row["activite_principale_unite_legale"])
        self.assertEqual("8121Z", row["activite_principale_etablissement"])
        self.assertEqual("8121Z", row["code_naf_retenu"])
        self.assertEqual("2019-12-01", row["date_creation_unite_legale"])
        self.assertEqual("2020-01-02", row["date_creation_etablissement"])
        self.assertEqual("A", row["etat_administratif_unite_legale"])
        self.assertEqual("A", row["etat_administratif_etablissement"])
        self.assertEqual("03", row["tranche_effectifs_unite_legale"])
        self.assertEqual("01", row["tranche_effectifs_etablissement"])
        self.assertEqual("O", row["caractere_employeur_unite_legale"])
        self.assertEqual("N", row["caractere_employeur_etablissement"])
        self.assertEqual("ENSEIGNE A", row["enseigne_1"])
        self.assertEqual("ENSEIGNE B", row["enseigne_2"])
        self.assertEqual("ENSEIGNE C", row["enseigne_3"])
        self.assertEqual("NOM USUEL ETAB", row["denomination_usuelle_etablissement"])
        self.assertEqual("12", row["numero_voie"])
        self.assertEqual("RUE", row["type_voie"])
        self.assertEqual("DES LILAS", row["libelle_voie"])
        self.assertEqual("BAT A", row["complement_adresse"])
        self.assertEqual("33000", row["code_postal"])
        self.assertEqual("BORDEAUX", row["commune"])
        self.assertEqual("33063", row["code_commune"])
        self.assertEqual(
            "12 RUE DES LILAS, BAT A, 33000 BORDEAUX",
            row["adresse_complete"],
        )
        self.assertIn("age_etablissement_annees", row)
        self.assertIn("score_priorisation", row)
        self.assertIn("raison_score", row)

    def test_name_priority_uses_enseigne_then_unite_legale_then_person_name(self) -> None:
        base_etablissement = {"siren": "123456789", "siret": "12345678900012"}

        self.assertEqual(
            "ENSEIGNE",
            map_etablissement_to_csv_row(
                {**base_etablissement, "enseigne1Etablissement": "ENSEIGNE"},
                {"denominationUniteLegale": "DENOMINATION"},
            )["nom_ou_denomination"],
        )
        self.assertEqual(
            "DENOMINATION",
            map_etablissement_to_csv_row(
                base_etablissement,
                {"denominationUniteLegale": "DENOMINATION"},
            )["nom_ou_denomination"],
        )
        self.assertEqual(
            "JEAN DUPONT",
            map_etablissement_to_csv_row(
                base_etablissement,
                {
                    "prenomUsuelUniteLegale": "JEAN",
                    "nomUniteLegale": "DUPONT",
                },
            )["nom_ou_denomination"],
        )

    def test_micro_entrepreneur_probable_requires_ei_and_small_headcount(self) -> None:
        etablissement = {
            "siren": "123456789",
            "siret": "12345678900012",
            "trancheEffectifsEtablissement": "01",
        }

        row = map_etablissement_to_csv_row(
            etablissement,
            {"categorieJuridiqueUniteLegale": "1000"},
        )
        self.assertTrue(row["est_entrepreneur_individuel"])
        self.assertTrue(row["est_micro_entrepreneur_probable"])

        row = map_etablissement_to_csv_row(
            etablissement,
            {
                "categorieJuridiqueUniteLegale": "1000",
                "trancheEffectifsUniteLegale": "03",
            },
        )
        self.assertFalse(row["est_micro_entrepreneur_probable"])

        row = map_etablissement_to_csv_row(
            etablissement,
            {
                "categorieJuridiqueUniteLegale": "5710",
                "trancheEffectifsUniteLegale": "01",
            },
        )
        self.assertFalse(row["est_entrepreneur_individuel"])
        self.assertFalse(row["est_micro_entrepreneur_probable"])

    def test_build_consolidated_row_fetches_unite_legale_by_siren(self) -> None:
        client = FakeSireneClient(
            {
                "123456789": {
                    "uniteLegale": {
                        "siren": "123456789",
                        "denominationUniteLegale": "ALPHA",
                    }
                }
            }
        )

        row = build_consolidated_etablissement_row(
            client,
            {"siren": "123456789", "siret": "12345678900012"},
        )

        self.assertEqual(["123456789"], client.calls)
        self.assertEqual("ALPHA", row["nom_ou_denomination"])

    def test_build_consolidated_row_extracts_siren_from_siret_when_missing(self) -> None:
        client = FakeSireneClient(
            {
                "123456789": {
                    "uniteLegale": {"denominationUniteLegale": "ALPHA"}
                }
            }
        )

        row = build_consolidated_etablissement_row(
            client,
            {"siret": "12345678900012"},
        )

        self.assertEqual(["123456789"], client.calls)
        self.assertEqual("123456789", row["siren"])

    def test_build_consolidated_rows_processes_each_etablissement(self) -> None:
        client = FakeSireneClient(
            {
                "111111111": {"uniteLegale": {"denominationUniteLegale": "A"}},
                "222222222": {"uniteLegale": {"denominationUniteLegale": "B"}},
            }
        )

        rows = build_consolidated_etablissement_rows(
            client,
            [
                {"siren": "111111111", "siret": "11111111100011"},
                {"siren": "222222222", "siret": "22222222200022"},
            ],
        )

        self.assertEqual(["111111111", "222222222"], client.calls)
        self.assertEqual(["A", "B"], [row["nom_ou_denomination"] for row in rows])

    def test_mapping_handles_missing_fields_cleanly(self) -> None:
        row = map_etablissement_to_csv_row({}, {})

        self.assertEqual(set(CSV_COLUMNS), set(row))
        self.assertFalse(row["est_entrepreneur_individuel"])
        self.assertFalse(row["est_micro_entrepreneur_probable"])
        string_values = {
            key: value
            for key, value in row.items()
            if key
            not in {
                "est_entrepreneur_individuel",
                "est_micro_entrepreneur_probable",
                "score_priorisation",
            }
        }
        self.assertTrue(all(value == "" for value in string_values.values()))
        self.assertEqual(0, row["score_priorisation"])

    def test_compute_prioritization_score_applies_all_positive_rules(self) -> None:
        score = compute_prioritization_score(
            activite_principale="8810A",
            date_creation_etablissement="2010-05-31",
            caractere_employeur_unite_legale="O",
            enseigne_1="ENSEIGNE",
            today=date(2026, 6, 5),
        )

        self.assertEqual(16, score["age_etablissement_annees"])
        self.assertEqual(11, score["score_priorisation"])
        self.assertEqual(
            "activite_8810A:+3; "
            "age_plus_5_ans:+2; "
            "age_plus_10_ans:+3; "
            "employeur_unite_legale:+2; "
            "enseigne_renseignee:+1",
            score["raison_score"],
        )

    def test_compute_prioritization_score_scores_8121z_and_recent_penalty(self) -> None:
        score = compute_prioritization_score(
            activite_principale="8121Z",
            date_creation_etablissement="2026-01-10",
            caractere_employeur_unite_legale="N",
            today=date(2026, 6, 5),
        )

        self.assertEqual(0, score["age_etablissement_annees"])
        self.assertEqual(0, score["score_priorisation"])
        self.assertEqual(
            "activite_8121Z:+2; creation_moins_1_an:-2",
            score["raison_score"],
        )

    def test_compute_prioritization_score_handles_missing_or_invalid_date(self) -> None:
        score = compute_prioritization_score(
            activite_principale="8129B",
            date_creation_etablissement="not-a-date",
            caractere_employeur_unite_legale="",
            today=date(2026, 6, 5),
        )

        self.assertEqual("", score["age_etablissement_annees"])
        self.assertEqual(0, score["score_priorisation"])
        self.assertEqual("", score["raison_score"])

    def test_compute_age_years_uses_completed_years(self) -> None:
        self.assertEqual(
            4,
            compute_age_years("2021-06-06", today=date(2026, 6, 5)),
        )
        self.assertEqual(
            5,
            compute_age_years("2021-06-05", today=date(2026, 6, 5)),
        )

    def test_build_adresse_complete_ignores_missing_parts(self) -> None:
        self.assertEqual(
            "12 RUE DES LILAS, 33000 BORDEAUX",
            build_adresse_complete(
                numero_voie="12",
                type_voie="RUE",
                libelle_voie="DES LILAS",
                code_postal="33000",
                commune="BORDEAUX",
            ),
        )
        self.assertEqual(
            "33000 BORDEAUX",
            build_adresse_complete(code_postal="33000", commune="BORDEAUX"),
        )

    def test_address_mapping_supports_nested_adresse_etablissement(self) -> None:
        row = map_etablissement_to_csv_row(
            {
                "siren": "123456789",
                "siret": "12345678900012",
                "adresseEtablissement": {
                    "numeroVoieEtablissement": "4",
                    "typeVoieEtablissement": "AV",
                    "libelleVoieEtablissement": "VICTOR HUGO",
                    "codePostalEtablissement": "33100",
                    "libelleCommuneEtablissement": "BORDEAUX",
                },
            },
            {},
        )

        self.assertEqual("4", row["numero_voie"])
        self.assertEqual("AV", row["type_voie"])
        self.assertEqual("VICTOR HUGO", row["libelle_voie"])
        self.assertEqual("33100", row["code_postal"])
        self.assertEqual("4 AV VICTOR HUGO, 33100 BORDEAUX", row["adresse_complete"])

    def test_build_consolidated_row_requires_siren_or_siret(self) -> None:
        client = FakeSireneClient({})

        with self.assertRaises(ValueError):
            build_consolidated_etablissement_row(client, {})


if __name__ == "__main__":
    unittest.main()
