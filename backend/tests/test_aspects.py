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


def test_lookup_ignores_fragment():
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
