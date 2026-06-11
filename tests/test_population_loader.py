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
    from services.population_loader import (
        PopulationColumnError,
        extract_population_75_plus_by_iris,
        load_population_iris,
    )


@unittest.skipIf(pandas is None, "pandas is not installed")
class PopulationLoaderTest(unittest.TestCase):
    def test_load_population_csv_and_sum_exact_age_bands(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rp_iris_2021.csv"
            path.write_text(
                "iris;p21_pop;p21_pop7579;p21_pop8084;p21_pop8589;p21_pop90p\n"
                "330630101;1000;20;15;10;5\n"
                "330630102;800;12;8;6;4\n",
                encoding="utf-8",
            )

            df = load_population_iris(path)
            output = extract_population_75_plus_by_iris(df)

        self.assertEqual(
            list(output.columns),
            [
                "iris_code",
                "population_total",
                "population_75_plus",
                "source_name",
                "source_year",
                "quality_flag",
            ],
        )
        self.assertEqual(output.loc[0, "iris_code"], "330630101")
        self.assertEqual(output.loc[0, "population_total"], 1000.0)
        self.assertEqual(output.loc[0, "population_75_plus"], 50.0)
        self.assertEqual(
            output.loc[0, "source_name"], "INSEE Recensement de la population IRIS"
        )
        self.assertEqual(output.loc[0, "source_year"], "2021")
        self.assertEqual(output.loc[0, "quality_flag"], "exact")

    def test_extract_uses_direct_75_plus_column(self) -> None:
        df = pandas.DataFrame(
            {
                "code_iris": ["330630101"],
                "population_total": ["1000"],
                "population_75_plus": ["55"],
            }
        )
        df.attrs["source_year"] = "2020"

        output = extract_population_75_plus_by_iris(df)

        self.assertEqual(output.loc[0, "population_75_plus"], 55.0)
        self.assertEqual(output.loc[0, "quality_flag"], "exact")
        self.assertEqual(output.loc[0, "source_year"], "2020")

    def test_extract_flags_approximate_age_bands(self) -> None:
        df = pandas.DataFrame(
            {
                "iris": ["330630101"],
                "p21_pop6579": ["70"],
                "p21_pop80p": ["40"],
            }
        )

        output = extract_population_75_plus_by_iris(df)

        self.assertEqual(output.loc[0, "population_75_plus"], 110.0)
        self.assertEqual(output.loc[0, "quality_flag"], "approximate_age_bands")

    def test_load_population_zip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rp_iris_2019.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr(
                    "population.csv",
                    "iris;p19_pop75p\n330630101;42\n",
                )

            df = load_population_iris(path)
            output = extract_population_75_plus_by_iris(df)

        self.assertEqual(output.loc[0, "population_75_plus"], 42.0)
        self.assertEqual(output.loc[0, "source_year"], "2019")

    def test_extract_raises_when_age_columns_are_unavailable(self) -> None:
        df = pandas.DataFrame(
            {
                "iris": ["330630101"],
                "p21_pop6074": ["100"],
            }
        )

        with self.assertRaises(PopulationColumnError) as context:
            extract_population_75_plus_by_iris(df)

        message = str(context.exception)
        self.assertIn("Candidate groups:", message)
        self.assertIn("75_79+80_84+85_89+90_plus", message)
        self.assertIn("Available columns:", message)
        self.assertIn("p21_pop6074", message)


if __name__ == "__main__":
    unittest.main()
