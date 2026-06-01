import stat
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


class InitFinancialDocumentsTest(unittest.TestCase):
    def test_find_latest_ca_pdf_for_siren_stops_at_latest_matching_year(self) -> None:
        fake_sftp = FakeSFTPClient()

        with patch.object(
            init_documents.InpiSFTPClient,
            "from_environment",
            return_value=fake_sftp,
        ):
            path = init_documents.find_latest_ca_pdf_for_siren("781241799")

        self.assertEqual(
            (
                "Bilans_PDF/2025/01/01/"
                "CA_781241799_7401_2012B00001_2025_K00002/"
                "CA_781241799_7401_2012B00001_2025_K00002.pdf"
            ),
            path,
        )


if __name__ == "__main__":
    unittest.main()
