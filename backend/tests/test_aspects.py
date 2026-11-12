import dataclasses
import json
from pathlib import Path

import pytest

from catenax_simplified.aspects import (
    AspectPayloadError,
    AspectType,
    Part,
    PartKind,
    Relations,
    RelationSource,
    is_supported,
    lookup,
    parse,
)
from catenax_simplified.aspects.ids import normalize_global_asset_id

FIXTURES = Path(__file__).parent / "fixtures" / "aspects"

ASPECT_NAMES = {
    "serial_part": "SerialPart",
    "batch": "Batch",
    "just_in_sequence_part": "JustInSequencePart",
    "single_level_bom_as_built": "SingleLevelBomAsBuilt",
    "single_level_usage_as_built": "SingleLevelUsageAsBuilt",
}


def _fixture_cases():
    for path in sorted(FIXTURES.glob("*.json")):
        namespace, version = path.stem.rsplit("-", 1)
        aspect = ASPECT_NAMES[namespace.rsplit(".", 1)[1]]
        yield pytest.param(f"urn:samm:{namespace}:{version}#{aspect}", path, id=path.stem)


@pytest.mark.parametrize(("semantic_id", "path"), list(_fixture_cases()))
def test_every_official_example_is_supported_and_parses(semantic_id, path):
    assert is_supported(semantic_id)
    result = parse(semantic_id, json.loads(path.read_text()))
    if isinstance(result, Part):
        assert result.global_asset_id.startswith("urn:uuid:")
        assert result.manufacturer_part_id == "123-0.740-3434-A"
        assert result.classifications[0].id == "1004712"
        assert result.classifications[0].standard == "GIN 20510-21513"
        assert result.site_ids and result.site_ids[0].startswith("BPNS")
        assert result.production_date
    else:
        assert isinstance(result, Relations)
        assert len(result.items) == 1
        assert result.items[0].quantity == 20.0
        assert result.items[0].unit == "unit:piece"
        assert result.items[0].business_partner == "BPNL50096894aNXY"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def test_serial_part_v3_and_v4_map_to_the_same_fields():
    v3 = parse(
        "urn:samm:io.catenax.serial_part:3.0.0#SerialPart", _load("io.catenax.serial_part-3.0.0")
    )
    v4 = parse(
        "urn:samm:io.catenax.industry_core.serial_part:4.0.0#SerialPart",
        _load("io.catenax.industry_core.serial_part-4.0.0"),
    )
    assert v3.kind == v4.kind == PartKind.SERIAL
    assert v3.global_asset_id == "urn:uuid:580d3adf-1981-44a0-a214-13d6ceed9379"
    assert v3.local_identifiers == {"partInstanceId": "SN12345678"}
    assert v3.production_date == "2022-02-04T14:48:54"
    assert v3.site_ids == ("BPNS1234567890ZZ",)
    assert v3.name_at_customer == v4.name_at_customer == "side element A"
    assert v4.production_date == "2025-09-26"
    assert v4.classifications == v3.classifications


def test_batch_kind():
    batch = parse("urn:samm:io.catenax.batch:3.0.0#Batch", _load("io.catenax.batch-3.0.0"))
    assert batch.kind == PartKind.BATCH
    assert batch.local_identifiers == {"batchId": "BID12345678"}


def test_bom_relation_direction():
    bom = parse(
        "urn:samm:io.catenax.single_level_bom_as_built:4.0.0#SingleLevelBomAsBuilt",
        _load("io.catenax.single_level_bom_as_built-4.0.0"),
    )
    assert bom.source == RelationSource.BOM
    assert bom.declared_by == bom.items[0].parent_id
    assert bom.items[0].child_id == "urn:uuid:9BBfdaad-afdf-5bAC-00EF-fE5d9bB3A96b"


def test_usage_relation_direction_and_customers():
    usage = parse(
        "urn:samm:io.catenax.single_level_usage_as_built:3.0.0#SingleLevelUsageAsBuilt",
        _load("io.catenax.single_level_usage_as_built-3.0.0"),
    )
    assert usage.source == RelationSource.USAGE
    assert usage.declared_by == usage.items[0].child_id
    assert usage.customers == ("BPNL50096894aNXY",)
    assert usage.items[0].is_only_potential_parent is False


@pytest.mark.parametrize(
    "semantic_id",
    [
        "urn:samm:io.catenax.serial_part:2.0.0#SerialPart",  # invalidated
        "urn:samm:io.catenax.single_level_bom_as_built:2.0.0#SingleLevelBomAsBuilt",
        "urn:samm:io.catenax.pcf:7.0.0#Pcf",
        "not-a-urn",
    ],
)
def test_unsupported_semantic_ids(semantic_id):
    assert lookup(semantic_id) is None
    with pytest.raises(ValueError, match="unsupported"):
        parse(semantic_id, {})


