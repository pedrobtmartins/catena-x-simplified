from datetime import UTC, datetime

import pytest

from catenax_simplified.storage import (
    PartRepository,
    init_schema,
    make_engine,
    make_session_factory,
)
from catenax_simplified.storage.tables import PartRow, RelationRow
from catenax_simplified.traceability import part_structure, where_used

OWN = "BPNL00000000OWN1"
SUPPLIER = "BPNL0000000SUPP1"
CUSTOMER = "BPNL0000000CUST1"


@pytest.fixture
def session():
    engine = make_engine("sqlite:///:memory:")
    init_schema(engine)
    with make_session_factory(engine)() as session:
        session.add_all(
            [
                _part("vehicle"),
                _part("battery"),
                _part("module"),
                _part("cell", own=False),  # a supplier part, cached by a partner sync
                _link("vehicle", "battery", OWN),
                _link("battery", "module", OWN),
                _link("module", "cell", SUPPLIER),
                _link("battery", "cell", SUPPLIER),  # declared twice
                _link("vehicle", "sensor", SUPPLIER),  # not cached
                # The supplier's own contents are not followed, even where the cache has them.
                _link("cell", "cathode", "BPNL0000000SUPP2"),
                # The vehicle went to a customer's fleet.
                _link("fleet", "vehicle", CUSTOMER, source="usage"),
            ]
        )
        session.flush()
        yield session


def _part(gid: str, own: bool = True) -> PartRow:
    return PartRow(
        global_asset_id=gid,
        kind="serial",
        semantic_id="urn:samm:io.catenax.serial_part:3.0.0#SerialPart",
        manufacturer_id=OWN if own else SUPPLIER,
        is_own=own,
        local_identifiers={"manufacturerId": OWN, "partInstanceId": f"SN-{gid}"},
        synced_at=datetime(2026, 10, 19, tzinfo=UTC),
    )


def _link(parent: str, child: str, partner: str, source: str = "bom") -> RelationRow:
    return RelationRow(
        parent_id=parent,
        child_id=child,
        source=source,
        declared_by=parent if source == "bom" else child,
        business_partner=partner,
        quantity=1,
        unit="unit:piece",
    )


def test_the_structure_opens_every_own_level_and_stops_at_another_company(session):
    structure = part_structure(PartRepository(session), "vehicle", OWN)

    assert set(structure.parts) == {"vehicle", "battery", "module", "cell", "sensor"}
    assert structure.parts["sensor"] is None  # linked, not cached
    links = {(link.parent, link.child) for link in structure.links}
    assert links == {
        ("vehicle", "battery"),
        ("vehicle", "sensor"),
        ("battery", "module"),
        ("battery", "cell"),
        ("module", "cell"),
    }
    assert ("cell", "cathode") not in links
    assert not structure.truncated


def test_a_large_structure_is_cut_and_says_so(session):
    structure = part_structure(PartRepository(session), "vehicle", OWN, max_parts=2)
    assert len(structure.parts) == 2 and structure.truncated


def test_where_used_lists_every_path_up_to_what_nothing_contains(session):
    used = where_used(PartRepository(session), "cell")

    assert sorted(used.paths) == [
        ["cell", "battery", "vehicle", "fleet"],
        ["cell", "module", "battery", "vehicle", "fleet"],
    ]
    assert used.parts["fleet"] is None  # the customer's part, known only by its ID
