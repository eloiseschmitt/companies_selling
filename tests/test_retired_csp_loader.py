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
        DIRECT_METRIC_DEFINITION,
        UNAVAILABLE_METRIC_DEFINITION,
        RetiredCspColumnError,
        extract_retired_csp_plus_by_iris,
        load_retired_csp_iris,
    )


@unittest.skipIf(pandas is None, "pandas is not installed")
class RetiredCspLoaderTest(unittest.TestCase):
    def test_extract_direct_count_and_share(self) -> None:
        df = pandas.DataFrame(
            {
                "iris": ["330630101"],
                "p21_retraites_anciens_cadres": ["42"],
                "p21_tx_retraites_anciens_cadres": ["12,5"],
            }
        )
        df.attrs["source_year"] = "2021"

        output = extract_retired_csp_plus_by_iris(df)

        self.assertEqual(
            list(output.columns),
            [
                "iris_code",
                "retired_csp_plus_count",
                "retired_csp_plus_share",
                "metric_definition",
                "quality_flag",
                "source_name",
                "source_year",
            ],
        )
        self.assertEqual(output.loc[0, "retired_csp_plus_count"], 42.0)
        self.assertEqual(output.loc[0, "retired_csp_plus_share"], 0.125)
        self.assertEqual(output.loc[0, "metric_definition"], DIRECT_METRIC_DEFINITION)
        self.assertEqual(output.loc[0, "quality_flag"], "direct_count_and_share")
        self.assertEqual(output.loc[0, "source_year"], "2021")

    def test_extract_direct_count_only(self) -> None:
        df = pandas.DataFrame(
            {
                "code_iris": ["330630101"],
                "retraites_csp_plus": ["30"],
            }
        )

        output = extract_retired_csp_plus_by_iris(df)

        self.assertEqual(output.loc[0, "retired_csp_plus_count"], 30.0)
        self.assertIsNone(output.loc[0, "retired_csp_plus_share"])
        self.assertEqual(output.loc[0, "quality_flag"], "direct_count")

    def test_extract_returns_none_when_indicator_unavailable(self) -> None:
        df = pandas.DataFrame(
            {
                "iris": ["330630101"],
                "p21_retraites": ["300"],
                "p21_pop15p_cs3": ["100"],
            }
        )

        output = extract_retired_csp_plus_by_iris(df)

        self.assertIsNone(output.loc[0, "retired_csp_plus_count"])
        self.assertIsNone(output.loc[0, "retired_csp_plus_share"])
        self.assertEqual(
            output.loc[0, "metric_definition"], UNAVAILABLE_METRIC_DEFINITION
        )
        self.assertEqual(
            output.loc[0, "quality_flag"],
            "not_available_directly_at_iris_level",
        )

    def test_load_retired_csp_zip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "retired_csp_2019.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr(
                    "retired.csv",
                    "iris;p19_retraites_anciens_cadres\n330630101;10\n",
                )

            df = load_retired_csp_iris(path)
            output = extract_retired_csp_plus_by_iris(df)

        self.assertEqual(output.loc[0, "retired_csp_plus_count"], 10.0)
        self.assertEqual(output.loc[0, "source_year"], "2019")

    def test_extract_raises_when_iris_column_missing(self) -> None:
        df = pandas.DataFrame({"retraites_csp_plus": ["12"]})

        with self.assertRaises(RetiredCspColumnError) as context:
            extract_retired_csp_plus_by_iris(df)

        message = str(context.exception)
        self.assertIn("Candidate columns:", message)
        self.assertIn("code_iris", message)
        self.assertIn("Available columns:", message)


if __name__ == "__main__":
    unittest.main()
