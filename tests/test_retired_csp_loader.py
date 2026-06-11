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
    from services.retired_csp_loader import (
        METRIC_DEFINITION,
        QUALITY_NOTE,
        RetiredCspColumnError,
        extract_retired_csp_plus_by_iris,
        load_retired_csp_iris,
    )


@unittest.skipIf(pandas is None, "pandas is not installed")
class RetiredCspLoaderTest(unittest.TestCase):
    def test_extract_retired_and_csp_plus_marginal_counts(self) -> None:
        df = pandas.DataFrame(
            {
                "iris": ["330630101"],
                "p22_pop15p_retraites": ["420"],
                "p22_pop15p_cs3": ["125"],
            }
        )
        df.attrs["source_year"] = "2022"

        output = extract_retired_csp_plus_by_iris(df)

        self.assertEqual(
            list(output.columns),
            [
                "iris_code",
                "retired_count",
                "csp_plus_15_plus_count",
                "metric_definition",
                "quality_flag",
                "quality_note",
                "source_name",
                "source_year",
            ],
        )
        self.assertEqual(output.loc[0, "retired_count"], 420.0)
        self.assertEqual(output.loc[0, "csp_plus_15_plus_count"], 125.0)
        self.assertEqual(output.loc[0, "metric_definition"], METRIC_DEFINITION)
        self.assertEqual(
            output.loc[0, "quality_flag"],
            "retired_and_csp_plus_available",
        )
        self.assertEqual(output.loc[0, "quality_note"], QUALITY_NOTE)
        self.assertEqual(output.loc[0, "source_year"], "2022")

    def test_extract_retired_count_only(self) -> None:
        df = pandas.DataFrame(
            {
                "code_iris": ["330630101"],
                "retraites": ["300"],
            }
        )

        output = extract_retired_csp_plus_by_iris(df)

        self.assertEqual(output.loc[0, "retired_count"], 300.0)
        self.assertIsNone(output.loc[0, "csp_plus_15_plus_count"])
        self.assertEqual(output.loc[0, "quality_flag"], "retired_count_available")

    def test_extract_returns_none_when_indicator_unavailable(self) -> None:
        df = pandas.DataFrame(
            {
                "iris": ["330630101"],
                "p21_retraites": ["300"],
                "p21_pop15p_cs3": ["100"],
            }
        )

        output = extract_retired_csp_plus_by_iris(df)

        self.assertEqual(output.loc[0, "retired_count"], 300.0)
        self.assertEqual(output.loc[0, "csp_plus_15_plus_count"], 100.0)
        self.assertEqual(output.loc[0, "metric_definition"], METRIC_DEFINITION)
        self.assertEqual(
            output.loc[0, "quality_flag"],
            "retired_and_csp_plus_available",
        )

    def test_load_retired_csp_zip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "retired_csp_2019.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr(
                    "retired.csv",
                    "iris;p19_pop15p_retraites\n330630101;10\n",
                )

            df = load_retired_csp_iris(path)
            output = extract_retired_csp_plus_by_iris(df)

        self.assertEqual(output.loc[0, "retired_count"], 10.0)
        self.assertEqual(output.loc[0, "source_year"], "2019")

    def test_extract_raises_when_iris_column_missing(self) -> None:
        df = pandas.DataFrame({"retraites": ["12"]})

        with self.assertRaises(RetiredCspColumnError) as context:
            extract_retired_csp_plus_by_iris(df)

        message = str(context.exception)
        self.assertIn("Candidate columns:", message)
        self.assertIn("code_iris", message)
        self.assertIn("Available columns:", message)


if __name__ == "__main__":
    unittest.main()
