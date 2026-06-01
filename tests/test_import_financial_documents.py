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
    def __init__(self, files: dict[str, str]):
        self.files = files

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return None

    def list_entries(self, remote_path: str = "."):
        return [
            SimpleNamespace(filename=path, st_mode=stat.S_IFREG)
            for path in self.files
        ]

    def read_text_file(self, remote_path: str, max_bytes: int = 10_000_000):
        return self.files[remote_path]


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

    def test_extracts_siren_from_company_siret(self) -> None:
        self.create_companies(["12345678900012"])

        conn = self.connect()
        try:
            sirens, sirets_by_siren = importer.get_existing_company_identifiers(conn)
        finally:
            conn.close()

        self.assertEqual({"123456789"}, sirens)
        self.assertEqual({"12345678900012"}, sirets_by_siren["123456789"])

    def test_parses_metadata_from_sftp_path(self) -> None:
        metadata = importer.extract_metadata_from_path(
            "bilans/12345678900012_comptes_annuels_2023-12-31_2024-05-01.pdf"
        )

        self.assertIsNotNone(metadata)
        self.assertEqual("123456789", metadata.siren)
        self.assertEqual("12345678900012", metadata.siret)
        self.assertEqual("2023-12-31", metadata.closing_date)
        self.assertEqual("2024-05-01", metadata.filing_date)
        self.assertEqual("bilan", metadata.document_type)

    def test_ignores_documents_missing_from_companies(self) -> None:
        self.create_companies(["12345678900012"])
        fake_sftp = FakeSFTPClient(
            {
                "index.csv": (
                    "siren;date_cloture;date_depot;type_document;fichier\n"
                    "999999999;2023-12-31;2024-05-01;bilan;missing.pdf\n"
                )
            }
        )

        with patch.object(importer, "DATABASE_FILE", self.temp_db.name), patch.object(
            importer.InpiSFTPClient,
            "from_environment",
            return_value=fake_sftp,
        ):
            stats = importer.import_financial_documents()

        conn = self.connect()
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM financial_documents"
            ).fetchone()[0]
        finally:
            conn.close()

        self.assertEqual(1, stats.files_scanned)
        self.assertEqual(1, stats.documents_ignored)
        self.assertEqual(0, stats.documents_inserted)
        self.assertEqual(0, count)

    def test_import_is_idempotent_without_duplicates(self) -> None:
        self.create_companies(["12345678900012"])
        fake_sftp = FakeSFTPClient(
            {
                "index.csv": (
                    "siren;date_cloture;date_depot;type_document;fichier\n"
                    "123456789;2023-12-31;2024-05-01;bilan;document.pdf\n"
                )
            }
        )

        with patch.object(importer, "DATABASE_FILE", self.temp_db.name), patch.object(
            importer.InpiSFTPClient,
            "from_environment",
            return_value=fake_sftp,
        ):
            first_stats = importer.import_financial_documents()
            second_stats = importer.import_financial_documents()

        conn = self.connect()
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM financial_documents"
            ).fetchone()[0]
        finally:
            conn.close()

        self.assertEqual(1, first_stats.documents_inserted)
        self.assertEqual(0, second_stats.documents_inserted)
        self.assertEqual(0, second_stats.documents_updated)
        self.assertEqual(1, count)

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
