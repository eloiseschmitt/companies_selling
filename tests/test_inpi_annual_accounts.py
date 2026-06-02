import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from services.inpi_annual_accounts import (
    API_BASE_URL,
    LOGIN_URL,
    HTTP_ERROR_MESSAGES,
    InpiAnnualAccountsClient,
    InpiApiError,
    InpiAuthenticationError,
    InpiDownloadError,
    MissingInpiCredentialsError,
    select_best_bilan_pdf,
)


def make_response(status_code: int = 200, payload=None, text: str = ""):
    response = Mock()
    response.status_code = status_code
    response.text = text
    response.json.return_value = payload if payload is not None else {}
    response.content = b""
    return response


class InpiAnnualAccountsClientTest(unittest.TestCase):
    def test_authenticate_posts_credentials_and_stores_token(self) -> None:
        session = Mock()
        session.post.return_value = make_response(payload={"token": "abc-token"})
        client = InpiAnnualAccountsClient(session=session)

        with patch.dict(
            os.environ,
            {"SFTP_USER": "demo-user", "SFTP_PASSWORD": "demo-password"},
            clear=False,
        ):
            token = client.authenticate()

        self.assertEqual("abc-token", token)
        self.assertEqual("abc-token", client.token)
        session.post.assert_called_once_with(
            LOGIN_URL,
            json={"username": "demo-user", "password": "demo-password"},
            timeout=30,
        )

    def test_authenticate_requires_environment_credentials(self) -> None:
        session = Mock()
        client = InpiAnnualAccountsClient(session=session)

        with patch(
            "services.inpi_annual_accounts.load_dotenv",
            return_value=None,
        ), patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(MissingInpiCredentialsError):
                client.authenticate()

        session.post.assert_not_called()

    def test_authenticate_requires_token_in_response(self) -> None:
        session = Mock()
        session.post.return_value = make_response(payload={})
        client = InpiAnnualAccountsClient(session=session)

        with patch.dict(
            os.environ,
            {"SFTP_USER": "demo-user", "SFTP_PASSWORD": "demo-password"},
            clear=True,
        ):
            with self.assertRaises(InpiAuthenticationError):
                client.authenticate()

    def test_get_company_attachments_uses_bearer_token(self) -> None:
        session = Mock()
        session.get.return_value = make_response(payload={"attachments": []})
        client = InpiAnnualAccountsClient(session=session)
        client.token = "abc-token"

        attachments = client.get_company_attachments("123456789")

        self.assertEqual({"attachments": []}, attachments)
        session.get.assert_called_once_with(
            f"{API_BASE_URL}/companies/123456789/attachments",
            headers={"Authorization": "Bearer abc-token"},
            timeout=30,
        )

    def test_get_company_attachments_authenticates_when_needed(self) -> None:
        session = Mock()
        session.post.return_value = make_response(payload={"token": "abc-token"})
        session.get.return_value = make_response(payload=[{"id": "attachment-1"}])
        client = InpiAnnualAccountsClient(session=session)

        with patch.dict(
            os.environ,
            {"SFTP_USER": "demo-user", "SFTP_PASSWORD": "demo-password"},
            clear=True,
        ):
            attachments = client.get_company_attachments("123456789")

        self.assertEqual([{"id": "attachment-1"}], attachments)
        session.get.assert_called_once_with(
            f"{API_BASE_URL}/companies/123456789/attachments",
            headers={"Authorization": "Bearer abc-token"},
            timeout=30,
        )

    def test_get_company_attachments_rejects_invalid_siren(self) -> None:
        client = InpiAnnualAccountsClient(session=Mock())

        with self.assertRaises(ValueError):
            client.get_company_attachments("123")

    def test_known_http_errors_raise_clear_exception(self) -> None:
        for status_code in (400, 401, 403, 429, 500):
            with self.subTest(status_code=status_code):
                session = Mock()
                session.get.return_value = make_response(
                    status_code=status_code,
                    payload={"error": "failed"},
                    text="failed",
                )
                client = InpiAnnualAccountsClient(session=session)
                client.token = "abc-token"

                with self.assertRaises(InpiApiError) as raised:
                    client.get_company_attachments("123456789")

                self.assertEqual(status_code, raised.exception.status_code)
                self.assertEqual(
                    HTTP_ERROR_MESSAGES[status_code],
                    str(raised.exception),
                )

    def test_invalid_json_response_raises_api_error(self) -> None:
        response = make_response(status_code=200)
        response.json.side_effect = ValueError("not json")
        session = Mock()
        session.get.return_value = response
        client = InpiAnnualAccountsClient(session=session)
        client.token = "abc-token"

        with self.assertRaises(InpiApiError) as raised:
            client.get_company_attachments("123456789")

        self.assertEqual(200, raised.exception.status_code)

    def test_download_bilan_pdf_writes_binary_response(self) -> None:
        response = make_response()
        response.content = b"%PDF-1.4\ncontent"
        session = Mock()
        session.get.return_value = response
        client = InpiAnnualAccountsClient(session=session)
        client.token = "abc-token"

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "nested" / "bilan.pdf"

            downloaded_path = client.download_bilan_pdf("bilan-123", output_path)

            self.assertEqual(output_path, downloaded_path)
            self.assertEqual(b"%PDF-1.4\ncontent", output_path.read_bytes())

        session.get.assert_called_once_with(
            f"{API_BASE_URL}/bilans/bilan-123/download",
            headers={"Authorization": "Bearer abc-token"},
            timeout=30,
        )

    def test_download_bilan_pdf_authenticates_when_needed(self) -> None:
        login_response = make_response(payload={"token": "abc-token"})
        download_response = make_response()
        download_response.content = b"%PDF-1.4\ncontent"
        session = Mock()
        session.post.return_value = login_response
        session.get.return_value = download_response
        client = InpiAnnualAccountsClient(session=session)

        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"SFTP_USER": "demo-user", "SFTP_PASSWORD": "demo-password"},
            clear=True,
        ):
            output_path = Path(temp_dir) / "bilan.pdf"

            downloaded_path = client.download_bilan_pdf("bilan-123", output_path)

            self.assertEqual(output_path, downloaded_path)

        session.post.assert_called_once()
        session.get.assert_called_once_with(
            f"{API_BASE_URL}/bilans/bilan-123/download",
            headers={"Authorization": "Bearer abc-token"},
            timeout=30,
        )

    def test_download_bilan_pdf_rejects_empty_content(self) -> None:
        response = make_response()
        response.content = b""
        session = Mock()
        session.get.return_value = response
        client = InpiAnnualAccountsClient(session=session)
        client.token = "abc-token"

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "bilan.pdf"

            with self.assertRaises(InpiDownloadError):
                client.download_bilan_pdf("bilan-123", output_path)

            self.assertFalse(output_path.exists())

    def test_download_bilan_pdf_rejects_non_pdf_content(self) -> None:
        response = make_response()
        response.content = b"not a pdf"
        session = Mock()
        session.get.return_value = response
        client = InpiAnnualAccountsClient(session=session)
        client.token = "abc-token"

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "bilan.pdf"

            with self.assertRaises(InpiDownloadError):
                client.download_bilan_pdf("bilan-123", output_path)

            self.assertFalse(output_path.exists())

    def test_download_bilan_pdf_raises_api_error_before_writing_file(self) -> None:
        response = make_response(status_code=403, text="forbidden")
        response.content = b"%PDF-1.4\ncontent"
        session = Mock()
        session.get.return_value = response
        client = InpiAnnualAccountsClient(session=session)
        client.token = "abc-token"

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "bilan.pdf"

            with self.assertRaises(InpiApiError) as raised:
                client.download_bilan_pdf("bilan-123", output_path)

            self.assertEqual(403, raised.exception.status_code)
            self.assertFalse(output_path.exists())


