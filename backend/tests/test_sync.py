from datetime import UTC, datetime

import pytest
import scenario
from fakes import FakeReader, FakeRegistry
from sqlalchemy import select

from catenax_simplified.dataspace import DataspaceError
from catenax_simplified.storage import (
    PartRepository,
    RelationRow,
    init_schema,
    make_engine,
    make_session_factory,
)
from catenax_simplified.traceability import OwnTwinSync, part_tree


@pytest.fixture
def session_factory():
    engine = make_engine("sqlite:///:memory:")
    init_schema(engine)
    return make_session_factory(engine)


def _sync(session_factory, shells=None, payloads=None, fail_after=None) -> OwnTwinSync:
    return OwnTwinSync(
        FakeRegistry(shells if shells is not None else scenario.shells(), fail_after=fail_after),
        FakeReader(payloads if payloads is not None else scenario.payloads()),
        session_factory,
        own_bpnl=scenario.TIER1,
        clock=lambda: datetime(2026, 10, 12, tzinfo=UTC),
    )


def test_full_sync_mixes_v3_and_v4(session_factory):
    report = _sync(session_factory).run()

    assert report.complete
    assert report.issues == []
    assert (report.twins, report.parts, report.relation_sets) == (2, 2, 3)
    assert report.unsupported_submodels == 1  # the PCF submodel

    with session_factory() as session:
        repo = PartRepository(session)
        module_a = repo.get_part(scenario.MODULE_A)
        module_b = repo.get_part(scenario.MODULE_B)
        assert module_a.semantic_id.endswith("serial_part:4.0.0#SerialPart")
        assert module_b.semantic_id.endswith("serial_part:3.0.0#SerialPart")
        assert module_a.is_own and module_a.manufacturer_id == scenario.TIER1
        assert module_b.local_identifiers == {"partInstanceId": "SN2"}

        tree = part_tree(repo, scenario.MODULE_A)
        assert [c.global_asset_id for c in tree.children] == [scenario.CELL_1, scenario.CELL_2]
        assert all(c.business_partner == scenario.TIER2 for c in tree.children)
        assert all(c.part is None for c in tree.children)  # supplier parts are not cached yet
        assert [p.global_asset_id for p in tree.parents] == [scenario.VEHICLE]
        assert tree.parents[0].declared_in == ["usage"]


def test_resync_replaces_relations(session_factory):
    _sync(session_factory).run()
    payloads = scenario.payloads()
    from builders import bom_v4

    bom_url = f"{scenario.BASE}/{scenario.MODULE_A}/bom/submodel/$value"
    payloads[bom_url] = bom_v4(scenario.MODULE_A, [scenario.CELL_2], scenario.TIER2)
    _sync(session_factory, payloads=payloads).run()

    with session_factory() as session:
        tree = part_tree(PartRepository(session), scenario.MODULE_A)
        assert [c.global_asset_id for c in tree.children] == [scenario.CELL_2]


def test_parts_removed_from_registry_are_removed_from_cache(session_factory):
    _sync(session_factory).run()
    report = _sync(session_factory, shells=scenario.shells()[:1]).run()

    assert report.removed_parts == 1
    with session_factory() as session:
        assert PartRepository(session).get_part(scenario.MODULE_B) is None
        declared = session.scalars(
            select(RelationRow).where(RelationRow.declared_by == scenario.MODULE_B)
        ).all()
        assert declared == []


def test_aborted_listing_keeps_the_cache(session_factory):
    _sync(session_factory).run()
    report = _sync(session_factory, fail_after=1).run()

    assert not report.complete
    assert report.removed_parts == 0
    assert "registry listing failed" in report.issues[0].message
    with session_factory() as session:
        assert PartRepository(session).get_part(scenario.MODULE_B) is not None


def test_failing_submodel_is_reported_and_the_rest_is_synced(session_factory):
    payloads = scenario.payloads()
    payloads[f"{scenario.BASE}/{scenario.MODULE_A}/bom/submodel/$value"] = DataspaceError("timeout")
    payloads[f"{scenario.BASE}/{scenario.MODULE_B}/serialpart/submodel/$value"] = {"catenaXId": ""}

    report = _sync(session_factory, payloads=payloads).run()

    assert report.complete
    assert {(i.global_asset_id, i.message) for i in report.issues} == {
        (scenario.MODULE_A, "timeout"),
        (scenario.MODULE_B, "missing or invalid 'catenaXId'"),
    }
    assert (report.parts, report.relation_sets) == (1, 2)


def test_submodel_describing_another_twin_is_rejected(session_factory):
    payloads = scenario.payloads()
    from builders import part_v3

    payloads[f"{scenario.BASE}/{scenario.MODULE_B}/serialpart/submodel/$value"] = part_v3(
        scenario.MODULE_A, "wrong", "X"
    )
    report = _sync(session_factory, payloads=payloads).run()

    assert report.issues[0].global_asset_id == scenario.MODULE_B
    assert "not the twin's globalAssetId" in report.issues[0].message
    with session_factory() as session:
        assert PartRepository(session).get_part(scenario.MODULE_A).name_at_manufacturer == (
            "Battery module"
        )


