import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from services.inpi_sftp import (
    InpiSFTPClient,
    download_latest_financial_pdf_for_siren,
    find_latest_financial_pdf_path_for_siren,
    select_latest_financial_pdf_filename,
    validate_siren,
)


class FakeRawSFTP:
    def __init__(self, entries: dict[str, list[str]]) -> None:
        self.entries = entries
        self.downloads: list[tuple[str, str]] = []

    def listdir_attr(self, remote_path: str):
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

    def get(self, remote_path: str, local_path: str) -> None:
        self.downloads.append((remote_path, local_path))
        Path(local_path).write_bytes(b"%PDF-1.4")

    def close(self) -> None:
        return None


def make_entries() -> dict[str, list[str]]:
    return {
        "Bilans_PDF": ["2024", "2025", "2026"],
        "Bilans_PDF/2026": ["06"],
        "Bilans_PDF/2026/06": ["01"],
        "Bilans_PDF/2026/06/01": [
            "CA_999999999_7401_2012B00001_2025_K00001.pdf"
        ],
        "Bilans_PDF/2025": ["12"],
        "Bilans_PDF/2025/12": ["31"],
        "Bilans_PDF/2025/12/31": [
            "CA_123456789_7401_2012B00001_2024_K99999.pdf",
            "CA_123456789_7401_2012B00001_2025_K00001.pdf",
            "CA_123456789_7401_2012B00001_2025_K00003.pdf",
        ],
        "Bilans_PDF/2024": ["12"],
        "Bilans_PDF/2024/12": ["31"],
        "Bilans_PDF/2024/12/31": [
            "CA_123456789_7401_2012B00001_2026_K99999.pdf"
        ],
    }


def make_client(entries: dict[str, list[str]]) -> InpiSFTPClient:
    client = InpiSFTPClient("sftp.example.test", "user", "password")
    client._sftp = FakeRawSFTP(entries)
    return client


class InpiSFTPDownloadTest(unittest.TestCase):
    def test_validate_siren_requires_exactly_nine_digits(self) -> None:
        validate_siren("123456789")

        for value in ("12345678", "1234567890", "abcdefghi"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_siren(value)

    def test_selects_latest_financial_pdf_filename_by_closing_year(self) -> None:
        selected = select_latest_financial_pdf_filename(
            [
                "CA_123456789_7401_2012B00001_2023_K99999.pdf",
                "CA_123456789_7401_2012B00001_2025_K00001.pdf",
                "CA_123456789_7401_2012B00001_2024_K99999.pdf",
            ]
        )

        self.assertEqual(
            "CA_123456789_7401_2012B00001_2025_K00001.pdf",
            selected,
        )

    def test_selects_latest_financial_pdf_filename_by_chrono(self) -> None:
        selected = select_latest_financial_pdf_filename(
            [
                "CA_123456789_7401_2012B00001_2025_K00001.pdf",
                "CA_123456789_7401_2012B00001_2025_K00011.pdf",
                "CA_123456789_7401_2012B00001_2025_K00002.pdf",
            ]
        )

        self.assertEqual(
            "CA_123456789_7401_2012B00001_2025_K00011.pdf",
            selected,
        )

    def test_select_latest_financial_pdf_filename_ignores_invalid_names(self) -> None:
        selected = select_latest_financial_pdf_filename(
            [
                "not-a-financial-document.pdf",
                "CA_12345678_7401_2012B00001_2026_K99999.pdf",
                "CA_123456789_7401_2012B00001_2025_K00001.pdf",
            ]
        )

        self.assertEqual(
            "CA_123456789_7401_2012B00001_2025_K00001.pdf",
            selected,
        )

    def test_select_latest_financial_pdf_filename_returns_none_without_valid_file(
        self,
    ) -> None:
        selected = select_latest_financial_pdf_filename(
            ["not-a-financial-document.pdf"]
        )

        self.assertIsNone(selected)

    def test_finds_latest_financial_pdf_for_siren(self) -> None:
        client = make_client(make_entries())

        selected_path = find_latest_financial_pdf_path_for_siren(client, "123456789")

        self.assertEqual(
            "Bilans_PDF/2025/12/31/CA_123456789_7401_2012B00001_2025_K00003.pdf",
            selected_path,
        )

    def test_returns_none_when_no_financial_pdf_exists(self) -> None:
        client = make_client(make_entries())

        self.assertIsNone(
            find_latest_financial_pdf_path_for_siren(client, "111111111")
        )

    def test_downloads_latest_financial_pdf_to_destination(self) -> None:
        client = make_client(make_entries())

        with tempfile.TemporaryDirectory() as temp_dir:
            local_path = client.download_latest_financial_pdf_for_siren(
                "123456789",
                Path(temp_dir),
            )

            self.assertIsNotNone(local_path)
            assert local_path is not None
            self.assertTrue(local_path.exists())
            self.assertEqual(
                "CA_123456789_7401_2012B00001_2025_K00003.pdf",
                local_path.name,
            )

    def test_service_function_opens_connection_from_environment(self) -> None:
        client = make_client(make_entries())
        client.connect = lambda: None

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(
                InpiSFTPClient,
                "from_environment",
                return_value=client,
            ):
                local_path = download_latest_financial_pdf_for_siren(
                    "123456789",
                    Path(temp_dir),
                )

            self.assertIsNotNone(local_path)


if __name__ == "__main__":
    unittest.main()
