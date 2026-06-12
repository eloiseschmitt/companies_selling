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
    from services.income_loader import (
        FilosofiColumnError,
        extract_median_income_by_iris,
        load_filosofi_iris,
    )


@unittest.skipIf(pandas is None, "pandas is not installed")
class IncomeLoaderTest(unittest.TestCase):
    def test_load_filosofi_csv_and_extract_median_income(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "filosofi_iris_2021.csv"
            path.write_text(
                "CODE_IRIS;LIBIRIS;COM;DISP_MED21\n"
                "330630101;Cauderan;33063;30000,5\n"
                "330630102;Centre;33063;25000\n",
                encoding="utf-8",
            )

            df = load_filosofi_iris(path)
            output = extract_median_income_by_iris(df)

        self.assertEqual(
            list(output.columns),
            [
                "iris_code",
                "iris_label",
                "commune_code",
                "median_disposable_income",
                "source_name",
                "source_year",
            ],
        )
        self.assertEqual(output.loc[0, "iris_code"], "330630101")
        self.assertEqual(output.loc[0, "iris_label"], "Cauderan")
        self.assertEqual(output.loc[0, "commune_code"], "33063")
        self.assertEqual(output.loc[0, "median_disposable_income"], 30000.5)
        self.assertEqual(output.loc[0, "source_name"], "INSEE Filosofi IRIS")
        self.assertEqual(output.loc[0, "source_year"], "2021")

    def test_load_filosofi_zip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "filosofi_2020.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr(
                    "filosofi.csv",
                    "iris;lib_iris;depcom;disp_med20\n330630101;A;33063;30000\n",
                )

            df = load_filosofi_iris(path)
            output = extract_median_income_by_iris(df)

        self.assertEqual(output.loc[0, "median_disposable_income"], 30000.0)
        self.assertEqual(output.loc[0, "source_year"], "2020")

    def test_load_filosofi_zip_with_insee_xlsx(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            excel_path = tmp_path / "BASE_TD_FILO_IRIS_2021_DEC.xlsx"
            zip_path = tmp_path / "filosofi_2021.zip"
            raw_df = pandas.DataFrame(
                [
                    ["Titre", None, None, None],
                    ["Source", None, None, None],
                    ["IRIS", "Libellé de l'IRIS", "Commune ou ARM", "Médiane (€)"],
                    ["IRIS", "LIBIRIS", "COM", "DEC_MED21"],
                    ["330630101", "Cauderan", "33063", "30000"],
                ]
            )
            raw_df.to_excel(excel_path, index=False, header=False)
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.write(excel_path, arcname=excel_path.name)

            df = load_filosofi_iris(zip_path)
            output = extract_median_income_by_iris(df)

        self.assertEqual(output.loc[0, "iris_code"], "330630101")
        self.assertEqual(output.loc[0, "median_disposable_income"], 30000.0)

    def test_extract_detects_dec_med21_as_median_income(self) -> None:
        df = pandas.DataFrame(
            {
                "IRIS": ["330630101"],
                "DEC_MED21": ["30000"],
            }
        )

        output = extract_median_income_by_iris(df)

        self.assertEqual(output.loc[0, "median_disposable_income"], 30000.0)

    def test_extract_raises_explicit_error_when_income_column_missing(self) -> None:
        df = pandas.DataFrame(
            {
                "iris": ["330630101"],
                "other_column": ["30000"],
            }
        )

        with self.assertRaises(FilosofiColumnError) as context:
            extract_median_income_by_iris(df)

        message = str(context.exception)
        self.assertIn("Candidate columns:", message)
        self.assertIn("disp_med21", message)
        self.assertIn("Available columns:", message)
        self.assertIn("other_column", message)


if __name__ == "__main__":
    unittest.main()
