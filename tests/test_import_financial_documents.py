import os
import sqlite3
import stat
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import import_financial_documents as importer
from services.inpi_sftp import InpiSFTPClient, MissingSFTPCredentialsError


class FakeSFTPClient:
    def __init__(self) -> None:
        self.entries = {
            "Bilans_PDF": ["2026"],
            "Bilans_PDF/2026": ["06"],
            "Bilans_PDF/2026/06": ["01"],
            "Bilans_PDF/2026/06/01": [
                "CA_123456789_7401_2012B00001_2025_K00001",
                "CA_999999999_7401_2012B00002_2025_K00002",
            ],
            "Bilans_PDF/2026/06/01/CA_123456789_7401_2012B00001_2025_K00001": [
                "CA_123456789_7401_2012B00001_2025_K00001.pdf"
            ],
            "Bilans_PDF/2026/06/01/CA_999999999_7401_2012B00002_2025_K00002": [
                "CA_999999999_7401_2012B00002_2025_K00002.pdf"
            ],
        }

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return None

    def list_entries(self, remote_path: str = "."):
        names = self.entries[remote_path]
        return [
            SimpleNamespace(
                filename=name,
                st_mode=(
                    stat.S_IFDIR
                    if self._is_dir(remote_path, name)
                    else stat.S_IFREG
                ),
                st_size=4096 if self._is_dir(remote_path, name) else 1234,
            )
            for name in names
        ]

    def _is_dir(self, remote_path: str, name: str) -> bool:
        return f"{remote_path}/{name}" in self.entries


class FinancialDocumentsImportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db.close()
        self.addCleanup(self.cleanup_temp_db)

    def cleanup_temp_db(self) -> None:
        if os.path.exists(self.temp_db.name):
            os.unlink(self.temp_db.name)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.temp_db.name)
        conn.row_factory = sqlite3.Row
        return conn

    def create_companies(self, sirets: list[str]) -> None:
        conn = self.connect()
        try:
            conn.execute("CREATE TABLE companies (siret TEXT)")
            conn.executemany(
                "INSERT INTO companies (siret) VALUES (?)",
                [(siret,) for siret in sirets],
            )
            conn.commit()
        finally:
            conn.close()

    def test_extracts_siren_from_ca_pdf_filename(self) -> None:
        path = (
            "Bilans_PDF/2026/06/01/CA_123456789_7401_2012B00001_2025_K00001/"
            "CA_123456789_7401_2012B00001_2025_K00001.pdf"
        )

        self.assertEqual("123456789", importer.extract_siren_from_pdf_filename(path))

    def test_extracts_closing_year_from_ca_pdf_filename(self) -> None:
        path = (
            "Bilans_PDF/2026/06/01/CA_123456789_7401_2012B00001_2025_K00001/"
            "CA_123456789_7401_2012B00001_2025_K00001.pdf"
        )

        self.assertEqual("2025", importer.extract_closing_date_from_pdf_filename(path))

    def test_filters_by_siren_present_in_companies(self) -> None:
        self.create_companies(["12345678900012"])
        fake_sftp = FakeSFTPClient()

        with patch.object(importer, "DATABASE_FILE", self.temp_db.name), patch.object(
            importer.InpiSFTPClient,
            "from_environment",
            return_value=fake_sftp,
        ), patch.object(
            importer,
            "read_pdf_text",
            return_value="CHIFFRES D'AFFAIRES NETS 12 345",
        ):
            stats = importer.import_financial_documents()

        conn = self.connect()
        try:
            rows = conn.execute(
                "SELECT siren, revenue FROM financial_documents"
            ).fetchall()
        finally:
            conn.close()

        self.assertEqual(2, stats.files_scanned)
        self.assertEqual(1, stats.matching_sirens)
        self.assertEqual(1, stats.documents_ignored)
        self.assertEqual(1, stats.documents_inserted)
        self.assertEqual("123456789", rows[0]["siren"])
        self.assertEqual("12345", str(rows[0]["revenue"]))

    def test_extracts_revenue_from_matching_line(self) -> None:
        text = "Produits\nCHIFFRES D'AFFAIRES NETS 1 000 2 345 678\nCharges"

        self.assertEqual("2345678", str(importer.extract_revenue_from_text(text)))

    def test_returns_none_when_revenue_is_not_found(self) -> None:
        text = "Total bilan\nRésultat net 42"

        self.assertIsNone(importer.extract_revenue_from_text(text))

    def test_missing_sftp_environment_variable_raises_clear_error(self) -> None:
        complete_env = {
            "SFTP_HOST": "sftp.example.test",
            "SFTP_USER": "user",
            "SFTP_PASSWORD": "password",
        }

        for missing_name in complete_env:
            env = {
                key: value
                for key, value in complete_env.items()
                if key != missing_name
            }
            with self.subTest(missing_name=missing_name):
                with patch.dict(os.environ, env, clear=True), patch(
                    "services.inpi_sftp.load_env_file"
                ):
                    with self.assertRaisesRegex(
                        MissingSFTPCredentialsError,
                        missing_name,
                    ):
                        InpiSFTPClient.from_environment()


if __name__ == "__main__":
    unittest.main()
