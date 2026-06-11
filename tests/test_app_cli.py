from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

try:
    import pandas  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover - dependency may be absent locally.
    pandas = None

from app import main
from services.geography import SECTOR_NAMES


class AppCliTest(unittest.TestCase):
    def test_download_sources_without_sources_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            result = main(
                [
                    "download-sources",
                    "--raw-dir",
                    str(tmp_path / "raw"),
                    "--manifest",
                    str(tmp_path / "manifest.json"),
                ]
            )
        self.assertEqual(result, 0)

    def test_validate_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            mapping_path = write_mapping(
                tmp_path / "mapping.yml", {"Le Bouscat": ["330690101"]}
            )
            iris_path = tmp_path / "iris.csv"
            iris_path.write_text(
                "iris;libiris;com;libcom\n330690101;Centre;33069;Le Bouscat\n",
                encoding="utf-8",
            )

            result = main(
                [
                    "validate-mapping",
                    "--sector-mapping",
                    str(mapping_path),
                    "--iris-source",
                    str(iris_path),
                ]
            )

        self.assertEqual(result, 0)

    @unittest.skipIf(pandas is None, "pandas is not installed")
    def test_build_report_writes_expected_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            mapping_path = write_mapping(
                tmp_path / "mapping.yml", {"Le Bouscat": ["330690101"]}
            )
            income_path = tmp_path / "income.csv"
            population_path = tmp_path / "population.csv"
            household_path = tmp_path / "household.csv"
            retired_path = tmp_path / "retired.csv"
            manifest_path = tmp_path / "source_manifest.json"
            output_dir = tmp_path / "output"
            income_path.write_text(
                "iris;disp_med21\n330690101;30000\n",
                encoding="utf-8",
            )
            population_path.write_text(
                "iris;p21_pop75p\n330690101;40\n",
                encoding="utf-8",
            )
            household_path.write_text(
                "iris;p21_pop75p_seul\n330690101;12\n",
                encoding="utf-8",
            )
            retired_path.write_text(
                "iris;p21_retraites_anciens_cadres\n330690101;3\n",
                encoding="utf-8",
            )
            manifest_path.write_text(
                json.dumps({"sources": {"test": {"name": "test"}}}),
                encoding="utf-8",
            )

            result = main(
                [
                    "build-report",
                    "--sector-mapping",
                    str(mapping_path),
                    "--income-file",
                    str(income_path),
                    "--population-file",
                    str(population_path),
                    "--household-file",
                    str(household_path),
                    "--retired-csp-file",
                    str(retired_path),
                    "--manifest",
                    str(manifest_path),
                    "--output-dir",
                    str(output_dir),
                ]
            )

            self.assertEqual(result, 0)
            self.assertTrue((output_dir / "sector_report.csv").exists())
            self.assertTrue((output_dir / "sector_report.xlsx").exists())
            self.assertTrue((output_dir / "source_manifest.json").exists())
            self.assertTrue((output_dir / "quality_report.md").exists())


def write_mapping(path: Path, values: dict[str, list[str]]) -> Path:
    lines = ["sectors:"]
    for sector in SECTOR_NAMES:
        iris_codes = values.get(sector, [])
        if iris_codes:
            lines.append(f"  {sector}:")
            lines.extend(f"    - {iris_code}" for iris_code in iris_codes)
        else:
            lines.append(f"  {sector}: []")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    unittest.main()
