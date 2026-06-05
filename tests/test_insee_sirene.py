import os
import unittest
from unittest.mock import Mock, patch

import requests

from services.insee_sirene import (
    API_BASE_URL,
    API_KEY_HEADER,
    BORDEAUX_METROPOLE_POSTAL_CODES,
    HTTP_ERROR_MESSAGES,
    InseeSireneApiError,
    InseeSireneClient,
    InseeSireneRequestError,
    MissingInseeApiKeyError,
    TARGET_NAF_CODES,
    build_etablissements_query,
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

    def test_build_etablissements_query_contains_target_filters(self) -> None:
        query = build_etablissements_query(
            postal_codes=("33000", "33100"),
            naf_codes=("8121Z", "8129B"),
        )

        self.assertEqual(
            "etatAdministratifEtablissement:A"
            " AND etablissementSiege:true"
            " AND (codePostalEtablissement:33000 OR codePostalEtablissement:33100)"
            " AND (activitePrincipaleEtablissement:8121Z"
            " OR activitePrincipaleEtablissement:8129B)",
            query,
        )

    def test_search_etablissements_uses_siret_endpoint_q_and_cursor(self) -> None:
        session = Mock()
        session.get.return_value = make_response(
            payload={
                "header": {
                    "curseur": "*",
                    "curseurSuivant": "*",
                    "nombre": 1,
                    "total": 1,
                },
                "etablissements": [{"siret": "12345678900012"}],
            }
        )
        client = InseeSireneClient(session=session)

        with patch.dict(os.environ, {"INSEE_API_KEY": "secret-key"}, clear=True):
            etablissements = client.search_etablissements(
                postal_codes=("33000",),
                naf_codes=("8121Z",),
                page_delay_seconds=0,
            )

        self.assertEqual([{"siret": "12345678900012"}], etablissements)
        session.get.assert_called_once_with(
            f"{API_BASE_URL}/siret",
            headers={API_KEY_HEADER: "secret-key"},
            params={
                "q": (
                    "etatAdministratifEtablissement:A"
                    " AND etablissementSiege:true"
                    " AND codePostalEtablissement:33000"
                    " AND activitePrincipaleEtablissement:8121Z"
                ),
                "nombre": 1000,
                "curseur": "*",
            },
            timeout=30,
        )

    def test_search_etablissements_uses_default_bordeaux_and_naf_filters(self) -> None:
        session = Mock()
        session.get.return_value = make_response(
            payload={
                "header": {"curseur": "*", "curseurSuivant": "*"},
                "etablissements": [],
            }
        )
        client = InseeSireneClient(session=session)

        with patch.dict(os.environ, {"INSEE_API_KEY": "secret-key"}, clear=True):
            client.search_etablissements(page_delay_seconds=0)

        params = session.get.call_args.kwargs["params"]
        query = params["q"]
        for postal_code in BORDEAUX_METROPOLE_POSTAL_CODES:
            self.assertIn(f"codePostalEtablissement:{postal_code}", query)
        for naf_code in TARGET_NAF_CODES:
            self.assertIn(f"activitePrincipaleEtablissement:{naf_code}", query)
        self.assertIn("etatAdministratifEtablissement:A", query)
        self.assertIn("etablissementSiege:true", query)

    def test_search_etablissements_paginates_with_cursor(self) -> None:
        session = Mock()
        session.get.side_effect = [
            make_response(
                payload={
                    "header": {"curseur": "*", "curseurSuivant": "next-cursor"},
                    "etablissements": [{"siret": "11111111100011"}],
                }
            ),
            make_response(
                payload={
                    "header": {
                        "curseur": "next-cursor",
                        "curseurSuivant": "next-cursor",
                    },
                    "etablissements": [{"siret": "22222222200022"}],
                }
            ),
        ]
        client = InseeSireneClient(session=session)

        with patch.dict(os.environ, {"INSEE_API_KEY": "secret-key"}, clear=True):
            etablissements = client.search_etablissements(
                postal_codes=("33000",),
                naf_codes=("8121Z",),
                page_delay_seconds=0,
            )

        self.assertEqual(
            [{"siret": "11111111100011"}, {"siret": "22222222200022"}],
            etablissements,
        )
        first_params = session.get.call_args_list[0].kwargs["params"]
        second_params = session.get.call_args_list[1].kwargs["params"]
        self.assertEqual("*", first_params["curseur"])
        self.assertEqual("next-cursor", second_params["curseur"])
        self.assertNotIn("debut", first_params)
        self.assertNotIn("debut", second_params)

    def test_search_etablissements_limit_caps_results_and_page_size(self) -> None:
        session = Mock()
        session.get.return_value = make_response(
            payload={
                "header": {"curseur": "*", "curseurSuivant": "ignored"},
                "etablissements": [{"siret": "111"}, {"siret": "222"}],
            }
        )
        client = InseeSireneClient(session=session)

        with patch.dict(os.environ, {"INSEE_API_KEY": "secret-key"}, clear=True):
            etablissements = client.search_etablissements(
                limit=1,
                postal_codes=("33000",),
                naf_codes=("8121Z",),
                page_delay_seconds=0,
            )

        self.assertEqual([{"siret": "111"}], etablissements)
        self.assertEqual(1, session.get.call_args.kwargs["params"]["nombre"])

    def test_search_etablissements_zero_limit_does_not_call_api(self) -> None:
        session = Mock()
        client = InseeSireneClient(session=session)

        etablissements = client.search_etablissements(limit=0)

        self.assertEqual([], etablissements)
        session.get.assert_not_called()

    def test_search_etablissements_validates_arguments(self) -> None:
        client = InseeSireneClient(session=Mock())

        with self.assertRaises(ValueError):
            client.search_etablissements(limit=-1)
        with self.assertRaises(ValueError):
            client.search_etablissements(page_size=0)
        with self.assertRaises(ValueError):
            client.search_etablissements(postal_codes=())

    def test_search_etablissements_sleeps_between_pages(self) -> None:
        session = Mock()
        session.get.side_effect = [
            make_response(
                payload={
                    "header": {"curseur": "*", "curseurSuivant": "next-cursor"},
                    "etablissements": [{"siret": "11111111100011"}],
                }
            ),
            make_response(
                payload={
                    "header": {
                        "curseur": "next-cursor",
                        "curseurSuivant": "next-cursor",
                    },
                    "etablissements": [],
                }
            ),
        ]
        client = InseeSireneClient(session=session)

        with patch.dict(
            os.environ,
            {"INSEE_API_KEY": "secret-key"},
            clear=True,
        ), patch("services.insee_sirene.time.sleep") as sleep_mock:
            client.search_etablissements(
                postal_codes=("33000",),
                naf_codes=("8121Z",),
                page_delay_seconds=0.5,
            )

        sleep_mock.assert_called_once_with(0.5)


if __name__ == "__main__":
    unittest.main()
