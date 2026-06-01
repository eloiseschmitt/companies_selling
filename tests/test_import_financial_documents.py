import argparse
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
    def __init__(self, entries: dict[str, list[str]] | None = None) -> None:
        self.entries = entries or {
            "Bilans_PDF": ["2026"],
            "Bilans_PDF/2026": ["06"],
            "Bilans_PDF/2026/06": ["01"],
            "Bilans_PDF/2026/06/01": [
                "CA_123456789_7401_2012B00001_2025_K00001",
                "CA_123456789_7401_2012B00003_2024_K00003",
                "CA_999999999_7401_2012B00002_2025_K00002",
            ],
            "Bilans_PDF/2026/06/01/CA_123456789_7401_2012B00001_2025_K00001": [
                "CA_123456789_7401_2012B00001_2025_K00001.pdf"
            ],
            "Bilans_PDF/2026/06/01/CA_123456789_7401_2012B00003_2024_K00003": [
                "CA_123456789_7401_2012B00003_2024_K00003.pdf"
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


def make_targeted_entries() -> dict[str, list[str]]:
    return {
        "Bilans_PDF": ["2024", "2025", "2026"],
        "Bilans_PDF/2026": ["06"],
        "Bilans_PDF/2026/06": ["01"],
        "Bilans_PDF/2026/06/01": [
            "CA_999999999_7401_2012B00001_2025_K00001"
        ],
        "Bilans_PDF/2026/06/01/CA_999999999_7401_2012B00001_2025_K00001": [
            "CA_999999999_7401_2012B00001_2025_K00001.pdf"
        ],
        "Bilans_PDF/2025": ["12"],
        "Bilans_PDF/2025/12": ["31"],
        "Bilans_PDF/2025/12/31": [
            "CA_123456789_7401_2012B00001_2025_K00001",
            "CA_123456789_7401_2012B00001_2025_K00003",
            "CA_123456789_7401_2012B00001_2024_K00099",
        ],
        "Bilans_PDF/2025/12/31/CA_123456789_7401_2012B00001_2025_K00001": [
            "CA_123456789_7401_2012B00001_2025_K00001.pdf"
        ],
        "Bilans_PDF/2025/12/31/CA_123456789_7401_2012B00001_2025_K00003": [
            "CA_123456789_7401_2012B00001_2025_K00003.pdf"
        ],
        "Bilans_PDF/2025/12/31/CA_123456789_7401_2012B00001_2024_K00099": [
            "CA_123456789_7401_2012B00001_2024_K00099.pdf"
        ],
        "Bilans_PDF/2024": ["12"],
        "Bilans_PDF/2024/12": ["31"],
        "Bilans_PDF/2024/12/31": [
            "CA_123456789_7401_2012B00001_2026_K99999"
        ],
        "Bilans_PDF/2024/12/31/CA_123456789_7401_2012B00001_2026_K99999": [
            "CA_123456789_7401_2012B00001_2026_K99999.pdf"
        ],
    }


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

        self.assertEqual(3, stats.files_scanned)
        self.assertEqual(2, stats.matching_sirens)
        self.assertEqual(1, stats.documents_ignored)
        self.assertEqual(2, stats.documents_inserted)
        self.assertEqual("123456789", rows[0]["siren"])
        self.assertEqual("12345", str(rows[0]["revenue"]))

    def test_limit_only_processes_matching_company_pdfs(self) -> None:
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
        ) as read_pdf_text:
            stats = importer.import_financial_documents(limit=1)

        conn = self.connect()
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM financial_documents"
            ).fetchone()[0]
        finally:
            conn.close()

        self.assertEqual(1, stats.matching_sirens)
        self.assertEqual(1, stats.documents_inserted)
        self.assertEqual(1, count)
        self.assertEqual(1, read_pdf_text.call_count)

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

    def test_validates_targeted_siren_format(self) -> None:
        self.assertEqual("123456789", importer.validate_siren("123456789"))

        for value in ("12345678", "1234567890", "abcdefghi", "123 456 789"):
            with self.subTest(value=value):
                with self.assertRaises(argparse.ArgumentTypeError):
                    importer.validate_siren(value)

    def test_finds_latest_pdf_for_siren_in_latest_matching_year(self) -> None:
        fake_sftp = FakeSFTPClient(make_targeted_entries())

        selected_path, stats = importer.find_latest_ca_pdf_for_siren(
            fake_sftp,
            "123456789",
        )

        self.assertEqual(
            "Bilans_PDF/2025/12/31/CA_123456789_7401_2012B00001_2025_K00003/"
            "CA_123456789_7401_2012B00001_2025_K00003.pdf",
            selected_path,
        )
        self.assertEqual(2, stats.years_inspected)
        self.assertGreater(stats.files_examined, 0)

    def test_finds_latest_pdf_for_siren_in_requested_year(self) -> None:
        fake_sftp = FakeSFTPClient(make_targeted_entries())

        selected_path, stats = importer.find_latest_ca_pdf_for_siren(
            fake_sftp,
            "123456789",
            year="2024",
        )

        self.assertEqual(
            "Bilans_PDF/2024/12/31/CA_123456789_7401_2012B00001_2026_K99999/"
            "CA_123456789_7401_2012B00001_2026_K99999.pdf",
            selected_path,
        )
        self.assertEqual(1, stats.years_inspected)

    def test_returns_none_when_no_pdf_exists_for_siren(self) -> None:
        fake_sftp = FakeSFTPClient(make_targeted_entries())

        selected_path, stats = importer.find_latest_ca_pdf_for_siren(
            fake_sftp,
            "111111111",
        )

        self.assertIsNone(selected_path)
        self.assertEqual(3, stats.years_inspected)

    def test_targeted_import_updates_only_requested_company(self) -> None:
        self.create_companies(["12345678900012", "99999999900012"])
        conn = self.connect()
        try:
            from init_financial_documents import create_financial_documents_table

            create_financial_documents_table(conn)
            conn.execute(
                """
                INSERT INTO financial_documents (
                    siren,
                    siret,
                    closing_date,
                    document_path,
                    document_type,
                    source,
                    revenue
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "999999999",
                    "99999999900012",
                    "2025",
                    "existing.pdf",
                    "comptes_annuels_pdf",
                    "inpi_sftp",
                    "42",
                ),
            )
            conn.commit()
        finally:
            conn.close()

        fake_sftp = FakeSFTPClient(make_targeted_entries())
        with patch.object(importer, "DATABASE_FILE", self.temp_db.name), patch.object(
            importer.InpiSFTPClient,
            "from_environment",
            return_value=fake_sftp,
        ), patch.object(
            importer,
            "read_pdf_text",
            return_value="CHIFFRES D'AFFAIRES NETS 12 345",
        ) as read_pdf_text:
            summary = importer.import_financial_document_for_siren("123456789")

        conn = self.connect()
        try:
            rows = conn.execute(
                """
                SELECT siren, revenue
                FROM financial_documents
                ORDER BY siren
                """
            ).fetchall()
        finally:
            conn.close()

        self.assertEqual("inserted", summary["status"])
        self.assertEqual(1, read_pdf_text.call_count)
        self.assertEqual(["123456789", "999999999"], [row["siren"] for row in rows])
        self.assertEqual("12345", str(rows[0]["revenue"]))
        self.assertEqual("42", str(rows[1]["revenue"]))

    def test_targeted_import_requires_company_siren(self) -> None:
        self.create_companies(["99999999900012"])

        with patch.object(importer, "DATABASE_FILE", self.temp_db.name), patch.object(
            importer.InpiSFTPClient,
            "from_environment",
        ) as from_environment:
            with self.assertRaisesRegex(SystemExit, "absent de la table companies"):
                importer.import_financial_document_for_siren("123456789")

        from_environment.assert_not_called()

    def test_cli_passes_year_to_targeted_siren_import(self) -> None:
        summary = {
            "siren": "123456789",
            "document_path": "Bilans_PDF/2021/file.pdf",
            "closing_date": "2021",
            "revenue": None,
            "status": "inserted",
            "years_inspected": 1,
            "files_examined": 1,
            "search_duration_seconds": 0.0,
        }

        with patch(
            "sys.argv",
            [
                "import_financial_documents.py",
                "--siren",
                "123456789",
                "--year",
                "2021",
            ],
        ), patch.object(
            importer,
            "import_financial_document_for_siren",
            return_value=summary,
        ) as import_for_siren, patch("builtins.print"):
            importer.main()

        import_for_siren.assert_called_once_with("123456789", year="2021")


if __name__ == "__main__":
    unittest.main()
