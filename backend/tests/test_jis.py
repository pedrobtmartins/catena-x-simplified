"""JustInSequencePart twins end to end (own sync, partner sync, API), on the official example
payloads, unmodified.

The official SerialPart 3.0.0/3.0.1, Batch 3.0.0 and JustInSequencePart 3.0.0 examples all
describe the same object (``580d3adf-…``), so a twin carrying several of them is a realistic
contradicting twin without changing a payload. The v4 examples each have their own Catena-X ID;
one payload served under two semantic IDs stands for a twin publishing two versions.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from builders import BOM_V4, SERIAL_PART_V4, bom_v4, part_v4, shell_descriptor
from fakes import FakePartnerClient, FakeReader, FakeRegistry
from fastapi.testclient import TestClient

from catenax_simplified.api import create_app
from catenax_simplified.aspects.ids import normalize_global_asset_id
from catenax_simplified.config import Settings
from catenax_simplified.storage import (
    PartRepository,
    init_schema,
    make_engine,
    make_session_factory,
)
from catenax_simplified.traceability import OwnTwinSync, PartnerSync

FIXTURES = Path(__file__).parent / "fixtures" / "aspects"
OWN = "BPNL000000000T1A"
SUPPLIER = "BPNL000000000T2A"
CLOCK = datetime(2026, 10, 14, tzinfo=UTC)
BASE = "https://dataplane.example/api/public"

JIS_V3 = "urn:samm:io.catenax.just_in_sequence_part:3.0.0#JustInSequencePart"
JIS_V4 = "urn:samm:io.catenax.just_in_sequence_part:4.0.0#JustInSequencePart"
JIS_IC = "urn:samm:io.catenax.industry_core.just_in_sequence_part:4.0.0#JustInSequencePart"
SERIAL_V3 = "urn:samm:io.catenax.serial_part:3.0.0#SerialPart"
SERIAL_V301 = "urn:samm:io.catenax.serial_part:3.0.1#SerialPart"
BATCH_V3 = "urn:samm:io.catenax.batch:3.0.0#Batch"

EXAMPLE = {
    JIS_V3: "io.catenax.just_in_sequence_part-3.0.0",
    JIS_V4: "io.catenax.just_in_sequence_part-4.0.0",
    JIS_IC: "io.catenax.industry_core.just_in_sequence_part-4.0.0",
    SERIAL_V3: "io.catenax.serial_part-3.0.0",
    SERIAL_V301: "io.catenax.serial_part-3.0.1",
    BATCH_V3: "io.catenax.batch-3.0.0",
}
# The object all v3 examples describe, and the Catena-X IDs of the JIS v4 examples.
V3_OBJECT = "urn:uuid:580d3adf-1981-44a0-a214-13d6ceed9379"
JIS_V4_OBJECT = "urn:uuid:aC799196-3E4E-d0Ad-2d6F-e1130EfdF6Fc"
JIS_IC_OBJECT = "urn:uuid:3D08aed3-1C97-aEe1-ed7A-ebEf91FaFbc7"


def _official(semantic_id: str) -> dict:
    return json.loads((FIXTURES / f"{EXAMPLE[semantic_id]}.json").read_text())


def _twin(gid: str, semantic_ids: list[str], *, unreadable: tuple[str, ...] = ()):
    """A shell descriptor with these submodels (in this order) and their official payloads;
    the ``unreadable`` ones answer 404."""
    hrefs = {s: f"{BASE}/{gid}/{n}/submodel" for n, s in enumerate(semantic_ids)}
    payloads = {f"{href}/$value": _official(s) for s, href in hrefs.items() if s not in unreadable}
    return shell_descriptor(gid, hrefs, manufacturer_id=OWN), payloads


@pytest.fixture
def session_factory():
    engine = make_engine("sqlite:///:memory:")
    init_schema(engine)
    return make_session_factory(engine)


def _own_sync(session_factory, *twins):
    shells = [shell for shell, _ in twins]
    payloads = {k: v for _, p in twins for k, v in p.items()}
    return OwnTwinSync(
        FakeRegistry(shells), FakeReader(payloads), session_factory, OWN, clock=lambda: CLOCK
    ).run()


# --- own sync ---------------------------------------------------------------------------------


def test_the_three_official_jis_versions_are_read_as_jis_parts(session_factory):
    report = _own_sync(
        session_factory,
        _twin(V3_OBJECT, [JIS_V3]),
        _twin(JIS_V4_OBJECT, [JIS_V4]),
        _twin(JIS_IC_OBJECT, [JIS_IC]),
    )
    assert (report.parts, report.issues, report.unsupported_submodels) == (3, [], 0)
    with session_factory() as session:
        repo = PartRepository(session)
        rows = {gid: repo.get_part(gid) for gid in (V3_OBJECT, JIS_V4_OBJECT, JIS_IC_OBJECT)}
        assert {gid: (r.kind, r.semantic_id) for gid, r in rows.items()} == {
            V3_OBJECT: ("jis", JIS_V3),
            JIS_V4_OBJECT: ("jis", JIS_V4),
            JIS_IC_OBJECT: ("jis", JIS_IC),
        }
        assert rows[V3_OBJECT].local_identifiers == {"jisNumber": "12345678ABC"}


@pytest.mark.parametrize("order", [1, -1], ids=["serial-first", "jis-first"])
def test_a_twin_with_a_serialpart_and_a_jis_part_is_cached_once_as_jis(session_factory, order):
    """Both official v3 examples describe this object. The twin contradicts itself: it is read
    once and reported; at the same release JIS wins, whatever the descriptor order."""
    report = _own_sync(session_factory, _twin(V3_OBJECT, [SERIAL_V3, JIS_V3][::order]))

    assert report.parts == 1
    assert [i.message for i in report.issues] == [
        "twin has part submodels of different aspects (JustInSequencePart, SerialPart); "
        f"read as {JIS_V3}"
    ]
    with session_factory() as session:
        row = PartRepository(session).get_part(V3_OBJECT)
        assert (row.kind, row.local_identifiers) == ("jis", {"jisNumber": "12345678ABC"})


def test_a_batch_and_a_jis_part_on_one_twin_is_read_as_the_unit(session_factory):
    report = _own_sync(session_factory, _twin(V3_OBJECT, [BATCH_V3, JIS_V3]))
    assert report.parts == 1 and len(report.issues) == 1
    with session_factory() as session:
        assert PartRepository(session).get_part(V3_OBJECT).kind == "jis"


SERIAL_V4 = "urn:samm:io.catenax.serial_part:4.0.0#SerialPart"
SERIAL_IC = "urn:samm:io.catenax.industry_core.serial_part:4.0.0#SerialPart"
BATCH_IC = "urn:samm:io.catenax.industry_core.batch:4.0.0#Batch"


def _one_payload_twice(gid: str, example: str, semantic_ids: list[str]):
    """One official v4 payload under several semantic IDs (the v4 part payloads share their
    fields): a twin publishing the same object as several part aspects."""
    shell = shell_descriptor(
        gid, {s: f"{BASE}/{n}/submodel" for n, s in enumerate(semantic_ids)}, manufacturer_id=OWN
    )
    payload = json.loads((FIXTURES / f"{example}.json").read_text())
    return shell, {f"{BASE}/{n}/submodel/$value": payload for n in range(len(semantic_ids))}


@pytest.mark.parametrize("order", [1, -1], ids=["jis-first", "serial-first"])
def test_a_newer_release_wins_over_jis(session_factory, order):
    """A released industry_core SerialPart next to a deprecated io.catenax JIS part: the newer
    release is more likely the one its publisher keeps up to date."""
    twin = _one_payload_twice(
        JIS_V4_OBJECT, "io.catenax.just_in_sequence_part-4.0.0", [JIS_V4, SERIAL_IC][::order]
    )
    report = _own_sync(session_factory, twin)
    assert [i.message for i in report.issues] == [
        "twin has part submodels of different aspects (JustInSequencePart, SerialPart); "
        f"read as {SERIAL_IC}"
    ]
    with session_factory() as session:
        assert PartRepository(session).get_part(JIS_V4_OBJECT).semantic_id == SERIAL_IC


@pytest.mark.parametrize("order", [1, -1], ids=["batch-first", "serial-first"])
def test_a_unit_wins_over_a_batch_of_a_newer_release(session_factory, order):
    """Read as a batch, a unit would escape the "in two assemblies" data check."""
    gid = "urn:uuid:cCfeA55c-688E-FaEd-DcD7-c2eac69f9019"  # the official SerialPart 4.0.0's
    twin = _one_payload_twice(gid, "io.catenax.serial_part-4.0.0", [BATCH_IC, SERIAL_V4][::order])
    report = _own_sync(session_factory, twin)
    assert len(report.issues) == 1
    with session_factory() as session:
        row = PartRepository(session).get_part(gid)
        assert (row.kind, row.semantic_id) == ("serial", SERIAL_V4)


def test_two_versions_of_one_aspect_read_the_newest_without_an_issue(session_factory):
    """Publishing the new version next to the old one is normal during a migration."""
    report = _own_sync(session_factory, _twin(V3_OBJECT, [SERIAL_V301, SERIAL_V3]))
    assert (report.parts, report.issues) == (1, [])
    with session_factory() as session:
        row = PartRepository(session).get_part(V3_OBJECT)
        assert row.semantic_id == SERIAL_V301
        assert row.production_date == "2025-09-26"  # the 3.0.1 example's date, not 3.0.0's


def test_industry_core_is_preferred_at_the_same_version(session_factory):
    """One official payload under both 4.0.0 namespaces (they share the payload shape)."""
    shell = shell_descriptor(
        JIS_IC_OBJECT,
        {JIS_V4: f"{BASE}/a/submodel", JIS_IC: f"{BASE}/b/submodel"},
        manufacturer_id=OWN,
    )
    payloads = {f"{BASE}/{x}/submodel/$value": _official(JIS_IC) for x in "ab"}
    report = _own_sync(session_factory, (shell, payloads))
    assert (report.parts, report.issues) == (1, [])
    with session_factory() as session:
        assert PartRepository(session).get_part(JIS_IC_OBJECT).semantic_id == JIS_IC


def test_an_unreadable_preferred_submodel_falls_back_to_the_next(session_factory):
    report = _own_sync(session_factory, _twin(V3_OBJECT, [SERIAL_V3, JIS_V3], unreadable=(JIS_V3,)))
    assert report.parts == 1
    assert [i.semantic_id for i in report.issues] == [JIS_V3, None]
    assert report.issues[1].message.endswith(f"read as {SERIAL_V3}")
    with session_factory() as session:
        assert PartRepository(session).get_part(V3_OBJECT).kind == "serial"


@pytest.mark.parametrize(
    ("semantic_id", "kind"),
    [
        ("urn:samm:io.catenax.serial_part:3.0.0#JustInSequencePart", "serial"),
        ("urn:samm:io.catenax.serial_part:3.0.0#serialPart", "serial"),  # a slip of case
    ],
)
def test_a_semantic_id_naming_another_aspect_is_read_by_its_namespace_and_reported(
    session_factory, semantic_id, kind
):
    shell = shell_descriptor(V3_OBJECT, {semantic_id: f"{BASE}/x/submodel"}, manufacturer_id=OWN)
    payload = _official(SERIAL_V3)
    report = _own_sync(session_factory, (shell, {f"{BASE}/x/submodel/$value": payload}))

    assert (report.parts, report.unsupported_submodels) == (1, 0)
    fragment = semantic_id.rsplit("#", 1)[1]
    assert [(i.semantic_id, i.message) for i in report.issues] == [
        (
            semantic_id,
            "read by its namespace: io.catenax.serial_part:3.0.0 is a SerialPart model, "
            f"but the semantic ID names #{fragment}",
        )
    ]
    with session_factory() as session:
        assert PartRepository(session).get_part(V3_OBJECT).kind == kind


BOM_OBJECT = "urn:uuid:055c1128-0375-47c8-98de-7cf802c3241d"  # official BoM and usage 3.0.0


@pytest.mark.parametrize("order", [1, -1], ids=["bom-first", "usage-first"])
def test_a_usage_under_the_bom_namespace_does_not_erase_the_real_bom(session_factory, order):
    """Read by its namespace, the official usage example would be an empty BoM of the same twin
    and replace the real one's relations (when listed after it). It is refused and reported."""
    bom = "urn:samm:io.catenax.single_level_bom_as_built:3.0.0#SingleLevelBomAsBuilt"
    usage_as_bom = "urn:samm:io.catenax.single_level_bom_as_built:3.0.0#SingleLevelUsageAsBuilt"
    examples = [
        (bom, "io.catenax.single_level_bom_as_built-3.0.0"),
        (usage_as_bom, "io.catenax.single_level_usage_as_built-3.0.0"),
    ][::order]
    hrefs = {s: f"{BASE}/{n}/submodel" for n, (s, _) in enumerate(examples)}
    payloads = {
        f"{BASE}/{n}/submodel/$value": json.loads((FIXTURES / f"{e}.json").read_text())
        for n, (_, e) in enumerate(examples)
    }
    report = _own_sync(session_factory, (shell_descriptor(BOM_OBJECT, hrefs), payloads))

    assert report.relation_sets == 1
    assert [i.semantic_id for i in report.issues] == [usage_as_bom]
    assert "no 'childItems'" in report.issues[0].message
    with session_factory() as session:
        assert len(PartRepository(session).children(BOM_OBJECT)) == 1


