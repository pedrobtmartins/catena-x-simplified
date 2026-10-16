import pytest
import responses
import scenario
from fakes import FakeRegistry
from fastapi.testclient import TestClient

from catenax_simplified.api import create_app
from catenax_simplified.config import Settings
from catenax_simplified.dataspace import DataspaceError
from catenax_simplified.dataspace.discovery import EdcDiscovery, SdkConnectorDiscovery
from catenax_simplified.wiring import build_connector_discovery, central_auth

FINDER = "https://discoveryfinder.example/api/v1.0/administration/connectors/discovery/search"
EDC_DISCOVERY = "https://portal-backend.example/api/administration/connectors/discovery"
NEW = "BPNL0000000NEW1A"


class FakeOAuth:
    connected = True

    def add_auth_header(self, headers=None):
        return {**(headers or {}), "Authorization": "Bearer token"}


class FakeDiscovery:
    def __init__(self, endpoints=None, error=None):
        self.endpoints = endpoints or {}
        self.error = error
        self.calls: list[str] = []

    def find(self, bpnl):
        self.calls.append(bpnl)
        if self.error:
            raise DataspaceError(self.error)
        return self.endpoints.get(bpnl, [])


def _mock_finder(mock):
    mock.post(
        FINDER,
        json={"endpoints": [{"type": "bpn", "endpointAddress": EDC_DISCOVERY}]},
        match=[responses.matchers.json_params_matcher({"types": ["bpn"]})],
    )


@responses.activate
def test_sdk_discovery_returns_the_endpoints_of_the_bpnl():
    _mock_finder(responses)
    a, b = "https://edc-a.example/api/v1/dsp", "https://edc-b.example/api/v1/dsp"
    responses.post(
        EDC_DISCOVERY,
        json=[
            {"bpn": "BPNL000000000OTH", "connectorEndpoint": ["https://other/api/v1/dsp"]},
            {"bpn": NEW, "connectorEndpoint": [a, b, a]},
        ],
        match=[responses.matchers.json_params_matcher([NEW])],
    )
    discovery = SdkConnectorDiscovery(FINDER, FakeOAuth())
    assert discovery.find(NEW) == [a, b]
    assert responses.calls[1].request.headers["Authorization"] == "Bearer token"


@responses.activate
def test_sdk_discovery_of_an_unknown_bpnl_is_empty():
    _mock_finder(responses)
    responses.post(EDC_DISCOVERY, json=[])
    assert SdkConnectorDiscovery(FINDER, FakeOAuth()).find(NEW) == []


@responses.activate
def test_sdk_discovery_failures_are_dataspace_errors():
    responses.post(FINDER, status=500)
    with pytest.raises(DataspaceError, match=NEW):
        SdkConnectorDiscovery(FINDER, FakeOAuth()).find(NEW)


def test_sdk_discovery_reports_a_token_failure():
    class NoToken(FakeOAuth):
        def add_auth_header(self, headers=None):
            raise DataspaceError("token request to https://centralidp failed: HTTP 401")

    with pytest.raises(DataspaceError, match="HTTP 401"):
        SdkConnectorDiscovery(FINDER, NoToken()).find(NEW)


def test_discovery_needs_a_finder_and_the_central_idp():
    def build(**settings):
        settings = Settings(own_bpnl=scenario.TIER1, discovery_finder_url=FINDER, **settings)
        return build_connector_discovery(settings, central_auth(settings))

    # The DTR's credentials are not the central IdP's.
    assert build(oauth_url="https://company-idp.example/auth/") is None
    assert build(central_idp_url="https://centralidp.example/auth/") is not None
    assert build(central_idp_url="https://centralidp.example/auth/", dev_direct=True) is None


