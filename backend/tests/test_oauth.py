import contextlib
import re

import pytest
import responses
import scenario

from catenax_simplified.config import Settings
from catenax_simplified.dataspace import DataspaceError
from catenax_simplified.dataspace import oauth as oauth_module
from catenax_simplified.dataspace.oauth import (
    ClientCredentials,
    authenticate_sdk_service,
    keycloak_token_url,
)
from catenax_simplified.wiring import build_edc_consumer, dtr_auth

TOKEN_URL = "https://login.example.com/oauth2/token"
MANAGEMENT = "https://edc-controlplane.example.com"


def test_keycloak_token_url():
    expected = "https://kc.example/auth/realms/CX-Central/protocol/openid-connect/token"
    assert keycloak_token_url("https://kc.example/auth/", "CX-Central") == expected
    assert keycloak_token_url("https://kc.example/auth", "CX-Central") == expected


@responses.activate
def test_token_is_requested_with_client_credentials_and_cached(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(oauth_module.time, "monotonic", lambda: now[0])
    responses.post(
        TOKEN_URL,
        json={"access_token": "t1", "expires_in": 300},
        match=[
            responses.matchers.urlencoded_params_matcher(
                {"grant_type": "client_credentials", "scope": "api://edc/.default"}
            )
        ],
    )
    auth = ClientCredentials(TOKEN_URL, "app", "s3cret", scope="api://edc/.default")
    assert auth.add_auth_header({"Accept": "x"}) == {"Accept": "x", "Authorization": "Bearer t1"}
    assert auth.token() == "t1"
    assert len(responses.calls) == 1  # cached
    assert responses.calls[0].request.headers["Authorization"].startswith("Basic ")

    responses.replace(responses.POST, TOKEN_URL, json={"access_token": "t2", "expires_in": 300})
    now[0] += 300 - oauth_module.EXPIRY_MARGIN  # renewed before it expires
    assert auth.token() == "t2"


@responses.activate
def test_token_errors_name_the_reason_but_not_the_secret():
    responses.post(
        TOKEN_URL,
        status=401,
        json={"error": "invalid_client", "error_description": "Invalid client credentials"},
    )
    with pytest.raises(DataspaceError) as error:
        ClientCredentials(TOKEN_URL, "app", "s3cret").token()
    assert "HTTP 401 (Invalid client credentials)" in str(error.value)
    assert "s3cret" not in str(error.value)


def test_dtr_auth_from_keycloak_or_any_token_endpoint():
    base = {"own_bpnl": scenario.TIER1, "oauth_client_id": "dtr", "oauth_client_secret": "x"}
    assert dtr_auth(Settings(**base)) is None
    keycloak = dtr_auth(Settings(**base, oauth_url="https://kc.example/auth/", oauth_realm="R"))
    assert keycloak.token_url == "https://kc.example/auth/realms/R/protocol/openid-connect/token"
    generic = dtr_auth(Settings(**base, oauth_token_url=TOKEN_URL, oauth_url="https://kc/"))
    assert generic.token_url == TOKEN_URL


def test_every_session_of_an_sdk_service_gets_the_auth():
    settings = Settings(own_bpnl=scenario.TIER1, edc_management_url=MANAGEMENT)
    consumer = build_edc_consumer(settings)
    auth = ClientCredentials(TOKEN_URL, "app", "s3cret")
    # The Saturn consumer keeps one adapter for discovery and one for the other controllers.
    assert authenticate_sdk_service(consumer, auth) >= 2


@responses.activate
def test_edc_management_calls_carry_a_token_and_the_api_key():
    responses.post(TOKEN_URL, json={"access_token": "edc-token", "expires_in": 300})
    responses.add(responses.POST, re.compile(re.escape(MANAGEMENT) + ".*"), json={})
    responses.add(responses.GET, re.compile(re.escape(MANAGEMENT) + ".*"), json={})
    settings = Settings(
        own_bpnl=scenario.TIER1,
        edc_management_url=MANAGEMENT,
        edc_api_key="key",
        edc_oauth_token_url=TOKEN_URL,
        edc_oauth_client_id="app",
        edc_oauth_client_secret="s3cret",
    )
    consumer = build_edc_consumer(settings)
    for call in (
        lambda: consumer.get_discovery_info(
            bpnl=scenario.TIER2, counter_party_address="https://edc.tier2/api/v1/dsp"
        ),
        lambda: consumer.get_catalog_with_filter(
            counter_party_id="did:web:tier2",
            counter_party_address="https://edc.tier2/api/v1/dsp/2025-1",
            filter_expression=[],
        ),
    ):
        # The answers are empty; only the requests matter here.
        with contextlib.suppress(Exception):
            call()
    management = [c for c in responses.calls if c.request.url.startswith(MANAGEMENT)]
    assert len(management) >= 2
    for call in management:
        assert call.request.headers["Authorization"] == "Bearer edc-token"
        assert call.request.headers["X-Api-Key"] == "key"