# --- partner sync -----------------------------------------------------------------------------


def _with_own_module(session_factory, children: list[str]) -> None:
    """An own module whose BoM names these supplier twins (the BoM is ours, not an example)."""
    module = "urn:uuid:aaaaaaaa-0000-4000-8000-000000000001"
    hrefs = {SERIAL_PART_V4: f"{BASE}/m/part", BOM_V4: f"{BASE}/m/bom"}
    payloads = {
        f"{BASE}/m/part/$value": part_v4(module, "Seat module", "SM-1"),
        f"{BASE}/m/bom/$value": bom_v4(module, children, SUPPLIER),
    }
    report = _own_sync(session_factory, (shell_descriptor(module, hrefs), payloads))
    assert report.issues == []


def test_partner_jis_twins_are_cached_and_a_contradicting_one_is_reported(session_factory):
    _with_own_module(session_factory, [V3_OBJECT, JIS_IC_OBJECT])
    both, both_payloads = _twin(V3_OBJECT, [SERIAL_V3, JIS_V3])
    core, core_payloads = _twin(JIS_IC_OBJECT, [JIS_IC])
    client = FakePartnerClient(
        {(SUPPLIER, V3_OBJECT): both, (SUPPLIER, JIS_IC_OBJECT): core},
        {**both_payloads, **core_payloads},
    )
    report = PartnerSync(
        client,
        session_factory,
        OWN,
        configured_connectors={SUPPLIER: "https://supplier/dsp"},
        clock=lambda: CLOCK,
        parallel_twins=1,
    ).run()

    (result,) = report.partners
    assert (result.parts_cached, result.status) == (2, "partial")
    assert result.issues == [
        f"{V3_OBJECT}: twin has part submodels of different aspects "
        "(JustInSequencePart, SerialPart)"
    ]
    # Only the preferred submodel was read: no extra request on the partner's data plane.
    assert sorted(client.reader.reads) == [
        f"{BASE}/{JIS_IC_OBJECT}/0/submodel/$value",
        f"{BASE}/{V3_OBJECT}/1/submodel/$value",  # the JIS part, not the SerialPart at /0/
    ]
    with session_factory() as session:
        repo = PartRepository(session)
        assert repo.get_part(V3_OBJECT).kind == "jis"
        assert repo.get_part(JIS_IC_OBJECT).kind == "jis"
        assert repo.get_part(JIS_IC_OBJECT).is_own is False