@responses.activate
def test_edc_discovery_asked_directly():
    a, b = "https://edc-a.example/api/v1/dsp", "https://edc-b.example/api/v1/dsp"
    responses.post(
        EDC_DISCOVERY,
        json=[
            {"bpn": "BPNL000000000OTH", "connectorEndpoint": ["https://other/api/v1/dsp"]},
            {"bpn": NEW, "connectorEndpoint": [a, b, a]},
        ],
        match=[responses.matchers.json_params_matcher([NEW])],
    )
    discovery = EdcDiscovery(EDC_DISCOVERY, FakeOAuth())
    assert discovery.find(NEW) == [a, b]
    assert discovery.find(NEW) == [a, b]
    assert responses.calls[0].request.headers["Authorization"] == "Bearer token"
    assert all(call.request.url == EDC_DISCOVERY for call in responses.calls)


@responses.activate
def test_edc_discovery_failures_are_dataspace_errors():
    responses.post(EDC_DISCOVERY, status=400, json={"errors": {"$": ["Invalid input data"]}})
    with pytest.raises(DataspaceError, match="HTTP 400"):
        EdcDiscovery(EDC_DISCOVERY, FakeOAuth()).find(NEW)


def test_the_edc_discovery_address_wins_over_the_finder():
    settings = Settings(
        own_bpnl=scenario.TIER1,
        central_idp_url="https://centralidp.example/auth/",
        discovery_finder_url=FINDER,
        edc_discovery_url=EDC_DISCOVERY,
    )
    assert isinstance(build_connector_discovery(settings, central_auth(settings)), EdcDiscovery)
    finder_only = settings.model_copy(update={"edc_discovery_url": None})
    discovery = build_connector_discovery(finder_only, central_auth(finder_only))
    assert isinstance(discovery, SdkConnectorDiscovery)


def _client(discovery=None):
    settings = Settings(own_bpnl=scenario.TIER1, database_url="sqlite:///:memory:")
    app = create_app(settings, registry=FakeRegistry([]), discovery=discovery)
    return TestClient(app)


def test_discover_connectors_of_a_partner():
    address = "https://edc.new.example/api/v1/dsp"
    discovery = FakeDiscovery({NEW: [address]})
    with _client(discovery) as client:
        assert client.get("/api/health").json()["can_discover_connectors"] is True
        response = client.get(f"/api/partners/{NEW}/discovery")
        assert response.json() == {"bpnl": NEW, "endpoints": [address]}
        # Nothing is stored until an endpoint is chosen.
        assert client.get("/api/partners").json() == []
        assert client.get("/api/partners/BPNL0000000UNKNO/discovery").json()["endpoints"] == []
        assert client.get("/api/partners/not-a-bpnl/discovery").status_code == 422
    assert discovery.calls == [NEW, "BPNL0000000UNKNO"]


def test_discovery_not_configured_or_failing():
    with _client() as client:
        assert client.get("/api/health").json()["can_discover_connectors"] is False
        response = client.get(f"/api/partners/{NEW}/discovery")
        assert response.status_code == 503
        assert "CXS_EDC_DISCOVERY_URL" in response.json()["detail"]
    with _client(FakeDiscovery(error="discovery finder down")) as client:
        response = client.get(f"/api/partners/{NEW}/discovery")
        assert (response.status_code, response.json()["detail"]) == (502, "discovery finder down")


def test_add_and_remove_a_partner_by_hand():
    address = "https://edc.new.example/api/v1/dsp"
    with _client() as client:
        added = client.put(
            f"/api/partners/{NEW}", json={"name": "New supplier", "connector_address": address}
        ).json()
        assert (added["name"], added["roles"], added["connector_address"]) == (
            "New supplier",
            [],
            address,
        )
        assert added["connector_source"] == "api"
        assert [p["bpnl"] for p in client.get("/api/partners").json()] == [NEW]

        assert client.delete(f"/api/partners/{NEW}").status_code == 204
        assert client.get("/api/partners").json() == []
        assert client.delete(f"/api/partners/{NEW}").status_code == 404


def test_partner_input_is_validated():
    with _client() as client:
        assert client.put("/api/partners/BPNL123", json={"name": "x"}).status_code == 422
        response = client.put(f"/api/partners/{NEW}", json={"connector_address": "edc.example"})
        assert response.status_code == 422
        assert client.get("/api/partners").json() == []
