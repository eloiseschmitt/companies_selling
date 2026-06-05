import io
import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import services.inpi_sftp as inpi_sftp
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
        self.opens: list[str] = []

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

    def open(self, remote_path: str, mode: str = "r"):
        self.opens.append(remote_path)
        raise AssertionError(f"Le PDF ne doit pas être ouvert en mode {mode}.")

    def close(self) -> None:
        return None


def make_entries() -> dict[str, list[str]]:
    return {
        "Bilans_PDF": ["2024", "2025", "2026"],
        "Bilans_PDF/2026": ["06"],
        "Bilans_PDF/2026/06": ["01"],
        "Bilans_PDF/2026/06/01": ["CA_999999999_7401_2012B00001_2025_K00001.pdf"],
        "Bilans_PDF/2025": ["12"],
        "Bilans_PDF/2025/12": ["31"],
        "Bilans_PDF/2025/12/31": [
            "CA_123456789_7401_2012B00001_2024_K99999.pdf",
            "CA_123456789_7401_2012B00001_2025_K00001.pdf",
            "CA_123456789_7401_2012B00001_2025_K00003.pdf",
        ],
        "Bilans_PDF/2024": ["12"],
        "Bilans_PDF/2024/12": ["31"],
        "Bilans_PDF/2024/12/31": ["CA_123456789_7401_2012B00001_2026_K99999.pdf"],
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

        self.assertIsNone(find_latest_financial_pdf_path_for_siren(client, "111111111"))

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

    def test_download_does_not_write_database_or_parse_pdf(self) -> None:
        client = make_client(make_entries())

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch(
                "sqlite3.connect",
                side_effect=AssertionError("La base ne doit pas être ouverte."),
            ),
            patch.object(
                client,
                "read_binary_file",
                side_effect=AssertionError("Le PDF ne doit pas être lu."),
            ),
            patch.object(
                client,
                "read_text_file",
                side_effect=AssertionError("Le PDF ne doit pas être parsé."),
            ),
        ):
            local_path = client.download_latest_financial_pdf_for_siren(
                "123456789",
                Path(temp_dir),
            )

        self.assertIsNotNone(local_path)
        assert client._sftp is not None
        self.assertEqual([], client._sftp.opens)
        self.assertEqual(1, len(client._sftp.downloads))

    def test_does_not_redownload_existing_pdf_without_force(self) -> None:
        client = make_client(make_entries())

        with tempfile.TemporaryDirectory() as temp_dir:
            local_path = Path(temp_dir) / "CA_123456789_7401_2012B00001_2025_K00003.pdf"
            local_path.write_bytes(b"existing")

            downloaded_path = client.download_latest_financial_pdf_for_siren(
                "123456789",
                Path(temp_dir),
            )

            self.assertEqual(local_path, downloaded_path)
            self.assertEqual(b"existing", local_path.read_bytes())
            assert client._sftp is not None
            self.assertEqual([], client._sftp.downloads)

    def test_redownloads_existing_pdf_with_force(self) -> None:
        client = make_client(make_entries())

        with tempfile.TemporaryDirectory() as temp_dir:
            local_path = Path(temp_dir) / "CA_123456789_7401_2012B00001_2025_K00003.pdf"
            local_path.write_bytes(b"existing")

            downloaded_path = client.download_latest_financial_pdf_for_siren(
                "123456789",
                Path(temp_dir),
                force=True,
            )

            self.assertEqual(local_path, downloaded_path)
            self.assertEqual(b"%PDF-1.4", local_path.read_bytes())
            assert client._sftp is not None
            self.assertEqual(1, len(client._sftp.downloads))

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
                    force=True,
                )

            self.assertIsNotNone(local_path)

    def test_cli_requires_siren(self) -> None:
        with patch("sys.argv", ["inpi_sftp.py"]), patch("sys.stderr", io.StringIO()):
            with self.assertRaises(SystemExit):
                inpi_sftp.parse_args()

    def test_cli_rejects_invalid_siren(self) -> None:
        with (
            patch(
                "sys.argv",
                ["inpi_sftp.py", "--siren", "123"],
            ),
            patch("sys.stderr", io.StringIO()),
        ):
            with self.assertRaises(SystemExit):
                inpi_sftp.parse_args()

    def test_cli_downloads_pdf_to_default_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            expected_path = Path("downloads") / "annual.pdf"

            def fake_download(
                siren: str,
                destination_dir: Path,
                force: bool = False,
            ) -> Path:
                self.assertEqual("123456789", siren)
                self.assertEqual(Path("downloads"), destination_dir)
                self.assertFalse(force)
                self.assertTrue(destination_dir.exists())
                return expected_path

            original_cwd = os.getcwd()
            try:
                os.chdir(temp_dir)
                with (
                    patch(
                        "sys.argv",
                        ["inpi_sftp.py", "--siren", "123456789"],
                    ),
                    patch(
                        "services.inpi_sftp.download_latest_financial_pdf_for_siren",
                        side_effect=fake_download,
                    ),
                    patch("builtins.print") as print_mock,
                ):
                    inpi_sftp.main()
            finally:
                os.chdir(original_cwd)

            print_mock.assert_called_once_with(f"PDF téléchargé: {expected_path}")

    def test_cli_downloads_pdf_to_custom_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "custom-downloads"
            expected_path = destination / "annual.pdf"

            def fake_download(
                siren: str,
                destination_dir: Path,
                force: bool = False,
            ) -> Path:
                self.assertEqual("123456789", siren)
                self.assertEqual(destination, destination_dir)
                self.assertFalse(force)
                self.assertTrue(destination_dir.exists())
                return expected_path

            with (
                patch(
                    "sys.argv",
                    [
                        "inpi_sftp.py",
                        "--siren",
                        "123456789",
                        "--destination",
                        str(destination),
                    ],
                ),
                patch(
                    "services.inpi_sftp.download_latest_financial_pdf_for_siren",
                    side_effect=fake_download,
                ),
                patch("builtins.print") as print_mock,
            ):
                inpi_sftp.main()

            print_mock.assert_called_once_with(f"PDF téléchargé: {expected_path}")

    def test_cli_passes_force_option(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "downloads"
            expected_path = destination / "annual.pdf"

            def fake_download(
                siren: str,
                destination_dir: Path,
                force: bool = False,
            ) -> Path:
                self.assertEqual("123456789", siren)
                self.assertEqual(destination, destination_dir)
                self.assertTrue(force)
                return expected_path

            with (
                patch(
                    "sys.argv",
                    [
                        "inpi_sftp.py",
                        "--siren",
                        "123456789",
                        "--destination",
                        str(destination),
                        "--force",
                    ],
                ),
                patch(
                    "services.inpi_sftp.download_latest_financial_pdf_for_siren",
                    side_effect=fake_download,
                ),
                patch("builtins.print") as print_mock,
            ):
                inpi_sftp.main()

            print_mock.assert_called_once_with(f"PDF téléchargé: {expected_path}")

    def test_cli_prints_clear_message_when_no_pdf_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "downloads"

            with (
                patch(
                    "sys.argv",
                    [
                        "inpi_sftp.py",
                        "--siren",
                        "123456789",
                        "--destination",
                        str(destination),
                    ],
                ),
                patch(
                    "services.inpi_sftp.download_latest_financial_pdf_for_siren",
                    return_value=None,
                ),
                patch("builtins.print") as print_mock,
            ):
                inpi_sftp.main()

            self.assertTrue(destination.exists())
            print_mock.assert_called_once_with(
                "Aucun PDF de comptes annuels trouvé pour le SIREN 123456789."
            )


if __name__ == "__main__":
    unittest.main()