def test_a_partner_part_with_an_inconsistent_semantic_id_is_cached_and_reported(
    session_factory,
):
    _with_own_module(session_factory, [V3_OBJECT])
    typo = "urn:samm:io.catenax.just_in_sequence_part:3.0.0#JustInSequencepart"
    shell = shell_descriptor(V3_OBJECT, {typo: f"{BASE}/p/submodel"})
    client = FakePartnerClient(
        {(SUPPLIER, V3_OBJECT): shell}, {f"{BASE}/p/submodel/$value": _official(JIS_V3)}
    )
    report = PartnerSync(
        client,
        session_factory,
        OWN,
        configured_connectors={SUPPLIER: "https://supplier/dsp"},
        clock=lambda: CLOCK,
    ).run()

    (result,) = report.partners
    assert (result.parts_cached, result.status) == (1, "partial")
    assert result.issues == [
        f"{V3_OBJECT}: read by its namespace: io.catenax.just_in_sequence_part:3.0.0 is a "
        "JustInSequencePart model, but the semantic ID names #JustInSequencepart"
    ]
    with session_factory() as session:
        assert PartRepository(session).get_part(V3_OBJECT).kind == "jis"


# --- API --------------------------------------------------------------------------------------


@pytest.fixture
def client():
    twins = [
        _twin(V3_OBJECT, [JIS_V3]),
        _twin(JIS_IC_OBJECT, [JIS_IC]),
        _twin(normalize_global_asset_id("27fD1eeE-9e3E-d9ee-79Bc-aBF5eA66Bb35"), []),
    ]
    app = create_app(
        Settings(own_bpnl=OWN, database_url="sqlite:///:memory:"),
        registry=FakeRegistry([shell for shell, _ in twins]),
        reader=FakeReader({k: v for _, p in twins for k, v in p.items()}),
    )
    with TestClient(app) as test_client:
        assert test_client.post("/api/sync", params={"wait": True}).json()["issues"] == []
        yield test_client


