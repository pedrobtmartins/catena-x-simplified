from datetime import UTC, datetime

import pytest

from catenax_simplified.storage import (
    PartRepository,
    init_schema,
    make_engine,
    make_session_factory,
)
from catenax_simplified.storage.tables import PartRow, RelationRow
from catenax_simplified.traceability import DataFinding, bom_findings

OWN = "BPNL00000000OWN1"
SUPPLIER = "BPNL0000000SUPP1"


@pytest.fixture
def session():
    engine = make_engine("sqlite:///:memory:")
    init_schema(engine)
    with make_session_factory(engine)() as session:
        yield session


def _part(gid: str, kind: str = "serial", own: bool = True) -> PartRow:
    return PartRow(
        global_asset_id=gid,
        kind=kind,
        semantic_id="urn:samm:io.catenax.serial_part:3.0.0#SerialPart",
        manufacturer_id=OWN if own else SUPPLIER,
        is_own=own,
        synced_at=datetime(2026, 10, 18, tzinfo=UTC),
    )


def _bom(parent: str, child: str, partner: str = SUPPLIER) -> RelationRow:
    return RelationRow(
        parent_id=parent, child_id=child, source="bom", declared_by=parent, business_partner=partner
    )


def test_a_part_in_an_assembly_and_in_its_sub_assembly_is_declared_at_two_levels(session):
    session.add_all(
        [
            _part("vehicle"),
            _part("battery"),
            _part("module"),
            _bom("vehicle", "battery", OWN),
            _bom("battery", "module", OWN),
            # the same cell in the battery and in the module inside it
            _bom("battery", "cell"),
            _bom("module", "cell"),
            # a sensor in the vehicle and two levels down, in the module
            _bom("vehicle", "sensor"),
            _bom("module", "sensor"),
            # declared once: fine
            _bom("module", "connector"),
        ]
    )
    session.flush()

    assert bom_findings(PartRepository(session)) == [
        DataFinding("two_levels", "cell", SUPPLIER, ("battery", "module")),
        DataFinding("two_levels", "sensor", SUPPLIER, ("vehicle", "module")),
    ]


def test_a_serialized_part_in_two_unrelated_assemblies_is_reported_a_batch_is_not(session):
    session.add_all(
        [
            _part("vehicle-1"),
            _part("vehicle-2"),
            _part("glue-lot", kind="batch", own=False),
            _bom("vehicle-1", "wheel"),
            _bom("vehicle-2", "wheel"),
            _bom("vehicle-1", "glue-lot"),
            _bom("vehicle-2", "glue-lot"),
        ]
    )
    session.flush()

    assert bom_findings(PartRepository(session)) == [
        DataFinding("two_assemblies", "wheel", SUPPLIER, ("vehicle-1", "vehicle-2")),
    ]


def test_the_unit_is_named_by_its_instance_id_not_its_manufacturer():
    from catenax_simplified.api.app import instance_id

    assert instance_id({"manufacturerId": OWN, "partInstanceId": "SN-1"}) == "SN-1"
    assert instance_id({"manufacturerId": OWN, "batchId": "LOT-7"}) == "LOT-7"
    assert instance_id({"manufacturerId": OWN}) is None
