import responses
import scenario
from fakes import FakeRegistry
from fastapi.testclient import TestClient

from catenax_simplified.api import create_app
from catenax_simplified.config import Settings
from catenax_simplified.wiring import build_connection_tester

DTR = "https://dtr.example.com"
MANAGEMENT = "https://edc-controlplane.example.com"
COMPANY_TOKEN = "https://login.example.com/oauth2/token"
CENTRAL = "https://centralidp.example.com/auth/"
CENTRAL_TOKEN = (
    "https://centralidp.example.com/auth/realms/CX-Central/protocol/openid-connect/token"
)
FINDER = "https://discoveryfinder.example.com/api/v1.0/administration/connectors/discovery/search"
POOL = "https://business-partners.example.com/pool/api"
EDC_DISCOVERY = "https://portal-backend.example.com/api/administration/connectors/discovery"


def _settings(**overrides):
    values = {
        "own_bpnl": scenario.TIER1,
        "dtr_base_url": DTR,
        "oauth_token_url": COMPANY_TOKEN,
        "oauth_client_id": "dtr",
        "oauth_client_secret": "dtr-secret",
        "edc_management_url": MANAGEMENT,
        "edc_api_key": "key",
        "edc_oauth_token_url": COMPANY_TOKEN,
        "edc_oauth_client_id": "edc",
        "edc_oauth_client_secret": "edc-secret",
        "central_idp_url": CENTRAL,
        "central_idp_client_id": "sa-cx",
        "central_idp_client_secret": "central-secret",
        "discovery_finder_url": FINDER,
        "bpdm_pool_url": POOL,
    }
    return Settings(**{**values, **overrides})


def _run(settings):
    return {c.key: c for c in build_connection_tester(settings).run()}


def _mock_all(mock, dtr_status=200):
    mock.post(COMPANY_TOKEN, json={"access_token": "company", "expires_in": 300})
    mock.post(CENTRAL_TOKEN, json={"access_token": "central", "expires_in": 300})
    mock.get(f"{DTR}/api/v3/shell-descriptors", status=dtr_status, json={"result": []})
    mock.post(f"{MANAGEMENT}/management/v3/assets/request", json=[])
    mock.post(
        FINDER,
        json={"endpoints": [{"type": "bpn", "endpointAddress": "https://portal/discovery"}]},
    )
    mock.get(f"{POOL}/v7/legal-entities/{scenario.TIER1}", json={"legalName": "Tier-1 Modules"})


@responses.activate
def test_every_connection_works():
    _mock_all(responses)
    checks = _run(_settings())
    assert {k: c.status for k, c in checks.items()} == {
        **dict.fromkeys(["dtr", "edc", "central_idp", "discovery", "bpdm"], "ok"),
        "bp_explorer": "not_configured",
    }
    assert (
        checks["edc"].detail == "The management API answered with an OAuth token and the API key."
    )
    assert checks["discovery"].detail == "EDC Discovery at https://portal/discovery."
    assert checks["bpdm"].detail == "Your legal name: Tier-1 Modules."

    by_url = {c.request.url.split("?")[0]: c.request for c in responses.calls}
    dtr = by_url[f"{DTR}/api/v3/shell-descriptors"]
    assert (dtr.headers["Authorization"], dtr.headers["Edc-Bpn"]) == (
        "Bearer company",
        scenario.TIER1,
    )
    edc = by_url[f"{MANAGEMENT}/management/v3/assets/request"]
    assert (edc.headers["Authorization"], edc.headers["X-Api-Key"]) == ("Bearer company", "key")
    assert by_url[FINDER].headers["Authorization"] == "Bearer central"


@responses.activate
def test_rejected_credentials_and_a_failing_central_idp():
    _mock_all(responses, dtr_status=401)
    responses.replace(
        responses.POST,
        CENTRAL_TOKEN,
        status=401,
        json={"error": "unauthorized_client", "error_description": "Invalid client secret"},
    )
    checks = _run(_settings())
    assert (checks["dtr"].status, checks["dtr"].detail) == (
        "failed",
        "HTTP 401: the credentials were rejected",
    )
    assert checks["edc"].status == "ok"
    assert checks["central_idp"].status == "failed"
    assert "Invalid client secret" in checks["central_idp"].detail
    assert "central-secret" not in checks["central_idp"].detail
    assert (checks["discovery"].status, checks["bpdm"].status) == ("skipped", "skipped")


@responses.activate
def test_unreachable_service():
    responses.post(COMPANY_TOKEN, json={"access_token": "company", "expires_in": 300})
    checks = _run(_settings(central_idp_url=None))
    assert checks["dtr"].status == "failed"
    assert checks["dtr"].detail.startswith(f"{DTR}/api/v3/shell-descriptors is not reachable")


@responses.activate
def test_edc_discovery_without_the_finder():
    _mock_all(responses)
    responses.post(
        EDC_DISCOVERY,
        json=[{"bpn": scenario.TIER1, "connectorEndpoint": ["https://edc/api/v1/dsp"]}],
        match=[responses.matchers.json_params_matcher([scenario.TIER1])],
    )
    checks = _run(_settings(discovery_finder_url=None, edc_discovery_url=EDC_DISCOVERY))
    assert checks["discovery"].status == "ok"
    assert checks["discovery"].detail == (
        f"EDC Discovery at {EDC_DISCOVERY} answered: "
        f"1 connector(s) registered for {scenario.TIER1}."
    )
    assert not any(call.request.url == FINDER for call in responses.calls)


@responses.activate
def test_the_edc_discovery_entered_as_the_finder():
    # The EDC Discovery expects a list of BPNLs, not the Discovery Finder's request.
    _mock_all(responses)
    responses.post(EDC_DISCOVERY, status=400, json={"errors": {"$": ["Invalid input data"]}})
    checks = _run(_settings(discovery_finder_url=EDC_DISCOVERY))
    assert checks["discovery"].status == "failed"
    assert checks["discovery"].detail.startswith("HTTP 400")
    assert (
        "enter it as the EDC Discovery address (CXS_EDC_DISCOVERY_URL)"
        in checks["discovery"].detail
    )


def test_nothing_configured():
    checks = _run(Settings(own_bpnl=scenario.TIER1))
    assert {c.status for c in checks.values()} == {"not_configured"}
    assert checks["edc"].detail == "CXS_EDC_MANAGEMENT_URL is not set"
    assert checks["bpdm"].detail == "CXS_BPDM_POOL_URL is not set"
    assert checks["bp_explorer"].detail == "CXS_BP_EXPLORER_ADDRESS is not set"


def test_connection_tests_endpoint():
    settings = Settings(own_bpnl=scenario.TIER1, database_url="sqlite:///:memory:")
    with TestClient(create_app(settings, registry=FakeRegistry([]))) as client:
        checks = client.post("/api/setup/connection-tests").json()
    assert [c["key"] for c in checks] == [
        "dtr",
        "edc",
        "central_idp",
        "discovery",
        "bpdm",
        "bp_explorer",
    ]
    assert checks[0] == {
        "key": "dtr",
        "name": "Digital Twin Registry",
        "status": "not_configured",
        "detail": "CXS_DTR_BASE_URL is not set",
    }
