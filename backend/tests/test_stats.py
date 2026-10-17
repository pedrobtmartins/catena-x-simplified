from datetime import UTC, datetime

import pytest

from catenax_simplified.storage import (
    PartRepository,
    init_schema,
    make_engine,
    make_session_factory,
)
from catenax_simplified.storage.tables import PartRow, RelationRow

OWN = "BPNL00000000OWN1"
SUPPLIER = "BPNL0000000SUPP1"
CUSTOMER = "BPNL0000000CUST1"


@pytest.fixture
def session():
    engine = make_engine("sqlite:///:memory:")
    init_schema(engine)
    with make_session_factory(engine)() as session:
        yield session


def _part(gid: str, manufacturer: str, own: bool) -> PartRow:
    return PartRow(
        global_asset_id=gid,
        kind="serial",
        semantic_id="urn:samm:io.catenax.serial_part:3.0.0#SerialPart",
        manufacturer_id=manufacturer,
        is_own=own,
        synced_at=datetime(2026, 10, 18, tzinfo=UTC),
    )


def _link(parent: str, child: str, source: str, partner: str | None) -> RelationRow:
    return RelationRow(
        parent_id=parent,
        child_id=child,
        source=source,
        declared_by=parent,
        business_partner=partner,
    )


def test_links_between_own_parts_count_for_neither_suppliers_nor_customers(session):
    session.add_all(
        [
            _part("vehicle", OWN, True),
            _part("battery", OWN, True),
            # vehicle → own battery: internal, from either side
            _link("vehicle", "battery", "bom", OWN),
            # battery → a supplier's cell, twice under two own parents
            _link("battery", "cell-1", "bom", SUPPLIER),
            _link("vehicle", "cell-1", "bom", SUPPLIER),
            # an own child not cached (a subset sync): internal by its partner
            _link("vehicle", "own-child-not-cached", "bom", OWN),
            # the vehicle went to a customer
            _link("customer-fleet", "vehicle", "usage", CUSTOMER),
        ]
    )
    session.flush()

    stats = PartRepository(session).stats(OWN)

    assert stats["own_parts"] == 2
    assert (stats["supplier_links"], stats["suppliers"]) == (2, 1)
    assert (stats["customer_links"], stats["customers"]) == (1, 1)