def test_lookup_does_not_need_the_fragment():
    assert lookup("urn:samm:io.catenax.serial_part:3.0.1").type == AspectType.SERIAL_PART


def test_payload_without_id_is_rejected():
    with pytest.raises(AspectPayloadError, match="globalAssetId"):
        parse("urn:samm:io.catenax.serial_part:4.0.0#SerialPart", {"localIdentifiers": []})


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("580d3adf-1981-44a0-a214-13d6ceed9379", "urn:uuid:580d3adf-1981-44a0-a214-13d6ceed9379"),
        (
            " urn:uuid:580D3ADF-1981-44a0-a214-13d6ceed9379",
            "urn:uuid:580D3ADF-1981-44a0-a214-13d6ceed9379",
        ),
        ("some-other-id", "some-other-id"),
    ],
)
def test_normalize_global_asset_id(raw, expected):
    assert normalize_global_asset_id(raw) == expected


# --- JustInSequencePart, and telling the part aspects apart ---------------------------------

SCHEMAS = Path(__file__).parent / "fixtures" / "schemas"
JIS_V3 = "urn:samm:io.catenax.just_in_sequence_part:3.0.0#JustInSequencePart"
JIS_V4 = "urn:samm:io.catenax.just_in_sequence_part:4.0.0#JustInSequencePart"
JIS_IC = "urn:samm:io.catenax.industry_core.just_in_sequence_part:4.0.0#JustInSequencePart"
SERIAL_IC = "urn:samm:io.catenax.industry_core.serial_part:4.0.0#SerialPart"
BATCH_IC = "urn:samm:io.catenax.industry_core.batch:4.0.0#Batch"


def test_every_supported_version_has_an_official_example():
    """Each entry of the registry is exercised by an unmodified official payload."""
    from catenax_simplified.aspects.registry import SUPPORTED

    examples = {":".join(p.stem.rsplit("-", 1)) for p in FIXTURES.glob("*.json")}
    assert set(SUPPORTED) == examples


def _schema_errors(name: str, payload: dict) -> list[str]:
    """Where a payload breaks the official JSON schema of ``name`` (draft 4, formats checked)."""
    from jsonschema import Draft4Validator, FormatChecker

    schema = json.loads((SCHEMAS / f"{name}-schema.json").read_text())
    validator = Draft4Validator(schema, format_checker=FormatChecker())
    return sorted("/".join(map(str, e.absolute_path)) for e in validator.iter_errors(payload))


@pytest.mark.parametrize(
    "name",
    [
        "io.catenax.just_in_sequence_part-4.0.0",
        "io.catenax.industry_core.just_in_sequence_part-4.0.0",
    ],
)
def test_official_jis_v4_examples_match_their_official_schema(name):
    assert _schema_errors(name, _load(name)) == []


def test_the_official_jis_v3_example_breaks_its_own_date_pattern_and_is_read_anyway():
    """Upstream inconsistency: the 3.0.0 example's date has no time zone, which its schema's
    DateTimeTrait does not allow (it wants Z, an offset, or a date alone). It is the only
    error, and the app reads the date as published."""
    name = "io.catenax.just_in_sequence_part-3.0.0"
    assert _schema_errors(name, _load(name)) == ["manufacturingInformation/date"]
    assert parse(JIS_V3, _load(name)).production_date == "2022-02-04T14:48:54"


def test_jis_v3_and_v4_map_to_the_same_fields():
    v3 = parse(JIS_V3, _load("io.catenax.just_in_sequence_part-3.0.0"))
    v4 = parse(JIS_V4, _load("io.catenax.just_in_sequence_part-4.0.0"))
    core = parse(JIS_IC, _load("io.catenax.industry_core.just_in_sequence_part-4.0.0"))
    assert v3.kind == v4.kind == core.kind == PartKind.JIS
    assert (v3.semantic_id, v4.semantic_id, core.semantic_id) == (JIS_V3, JIS_V4, JIS_IC)
    assert v3.global_asset_id == "urn:uuid:580d3adf-1981-44a0-a214-13d6ceed9379"
    # The 4.0.0 example omits the urn:uuid: prefix; the app adds it, as for the other aspects.
    assert v4.global_asset_id == "urn:uuid:aC799196-3E4E-d0Ad-2d6F-e1130EfdF6Fc"
    assert v3.local_identifiers == {"jisNumber": "12345678ABC"}
    assert core.local_identifiers == {"manufacturerId": "BID12345678"}
    assert v3.production_date == "2022-02-04T14:48:54"
    assert v4.production_date == core.production_date == "2025-09-26"
    assert v3.site_ids == ("BPNS1234567890ZZ",)
    assert core.site_ids == ("BPNSR5ftcGHMMhJE",)
    assert v3.name_at_customer == core.name_at_customer == "side element A"
    assert v3.customer_part_id == core.customer_part_id == "PRT-12345"
    assert v3.classifications == core.classifications


