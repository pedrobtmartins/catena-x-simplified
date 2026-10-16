import json

import pytest
import responses
import scenario
from fakes import FakeReader, FakeRegistry
from fastapi.testclient import TestClient

from catenax_simplified.api import create_app
from catenax_simplified.config import Settings
from catenax_simplified.dataspace import DataspaceError
from catenax_simplified.dataspace.business_partners import BpdmPool, BpExplorer
from catenax_simplified.dataspace.connections import ConnectionTester
from catenax_simplified.dataspace.edc import (
    ASSET_ID_KEY,
    DSP_0_8,
    JUPITER_NEGOTIATION_CONTEXT,
    equals,
)
from catenax_simplified.wiring import build_partner_directory, central_auth

POOL = "https://business-partners.example/pool/api"
EXPLORER = "https://business-partner-explorer-edc.example/api/v1/dsp"
EXPLORER_BPNL = "BPNLCOFINITYEZFA"
DATA_PLANE = "https://business-partner-explorer-edc.example/api/public"
SEARCH = f"{DATA_PLANE}/legal-entities/search"
DSP_2025 = "dataspace-protocol-http:2025-1"
POLICY = {"odrl:permission": {"odrl:action": "odrl:use"}}
NEW = "BPNL0000000NEW1A"


class FakeOAuth:
    def add_auth_header(self, headers=None):
        return {**(headers or {}), "Authorization": "Bearer token"}


class FakeDirectory:
    source = "BPDM Pool"

    def __init__(self, names, failing=()):
        self.names = names
        self.failing = set(failing)

    def legal_name(self, bpnl):
        if bpnl in self.failing:
            raise DataspaceError(f"BPDM lookup of {bpnl} failed: HTTP 503")
        return self.names.get(bpnl)


@responses.activate
def test_pool_returns_the_legal_name():
    responses.get(
        f"{POOL}/v7/legal-entities/{NEW}",
        json={"bpnl": NEW, "legalName": "New Cells GmbH", "legalShortName": "New Cells"},
    )
    assert BpdmPool(POOL + "/", FakeOAuth()).legal_name(NEW) == "New Cells GmbH"
    assert responses.calls[0].request.headers["Authorization"] == "Bearer token"


@responses.activate
def test_pool_unknown_bpnl_and_failures():
    pool = BpdmPool(POOL, FakeOAuth())
    responses.get(f"{POOL}/v7/legal-entities/{NEW}", status=404)
    assert pool.legal_name(NEW) is None
    responses.replace(responses.GET, f"{POOL}/v7/legal-entities/{NEW}", status=401)
    with pytest.raises(DataspaceError, match="HTTP 401"):
        pool.legal_name(NEW)


def test_names_need_a_pool_and_the_central_idp():
    def build(**settings):
        settings = Settings(own_bpnl=scenario.TIER1, bpdm_pool_url=POOL, **settings)
        return build_partner_directory(settings, central_auth(settings))

    assert build() is None
    assert build(central_idp_url="https://centralidp.example/auth/") is not None


def _client(directory=None):
    settings = Settings(own_bpnl=scenario.TIER1, database_url="sqlite:///:memory:")
    app = create_app(
        settings,
        registry=FakeRegistry(scenario.shells()),
        reader=FakeReader(scenario.payloads()),
        directory=directory,
    )
    return TestClient(app)


def test_look_up_a_legal_name():
    with _client(FakeDirectory({NEW: "New Cells GmbH"})) as client:
        assert client.get("/api/health").json()["can_look_up_names"] is True
        assert client.get(f"/api/partners/{NEW}/legal-entity").json() == {
            "bpnl": NEW,
            "legal_name": "New Cells GmbH",
        }
        unknown = client.get("/api/partners/BPNL0000000UNKNO/legal-entity").json()
        assert unknown["legal_name"] is None
        assert client.get("/api/partners").json() == []  # nothing stored


