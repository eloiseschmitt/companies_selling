from __future__ import annotations

import csv
import tempfile
import unittest
import zipfile
from pathlib import Path

import pandas

from services.geography import (
    SECTOR_NAMES,
    SectorMappingError,
    build_iris_candidates,
    export_iris_candidates,
    load_iris_table,
    load_sector_iris_mapping,
    update_sector_mapping_from_candidates,
    validate_sector_mapping,
)


class GeographyTest(unittest.TestCase):
    def test_load_iris_table_and_export_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            iris_path = tmp_path / "iris.csv"
            iris_path.write_text(
                "code_iris;libelle_iris;code_commune;nom_commune\n"
                "330630101;Cauderan 1;33063;Bordeaux\n"
                "330690101;Centre;33069;Le Bouscat\n"
                "999990101;Outside;99999;Outside\n",
                encoding="utf-8",
            )

            iris_areas = load_iris_table(iris_path)
            candidates = build_iris_candidates(iris_areas)
            output_path = tmp_path / "iris_candidates.csv"
            export_iris_candidates(output_path, candidates)

            self.assertEqual(len(iris_areas), 3)
            self.assertEqual(len(candidates), 2)
            with output_path.open(encoding="utf-8-sig", newline="") as csv_file:
                rows = list(csv.DictReader(csv_file))
            self.assertEqual(rows[0]["commune_code"], "33063")
            self.assertIn("Bordeaux Caudéran", rows[0]["candidate_sectors"])
            self.assertIn("Bordeaux Fondaudège", rows[0]["candidate_sectors"])
            self.assertEqual(rows[1]["candidate_sectors"], "Le Bouscat")

    def test_load_iris_table_supports_cp1252_csv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            iris_path = tmp_path / "iris_cp1252.csv"
            iris_path.write_bytes(
                (
                    "code_iris;libelle_iris;code_commune;nom_commune\n"
                    "330630101;Caudéran;33063;Bordeaux\n"
                ).encode("cp1252")
            )

            iris_areas = load_iris_table(iris_path)

            self.assertEqual(iris_areas[0].iris_label, "Caudéran")

    def test_load_iris_table_supports_insee_excel_inside_zip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            excel_path = tmp_path / "reference_IRIS_geo2024.xlsx"
            zip_path = tmp_path / "reference_IRIS_geo2024.zip"
            raw_df = pandas.DataFrame(
                [
                    ["Liste des IRIS au 1er janvier 2024", None, None, None],
                    ["Source Insee", None, None, None],
                    ["Code IRIS", "Libellé IRIS", "Code commune", "Nom commune"],
                    ["CODE_IRIS", "LIB_IRIS", "DEPCOM", "LIBCOM"],
                    ["330630101", "Caudéran", "33063", "Bordeaux"],
                ]
            )
            raw_df.to_excel(excel_path, index=False, header=False)
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.write(excel_path, arcname=excel_path.name)

            iris_areas = load_iris_table(zip_path)

            self.assertEqual(iris_areas[0].iris_code, "330630101")
            self.assertEqual(iris_areas[0].commune_code, "33063")

    def test_load_sector_iris_mapping_and_validate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            mapping_path = tmp_path / "mapping.yml"
            mapping_path.write_text(
                "sectors:\n"
                + "\n".join(f"  {sector}: []" for sector in SECTOR_NAMES)
                + "\n",
                encoding="utf-8",
            )
            mapping = load_sector_iris_mapping(mapping_path)

        self.assertEqual(set(mapping), set(SECTOR_NAMES))
        self.assertEqual(mapping["Bordeaux Caudéran"], ())

    def test_update_sector_mapping_from_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            mapping_path = tmp_path / "mapping.yml"
            candidates_path = tmp_path / "iris_candidates.csv"
            mapping_path.write_text(
                "sectors:\n"
                "  Bordeaux Caudéran:\n"
                "    - 330630101\n"
                "  Bordeaux Fondaudège: []\n"
                "  Bordeaux Chartrons: []\n"
                "  Le Bouscat: []\n"
                "  Bruges: []\n"
                "  Mérignac centre: []\n"
                "  Saint-Médard-en-Jalles: []\n"
                "  Talence: []\n"
                "  Pessac centre: []\n"
                "  Bègles secteur résidentiel: []\n",
                encoding="utf-8",
            )
            candidates_path.write_text(
                "commune_code,commune_name,iris_code,iris_label,candidate_sectors\n"
                "33063,Bordeaux,330630101,Le Lac 1,"
                "Bordeaux Caudéran; Bordeaux Fondaudège; Bordeaux Chartrons\n",
                encoding="utf-8",
            )

            mapping = update_sector_mapping_from_candidates(
                candidates_path,
                mapping_path,
            )

            self.assertEqual(mapping["Bordeaux Caudéran"], ("330630101",))
            self.assertEqual(mapping["Bordeaux Fondaudège"], ("330630101",))
            self.assertEqual(mapping["Bordeaux Chartrons"], ("330630101",))
            written_mapping = load_sector_iris_mapping(mapping_path)
            self.assertEqual(written_mapping["Bordeaux Chartrons"], ("330630101",))

    def test_validate_sector_mapping_rejects_wrong_commune(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            iris_path = tmp_path / "iris.csv"
            iris_path.write_text(
                "iris;libiris;com;libcom\n330690101;Centre;33069;Le Bouscat\n",
                encoding="utf-8",
            )
            iris_areas = load_iris_table(iris_path)
            mapping = {sector: () for sector in SECTOR_NAMES}
            mapping["Bordeaux Caudéran"] = ("330690101",)

            with self.assertRaises(SectorMappingError):
                validate_sector_mapping(mapping, iris_areas)

    def test_load_sector_iris_mapping_rejects_missing_sector(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            mapping_path = tmp_path / "mapping.yml"
            mapping_path.write_text(
                "sectors:\n  Bordeaux Caudéran: []\n",
                encoding="utf-8",
            )
            with self.assertRaises(SectorMappingError):
                load_sector_iris_mapping(mapping_path)


if __name__ == "__main__":
    unittest.main()