# --- a subset of the registry (CXS_SYNC_TWIN_IDS) ------------------------------------------

VEHICLE_1 = "urn:uuid:11111111-0000-4000-8000-000000000011"
VEHICLE_2 = "urn:uuid:11111111-0000-4000-8000-000000000012"
BATTERY = "urn:uuid:22222222-0000-4000-8000-000000000021"
PENTHOUSE = "urn:uuid:33333333-0000-4000-8000-000000000031"
SUPPLIER_PART = "urn:uuid:44444444-0000-4000-8000-000000000041"
UNKNOWN = "urn:uuid:99999999-0000-4000-8000-000000000091"


def _subset_registry():
    from builders import BOM_V4, SERIAL_PART_V4, bom_v4, part_v4, shell_descriptor

    def href(gid, aspect):
        return f"https://dtr.example/{gid}/{aspect}"

    def bom(gid, own, supplied):
        items = bom_v4(gid, own, scenario.TIER1)["childItems"]
        items += bom_v4(gid, supplied, scenario.TIER2)["childItems"]
        return {"globalAssetId": gid, "childItems": items}

    parts = {
        VEHICLE_1: ([BATTERY], [SUPPLIER_PART]),
        VEHICLE_2: ([], []),
        BATTERY: ([PENTHOUSE], [scenario.CELL_1]),
        PENTHOUSE: None,
    }
    shells, payloads = [], {}
    for gid, children in parts.items():
        submodels = {SERIAL_PART_V4: href(gid, "part")}
        payloads[href(gid, "part") + "/$value"] = part_v4(gid, "Part", "P-1")
        if children:
            submodels[BOM_V4] = href(gid, "bom")
            payloads[href(gid, "bom") + "/$value"] = bom(gid, *children)
        shells.append(shell_descriptor(gid, submodels, manufacturer_id=scenario.TIER1))
    return shells, payloads


def _aas_id(gid):
    return f"urn:uuid:aas-{gid[-12:]}"


def test_subset_loads_the_listed_twins_and_their_own_children(session_factory):
    shells, payloads = _subset_registry()
    _sync(session_factory).run()  # a full sync before: MODULE_A and MODULE_B are cached
    registry = FakeRegistry(shells, fail_after=0)  # listing the registry would fail
    sync = OwnTwinSync(
        registry,
        FakeReader(payloads),
        session_factory,
        own_bpnl=scenario.TIER1,
        twin_ids=[_aas_id(VEHICLE_1), UNKNOWN],
    )
    report = sync.run()

    assert report.complete
    assert (report.twins, report.parts) == (3, 3)  # vehicle, battery, penthouse
    assert [(i.global_asset_id, i.message) for i in report.issues] == [
        (UNKNOWN, "listed twin not found in the registry")
    ]
    # Suppliers' parts are not looked up in the own registry.
    looked_up = [value for kind, value in registry.requests if kind == "lookup"]
    assert looked_up == [UNKNOWN, BATTERY, PENTHOUSE]
    with session_factory() as session:
        repo = PartRepository(session)
        assert {p.global_asset_id for p in repo.list_parts(own_only=True)[0]} == {
            VEHICLE_1,
            BATTERY,
            PENTHOUSE,
        }
        tree = part_tree(repo, BATTERY)
        assert {c.global_asset_id for c in tree.children} == {PENTHOUSE, scenario.CELL_1}


def test_a_listed_global_asset_id_is_looked_up(session_factory):
    shells, payloads = _subset_registry()
    report = OwnTwinSync(
        FakeRegistry(shells),
        FakeReader(payloads),
        session_factory,
        own_bpnl=scenario.TIER1,
        twin_ids=[VEHICLE_2],
    ).run()
    assert (report.twins, report.issues) == (1, [])


def test_parse_twin_ids():
    from catenax_simplified.traceability import parse_twin_ids

    csv = (
        "vehicle_aas_uuid,vehicle_serial,battery_gen6_aas_uuid,children\n"
        f"{VEHICLE_1},AAIe/x+=,{BATTERY},HELLA:LIGHT x2\n"
        f"{VEHICLE_1.upper()},AAO5,{PENTHOUSE},\n"
    )
    assert parse_twin_ids(csv) == [VEHICLE_1, BATTERY, VEHICLE_1.upper(), PENTHOUSE]
    assert parse_twin_ids(" aas-1, aas-2;aas-1\naas-3 ") == ["aas-1", "aas-2", "aas-3"]
    assert parse_twin_ids("") == parse_twin_ids(None) == []
