"""The demo data (``devtools/mock_participant.py``, also seeded into the umbrella environment):
its JustInSequencePart modules are the official examples with other values, valid against the
official schemas, and the app reads them as JIS parts, own and as a partner's."""

import copy
import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fakes import FakePartnerClient, FakeReader, FakeRegistry
from jsonschema import Draft4Validator, FormatChecker

from catenax_simplified.aspects import instance_id
from catenax_simplified.storage import PartRepository, init_schema, make_engine
from catenax_simplified.storage import make_session_factory as sessions
from catenax_simplified.traceability import OwnTwinSync, PartnerSync

HERE = Path(__file__).parent
FIXTURES = HERE / "fixtures"
_spec = importlib.util.spec_from_file_location(
    "mock_participant", HERE.parent / "devtools" / "mock_participant.py"
)
mock = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mock)

NAMES = {
    mock.JIS_V3: "io.catenax.just_in_sequence_part-3.0.0",
    mock.JIS_V4: "io.catenax.just_in_sequence_part-4.0.0",
    mock.JIS_IC: "io.catenax.industry_core.just_in_sequence_part-4.0.0",
}
CLOCK = datetime(2026, 10, 14, tzinfo=UTC)


def _official(semantic_id: str) -> dict:
    return json.loads((FIXTURES / "aspects" / f"{NAMES[semantic_id]}.json").read_text())


def _dataset(participant: str):
    """Shells and payloads by value URL, as the fakes serve them."""
    shells, submodels = mock.build_dataset(participant)
    return shells, {f"{{base}}{path}": payload for path, payload in submodels.items()}


def _jis_modules() -> dict[str, tuple[str, dict]]:
    """Module Catena-X ID → (JIS semantic ID, payload) in the Tier-1 dataset."""
    shells, payloads = _dataset("tier1")
    found = {}
    for shell in shells:
        for descriptor in shell["submodelDescriptors"]:
            semantic_id = descriptor["semanticId"]["keys"][0]["value"]
            if semantic_id in NAMES:
                href = descriptor["endpoints"][0]["protocolInformation"]["href"]
                found[shell["globalAssetId"]] = (semantic_id, payloads[f"{href}/$value"])
    return found


def _paths(value, prefix=""):
    if isinstance(value, dict):
        return {p for k, v in value.items() for p in _paths(v, f"{prefix}/{k}")} | {prefix}
    if isinstance(value, list):
        return {p for v in value for p in _paths(v, f"{prefix}[]")} | {prefix}
    return {prefix}


@pytest.mark.parametrize("semantic_id", list(NAMES))
def test_the_embedded_examples_are_the_official_ones(semantic_id):
    assert mock.JIS_EXAMPLES[semantic_id] == _official(semantic_id)


def test_deriving_a_module_leaves_the_embedded_example_alone():
    before = copy.deepcopy(mock.JIS_EXAMPLES)
    mock.build_dataset("tier1")
    assert before == mock.JIS_EXAMPLES


def test_each_jis_version_is_in_the_demo_once():
    assert sorted(s for s, _ in _jis_modules().values()) == sorted(NAMES)


@pytest.mark.parametrize("semantic_id", list(NAMES))
def test_a_jis_module_has_the_fields_of_the_official_example(semantic_id):
    """Only values changed, and localIdentifiers has more entries of the same shape."""
    (payload,) = [p for s, p in _jis_modules().values() if s == semantic_id]
    assert _paths(payload) == _paths(_official(semantic_id))
    assert {i["key"] for i in payload["localIdentifiers"]} == {
        "manufacturerId",
        "jisNumber",
        "parentOrderNumber",
        "jisCallDate",
    }


@pytest.mark.parametrize("semantic_id", list(NAMES))
def test_a_jis_module_is_valid_against_the_official_schema(semantic_id):
    (payload,) = [p for s, p in _jis_modules().values() if s == semantic_id]
    schema = json.loads((FIXTURES / "schemas" / f"{NAMES[semantic_id]}-schema.json").read_text())
    errors = Draft4Validator(schema, format_checker=FormatChecker()).iter_errors(payload)
    assert [e.message for e in errors] == []


@pytest.fixture
def session_factory():
    engine = make_engine("sqlite:///:memory:")
    init_schema(engine)
    return sessions(engine)


def test_the_tier1_demo_shows_three_jis_modules(session_factory):
    shells, payloads = _dataset("tier1")
    report = OwnTwinSync(
        FakeRegistry(shells), FakeReader(payloads), session_factory, mock.TIER1, clock=lambda: CLOCK
    ).run()
    assert (report.twins, report.parts, report.issues) == (6, 6, [])

    with session_factory() as session:
        repo = PartRepository(session)
        rows, _ = repo.list_parts(own_only=True)
        assert sorted(r.kind for r in rows) == ["jis"] * 3 + ["serial"] * 3
        jis = {
            r.global_asset_id: (r.semantic_id, instance_id(r.local_identifiers, r.kind))
            for r in rows
            if r.kind == "jis"
        }
    assert jis == {
        "urn:uuid:aaaaaaaa-0000-4000-8000-000000000002": (
            mock.JIS_IC,
            "JIS-T1-000001 / OEM-ORD-2026-0001 / 2026-02-14",
        ),
        "urn:uuid:aaaaaaaa-0000-4000-8000-000000000004": (
            mock.JIS_V4,
            "JIS-T1-000002 / OEM-ORD-2026-0002 / 2026-04-14",
        ),
        "urn:uuid:aaaaaaaa-0000-4000-8000-000000000006": (
            mock.JIS_V3,
            "JIS-T1-000003 / OEM-ORD-2026-0003 / 2026-06-14",
        ),
    }


def test_the_oem_demo_reads_the_jis_modules_of_its_supplier(session_factory):
    oem_shells, oem_payloads = _dataset("oem")
    OwnTwinSync(
        FakeRegistry(oem_shells),
        FakeReader(oem_payloads),
        session_factory,
        mock.OEM,
        clock=lambda: CLOCK,
    ).run()
    tier1_shells, tier1_payloads = _dataset("tier1")
    client = FakePartnerClient(
        {(mock.TIER1, s["globalAssetId"]): s for s in tier1_shells}, tier1_payloads
    )
    report = PartnerSync(
        client,
        session_factory,
        mock.OEM,
        configured_connectors={mock.TIER1: "http://tier1/dsp"},
        clock=lambda: CLOCK,
    ).run()

    (tier1,) = [r for r in report.partners if r.bpnl == mock.TIER1]
    assert (tier1.parts_cached, tier1.status, tier1.issues) == (3, "ok", [])
    with session_factory() as session:
        modules = (
            PartRepository(session).get_parts({s["globalAssetId"] for s in tier1_shells}).values()
        )
        assert sorted((m.kind, m.is_own) for m in modules) == [("jis", False)] * 3
