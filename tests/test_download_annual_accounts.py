import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import download_annual_accounts as downloader


class FakeInpiAnnualAccountsClient:
    def __init__(self, attachments_by_siren, errors_by_siren=None) -> None:
        self.attachments_by_siren = attachments_by_siren
        self.errors_by_siren = errors_by_siren or {}
        self.attachments_calls: list[str] = []
        self.downloads: list[tuple[str, Path]] = []

    def get_company_attachments(self, siren: str):
        self.attachments_calls.append(siren)
        if siren in self.errors_by_siren:
            raise self.errors_by_siren[siren]
        return self.attachments_by_siren[siren]

    def download_bilan_pdf(self, bilan_id: str, output_path: Path) -> Path:
        self.downloads.append((bilan_id, output_path))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"%PDF-1.4\ncontent")
        return output_path


def read_result_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as csv_file:
        return list(csv.DictReader(csv_file))


class DownloadAnnualAccountsTest(unittest.TestCase):
    def test_read_sirens_requires_siren_column(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "input.csv"
            input_path.write_text("name\nExample\n", encoding="utf-8")

            with self.assertRaises(ValueError):
                downloader.read_sirens(input_path)

    def test_downloads_latest_public_bilan_and_writes_result_row(self) -> None:
        client = FakeInpiAnnualAccountsClient(
            {
                "123456789": {
                    "bilans": [
                        {
                            "id": "old",
                            "confidentiality": "Public",
                            "deleted": False,
                            "dateCloture": "2023-12-31",
                            "dateDepot": "2024-04-01",
                            "typeBilan": "C",
                        },
                        {
                            "id": "latest",
                            "confidentiality": "Public",
                            "deleted": False,
                            "dateCloture": "2024-12-31",
                            "dateDepot": "2025-04-01",
                            "typeBilan": "C",
                        },
                    ]
                }
            }
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / "input.csv"
            output_dir = temp_path / "downloads"
            results_path = temp_path / "results.csv"
            input_path.write_text("siren\n123456789\n", encoding="utf-8")

            downloader.download_annual_accounts(
                input_path,
                output_dir=output_dir,
                results_path=results_path,
                sleep_seconds=0,
                client=client,
            )

            rows = read_result_rows(results_path)

        self.assertEqual(1, len(rows))
        self.assertEqual("downloaded", rows[0]["status"])
        self.assertEqual("latest", rows[0]["bilan_id"])
        self.assertEqual("2024-12-31", rows[0]["date_cloture"])
        self.assertEqual("2025-04-01", rows[0]["date_depot"])
        self.assertEqual("Public", rows[0]["confidentiality"])
        self.assertEqual("C", rows[0]["type_bilan"])
        self.assertEqual("latest.pdf", rows[0]["filename"])
        self.assertEqual(
            [("latest", output_dir / "123456789" / "latest.pdf")],
            client.downloads,
        )

    def test_writes_not_found_confidential_and_deleted_statuses(self) -> None:
        client = FakeInpiAnnualAccountsClient(
            {
                "111111111": {"bilans": []},
                "222222222": {
                    "bilans": [
                        {
                            "id": "confidential",
                            "confidentiality": "Confidentiel",
                            "deleted": False,
                        }
                    ]
                },
                "333333333": {
                    "bilans": [
                        {
                            "id": "deleted",
                            "confidentiality": "Public",
                            "deleted": True,
                        }
                    ]
                },
            }
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / "input.csv"
            results_path = temp_path / "results.csv"
            input_path.write_text(
                "siren\n111111111\n222222222\n333333333\n",
                encoding="utf-8",
            )

            downloader.download_annual_accounts(
                input_path,
                output_dir=temp_path / "downloads",
                results_path=results_path,
                sleep_seconds=0,
                client=client,
            )
            rows = read_result_rows(results_path)

        self.assertEqual(
            ["not_found", "confidential", "deleted_only"],
            [row["status"] for row in rows],
        )
        self.assertEqual([], client.downloads)

    def test_continues_when_one_siren_fails(self) -> None:
        client = FakeInpiAnnualAccountsClient(
            {
                "222222222": {
                    "bilans": [
                        {
                            "id": "ok",
                            "confidentiality": "Public",
                            "deleted": False,
                            "dateDepot": "2025-01-01",
                        }
                    ]
                }
            },
            errors_by_siren={"111111111": RuntimeError("boom")},
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / "input.csv"
            results_path = temp_path / "results.csv"
            input_path.write_text("siren\n111111111\n222222222\n", encoding="utf-8")

            with patch.object(downloader.logger, "error"):
                downloader.download_annual_accounts(
                    input_path,
                    output_dir=temp_path / "downloads",
                    results_path=results_path,
                    sleep_seconds=0,
                    client=client,
                )
            rows = read_result_rows(results_path)

        self.assertEqual("error", rows[0]["status"])
        self.assertEqual("boom", rows[0]["message"])
        self.assertEqual("downloaded", rows[1]["status"])
        self.assertEqual(
            [("ok", temp_path / "downloads" / "222222222" / "ok.pdf")],
            client.downloads,
        )

    def test_sleeps_between_sirens(self) -> None:
        client = FakeInpiAnnualAccountsClient(
            {
                "111111111": {"bilans": []},
                "222222222": {"bilans": []},
            }
        )

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "download_annual_accounts.time.sleep"
        ) as sleep_mock:
            temp_path = Path(temp_dir)
            input_path = temp_path / "input.csv"
            input_path.write_text("siren\n111111111\n222222222\n", encoding="utf-8")

            downloader.download_annual_accounts(
                input_path,
                output_dir=temp_path / "downloads",
                results_path=temp_path / "results.csv",
                sleep_seconds=0.5,
                client=client,
            )

        sleep_mock.assert_called_once_with(0.5)

    def test_resume_skips_final_statuses_and_retries_errors(self) -> None:
        client = FakeInpiAnnualAccountsClient(
            {
                "222222222": {
                    "bilans": [
                        {
                            "id": "retry",
                            "confidentiality": "Public",
                            "deleted": False,
                            "dateDepot": "2025-01-01",
                        }
                    ]
                },
                "333333333": {"bilans": []},
            }
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / "input.csv"
            results_path = temp_path / "results.csv"
            input_path.write_text(
                "siren\n111111111\n222222222\n333333333\n",
                encoding="utf-8",
            )
            results_path.write_text(
                "siren,status,bilan_id,date_cloture,date_depot,"
                "confidentiality,type_bilan,filename,message\n"
                "111111111,downloaded,done,,,,,done.pdf,\n"
                "222222222,error,,,,,,,previous failure\n",
                encoding="utf-8",
            )

            downloader.download_annual_accounts(
                input_path,
                output_dir=temp_path / "downloads",
                results_path=results_path,
                sleep_seconds=0,
                client=client,
            )
            rows = read_result_rows(results_path)

        self.assertEqual(
            ["downloaded", "downloaded", "not_found"],
            [row["status"] for row in rows],
        )
        self.assertEqual(["222222222", "333333333"], client.attachments_calls)

    def test_force_reprocesses_final_statuses(self) -> None:
        client = FakeInpiAnnualAccountsClient(
            {
                "111111111": {
                    "bilans": [
                        {
                            "id": "new",
                            "confidentiality": "Public",
                            "deleted": False,
                            "dateDepot": "2025-01-01",
                        }
                    ]
                }
            }
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / "input.csv"
            results_path = temp_path / "results.csv"
            input_path.write_text("siren\n111111111\n", encoding="utf-8")
            results_path.write_text(
                "siren,status,bilan_id,date_cloture,date_depot,"
                "confidentiality,type_bilan,filename,message\n"
                "111111111,downloaded,old,,,,,old.pdf,\n",
                encoding="utf-8",
            )

            downloader.download_annual_accounts(
                input_path,
                output_dir=temp_path / "downloads",
                results_path=results_path,
                sleep_seconds=0,
                force=True,
                client=client,
            )
            rows = read_result_rows(results_path)

        self.assertEqual("new", rows[0]["bilan_id"])
        self.assertEqual(["111111111"], client.attachments_calls)

    def test_does_not_redownload_existing_non_empty_pdf(self) -> None:
        client = FakeInpiAnnualAccountsClient(
            {
                "123456789": {
                    "bilans": [
                        {
                            "id": "existing",
                            "confidentiality": "Public",
                            "deleted": False,
                            "dateDepot": "2025-01-01",
                        }
                    ]
                }
            }
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / "input.csv"
            output_dir = temp_path / "downloads"
            results_path = temp_path / "results.csv"
            existing_pdf = output_dir / "123456789" / "existing.pdf"
            existing_pdf.parent.mkdir(parents=True)
            existing_pdf.write_bytes(b"%PDF already here")
            input_path.write_text("siren\n123456789\n", encoding="utf-8")

            downloader.download_annual_accounts(
                input_path,
                output_dir=output_dir,
                results_path=results_path,
                sleep_seconds=0,
                client=client,
            )
            rows = read_result_rows(results_path)

        self.assertEqual("downloaded", rows[0]["status"])
        self.assertEqual("existing.pdf", rows[0]["filename"])
        self.assertEqual([], client.downloads)


if __name__ == "__main__":
    unittest.main()
