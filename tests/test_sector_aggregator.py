from __future__ import annotations

import unittest

try:
    import pandas
except ModuleNotFoundError:  # pragma: no cover - dependency may be absent locally.
    pandas = None

if pandas is not None:
    from services.sector_aggregator import aggregate_sector_indicators


@unittest.skipIf(pandas is None, "pandas is not installed")
class SectorAggregatorTest(unittest.TestCase):
    def test_aggregate_sector_indicators_with_weighted_income(self) -> None:
        mapping = {"Sector A": ("IRIS1", "IRIS2")}
        income_df = pandas.DataFrame(
            {
                "iris_code": ["IRIS1", "IRIS2"],
                "median_disposable_income": [30000, 20000],
                "income_weight": [100, 300],
                "source_year": ["2021", "2021"],
            }
        )
        population_df = pandas.DataFrame(
            {
                "iris_code": ["IRIS1", "IRIS2"],
                "population_75_plus": [10, 30],
                "source_year": ["2021", "2021"],
            }
        )
        household_df = pandas.DataFrame(
            {
                "iris_code": ["IRIS1", "IRIS2"],
                "single_75_plus_count": [4, 6],
                "quality_flag": [
                    "exact_persons_75_plus_living_alone",
                    "exact_persons_75_plus_living_alone",
                ],
                "source_year": ["2021", "2021"],
            }
        )
        retired_df = pandas.DataFrame(
            {
                "iris_code": ["IRIS1", "IRIS2"],
                "retired_csp_plus_count": [2, 3],
                "quality_flag": ["direct_count", "direct_count"],
                "source_year": ["2021", "2021"],
            }
        )

        output = aggregate_sector_indicators(
            mapping,
            income_df=income_df,
            population_df=population_df,
            household_df=household_df,
            retired_csp_df=retired_df,
            income_weight_column="income_weight",
        )

        self.assertEqual(output.loc[0, "sector_name"], "Sector A")
        self.assertEqual(output.loc[0, "iris_codes"], "IRIS1,IRIS2")
        self.assertEqual(output.loc[0, "median_income_min"], 20000.0)
        self.assertEqual(output.loc[0, "median_income_max"], 30000.0)
        self.assertEqual(output.loc[0, "median_income_weighted"], 22500.0)
        self.assertEqual(output.loc[0, "population_75_plus"], 40.0)
        self.assertEqual(output.loc[0, "single_75_plus_count"], 10.0)
        self.assertEqual(output.loc[0, "retired_csp_plus_count"], 5.0)
        self.assertEqual(output.loc[0, "source_years"], "2021")

    def test_income_without_weight_reports_range_only(self) -> None:
        output = aggregate_sector_indicators(
            {"Sector A": ("IRIS1", "IRIS2")},
            income_df=pandas.DataFrame(
                {
                    "iris_code": ["IRIS1", "IRIS2"],
                    "median_disposable_income": [30000, 20000],
                }
            ),
        )

        self.assertEqual(output.loc[0, "median_income_min"], 20000.0)
        self.assertEqual(output.loc[0, "median_income_max"], 30000.0)
        self.assertIsNone(output.loc[0, "median_income_weighted"])
        self.assertIn("not averaged", output.loc[0, "quality_notes"])

    def test_single_75_plus_not_summed_when_quality_is_not_summable(self) -> None:
        output = aggregate_sector_indicators(
            {"Sector A": ("IRIS1",)},
            household_df=pandas.DataFrame(
                {
                    "iris_code": ["IRIS1"],
                    "single_75_plus_count": [5],
                    "quality_flag": ["unsupported"],
                }
            ),
        )

        self.assertIsNone(output.loc[0, "single_75_plus_count"])
        self.assertIn("non-summable quality flags", output.loc[0, "quality_notes"])

    def test_retired_csp_not_aggregated_when_unavailable(self) -> None:
        output = aggregate_sector_indicators(
            {"Sector A": ("IRIS1",)},
            retired_csp_df=pandas.DataFrame(
                {
                    "iris_code": ["IRIS1"],
                    "retired_csp_plus_count": [None],
                    "quality_flag": ["not_available_directly_at_iris_level"],
                }
            ),
        )

        self.assertIsNone(output.loc[0, "retired_csp_plus_count"])
        self.assertIn("not directly reliable", output.loc[0, "quality_notes"])

    def test_retired_csp_count_from_share_requires_weight(self) -> None:
        output = aggregate_sector_indicators(
            {"Sector A": ("IRIS1", "IRIS2")},
            retired_csp_df=pandas.DataFrame(
                {
                    "iris_code": ["IRIS1", "IRIS2"],
                    "retired_csp_plus_share": ["10", "0.2"],
                    "retired_weight": [100, 50],
                    "quality_flag": ["direct_share", "direct_share"],
                }
            ),
            retired_weight_column="retired_weight",
        )

        self.assertEqual(output.loc[0, "retired_csp_plus_count"], 20.0)
        self.assertIn("derived from direct share", output.loc[0, "quality_notes"])


if __name__ == "__main__":
    unittest.main()
