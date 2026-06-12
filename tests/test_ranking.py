from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    import pandas
except ModuleNotFoundError:  # pragma: no cover - dependency may be absent locally.
    pandas = None

if pandas is not None:
    from ranking import FINAL_COLUMNS, build_ranking, build_ranking_files


@unittest.skipIf(pandas is None, "pandas is not installed")
class RankingTest(unittest.TestCase):
    def test_build_ranking_scores_and_rank(self) -> None:
        sector_report = pandas.DataFrame(
            {
                "sector_name": ["A", "B"],
                "median_income_max": [100, 200],
                "taxable_households_share_mean": [20, 40],
                "population_75_plus": [10, 30],
                "people_80_plus_living_alone": [5, 15],
            }
        )

        ranking = build_ranking(sector_report)

        self.assertEqual(list(ranking.columns), list(FINAL_COLUMNS))
        self.assertEqual(ranking.loc[0, "sector_name"], "B")
        self.assertEqual(ranking.loc[0, "premium_rank"], 1)
        self.assertEqual(ranking.loc[0, "premium_opportunity_score"], 100.0)
        self.assertEqual(ranking.loc[1, "premium_opportunity_score"], 0.0)

    def test_build_ranking_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            input_path = tmp_path / "sector_report.csv"
            output_csv = tmp_path / "sector_ranking.csv"
            output_xlsx = tmp_path / "sector_ranking.xlsx"
            pandas.DataFrame(
                {
                    "sector_name": ["A"],
                    "median_income_max": [100],
                    "taxable_households_share_mean": [20],
                    "population_75_plus": [10],
                    "people_80_plus_living_alone": [5],
                }
            ).to_csv(input_path, index=False)

            ranking = build_ranking_files(input_path, output_csv, output_xlsx)

            self.assertEqual(ranking.loc[0, "premium_rank"], 1)
            self.assertTrue(output_csv.exists())
            self.assertTrue(output_xlsx.exists())


if __name__ == "__main__":
    unittest.main()
