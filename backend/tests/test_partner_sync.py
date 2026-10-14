from datetime import UTC, datetime

import pytest
import scenario
from fakes import FakePartnerClient, FakeReader, FakeRegistry

from catenax_simplified.storage import (
    PartnerRepository,
    PartRepository,
    init_schema,
    make_engine,
    make_session_factory,
)
from catenax_simplified.traceability import OwnTwinSync, PartnerSync, part_tree

CLOCK = datetime(2026, 10, 14, tzinfo=UTC)


@pytest.fixture
def session_factory():
    engine = make_engine("sqlite:///:memory:")
    init_schema(engine)
    factory = make_session_factory(engine)
    OwnTwinSync(
        FakeRegistry(scenario.shells()),
        FakeReader(scenario.payloads()),
        factory,
        own_bpnl=scenario.TIER1,
        clock=lambda: CLOCK,
    ).run()
    return factory


def _partner_sync(session_factory, client=None, connectors=None) -> PartnerSync:
    return PartnerSync(
        client or FakePartnerClient(scenario.tier2_twins(), scenario.tier2_payloads()),
        session_factory,
        scenario.TIER1,
        configured_connectors=connectors
        if connectors is not None
        else {scenario.TIER2: scenario.TIER2_CONNECTOR},
        clock=lambda: CLOCK,
    )


def test_counterparts_come_from_own_relations(session_factory):
    with session_factory() as session:
        counterparts = PartRepository(session).partner_counterparts()
    assert counterparts == {
        scenario.TIER2: {
            "supplier": {scenario.CELL_1, scenario.CELL_2, scenario.CELL_3},
            "customer": set(),
        },
        scenario.OEM: {"supplier": set(), "customer": {scenario.VEHICLE}},
    }


def test_partner_twins_are_cached_one_level_only(session_factory):
    client = FakePartnerClient(scenario.tier2_twins(), scenario.tier2_payloads())
    report = _partner_sync(session_factory, client).run()

    by_bpnl = {r.bpnl: r for r in report.partners}
    tier2 = by_bpnl[scenario.TIER2]
    assert (tier2.roles, tier2.linked_twins) == (["supplier"], 3)
    assert (tier2.twins_found, tier2.twins_missing, tier2.status) == (2, 1, "partial")
    assert by_bpnl[scenario.OEM].status == "no_connector"
    # Only the partner's own twins were looked up — never their children.
    assert {gid for _, gid in client.lookups} == {
        scenario.CELL_1,
        scenario.CELL_2,
        scenario.CELL_3,
    }

    with session_factory() as session:
        repo = PartRepository(session)
        cell_1 = repo.get_part(scenario.CELL_1)
        assert (cell_1.is_own, cell_1.manufacturer_id) == (False, scenario.TIER2)
        assert cell_1.semantic_id.endswith("serial_part:3.0.0#SerialPart")
        assert repo.get_part(scenario.CELL_3).semantic_id.endswith("serial_part:4.0.0#SerialPart")
        assert repo.get_part(scenario.CELL_2) is None

        tree = part_tree(repo, scenario.MODULE_A)
        names = {c.global_asset_id: c.part and c.part.name_at_manufacturer for c in tree.children}
        assert names == {scenario.CELL_1: "Li-ion cell", scenario.CELL_2: None}

        rows = {row.bpnl: row for row in PartnerRepository(session).all()}
        assert rows[scenario.TIER2].last_status == "partial"
        assert rows[scenario.TIER2].twins_found == 2
        assert rows[scenario.OEM].last_status == "no_connector"


def test_stored_address_wins_over_settings(session_factory):
    with session_factory.begin() as session:
        PartnerRepository(session).get_or_create(scenario.OEM).connector_address = "https://oem/dsp"
    client = FakePartnerClient({}, {})
    report = _partner_sync(session_factory, client, connectors={scenario.OEM: "https://x"}).run(
        only_bpnl=scenario.OEM
    )
    assert [r.bpnl for r in report.partners] == [scenario.OEM]
    assert report.partners[0].twins_missing == 1
    assert client.lookups == [(scenario.OEM, scenario.VEHICLE)]


def test_unreachable_partner_keeps_its_cached_parts(session_factory):
    _partner_sync(session_factory).run()
    client = FakePartnerClient({}, {}, unreachable={scenario.TIER2})
    report = _partner_sync(session_factory, client).run(only_bpnl=scenario.TIER2)

    result = report.partners[0]
    assert result.status == "failed"
    assert "timeout" in result.issues[0]
    with session_factory() as session:
        assert PartRepository(session).get_part(scenario.CELL_1) is not None


def test_bad_submodel_is_reported(session_factory):
    payloads = scenario.tier2_payloads()
    for url in payloads:
        if scenario.CELL_3 in url:
            payloads[url] = {"globalAssetId": scenario.CELL_1}  # describes another twin
    report = _partner_sync(
        session_factory, FakePartnerClient(scenario.tier2_twins(), payloads)
    ).run(only_bpnl=scenario.TIER2)

    issues = report.partners[0].issues
    assert any(scenario.CELL_3 in issue and "describes" in issue for issue in issues)
    with session_factory() as session:
        assert PartRepository(session).get_part(scenario.CELL_3) is None


def test_own_bpnl_is_never_a_partner(session_factory):
    report = PartnerSync(
        FakePartnerClient({}, {}), session_factory, scenario.TIER2, clock=lambda: CLOCK
    ).run()
    assert scenario.TIER2 not in {r.bpnl for r in report.partners}
