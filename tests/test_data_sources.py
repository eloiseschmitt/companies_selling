from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from services.data_sources import (
    SourceReference,
    detect_format_from_url,
    detect_vintage,
    download_source,
    load_manifest,
)


class DataSourcesTest(unittest.TestCase):
    def test_download_source_writes_raw_file_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            raw_dir = tmp_path / "data" / "raw"
            manifest_path = tmp_path / "data" / "source_manifest.json"
            response = Mock()
            response.content = b"iris;value\n330630101;1\n"
            response.raise_for_status.return_value = None

            with patch(
                "services.data_sources.requests.get",
                return_value=response,
            ) as get:
                path = download_source(
                    SourceReference(
                        key="insee_filosofi_iris",
                        name="INSEE Filosofi IRIS",
                        url="https://example.test/filosofi_iris_2021.zip",
                        expected_format="zip",
                        vintage="2021",
                    ),
                    raw_dir=raw_dir,
                    manifest_path=manifest_path,
                )

            self.assertEqual(path, raw_dir / "insee_filosofi_iris_2021.zip")
            self.assertEqual(path.read_bytes(), response.content)
            get.assert_called_once()

            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            entry = payload["sources"]["https://example.test/filosofi_iris_2021.zip"]
            self.assertEqual(entry["name"], "INSEE Filosofi IRIS")
            self.assertEqual(
                entry["source_url"], "https://example.test/filosofi_iris_2021.zip"
            )
            self.assertEqual(entry["vintage"], "2021")
            self.assertEqual(entry["local_filename"], "insee_filosofi_iris_2021.zip")
            self.assertEqual(
                entry["sha256"],
                "f50e6d30702596b1f5bf49a0c54e94d1831a020db7ed2315f706cdd1647d8fd1",
            )

    def test_download_source_reuses_existing_file_without_force_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            raw_dir = tmp_path / "data" / "raw"
            raw_dir.mkdir(parents=True)
            existing_path = raw_dir / "insee_rp_iris_population_2021.csv"
            existing_path.write_bytes(b"existing")
            manifest_path = tmp_path / "data" / "source_manifest.json"

            with patch("services.data_sources.requests.get") as get:
                path = download_source(
                    SourceReference(
                        key="insee_rp_iris_population",
                        name="INSEE RP IRIS",
                        url="https://example.test/rp_iris_2021.csv",
                        expected_format="csv",
                        vintage="2021",
                    ),
                    raw_dir=raw_dir,
                    manifest_path=manifest_path,
                )

            self.assertEqual(path, existing_path)
            self.assertEqual(path.read_bytes(), b"existing")
            get.assert_not_called()
            manifest = load_manifest(manifest_path)
            self.assertIn("https://example.test/rp_iris_2021.csv", manifest)

    def test_download_source_force_refresh_overwrites_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            raw_dir = tmp_path / "data" / "raw"
            raw_dir.mkdir(parents=True)
            existing_path = raw_dir / "insee_rp_iris_households_2021.parquet"
            existing_path.write_bytes(b"old")
            response = Mock()
            response.content = b"new"
            response.raise_for_status.return_value = None

            with patch(
                "services.data_sources.requests.get",
                return_value=response,
            ) as get:
                path = download_source(
                    SourceReference(
                        key="insee_rp_iris_households",
                        name="INSEE RP IRIS Menages",
                        url="https://example.test/rp_iris_households_2021.parquet",
                        expected_format="parquet",
                        vintage="2021",
                    ),
                    raw_dir=raw_dir,
                    manifest_path=tmp_path / "data" / "source_manifest.json",
                    force_refresh=True,
                )

            self.assertEqual(path, existing_path)
            self.assertEqual(path.read_bytes(), b"new")
            get.assert_called_once()

    def test_detect_format_and_vintage(self) -> None:
        self.assertEqual(
            detect_format_from_url("https://example.test/data_2022.xlsx"),
            "xlsx",
        )
        self.assertEqual(
            detect_vintage("https://example.test/data_2020_2021.zip"),
            "2021",
        )


if __name__ == "__main__":
    unittest.main()
