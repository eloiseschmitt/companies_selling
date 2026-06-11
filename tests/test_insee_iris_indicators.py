from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.insee_iris_indicators import (
    INDICATOR_75_PLUS_LIVING_ALONE,
    INDICATOR_MEDIAN_INCOME,
    INDICATOR_POPULATION_75_PLUS,
    INDICATOR_UPPER_SOCIO_PROFESSIONAL_RETIRED,
    DataSource,
    InvalidSectorConfigError,
    SectorConfig,
    build_indicators,
    load_source_rows,
    save_results,
)


class InseeIrisIndicatorsTest(unittest.TestCase):
    def test_build_indicators_from_csv_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            income_path = tmp_path / "filosofi.csv"
            population_path = tmp_path / "population.csv"
            income_path.write_text(
                "iris;disp_med21;nbpersmenfisc21\n"
                "330630101;30000;100\n"
                "330630102;25000;200\n",
                encoding="utf-8",
            )
            population_path.write_text(
                "iris;p21_pop75p;p21_pop75p_seul;p21_pop15p_retraites;"
                "p21_pop15p_cs3;p21_pop15p_cs4\n"
                "330630101;40;12;80;20;30\n"
                "330630102;60;18;120;30;10\n",
                encoding="utf-8",
            )

            income_rows = load_source_rows(
                DataSource("INSEE Filosofi IRIS", str(income_path), "2021"),
                tmp_path / "cache",
            )
            population_rows = load_source_rows(
                DataSource("INSEE RP IRIS", str(population_path), "2021"),
                tmp_path / "cache",
            )

            results = build_indicators(
                sectors=[SectorConfig("Bordeaux test", ("330630101", "330630102"))],
                income_rows=income_rows,
                population_rows=population_rows,
            )

        by_indicator = {result.indicator: result for result in results}
        self.assertEqual(by_indicator[INDICATOR_MEDIAN_INCOME].value, 25000)
        self.assertEqual(by_indicator[INDICATOR_MEDIAN_INCOME].quality, "approximation")
        self.assertEqual(by_indicator[INDICATOR_POPULATION_75_PLUS].value, 100)
        self.assertEqual(by_indicator[INDICATOR_75_PLUS_LIVING_ALONE].value, 30)
        self.assertEqual(
            by_indicator[INDICATOR_UPPER_SOCIO_PROFESSIONAL_RETIRED].value,
            90,
        )
        self.assertEqual(
            by_indicator[INDICATOR_UPPER_SOCIO_PROFESSIONAL_RETIRED].quality,
            "approximation",
        )

    def test_build_indicators_requires_explicit_iris_codes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            source_path = tmp_path / "source.csv"
            source_path.write_text(
                "iris;disp_med21;p21_pop75p\n330630101;30000;40\n",
                encoding="utf-8",
            )
            source_rows = load_source_rows(
                DataSource("source", str(source_path), "2021"),
                tmp_path / "cache",
            )

            with self.assertRaises(InvalidSectorConfigError):
                build_indicators(
                    sectors=[SectorConfig("Missing perimeter", ())],
                    income_rows=source_rows,
                    population_rows=source_rows,
                )

    def test_save_results_upserts_sqlite_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            income_path = tmp_path / "filosofi.csv"
            population_path = tmp_path / "population.csv"
            income_path.write_text(
                "iris;disp_med21\n330630101;30000\n",
                encoding="utf-8",
            )
            population_path.write_text(
                "iris;p21_pop75p;p21_pop75p_seul\n330630101;40;12\n",
                encoding="utf-8",
            )
            income_rows = load_source_rows(
                DataSource("INSEE Filosofi IRIS", str(income_path), "2021"),
                tmp_path / "cache",
            )
            population_rows = load_source_rows(
                DataSource("INSEE RP IRIS", str(population_path), "2021"),
                tmp_path / "cache",
            )
            results = build_indicators(
                sectors=[SectorConfig("Bordeaux test", ("330630101",))],
                income_rows=income_rows,
                population_rows=population_rows,
            )

            db_path = tmp_path / "companies.db"
            save_results(db_path, results)
            save_results(db_path, results)

            with sqlite3.connect(db_path) as connection:
                row_count = connection.execute(
                    "SELECT COUNT(*) FROM insee_iris_indicators"
                ).fetchone()[0]
            self.assertEqual(row_count, 4)


if __name__ == "__main__":
    unittest.main()
