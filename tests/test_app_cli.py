from __future__ import annotations

import contextlib
import io
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

    def test_export_iris_candidates_uses_manifest_when_source_not_provided(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            raw_dir = tmp_path / "data" / "raw"
            raw_dir.mkdir(parents=True)
            manifest_path = tmp_path / "data" / "source_manifest.json"
            iris_path = raw_dir / "insee_iris_geography_2021.csv"
            output_path = tmp_path / "output" / "iris_candidates.csv"
            iris_path.write_text(
                "iris;libiris;com;libcom\n330690101;Centre;33069;Le Bouscat\n",
                encoding="utf-8",
            )
            write_manifest(
                manifest_path,
                "https://example.test/iris.csv",
                "insee_iris_geography_2021.csv",
            )

            result = main(
                [
                    "export-iris-candidates",
                    "--manifest",
                    str(manifest_path),
                    "--raw-dir",
                    str(raw_dir),
                    "--output",
                    str(output_path),
                ]
            )

            self.assertEqual(result, 0)
            self.assertTrue(output_path.exists())

    def test_validate_mapping_uses_manifest_when_source_not_provided(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            raw_dir = tmp_path / "data" / "raw"
            raw_dir.mkdir(parents=True)
            manifest_path = tmp_path / "data" / "source_manifest.json"
            mapping_path = write_mapping(
                tmp_path / "mapping.yml", {"Le Bouscat": ["330690101"]}
            )
            iris_path = raw_dir / "insee_iris_geography_2021.csv"
            iris_path.write_text(
                "iris;libiris;com;libcom\n330690101;Centre;33069;Le Bouscat\n",
                encoding="utf-8",
            )
            write_manifest(
                manifest_path,
                "https://example.test/iris.csv",
                "insee_iris_geography_2021.csv",
            )

            result = main(
                [
                    "validate-mapping",
                    "--sector-mapping",
                    str(mapping_path),
                    "--manifest",
                    str(manifest_path),
                    "--raw-dir",
                    str(raw_dir),
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
                "iris;p21_pop15p_retraites;p21_pop15p_cs3\n330690101;30;3\n",
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

    @unittest.skipIf(pandas is None, "pandas is not installed")
    def test_build_report_uses_manifest_when_files_not_provided(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            raw_dir = tmp_path / "data" / "raw"
            raw_dir.mkdir(parents=True)
            manifest_path = tmp_path / "data" / "source_manifest.json"
            output_dir = tmp_path / "output"
            mapping_path = write_mapping(
                tmp_path / "mapping.yml", {"Le Bouscat": ["330690101"]}
            )
            files = {
                "insee_filosofi_iris_2021.csv": ("iris;disp_med21\n330690101;30000\n"),
                "insee_rp_iris_population_2021.csv": (
                    "iris;p21_pop75p\n330690101;40\n"
                ),
                "insee_rp_iris_households_2021.csv": (
                    "iris;p21_pop75p_seul\n330690101;12\n"
                ),
                "insee_rp_iris_retired_csp_2021.csv": (
                    "iris;p21_pop15p_retraites;p21_pop15p_cs3\n330690101;30;3\n"
                ),
            }
            manifest_sources = {}
            for filename, content in files.items():
                (raw_dir / filename).write_text(content, encoding="utf-8")
                manifest_sources[f"https://example.test/{filename}"] = {
                    "name": filename,
                    "source_url": f"https://example.test/{filename}",
                    "downloaded_at": "2026-01-01T00:00:00+00:00",
                    "vintage": "2021",
                    "local_filename": filename,
                    "sha256": "test",
                }
            manifest_path.write_text(
                json.dumps({"sources": manifest_sources}),
                encoding="utf-8",
            )

            result = main(
                [
                    "build-report",
                    "--sector-mapping",
                    str(mapping_path),
                    "--manifest",
                    str(manifest_path),
                    "--raw-dir",
                    str(raw_dir),
                    "--output-dir",
                    str(output_dir),
                ]
            )

            self.assertEqual(result, 0)
            self.assertTrue((output_dir / "sector_report.csv").exists())
            self.assertTrue((output_dir / "sector_report.xlsx").exists())
            report_content = (output_dir / "sector_report.csv").read_text(
                encoding="utf-8-sig"
            )
            self.assertIn("Le Bouscat", report_content)

    def test_inspect_source_prints_columns_and_preview(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            source_path = tmp_path / "source.csv"
            source_path.write_text(
                "IRIS;P22_POP75P;MENAGE\n330690101;40;10\n",
                encoding="utf-8",
            )

            result = main(["inspect-source", "--source", str(source_path)])

        self.assertEqual(result, 0)

    @unittest.skipIf(pandas is None, "pandas is not installed")
    def test_debug_report_prints_source_and_mapping_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            mapping_path = write_mapping(
                tmp_path / "mapping.yml", {"Le Bouscat": ["330690101", "330690999"]}
            )
            income_path = tmp_path / "income.csv"
            population_path = tmp_path / "population.csv"
            household_path = tmp_path / "household.csv"
            retired_path = tmp_path / "retired.csv"
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
                "iris;p21_pop15p_retraites;p21_pop15p_cs3\n330690101;30;3\n",
                encoding="utf-8",
            )

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = main(
                    [
                        "debug-report",
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
                    ]
                )

        content = output.getvalue()
        self.assertEqual(result, 0)
        self.assertIn("Income source:", content)
        self.assertIn("- rows: 1", content)
        self.assertIn("- iris distinct: 1", content)
        self.assertIn("- iris column: iris", content)
        self.assertIn("330690101", content)
        self.assertIn("Le Bouscat", content)
        self.assertIn("- configured iris: 2", content)
        self.assertIn("- found: 1", content)
        self.assertIn("- missing: 1", content)
        self.assertIn("Bordeaux Caudéran", content)
        self.assertIn("- compared configured iris:", content)


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


def write_manifest(path: Path, source_url: str, local_filename: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "sources": {
                    source_url: {
                        "name": local_filename,
                        "source_url": source_url,
                        "downloaded_at": "2026-01-01T00:00:00+00:00",
                        "vintage": "2021",
                        "local_filename": local_filename,
                        "sha256": "test",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return path


if __name__ == "__main__":
    unittest.main()