def test_names_not_configured_or_failing():
    with _client() as client:
        assert client.get("/api/health").json()["can_look_up_names"] is False
        response = client.get(f"/api/partners/{NEW}/legal-entity")
        assert response.status_code == 503
        assert "CXS_BPDM_POOL_URL" in response.json()["detail"]
        assert client.post("/api/partners/names").status_code == 503
    with _client(FakeDirectory({}, failing=[NEW])) as client:
        assert client.get(f"/api/partners/{NEW}/legal-entity").status_code == 502


def test_fill_the_names_of_unnamed_partners():
    directory = FakeDirectory(
        {scenario.TIER2: "Tier-2 Cells AG", NEW: "New Cells GmbH"}, failing=[scenario.OEM]
    )
    with _client(directory) as client:
        client.post("/api/sync")
        client.put(f"/api/partners/{NEW}", json={"name": "Our name for them"})
        results = {r["bpnl"]: r for r in client.post("/api/partners/names").json()}
        assert set(results) == {scenario.TIER2, scenario.OEM}  # NEW already had a name
        assert results[scenario.TIER2] == {
            "bpnl": scenario.TIER2,
            "status": "named",
            "name": "Tier-2 Cells AG",
            "message": None,
        }
        assert results[scenario.OEM]["status"] == "failed"
        names = {p["bpnl"]: p["name"] for p in client.get("/api/partners").json()}
        assert names == {
            scenario.TIER2: "Tier-2 Cells AG",
            scenario.OEM: None,
            NEW: "Our name for them",
        }


class FakeConsumer:
    """Our EDC: the explorer's catalog and negotiations, as the Tractus-X SDK returns them."""

    def __init__(self, asset_ids=("bpdm-pool-members-read",), protocol=DSP_2025):
        self.asset_ids = list(asset_ids)
        self.protocol = protocol
        self.contexts = []
        self.catalog_requests = []
        self.negotiations = []

    def get_discovery_info(self, bpnl, counter_party_address=None):
        return counter_party_address, f"did:web:{bpnl}", self.protocol

    def get_catalog_with_filter(
        self, counter_party_id, counter_party_address, filter_expression, timeout=None, **_
    ):
        self.catalog_requests.append(filter_expression)
        wanted = {f["operandRight"] for f in filter_expression}
        ids = [i for i in self.asset_ids if not wanted or i in wanted]
        return {"@type": "dcat:Catalog", "dcat:dataset": [{"@id": i} for i in ids]}

    def do_dsp(
        self,
        counter_party_id,
        counter_party_address,
        filter_expression,
        policies,
        negotiation_context=None,
        **_,
    ):
        assert filter_expression[0]["operandLeft"] == ASSET_ID_KEY
        self.contexts.append(negotiation_context)
        self.negotiations.append((counter_party_id, filter_expression[0]["operandRight"]))
        return DATA_PLANE, "edr-token"


def _page(*entities):
    return {"totalElements": len(entities), "page": 0, "content": list(entities)}


@responses.activate
def test_explorer_reads_the_legal_name_through_the_edc():
    consumer = FakeConsumer()
    explorer = BpExplorer(consumer, [POLICY], EXPLORER)
    responses.post(
        SEARCH,
        json=_page({"bpnl": NEW, "legalName": "New Cells GmbH", "isCatenaXMemberData": True}),
    )
    assert explorer.legal_name(NEW) == "New Cells GmbH"
    request = responses.calls[0].request
    assert request.headers["Authorization"] == "edr-token"
    assert json.loads(request.body) == {"bpnLs": [NEW]}
    assert "size=" in request.url

    # The asset is found in the catalog once (then its offers are read for the negotiation); the
    # EDR is reused for the next lookup.
    responses.replace(responses.POST, SEARCH, json=_page())
    assert explorer.legal_name(scenario.TIER2) is None
    assert consumer.catalog_requests == [[], [equals(ASSET_ID_KEY, "bpdm-pool-members-read")]]
    assert consumer.negotiations == [(f"did:web:{EXPLORER_BPNL}", "bpdm-pool-members-read")]
    assert consumer.contexts == [None]


