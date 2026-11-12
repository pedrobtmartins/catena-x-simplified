"""The label a unit or lot is known by (``aspects.instance_id``), per kind of part.

The official examples carry one local identifier each, so they only show the simplest cases; the
combinations are given here as local identifiers directly (never as aspect payloads).
"""

import json
from itertools import permutations
from pathlib import Path

import pytest

from catenax_simplified.aspects import PartKind, instance_id, parse

FIXTURES = Path(__file__).parent / "fixtures" / "aspects"
OWN = "BPNL00000000OWN1"


def _official(namespace: str, version: str, aspect: str):
    payload = json.loads((FIXTURES / f"{namespace}-{version}.json").read_text())
    return parse(f"urn:samm:{namespace}:{version}#{aspect}", payload)


# --- the official examples, as read -----------------------------------------------------------


@pytest.mark.parametrize(
    ("namespace", "version", "aspect", "expected"),
    [
        ("io.catenax.serial_part", "3.0.0", "SerialPart", "SN12345678"),
        ("io.catenax.batch", "3.0.0", "Batch", "BID12345678"),
        ("io.catenax.just_in_sequence_part", "3.0.0", "JustInSequencePart", "12345678ABC"),
        # The 4.0.0 examples only say who made the part: no label, the UI shows the Catena-X ID.
        ("io.catenax.just_in_sequence_part", "4.0.0", "JustInSequencePart", None),
        ("io.catenax.industry_core.just_in_sequence_part", "4.0.0", "JustInSequencePart", None),
        ("io.catenax.industry_core.serial_part", "4.0.0", "SerialPart", None),
    ],
)
def test_official_examples(namespace, version, aspect, expected):
    part = _official(namespace, version, aspect)
    assert instance_id(part.local_identifiers, part.kind) == expected


# --- serialized parts and batches: unchanged ------------------------------------------------


def test_a_unit_or_lot_is_named_by_its_instance_id_not_its_manufacturer():
    for kind in (None, PartKind.SERIAL, PartKind.BATCH):
        assert instance_id({"manufacturerId": OWN, "partInstanceId": "SN-1"}, kind) == "SN-1"
        assert instance_id({"manufacturerId": OWN, "batchId": "LOT-7"}, kind) == "LOT-7"
        assert instance_id({"manufacturerId": OWN, "van": "VAN-1"}, kind) == "VAN-1"
        assert instance_id({"manufacturerId": OWN}, kind) is None
        # A serialized cell of a lot (SerialPart 3 allows both): the unit, not the lot.
        assert instance_id({"batchId": "LOT-7", "partInstanceId": "SN-1"}, kind) == "SN-1"


def test_jis_keys_on_a_serialized_part_do_not_replace_its_serial_number():
    """v4 SerialParts share the key list that includes the JIS keys; their serial still wins."""
    ids = {"jisNumber": "J-1", "partInstanceId": "SN-1", "manufacturerId": OWN}
    assert instance_id(ids, PartKind.SERIAL) == "SN-1"
    assert instance_id(ids, PartKind.JIS) == "J-1"


# --- just-in-sequence parts -------------------------------------------------------------------

JIS_CALL = {
    "manufacturerId": OWN,
    "jisNumber": "JIS-0815",
    "parentOrderNumber": "ORD-4711",
    "jisCallDate": "2026-04-14",
}


def test_a_jis_part_is_named_by_the_combination_of_its_jis_keys():
    assert instance_id(JIS_CALL, PartKind.JIS) == "JIS-0815 / ORD-4711 / 2026-04-14"
    assert instance_id(JIS_CALL, "jis") == "JIS-0815 / ORD-4711 / 2026-04-14"  # as stored


def test_the_jis_label_does_not_depend_on_the_published_order():
    labels = {instance_id(dict(order), PartKind.JIS) for order in permutations(JIS_CALL.items())}
    assert labels == {"JIS-0815 / ORD-4711 / 2026-04-14"}


def test_two_jis_calls_with_the_same_number_get_different_labels():
    """The JIS number alone is not the identity: the same number on another call date or for
    another order is another unit, and the label shows it."""
    other_day = {**JIS_CALL, "jisCallDate": "2026-04-15"}
    other_order = {**JIS_CALL, "parentOrderNumber": "ORD-4712"}
    labels = {instance_id(ids, PartKind.JIS) for ids in (JIS_CALL, other_day, other_order)}
    assert len(labels) == 3
    assert all(label.startswith("JIS-0815 / ") for label in labels)  # what the UI keeps


@pytest.mark.parametrize(
    ("ids", "expected"),
    [
        ({"jisNumber": "JIS-0815"}, "JIS-0815"),
        ({"jisNumber": "JIS-0815", "jisCallDate": "2026-04-14"}, "JIS-0815 / 2026-04-14"),
        ({"parentOrderNumber": "ORD-4711", "jisCallDate": "2026-04-14"}, "ORD-4711 / 2026-04-14"),
        ({"jisNumber": "", "parentOrderNumber": "ORD-4711"}, "ORD-4711"),  # empty values skipped
        # The JIS combination wins over a unit's own identifiers on a JIS part.
        ({"partInstanceId": "SN-1", "jisNumber": "JIS-0815"}, "JIS-0815"),
        # Without JIS keys: the unit's own identifier, never the lot it comes from.
        ({"batchId": "LOT-7", "partInstanceId": "SN-1"}, "SN-1"),
        ({"batchId": "LOT-7", "van": "VAN-1"}, "VAN-1"),
        ({"manufacturerId": OWN, "batchId": "LOT-7"}, None),
        ({"manufacturerId": OWN, "batchId": "LOT-7", "customKey:line": "L3"}, "L3"),
        ({"manufacturerId": OWN}, None),
        ({}, None),
    ],
)
def test_jis_label_cases(ids, expected):
    assert instance_id(ids, PartKind.JIS) == expected