def test_jis_parts_in_the_api(client):
    health = client.get("/api/health").json()
    assert {
        "io.catenax.just_in_sequence_part:3.0.0",
        "io.catenax.just_in_sequence_part:4.0.0",
        "io.catenax.industry_core.just_in_sequence_part:4.0.0",
    } <= set(health["supported_aspects"])

    jis = client.get("/api/parts", params={"kind": "jis"}).json()
    assert {p["global_asset_id"] for p in jis["items"]} == {V3_OBJECT, JIS_IC_OBJECT}
    assert client.get("/api/parts", params={"kind": "serial"}).json()["total"] == 0

    part = client.get(f"/api/parts/{V3_OBJECT}").json()
    assert (part["kind"], part["serial"]) == ("jis", "12345678ABC")
    # The 4.0.0 example only names its manufacturer: no label (the UI shows the Catena-X ID).
    assert client.get(f"/api/parts/{JIS_IC_OBJECT}").json()["serial"] is None

    stats = client.get("/api/stats").json()
    assert stats["own_parts_by_kind"] == {"jis": 2}
    assert stats["own_parts_by_semantic_id"] == {JIS_V3: 1, JIS_IC: 1}

    structure = client.get(f"/api/parts/{V3_OBJECT}/structure").json()
    (node,) = structure["parts"]
    assert (node["kind"], node["serial"]) == ("jis", "12345678ABC")


def test_the_serial_label_is_in_every_part_the_api_returns(client):
    page = client.get("/api/parts").json()
    assert {p["global_asset_id"]: p["serial"] for p in page["items"]} == {
        V3_OBJECT: "12345678ABC",
        JIS_IC_OBJECT: None,
    }
    tree = client.get(f"/api/parts/{V3_OBJECT}/tree").json()
    assert tree["part"]["serial"] == "12345678ABC"
