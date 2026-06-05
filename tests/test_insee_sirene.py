import os
import unittest
from unittest.mock import Mock, patch

import requests

from services.insee_sirene import (
    API_BASE_URL,
    API_KEY_HEADER,
    HTTP_ERROR_MESSAGES,
    InseeSireneApiError,
    InseeSireneClient,
    InseeSireneRequestError,
    MissingInseeApiKeyError,
)


def make_response(status_code: int = 200, payload=None, text: str = ""):
    response = Mock()
    response.status_code = status_code
    response.text = text
    response.json.return_value = payload if payload is not None else {}
    return response


class InseeSireneClientTest(unittest.TestCase):
    def test_get_siren_uses_api_key_header_from_environment(self) -> None:
        session = Mock()
        session.get.return_value = make_response(payload={"uniteLegale": {}})
        client = InseeSireneClient(session=session)

        with patch.dict(os.environ, {"INSEE_API_KEY": "secret-key"}, clear=True):
            payload = client.get_siren("123456789")

        self.assertEqual({"uniteLegale": {}}, payload)
        session.get.assert_called_once_with(
            f"{API_BASE_URL}/siren/123456789",
            headers={API_KEY_HEADER: "secret-key"},
            timeout=30,
        )

    def test_get_siret_uses_api_key_header_from_environment(self) -> None:
        session = Mock()
        session.get.return_value = make_response(payload={"etablissement": {}})
        client = InseeSireneClient(session=session)

        with patch.dict(os.environ, {"INSEE_API_KEY": "secret-key"}, clear=True):
            payload = client.get_siret("12345678900012")

        self.assertEqual({"etablissement": {}}, payload)
        session.get.assert_called_once_with(
            f"{API_BASE_URL}/siret/12345678900012",
            headers={API_KEY_HEADER: "secret-key"},
            timeout=30,
        )

    def test_requires_api_key_environment_variable(self) -> None:
        session = Mock()
        client = InseeSireneClient(session=session)

        with patch("services.insee_sirene.load_dotenv"), patch.dict(
            os.environ,
            {},
            clear=True,
        ):
            with self.assertRaises(MissingInseeApiKeyError):
                client.get_siren("123456789")

        session.get.assert_not_called()

    def test_rejects_invalid_siren_and_siret(self) -> None:
        client = InseeSireneClient(session=Mock())

        with self.assertRaises(ValueError):
            client.get_siren("123")
        with self.assertRaises(ValueError):
            client.get_siret("123456789")

    def test_http_errors_raise_clear_exception(self) -> None:
        for status_code in (400, 403, 404, 500):
            with self.subTest(status_code=status_code):
                session = Mock()
                session.get.return_value = make_response(
                    status_code=status_code,
                    text="secret-key should not be logged",
                )
                client = InseeSireneClient(session=session)

                with patch.dict(
                    os.environ,
                    {"INSEE_API_KEY": "secret-key"},
                    clear=True,
                ):
                    with self.assertRaises(InseeSireneApiError) as raised:
                        client.get_siren("123456789")

                self.assertEqual(status_code, raised.exception.status_code)
                self.assertIn(HTTP_ERROR_MESSAGES[status_code], str(raised.exception))
                self.assertIn(f"{API_BASE_URL}/siren/123456789", str(raised.exception))

    def test_429_retries_once_then_succeeds(self) -> None:
        session = Mock()
        session.get.side_effect = [
            make_response(status_code=429),
            make_response(payload={"uniteLegale": {"siren": "123456789"}}),
        ]
        client = InseeSireneClient(
            session=session,
            retry_attempts=2,
            retry_delay_seconds=0.25,
        )

        with patch.dict(
            os.environ,
            {"INSEE_API_KEY": "secret-key"},
            clear=True,
        ), patch("services.insee_sirene.time.sleep") as sleep_mock:
            payload = client.get_siren("123456789")

        self.assertEqual({"uniteLegale": {"siren": "123456789"}}, payload)
        self.assertEqual(2, session.get.call_count)
        sleep_mock.assert_called_once_with(0.25)

    def test_429_after_retry_raises_explicit_error(self) -> None:
        session = Mock()
        session.get.side_effect = [
            make_response(status_code=429),
            make_response(status_code=429),
        ]
        client = InseeSireneClient(
            session=session,
            retry_attempts=2,
            retry_delay_seconds=0,
        )

        with patch.dict(os.environ, {"INSEE_API_KEY": "secret-key"}, clear=True):
            with self.assertRaises(InseeSireneApiError) as raised:
                client.get_siren("123456789")

        self.assertEqual(429, raised.exception.status_code)
        self.assertIn(HTTP_ERROR_MESSAGES[429], str(raised.exception))

    def test_error_log_does_not_include_api_key_or_response_body(self) -> None:
        session = Mock()
        session.get.return_value = make_response(
            status_code=403,
            text="secret-key",
        )
        client = InseeSireneClient(session=session)

        with patch.dict(
            os.environ,
            {"INSEE_API_KEY": "secret-key"},
            clear=True,
        ), patch("services.insee_sirene.logger.error") as log_error:
            with self.assertRaises(InseeSireneApiError):
                client.get_siren("123456789")

        logged_text = " ".join(str(value) for value in log_error.call_args.args)
        self.assertNotIn("secret-key", logged_text)

    def test_request_exception_is_wrapped(self) -> None:
        session = Mock()
        session.get.side_effect = requests.Timeout("timeout")
        client = InseeSireneClient(session=session)

        with patch.dict(os.environ, {"INSEE_API_KEY": "secret-key"}, clear=True):
            with self.assertRaises(InseeSireneRequestError):
                client.get_siren("123456789")

    def test_invalid_json_response_raises_api_error(self) -> None:
        response = make_response()
        response.json.side_effect = ValueError("not json")
        session = Mock()
        session.get.return_value = response
        client = InseeSireneClient(session=session)

        with patch.dict(os.environ, {"INSEE_API_KEY": "secret-key"}, clear=True):
            with self.assertRaises(InseeSireneApiError) as raised:
                client.get_siret("12345678900012")

        self.assertEqual(200, raised.exception.status_code)

    def test_non_object_json_response_raises_api_error(self) -> None:
        session = Mock()
        session.get.return_value = make_response(payload=[])
        client = InseeSireneClient(session=session)

        with patch.dict(os.environ, {"INSEE_API_KEY": "secret-key"}, clear=True):
            with self.assertRaises(InseeSireneApiError):
                client.get_siren("123456789")


if __name__ == "__main__":
    unittest.main()
