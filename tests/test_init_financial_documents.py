import argparse
import os
import sqlite3
import stat
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import init_financial_documents as init_documents


class FakeSFTPClient:
    def __init__(self) -> None:
        self.entries = {
            "Bilans_PDF": ["2024", "2025", "2026"],
            "Bilans_PDF/2026": ["01"],
            "Bilans_PDF/2026/01": ["01"],
            "Bilans_PDF/2026/01/01": [
                "CA_111111111_7401_2012B00001_2026_K00001"
            ],
            "Bilans_PDF/2025": ["01"],
            "Bilans_PDF/2025/01": ["01"],
            "Bilans_PDF/2025/01/01": [
                "CA_781241799_7401_2012B00001_2024_K00001",
                "CA_781241799_7401_2012B00001_2025_K00001",
                "CA_781241799_7401_2012B00001_2025_K00002",
            ],
            "Bilans_PDF/2025/01/01/CA_781241799_7401_2012B00001_2024_K00001": [
                "CA_781241799_7401_2012B00001_2024_K00001.pdf"
            ],
            "Bilans_PDF/2025/01/01/CA_781241799_7401_2012B00001_2025_K00001": [
                "CA_781241799_7401_2012B00001_2025_K00001.pdf"
            ],
            "Bilans_PDF/2025/01/01/CA_781241799_7401_2012B00001_2025_K00002": [
                "CA_781241799_7401_2012B00001_2025_K00002.pdf"
            ],
            "Bilans_PDF/2024": ["01"],
            "Bilans_PDF/2024/01": ["01"],
            "Bilans_PDF/2024/01/01": [
                "CA_781241799_7401_2012B00001_2026_K99999"
            ],
            "Bilans_PDF/2024/01/01/CA_781241799_7401_2012B00001_2026_K99999": [
                "CA_781241799_7401_2012B00001_2026_K99999.pdf"
            ],
        }

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return None

    def list_entries(self, remote_path: str = "."):
        return [
            SimpleNamespace(
                filename=name,
                st_mode=(
                    stat.S_IFDIR
                    if f"{remote_path}/{name}" in self.entries
                    else stat.S_IFREG
                ),
            )
            for name in self.entries[remote_path]
        ]

    def read_binary_file(self, remote_path: str, max_bytes: int = 50_000_000):
        return b"pdf-content"


class InitFinancialDocumentsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db.close()
        self.addCleanup(self.cleanup_temp_db)

    def cleanup_temp_db(self) -> None:
        if os.path.exists(self.temp_db.name):
            os.unlink(self.temp_db.name)

    def create_companies(self, sirets: list[str] | None = None) -> None:
        if sirets is None:
            sirets = ["78124179900012"]

        conn = sqlite3.connect(self.temp_db.name)
        try:
            conn.execute("CREATE TABLE companies (siret TEXT)")
            conn.executemany(
                "INSERT INTO companies (siret) VALUES (?)",
                [(siret,) for siret in sirets],
            )
            conn.commit()
        finally:
            conn.close()

    def test_validate_siren_accepts_exactly_nine_digits(self) -> None:
        self.assertEqual("781241799", init_documents.validate_siren("781241799"))

        invalid_values = ["", "78124179", "7812417990", "78124179A"]
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(argparse.ArgumentTypeError):
                    init_documents.validate_siren(value)

    def test_find_latest_ca_pdf_for_siren_stops_at_latest_matching_year(self) -> None:
        fake_sftp = FakeSFTPClient()

        with patch.object(
            init_documents.InpiSFTPClient,
            "from_environment",
            return_value=fake_sftp,
        ):
            path, stats = init_documents.find_latest_ca_pdf_for_siren("781241799")

        self.assertEqual(
            (
                "Bilans_PDF/2025/01/01/"
                "CA_781241799_7401_2012B00001_2025_K00002/"
                "CA_781241799_7401_2012B00001_2025_K00002.pdf"
            ),
            path,
        )
        self.assertEqual(2, stats.years_inspected)
        self.assertGreater(stats.files_examined, 0)
        self.assertGreaterEqual(stats.duration_seconds, 0)

    def test_find_latest_ca_pdf_returns_none_when_no_pdf_exists(self) -> None:
        fake_sftp = FakeSFTPClient()

        with patch.object(
            init_documents.InpiSFTPClient,
            "from_environment",
            return_value=fake_sftp,
        ):
            path, stats = init_documents.find_latest_ca_pdf_for_siren("000000000")

        self.assertIsNone(path)
        self.assertEqual(3, stats.years_inspected)
        self.assertGreater(stats.files_examined, 0)

    def test_select_latest_ca_pdf_prefers_latest_closing_then_chrono(self) -> None:
        paths = [
            (
                "Bilans_PDF/2025/01/01/"
                "CA_781241799_7401_2012B00001_2025_K00001/"
                "CA_781241799_7401_2012B00001_2025_K00001.pdf"
            ),
            (
                "Bilans_PDF/2025/01/01/"
                "CA_781241799_7401_2012B00001_2024_K99999/"
                "CA_781241799_7401_2012B00001_2024_K99999.pdf"
            ),
            (
                "Bilans_PDF/2025/01/01/"
                "CA_781241799_7401_2012B00001_2025_K00002/"
                "CA_781241799_7401_2012B00001_2025_K00002.pdf"
            ),
        ]

        selected_path = init_documents.select_latest_ca_pdf(paths, "781241799")

        self.assertTrue(selected_path.endswith("2025_K00002.pdf"))

    def test_process_latest_pdf_for_siren_inserts_financial_document(self) -> None:
        self.create_companies()
        fake_sftp = FakeSFTPClient()

        with patch.object(
            init_documents,
            "DATABASE_FILE",
            self.temp_db.name,
        ), patch.object(
            init_documents.InpiSFTPClient,
            "from_environment",
            return_value=fake_sftp,
        ), patch(
            "import_financial_documents.extract_text_from_pdf_bytes",
            return_value="CHIFFRES D'AFFAIRES NETS 98 765",
        ):
            summary = init_documents.process_latest_pdf_for_siren("781241799")

        conn = sqlite3.connect(self.temp_db.name)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                """
                SELECT siren, siret, closing_date, revenue, document_type, source
                FROM financial_documents
                """
            ).fetchone()
        finally:
            conn.close()

        self.assertEqual("781241799", summary["siren"])
        self.assertEqual("2025", summary["closing_date"])
        self.assertEqual("inserted", summary["status"])
        self.assertEqual("98765", str(summary["revenue"]))
        self.assertEqual(2, summary["years_inspected"])
        self.assertGreater(summary["files_examined"], 0)
        self.assertEqual("781241799", row["siren"])
        self.assertEqual("78124179900012", row["siret"])
        self.assertEqual("2025", row["closing_date"])
        self.assertEqual("98765", str(row["revenue"]))
        self.assertEqual("comptes_annuels_pdf", row["document_type"])
        self.assertEqual("inpi_sftp", row["source"])

    def test_targeted_mode_does_not_update_other_companies(self) -> None:
        self.create_companies(["78124179900012", "99999999900012"])
        conn = sqlite3.connect(self.temp_db.name)
        try:
            init_documents.create_financial_documents_table(conn)
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

        fake_sftp = FakeSFTPClient()
        with patch.object(
            init_documents,
            "DATABASE_FILE",
            self.temp_db.name,
        ), patch.object(
            init_documents.InpiSFTPClient,
            "from_environment",
            return_value=fake_sftp,
        ), patch(
            "import_financial_documents.extract_text_from_pdf_bytes",
            return_value="CHIFFRES D'AFFAIRES NETS 98 765",
        ):
            init_documents.process_latest_pdf_for_siren("781241799")

        conn = sqlite3.connect(self.temp_db.name)
        conn.row_factory = sqlite3.Row
        try:
            other_company_row = conn.execute(
                """
                SELECT revenue
                FROM financial_documents
                WHERE siren = ?
                """,
                ("999999999",),
            ).fetchone()
            total_count = conn.execute(
                "SELECT COUNT(*) FROM financial_documents"
            ).fetchone()[0]
        finally:
            conn.close()

        self.assertEqual("42", str(other_company_row["revenue"]))
        self.assertEqual(2, total_count)


if __name__ == "__main__":
    unittest.main()