def _key_paths(value, prefix=""):
    """The field names of a payload, as paths: what its shape says, without the values."""
    if isinstance(value, dict):
        return {p for k, v in value.items() for p in _key_paths(v, f"{prefix}/{k}")} | {prefix}
    if isinstance(value, list):
        return {p for v in value for p in _key_paths(v, f"{prefix}[]")} | {prefix}
    return {prefix}


def test_a_payload_does_not_say_which_part_aspect_it_is():
    """The official SerialPart and JustInSequencePart examples have exactly the same fields, in
    v3 and in v4; a Batch has a subset of them. Only the semantic ID can tell them apart."""
    for serial, jis in [
        ("io.catenax.serial_part-3.0.0", "io.catenax.just_in_sequence_part-3.0.0"),
        ("io.catenax.serial_part-4.0.0", "io.catenax.just_in_sequence_part-4.0.0"),
        (
            "io.catenax.industry_core.serial_part-4.0.0",
            "io.catenax.industry_core.just_in_sequence_part-4.0.0",
        ),
    ]:
        assert _key_paths(_load(serial)) == _key_paths(_load(jis))
    assert _key_paths(_load("io.catenax.industry_core.batch-4.0.0")) < _key_paths(
        _load("io.catenax.industry_core.just_in_sequence_part-4.0.0")
    )
    # So one payload read under each semantic ID gives each kind, and nothing else differs.
    payload = _load("io.catenax.industry_core.just_in_sequence_part-4.0.0")
    parts = {s: parse(s, payload) for s in (JIS_IC, SERIAL_IC, BATCH_IC)}
    assert [p.kind for p in parts.values()] == [PartKind.JIS, PartKind.SERIAL, PartKind.BATCH]
    as_jis = [dataclasses.replace(p, kind=PartKind.JIS, semantic_id=JIS_IC) for p in parts.values()]
    assert as_jis == [parts[JIS_IC]] * 3


@pytest.mark.parametrize(
    ("semantic_id", "expected"),
    [
        (JIS_V3, AspectType.JUST_IN_SEQUENCE_PART),
        (JIS_V4, AspectType.JUST_IN_SEQUENCE_PART),
        (JIS_IC, AspectType.JUST_IN_SEQUENCE_PART),
        ("urn:samm:io.catenax.just_in_sequence_part:4.0.0", AspectType.JUST_IN_SEQUENCE_PART),
        ("urn:samm:io.catenax.serial_part:4.0.0#SerialPart", AspectType.SERIAL_PART),
        ("urn:samm:io.catenax.batch:4.0.0#Batch", AspectType.BATCH),
    ],
)
def test_the_namespace_decides_the_aspect(semantic_id, expected):
    assert lookup(semantic_id).type == expected


@pytest.mark.parametrize(
    "semantic_id",
    [
        "urn:samm:io.catenax.just_in_sequence_part:3.0.1#JustInSequencePart",
        "urn:samm:io.catenax.just_in_sequence_part:2.0.0#JustInSequencePart",
        "urn:samm:io.catenax.industry_core.just_in_sequence_part:3.0.0#JustInSequencePart",
    ],
)
def test_versions_never_published_are_not_read(semantic_id):
    assert lookup(semantic_id) is None
    with pytest.raises(ValueError, match="unsupported"):
        parse(semantic_id, _load("io.catenax.industry_core.just_in_sequence_part-4.0.0"))


@pytest.mark.parametrize(
    ("semantic_id", "kind"),
    [
        # A fragment naming another element is a publisher's slip: the namespace decides.
        ("urn:samm:io.catenax.serial_part:4.0.0#JustInSequencePart", PartKind.SERIAL),
        ("urn:samm:io.catenax.just_in_sequence_part:4.0.0#SerialPart", PartKind.JIS),
        ("urn:samm:io.catenax.industry_core.batch:4.0.0#JustInSequencePart", PartKind.BATCH),
        ("urn:samm:io.catenax.just_in_sequence_part:4.0.0#justInSequencePart", PartKind.JIS),
    ],
)
def test_a_contradicting_fragment_is_read_by_its_namespace(semantic_id, kind):
    payload = _load("io.catenax.just_in_sequence_part-4.0.0")
    assert parse(semantic_id, payload).kind == kind