@responses.activate
def test_explorer_with_a_configured_asset_and_a_rejected_token():
    consumer = FakeConsumer(asset_ids=["a", "b"])
    explorer = BpExplorer(consumer, [POLICY], EXPLORER, asset_id="b")
    responses.post(SEARCH, status=403)
    with pytest.raises(DataspaceError, match="HTTP 403"):
        explorer.legal_name(NEW)
    responses.replace(responses.POST, SEARCH, json=_page({"bpnl": NEW, "legalName": "N"}))
    assert explorer.legal_name(NEW) == "N"
    # The asset is not looked for; a rejected token negotiates again.
    assert [] not in consumer.catalog_requests
    assert [asset for _, asset in consumer.negotiations] == ["b", "b"]


@responses.activate
def test_explorer_on_dsp_0_8_negotiates_with_the_jupiter_context():
    consumer = FakeConsumer(protocol=DSP_0_8)
    responses.post(SEARCH, json=_page({"bpnl": NEW, "legalName": "N"}))
    assert BpExplorer(consumer, [POLICY], EXPLORER).legal_name(NEW) == "N"
    assert consumer.contexts == [JUPITER_NEGOTIATION_CONTEXT]


def test_explorer_asset_must_be_clear():
    with pytest.raises(DataspaceError, match="no asset: is the subscription active"):
        BpExplorer(FakeConsumer([]), [POLICY], EXPLORER).legal_name(NEW)
    with pytest.raises(DataspaceError, match="several assets .*CXS_BP_EXPLORER_ASSET_ID"):
        BpExplorer(FakeConsumer(["a", "b"]), [POLICY], EXPLORER).legal_name(NEW)
    with pytest.raises(DataspaceError, match="does not offer us c"):
        BpExplorer(FakeConsumer(["a"]), [POLICY], EXPLORER, asset_id="c").find_offer()
    with pytest.raises(DataspaceError, match="CXS_ACCEPTED_POLICIES"):
        BpExplorer(FakeConsumer(), [], EXPLORER).legal_name(NEW)


def test_explorer_wins_and_needs_an_edc():
    central = "https://centralidp.example/auth/"

    def build(consumer=None, **settings):
        settings = Settings(own_bpnl=scenario.TIER1, central_idp_url=central, **settings)
        return build_partner_directory(settings, central_auth(settings), consumer)

    assert isinstance(build(bpdm_pool_url=POOL), BpdmPool)
    assert isinstance(build(bpdm_pool_url=POOL, bp_explorer_address=EXPLORER), BpdmPool)
    explorer = build(FakeConsumer(), bpdm_pool_url=POOL, bp_explorer_address=EXPLORER)
    assert isinstance(explorer, BpExplorer)
    assert (explorer.address, explorer.bpnl, explorer.source) == (
        EXPLORER,
        EXPLORER_BPNL,
        "Business Partner Explorer",
    )
    assert build(FakeConsumer(), bp_explorer_address=EXPLORER, dev_direct=True) is None


def test_explorer_connection_check_reads_only_the_catalog():
    settings = Settings(own_bpnl=scenario.TIER1, bp_explorer_address=EXPLORER)
    consumer = FakeConsumer()
    tester = ConnectionTester(settings, bp_explorer=BpExplorer(consumer, [POLICY], EXPLORER))
    check = {c.key: c for c in tester.run()}["bp_explorer"]
    assert (check.status, check.detail) == (
        "ok",
        f"{EXPLORER_BPNL} offers bpdm-pool-members-read; names are read through your EDC.",
    )
    assert consumer.negotiations == []

    tester = ConnectionTester(settings, bp_explorer=BpExplorer(FakeConsumer([]), None, EXPLORER))
    check = {c.key: c for c in tester.run()}["bp_explorer"]
    assert check.status == "failed" and "subscription" in check.detail


def test_names_from_the_explorer_in_the_api():
    with _client(BpExplorer(FakeConsumer(), [POLICY], EXPLORER)) as client:
        health = client.get("/api/health").json()
        assert health["names_source"] == "Business Partner Explorer"
        with responses.RequestsMock() as mock:
            mock.post(SEARCH, json=_page({"bpnl": NEW, "legalName": "New Cells GmbH"}))
            entity = client.get(f"/api/partners/{NEW}/legal-entity").json()
        assert entity == {"bpnl": NEW, "legal_name": "New Cells GmbH"}
