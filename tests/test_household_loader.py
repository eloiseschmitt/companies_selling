from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

try:
    import pandas
except ModuleNotFoundError:  # pragma: no cover - dependency may be absent locally.
    pandas = None

if pandas is not None:
    from services.household_loader import (
        HOUSEHOLDS_REFERENCE_75_PLUS_DEFINITION,
        PERSONS_75_PLUS_LIVING_ALONE_DEFINITION,
        HouseholdColumnError,
        extract_single_75_plus_by_iris,
        load_household_iris,
    )


@unittest.skipIf(pandas is None, "pandas is not installed")
class HouseholdLoaderTest(unittest.TestCase):
    def test_extract_prefers_direct_persons_75_plus_living_alone(self) -> None:
        df = pandas.DataFrame(
            {
                "iris": ["330630101"],
                "p21_pop75p_seul": ["12"],
                "p21_men1p_75p": ["10"],
            }
        )
        df.attrs["source_year"] = "2021"

        output = extract_single_75_plus_by_iris(df)

        self.assertEqual(
            list(output.columns),
            [
                "iris_code",
                "single_75_plus_count",
                "metric_definition",
                "quality_flag",
                "source_name",
                "source_year",
            ],
        )
        self.assertEqual(output.loc[0, "single_75_plus_count"], 12.0)
        self.assertEqual(
            output.loc[0, "metric_definition"],
            PERSONS_75_PLUS_LIVING_ALONE_DEFINITION,
        )
        self.assertEqual(
            output.loc[0, "quality_flag"],
            "exact_persons_75_plus_living_alone",
        )
        self.assertEqual(output.loc[0, "source_year"], "2021")

    def test_extract_uses_one_person_household_reference_75_plus(self) -> None:
        df = pandas.DataFrame(
            {
                "code_iris": ["330630101"],
                "p21_men1p_75p": ["15"],
            }
        )

        output = extract_single_75_plus_by_iris(df)

        self.assertEqual(output.loc[0, "single_75_plus_count"], 15.0)
        self.assertEqual(
            output.loc[0, "metric_definition"],
            HOUSEHOLDS_REFERENCE_75_PLUS_DEFINITION,
        )
        self.assertEqual(
            output.loc[0, "quality_flag"],
            "exact_households_reference_75_plus",
        )

    def test_extract_raises_instead_of_estimating_from_75_plus_rate(self) -> None:
        df = pandas.DataFrame(
            {
                "iris": ["330630101"],
                "p21_pop75p": ["80"],
                "p21_tx_pop75p_seul": ["25"],
            }
        )

        with self.assertRaises(HouseholdColumnError):
            extract_single_75_plus_by_iris(df)

    def test_extract_raises_instead_of_estimating_from_overall_share(self) -> None:
        df = pandas.DataFrame(
            {
                "iris": ["330630101"],
                "p21_pop75p": ["100"],
                "p21_pop_seul": ["200"],
                "p21_pop": ["1000"],
            }
        )

        with self.assertRaises(HouseholdColumnError):
            extract_single_75_plus_by_iris(df)

    def test_extract_detects_2022_household_reference_75_plus_column(self) -> None:
        df = pandas.DataFrame(
            {
                "IRIS": ["330630101"],
                "C22_MENPSEUL75P": ["18"],
            }
        )

        output = extract_single_75_plus_by_iris(df)

        self.assertEqual(output.loc[0, "single_75_plus_count"], 18.0)
        self.assertEqual(
            output.loc[0, "quality_flag"],
            "exact_households_reference_75_plus",
        )

    def test_load_household_zip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "household_2019.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr(
                    "household.csv",
                    "iris;p19_pop75p_seul\n330630101;42\n",
                )

            df = load_household_iris(path)
            output = extract_single_75_plus_by_iris(df)

        self.assertEqual(output.loc[0, "single_75_plus_count"], 42.0)
        self.assertEqual(output.loc[0, "source_year"], "2019")

    def test_extract_raises_when_no_direct_indicator_is_available(self) -> None:
        df = pandas.DataFrame(
            {
                "iris": ["330630101"],
                "other_column": ["1"],
            }
        )

        with self.assertRaises(HouseholdColumnError) as context:
            extract_single_75_plus_by_iris(df)

        message = str(context.exception)
        self.assertIn("Candidate groups:", message)
        self.assertIn("persons 75+ living alone", message)
        self.assertIn("one-person households reference 75+", message)
        self.assertIn("Available columns:", message)
        self.assertIn("other_column", message)


if __name__ == "__main__":
    unittest.main()