class SelectBestBilanPdfTest(unittest.TestCase):
    def test_selects_latest_public_bilan_by_closing_date(self) -> None:
        selected, reason = select_best_bilan_pdf(
            {
                "bilans": [
                    {
                        "id": "old",
                        "confidentiality": "Public",
                        "deleted": False,
                        "dateCloture": "2023-12-31",
                        "dateDepot": "2024-04-20",
                    },
                    {
                        "id": "latest",
                        "confidentiality": "Public",
                        "deleted": False,
                        "dateCloture": "2024-12-31",
                        "dateDepot": "2025-04-20",
                    },
                ]
            }
        )

        self.assertEqual("latest", selected["id"])
        self.assertIsNone(reason)

    def test_falls_back_to_deposit_date_when_closing_date_is_missing(self) -> None:
        selected, reason = select_best_bilan_pdf(
            {
                "bilans": [
                    {
                        "id": "old",
                        "confidentiality": "Public",
                        "deleted": False,
                        "dateDepot": "2024-01-10",
                    },
                    {
                        "id": "latest",
                        "confidentiality": "Public",
                        "deleted": False,
                        "dateDepot": "2024-03-10",
                    },
                ]
            }
        )

        self.assertEqual("latest", selected["id"])
        self.assertIsNone(reason)

    def test_ignores_deleted_bilans(self) -> None:
        selected, reason = select_best_bilan_pdf(
            {
                "bilans": [
                    {
                        "id": "deleted-latest",
                        "confidentiality": "Public",
                        "deleted": True,
                        "dateCloture": "2025-12-31",
                    },
                    {
                        "id": "public-active",
                        "confidentiality": "Public",
                        "deleted": False,
                        "dateCloture": "2024-12-31",
                    },
                ]
            }
        )

        self.assertEqual("public-active", selected["id"])
        self.assertIsNone(reason)

    def test_ignores_confidential_bilans(self) -> None:
        selected, reason = select_best_bilan_pdf(
            {
                "bilans": [
                    {
                        "id": "confidential-latest",
                        "confidentiality": "Confidentiel",
                        "deleted": False,
                        "dateCloture": "2025-12-31",
                    },
                    {
                        "id": "public",
                        "confidentiality": "Public",
                        "deleted": False,
                        "dateCloture": "2024-12-31",
                    },
                ]
            }
        )

        self.assertEqual("public", selected["id"])
        self.assertIsNone(reason)

    def test_returns_no_bilan_reason_when_no_bilan_exists(self) -> None:
        selected, reason = select_best_bilan_pdf({"bilans": []})

        self.assertIsNone(selected)
        self.assertEqual("no_bilan", reason)

    def test_returns_only_confidential_reason_without_public_bilan(self) -> None:
        selected, reason = select_best_bilan_pdf(
            {
                "bilans": [
                    {
                        "id": "confidential",
                        "confidentiality": "Confidentiel",
                        "deleted": False,
                    }
                ]
            }
        )

        self.assertIsNone(selected)
        self.assertEqual("only_confidential", reason)

    def test_returns_only_deleted_reason_when_all_bilans_are_deleted(self) -> None:
        selected, reason = select_best_bilan_pdf(
            {
                "bilans": [
                    {
                        "id": "deleted",
                        "confidentiality": "Public",
                        "deleted": True,
                    }
                ]
            }
        )

        self.assertIsNone(selected)
        self.assertEqual("only_deleted", reason)


if __name__ == "__main__":
    unittest.main()
