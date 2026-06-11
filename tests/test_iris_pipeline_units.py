from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import pandas
except ModuleNotFoundError:  # pragma: no cover - dependency may be absent locally.
    pandas = None

from services.data_sources import SourceReference, download_source
from services.geography import (
    SECTOR_NAMES,
    SectorMappingError,
    load_sector_iris_mapping,
)

if pandas is not None:
    from services.household_loader import extract_single_75_plus_by_iris
    from services.income_loader import (
        FilosofiColumnError,
        extract_median_income_by_iris,
    )
    from services.population_loader import extract_population_75_plus_by_iris
    from services.sector_aggregator import aggregate_sector_indicators


@unittest.skipIf(pandas is None, "pandas is not installed")
class IrisPipelineDataFrameUnitsTest(unittest.TestCase):
    def test_detects_filosofi_columns_from_insee_like_names(self) -> None:
        df = pandas.DataFrame(
            {
                "CODE_IRIS": ["330630101"],
                "LIBIRIS": ["Cauderan"],
                "COM": ["33063"],
                "DISP_MED21": ["30000,5"],
            }
        )
        df.attrs["source_year"] = "2021"

        output = extract_median_income_by_iris(df)

        self.assertEqual(output.loc[0, "iris_code"], "330630101")
        self.assertEqual(output.loc[0, "iris_label"], "Cauderan")
        self.assertEqual(output.loc[0, "commune_code"], "33063")
        self.assertEqual(output.loc[0, "median_disposable_income"], 30000.5)
        self.assertEqual(output.loc[0, "source_year"], "2021")

    def test_population_75_plus_sums_exact_age_bands(self) -> None:
        df = pandas.DataFrame(
            {
                "iris": ["330630101"],
                "p21_pop": ["1000"],
                "p21_pop7579": ["20"],
                "p21_pop8084": ["15"],
                "p21_pop8589": ["10"],
                "p21_pop90p": ["5"],
            }
        )

        output = extract_population_75_plus_by_iris(df)

        self.assertEqual(output.loc[0, "population_total"], 1000.0)
        self.assertEqual(output.loc[0, "population_75_plus"], 50.0)
        self.assertEqual(output.loc[0, "quality_flag"], "exact")

    def test_distinguishes_persons_living_alone_from_one_person_households(
        self,
    ) -> None:
        persons_df = pandas.DataFrame(
            {
                "iris": ["330630101"],
                "p21_pop75p_seul": ["12"],
                "p21_men1p_75p": ["10"],
            }
        )
        households_df = pandas.DataFrame(
            {
                "iris": ["330630101"],
                "p21_men1p_75p": ["10"],
            }
        )

        persons_output = extract_single_75_plus_by_iris(persons_df)
        households_output = extract_single_75_plus_by_iris(households_df)

        self.assertEqual(persons_output.loc[0, "single_75_plus_count"], 12.0)
        self.assertEqual(
            persons_output.loc[0, "quality_flag"],
            "exact_persons_75_plus_living_alone",
        )
        self.assertIn("persons aged 75+", persons_output.loc[0, "metric_definition"])
        self.assertEqual(households_output.loc[0, "single_75_plus_count"], 10.0)
        self.assertEqual(
            households_output.loc[0, "quality_flag"],
            "exact_households_reference_75_plus",
        )
        self.assertIn(
            "one-person households",
            households_output.loc[0, "metric_definition"],
        )

    def test_aggregates_indicators_by_sector_without_simple_income_average(
        self,
    ) -> None:
        output = aggregate_sector_indicators(
            {"Sector A": ("IRIS1", "IRIS2")},
            income_df=pandas.DataFrame(
                {
                    "iris_code": ["IRIS1", "IRIS2"],
                    "median_disposable_income": [30000, 20000],
                }
            ),
            population_df=pandas.DataFrame(
                {
                    "iris_code": ["IRIS1", "IRIS2"],
                    "population_75_plus": [10, 30],
                }
            ),
            household_df=pandas.DataFrame(
                {
                    "iris_code": ["IRIS1", "IRIS2"],
                    "single_75_plus_count": [4, 6],
                    "quality_flag": [
                        "exact_persons_75_plus_living_alone",
                        "exact_persons_75_plus_living_alone",
                    ],
                }
            ),
        )

        self.assertEqual(output.loc[0, "population_75_plus"], 40.0)
        self.assertEqual(output.loc[0, "single_75_plus_count"], 10.0)
        self.assertEqual(output.loc[0, "median_income_min"], 20000.0)
        self.assertEqual(output.loc[0, "median_income_max"], 30000.0)
        self.assertEqual(
            output.loc[0, "median_income_iris_values"],
            "IRIS1:30000; IRIS2:20000",
        )
        self.assertIsNone(output.loc[0, "median_income_weighted"])
        self.assertIn("not averaged", output.loc[0, "quality_notes"])

    def test_missing_expected_filosofi_income_column_raises_explicit_error(
        self,
    ) -> None:
        df = pandas.DataFrame(
            {
                "iris": ["330630101"],
                "unrelated_column": ["30000"],
            }
        )

        with self.assertRaises(FilosofiColumnError) as context:
            extract_median_income_by_iris(df)

        message = str(context.exception)
        self.assertIn("Candidate columns:", message)
        self.assertIn("disp_med21", message)
        self.assertIn("Available columns:", message)
        self.assertIn("unrelated_column", message)


class IrisPipelineFileUnitsTest(unittest.TestCase):
    def test_validates_yaml_mapping_and_rejects_missing_sector(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mapping.yml"
            path.write_text(
                "sectors:\n"
                + "\n".join(f"  {sector}: []" for sector in SECTOR_NAMES)
                + "\n",
                encoding="utf-8",
            )
            mapping = load_sector_iris_mapping(path)
            self.assertEqual(set(mapping), set(SECTOR_NAMES))

            invalid_path = Path(directory) / "invalid_mapping.yml"
            invalid_path.write_text(
                "sectors:\n  Bordeaux Caudéran: []\n",
                encoding="utf-8",
            )
            with self.assertRaises(SectorMappingError):
                load_sector_iris_mapping(invalid_path)

    def test_download_source_does_not_redownload_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            raw_dir = tmp_path / "raw"
            raw_dir.mkdir()
            existing_path = raw_dir / "insee_filosofi_iris_2021.csv"
            existing_path.write_bytes(b"already here")

            with patch("services.data_sources.requests.get") as get:
                path = download_source(
                    SourceReference(
                        key="insee_filosofi_iris",
                        name="INSEE Filosofi IRIS",
                        url="https://example.test/filosofi_iris_2021.csv",
                        expected_format="csv",
                        vintage="2021",
                    ),
                    raw_dir=raw_dir,
                    manifest_path=tmp_path / "manifest.json",
                    force_refresh=False,
                )

            self.assertEqual(path, existing_path)
            self.assertEqual(path.read_bytes(), b"already here")
            get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
