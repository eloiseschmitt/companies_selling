import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

from scripts.export_bordeaux_independants import (
    CachedSireneClient,
    JsonSirenCache,
    count_uncached_etablissements,
    export_bordeaux_independants,
    extract_siren_from_etablissement,
    parse_args,
)


class FakeSireneClient:
    def __init__(
        self,
        etablissements: list[dict],
        unites_legales_by_siren: dict[str, dict],
    ) -> None:
        self.etablissements = etablissements
        self.unites_legales_by_siren = unites_legales_by_siren
        self.search_limits: list[int | None] = []
        self.get_siren_calls: list[str] = []

    def search_etablissements(self, limit: int | None = None) -> list[dict]:
        self.search_limits.append(limit)
        return self.etablissements[:limit] if limit is not None else self.etablissements

    def get_siren(self, siren: str) -> dict:
        self.get_siren_calls.append(siren)
        return self.unites_legales_by_siren[siren]


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as csv_file:
        return list(csv.DictReader(csv_file))


class ExportBordeauxIndependantsTest(unittest.TestCase):
    def test_exports_individual_entrepreneurs_with_bom_and_deduplication(self) -> None:
        client = FakeSireneClient(
            etablissements=[
                {
                    "siren": "111111111",
                    "siret": "11111111100011",
                    "nic": "00011",
                    "activitePrincipaleEtablissement": "8121Z",
                    "denominationUsuelleEtablissement": "EI CLEAN",
                    "codePostalEtablissement": "33000",
                    "libelleCommuneEtablissement": "BORDEAUX",
                    "etatAdministratifEtablissement": "A",
                },
                {
                    "siren": "111111111",
                    "siret": "11111111100011",
                    "nic": "00011",
                    "activitePrincipaleEtablissement": "8121Z",
                    "etatAdministratifEtablissement": "A",
                },
                {
                    "siren": "222222222",
                    "siret": "22222222200022",
                    "nic": "00022",
                    "activitePrincipaleEtablissement": "8130Z",
                    "etatAdministratifEtablissement": "A",
                },
            ],
            unites_legales_by_siren={
                "111111111": {
                    "uniteLegale": {
                        "categorieJuridiqueUniteLegale": "1000",
                        "etatAdministratifUniteLegale": "A",
                        "nomUniteLegale": "DUPONT",
                        "prenomUsuelUniteLegale": "ALICE",
                    }
                },
                "222222222": {
                    "uniteLegale": {
                        "categorieJuridiqueUniteLegale": "5710",
                        "etatAdministratifUniteLegale": "A",
                        "denominationUniteLegale": "BETA SARL",
                    }
                },
            },
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "independants.csv"
            cache_path = Path(temp_dir) / "cache.json"
            progress = io.StringIO()

            count = export_bordeaux_independants(
                output_path=output_path,
                cache_path=cache_path,
                client=client,
                progress_stream=progress,
                enrich_delay_seconds=0,
            )

            rows = read_csv_rows(output_path)
            raw_content = output_path.read_bytes()
            cached_payload = json.loads(cache_path.read_text(encoding="utf-8"))

        self.assertEqual(1, count)
        self.assertTrue(raw_content.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(1, len(rows))
        self.assertEqual("111111111", rows[0]["siren"])
        self.assertEqual("11111111100011", rows[0]["siret"])
        self.assertEqual("1000", rows[0]["categorie_juridique_unite_legale"])
        self.assertEqual("True", rows[0]["est_entrepreneur_individuel"])
        self.assertIn("2/2 100%", progress.getvalue())
        self.assertIn("Export terminé: 1 lignes", progress.getvalue())
        self.assertEqual(["111111111", "222222222"], client.get_siren_calls)
        self.assertEqual({"111111111", "222222222"}, set(cached_payload))

    def test_export_uses_limit_for_search(self) -> None:
        client = FakeSireneClient(
            etablissements=[],
            unites_legales_by_siren={},
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            export_bordeaux_independants(
                output_path=Path(temp_dir) / "out.csv",
                cache_path=Path(temp_dir) / "cache.json",
                limit=10,
                client=client,
                progress_stream=io.StringIO(),
                enrich_delay_seconds=0,
            )

        self.assertEqual([10], client.search_limits)

    def test_cached_sirene_client_avoids_repeated_get_siren_calls(self) -> None:
        client = FakeSireneClient(
            etablissements=[],
            unites_legales_by_siren={
                "111111111": {"uniteLegale": {"categorieJuridiqueUniteLegale": "1000"}}
            },
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonSirenCache(Path(temp_dir) / "cache.json")
            cached_client = CachedSireneClient(
                client,
                cache,
                enrich_delay_seconds=0,
            )

            first = cached_client.get_siren("111111111")
            second = cached_client.get_siren("111111111")

        self.assertEqual(first, second)
        self.assertEqual(["111111111"], client.get_siren_calls)

    def test_export_reuses_existing_cache_file(self) -> None:
        client = FakeSireneClient(
            etablissements=[
                {
                    "siren": "111111111",
                    "siret": "11111111100011",
                    "etatAdministratifEtablissement": "A",
                },
            ],
            unites_legales_by_siren={},
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "cache.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "111111111": {
                            "uniteLegale": {
                                "categorieJuridiqueUniteLegale": "1000",
                                "etatAdministratifUniteLegale": "A",
                                "denominationUniteLegale": "CACHE EI",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            output_path = Path(temp_dir) / "out.csv"

            count = export_bordeaux_independants(
                output_path=output_path,
                cache_path=cache_path,
                client=client,
                progress_stream=io.StringIO(),
                enrich_delay_seconds=0,
            )
            rows = read_csv_rows(output_path)

        self.assertEqual(1, count)
        self.assertEqual([], client.get_siren_calls)
        self.assertEqual("CACHE EI", rows[0]["nom_ou_denomination"])

    def test_export_progress_only_counts_uncached_etablissements(self) -> None:
        client = FakeSireneClient(
            etablissements=[
                {
                    "siren": "111111111",
                    "siret": "11111111100011",
                    "etatAdministratifEtablissement": "A",
                },
                {
                    "siren": "222222222",
                    "siret": "22222222200022",
                    "etatAdministratifEtablissement": "A",
                },
            ],
            unites_legales_by_siren={
                "222222222": {
                    "uniteLegale": {
                        "categorieJuridiqueUniteLegale": "1000",
                        "etatAdministratifUniteLegale": "A",
                        "denominationUniteLegale": "LIVE EI",
                    }
                }
            },
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "cache.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "111111111": {
                            "uniteLegale": {
                                "categorieJuridiqueUniteLegale": "1000",
                                "etatAdministratifUniteLegale": "A",
                                "denominationUniteLegale": "CACHE EI",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            output_path = Path(temp_dir) / "out.csv"
            progress = io.StringIO()

            count = export_bordeaux_independants(
                output_path=output_path,
                cache_path=cache_path,
                client=client,
                progress_stream=progress,
                enrich_delay_seconds=0,
            )
            rows = read_csv_rows(output_path)

        self.assertEqual(2, count)
        self.assertEqual(["222222222"], client.get_siren_calls)
        self.assertIn("1/1 100%", progress.getvalue())
        self.assertIn("1 établissement(s) repris depuis le cache", progress.getvalue())
        self.assertEqual(
            ["CACHE EI", "LIVE EI"],
            [row["nom_ou_denomination"] for row in rows],
        )

    def test_export_keeps_only_active_etablissement_and_active_unite_legale(
        self,
    ) -> None:
        client = FakeSireneClient(
            etablissements=[
                {
                    "siren": "111111111",
                    "siret": "11111111100011",
                    "etatAdministratifEtablissement": "A",
                },
                {
                    "siren": "222222222",
                    "siret": "22222222200022",
                    "etatAdministratifEtablissement": "F",
                },
                {
                    "siren": "333333333",
                    "siret": "33333333300033",
                    "etatAdministratifEtablissement": "A",
                },
                {
                    "siren": "444444444",
                    "siret": "44444444400044",
                    "etatAdministratifEtablissement": "A",
                    "periodesEtablissement": [
                        {
                            "dateFin": "2020-01-01",
                            "etatAdministratifEtablissement": "A",
                        },
                        {
                            "dateFin": None,
                            "etatAdministratifEtablissement": "F",
                        },
                    ],
                },
            ],
            unites_legales_by_siren={
                "111111111": {
                    "uniteLegale": {
                        "categorieJuridiqueUniteLegale": "1000",
                        "etatAdministratifUniteLegale": "A",
                        "denominationUniteLegale": "ACTIVE EI",
                    }
                },
                "333333333": {
                    "uniteLegale": {
                        "categorieJuridiqueUniteLegale": "1000",
                        "etatAdministratifUniteLegale": "C",
                        "denominationUniteLegale": "CESSÉE EI",
                    }
                },
            },
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "out.csv"

            count = export_bordeaux_independants(
                output_path=output_path,
                cache_path=Path(temp_dir) / "cache.json",
                client=client,
                progress_stream=io.StringIO(),
                enrich_delay_seconds=0,
            )
            rows = read_csv_rows(output_path)

        self.assertEqual(1, count)
        self.assertEqual(["111111111"], [row["siren"] for row in rows])
        self.assertEqual(["111111111", "333333333"], client.get_siren_calls)

    def test_export_excludes_current_cessed_unite_legale_period(self) -> None:
        client = FakeSireneClient(
            etablissements=[
                {
                    "siren": "111111111",
                    "siret": "11111111100011",
                    "etatAdministratifEtablissement": "A",
                },
            ],
            unites_legales_by_siren={
                "111111111": {
                    "uniteLegale": {
                        "siren": "111111111",
                        "periodesUniteLegale": [
                            {
                                "dateFin": "2020-01-01",
                                "categorieJuridiqueUniteLegale": "1000",
                                "etatAdministratifUniteLegale": "A",
                            },
                            {
                                "dateFin": None,
                                "categorieJuridiqueUniteLegale": "1000",
                                "etatAdministratifUniteLegale": "C",
                            },
                        ],
                    }
                },
            },
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "out.csv"

            count = export_bordeaux_independants(
                output_path=output_path,
                cache_path=Path(temp_dir) / "cache.json",
                client=client,
                progress_stream=io.StringIO(),
                enrich_delay_seconds=0,
            )
            rows = read_csv_rows(output_path)

        self.assertEqual(0, count)
        self.assertEqual([], rows)

    def test_count_uncached_etablissements_uses_cache_without_api(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "cache.json"
            cache_path.write_text(
                json.dumps({"111111111": {"uniteLegale": {}}}),
                encoding="utf-8",
            )
            cache = JsonSirenCache(cache_path)

            count = count_uncached_etablissements(
                [
                    {"siren": "111111111", "siret": "11111111100011"},
                    {"siren": "222222222", "siret": "22222222200022"},
                    {"siret": "33333333300033"},
                ],
                cache,
            )

        self.assertEqual(2, count)

    def test_extract_siren_from_etablissement_falls_back_to_siret(self) -> None:
        self.assertEqual(
            "123456789",
            extract_siren_from_etablissement({"siret": "12345678900012"}),
        )
        self.assertEqual("", extract_siren_from_etablissement({}))

    def test_parse_args_supports_requested_command(self) -> None:
        args = parse_args(
            [
                "--output",
                "independants_bordeaux_metropole.csv",
                "--limit",
                "5",
                "--enrich-delay",
                "2.5",
            ]
        )

        self.assertEqual(Path("independants_bordeaux_metropole.csv"), args.output)
        self.assertEqual(5, args.limit)
        self.assertEqual(2.5, args.enrich_delay)


if __name__ == "__main__":
    unittest.main()