def test_a_payload_of_another_model_is_not_read_under_a_contradicting_id():
    """The official BoM and usage 3.0.0 examples: each under the other's namespace, with the
    fragment naming what it really is. Read by the namespace, the usage would be an empty BoM."""
    usage_as_bom = (
        "urn:samm:io.catenax.single_level_bom_as_built:3.0.0#SingleLevelUsageAsBuilt",
        "io.catenax.single_level_usage_as_built-3.0.0",
        "childItems",
    )
    bom_as_usage = (
        "urn:samm:io.catenax.single_level_usage_as_built:3.0.0#SingleLevelBomAsBuilt",
        "io.catenax.single_level_bom_as_built-3.0.0",
        "parentItems",
    )
    part_as_bom = (
        "urn:samm:io.catenax.single_level_bom_as_built:3.0.0#SerialPart",
        "io.catenax.serial_part-3.0.0",
        "childItems",
    )
    bom_as_part = (
        "urn:samm:io.catenax.serial_part:3.0.0#SingleLevelBomAsBuilt",
        "io.catenax.single_level_bom_as_built-3.0.0",
        "partTypeInformation",
    )
    for semantic_id, example, missing in (usage_as_bom, bom_as_usage, part_as_bom, bom_as_part):
        with pytest.raises(AspectPayloadError, match=f"no '{missing}'"):
            parse(semantic_id, _load(example))


def test_the_guard_does_not_apply_to_consistent_ids():
    """A consistent semantic ID is read as before, whatever the payload lacks."""
    bom = parse(
        "urn:samm:io.catenax.single_level_bom_as_built:3.0.0#SingleLevelBomAsBuilt",
        {"catenaXId": "urn:uuid:055c1128-0375-47c8-98de-7cf802c3241d"},
    )
    assert bom.items == ()


def test_a_contradicting_fragment_is_explained():
    from catenax_simplified.aspects import PART_TYPES, contradiction

    assert contradiction("urn:samm:io.catenax.serial_part:4.0.0#JustInSequencePart") == (
        "io.catenax.serial_part:4.0.0 is a SerialPart model, "
        "but the semantic ID names #JustInSequencePart"
    )
    assert contradiction(JIS_IC) is None  # consistent
    assert contradiction("urn:samm:io.catenax.serial_part:4.0.0") is None  # no fragment
    assert contradiction("urn:samm:io.catenax.pcf:7.0.0#Batch") is None  # a model not read
    bom_as_pcf = "urn:samm:io.catenax.single_level_bom_as_built:3.0.0#Pcf"
    assert contradiction(bom_as_pcf) is not None
    assert contradiction(bom_as_pcf, among=PART_TYPES) is None  # not about a part aspect
    bom_as_part = "urn:samm:io.catenax.single_level_bom_as_built:3.0.0#SerialPart"
    assert contradiction(bom_as_part, among=PART_TYPES) is not None


def test_part_aspects_of_one_twin_are_preferred_in_a_fixed_order():
    """Units before batches, then the newest release, then JIS before SerialPart at the same
    release, then the newest version of one aspect."""
    from catenax_simplified.aspects import part_preference
    from catenax_simplified.aspects.registry import SUPPORTED

    part_ids = [
        f"urn:samm:{key}#{aspect.type.value}"
        for key, aspect in SUPPORTED.items()
        if part_preference(f"urn:samm:{key}") is not None
    ]
    ranked = sorted(reversed(part_ids), key=part_preference)
    assert [s.removeprefix("urn:samm:").split("#")[0] for s in ranked] == [
        "io.catenax.industry_core.just_in_sequence_part:4.0.0",
        "io.catenax.industry_core.serial_part:4.0.0",
        "io.catenax.just_in_sequence_part:4.0.0",
        "io.catenax.serial_part:4.0.0",
        "io.catenax.just_in_sequence_part:3.0.0",
        "io.catenax.serial_part:3.0.1",
        "io.catenax.serial_part:3.0.0",
        "io.catenax.industry_core.batch:4.0.0",
        "io.catenax.batch:4.0.0",
        "io.catenax.batch:3.0.1",
        "io.catenax.batch:3.0.0",
    ]
    assert part_preference("urn:samm:io.catenax.single_level_bom_as_built:4.0.0") is None
    # By the namespace, whatever the fragment says.
    assert part_preference("urn:samm:io.catenax.serial_part:4.0.0#Batch") == part_preference(
        "urn:samm:io.catenax.serial_part:4.0.0#SerialPart"
    )


def test_part_types_name_each_part_aspect_once():
    from catenax_simplified.aspects import part_types

    ids = [
        "urn:samm:io.catenax.serial_part:3.0.0#SerialPart",
        "urn:samm:io.catenax.serial_part:4.0.0#SerialPart",
        "urn:samm:io.catenax.single_level_bom_as_built:4.0.0#SingleLevelBomAsBuilt",
    ]
    assert part_types(ids) == [AspectType.SERIAL_PART]  # two versions: no contradiction
    assert part_types([*ids, BATCH_IC, JIS_V3]) == [
        AspectType.JUST_IN_SEQUENCE_PART,
        AspectType.SERIAL_PART,
        AspectType.BATCH,
    ]
