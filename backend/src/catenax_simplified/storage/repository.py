from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import asdict
from datetime import datetime

from sqlalchemy import and_, delete, func, or_, select, true
from sqlalchemy.orm import Session

from ..aspects import Part, Relations
from .tables import (
    NotificationMessageRow,
    NotificationRow,
    PartnerCheckRow,
    PartnerRow,
    PartRow,
    RelationRow,
    SyncRunRow,
)


class PartRepository:
    def __init__(self, session: Session):
        self._session = session

    def upsert_part(
        self, part: Part, *, manufacturer_id: str | None, is_own: bool, synced_at: datetime
    ) -> None:
        row = self._session.get(PartRow, part.global_asset_id) or PartRow(
            global_asset_id=part.global_asset_id
        )
        row.kind = part.kind.value
        row.semantic_id = part.semantic_id
        row.manufacturer_id = manufacturer_id
        row.is_own = is_own
        row.manufacturer_part_id = part.manufacturer_part_id
        row.customer_part_id = part.customer_part_id
        row.name_at_manufacturer = part.name_at_manufacturer
        row.name_at_customer = part.name_at_customer
        row.local_identifiers = dict(part.local_identifiers)
        row.production_date = part.production_date
        row.country = part.country
        row.site_ids = list(part.site_ids)
        row.classifications = [asdict(c) for c in part.classifications]
        row.synced_at = synced_at
        self._session.add(row)

    def replace_relations(self, relations: Relations) -> None:
        """Replace everything the declaring twin previously declared with this aspect."""
        self._session.execute(
            delete(RelationRow).where(
                RelationRow.declared_by == relations.declared_by,
                RelationRow.source == relations.source.value,
            )
        )
        # A twin may list the same counterpart twice; keep the first occurrence.
        seen: set[tuple[str, str]] = set()
        for item in relations.items:
            key = (item.parent_id, item.child_id)
            if key in seen:
                continue
            seen.add(key)
            self._session.add(
                RelationRow(
                    parent_id=item.parent_id,
                    child_id=item.child_id,
                    source=item.source.value,
                    declared_by=relations.declared_by,
                    business_partner=item.business_partner,
                    quantity=item.quantity,
                    unit=item.unit,
                    is_only_potential_parent=item.is_only_potential_parent,
                )
            )

    def delete_own_parts_except(self, keep: Collection[str]) -> int:
        """Remove own parts (and what they declared) that are no longer in the registry."""
        stale = [
            gid
            for gid in self._session.scalars(
                select(PartRow.global_asset_id).where(PartRow.is_own.is_(True))
            )
            if gid not in keep
        ]
        if stale:
            self._session.execute(delete(RelationRow).where(RelationRow.declared_by.in_(stale)))
            self._session.execute(delete(PartRow).where(PartRow.global_asset_id.in_(stale)))
        return len(stale)

    def get_part(self, global_asset_id: str) -> PartRow | None:
        return self._session.get(PartRow, global_asset_id)

    def get_parts(self, global_asset_ids: Collection[str]) -> dict[str, PartRow]:
        if not global_asset_ids:
            return {}
        rows = self._session.scalars(
            select(PartRow).where(PartRow.global_asset_id.in_(list(global_asset_ids)))
        )
        return {row.global_asset_id: row for row in rows}

    def list_parts(
        self,
        *,
        search: str | None = None,
        kind: str | None = None,
        aspect_major: int | None = None,
        own_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Sequence[PartRow], int]:
        query = select(PartRow)
        if aspect_major is not None:
            # semantic IDs look like urn:samm:<namespace>:<major>.<minor>.<patch>#<Aspect>
            query = query.where(PartRow.semantic_id.like(f"%:{aspect_major}.%"))
        if search:
            pattern = f"%{search.lower()}%"
            query = query.where(
                or_(
                    func.lower(PartRow.global_asset_id).like(pattern),
                    func.lower(PartRow.manufacturer_part_id).like(pattern),
                    func.lower(PartRow.customer_part_id).like(pattern),
                    func.lower(PartRow.name_at_manufacturer).like(pattern),
                    func.lower(PartRow.name_at_customer).like(pattern),
                )
            )
        if kind:
            query = query.where(PartRow.kind == kind)
        if own_only:
            query = query.where(PartRow.is_own.is_(True))
        total = self._session.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = self._session.scalars(
            query.order_by(PartRow.name_at_manufacturer, PartRow.global_asset_id)
            .limit(limit)
            .offset(offset)
        ).all()
        return rows, total

    def children(self, global_asset_id: str) -> Sequence[RelationRow]:
        return self._session.scalars(
            select(RelationRow)
            .where(RelationRow.parent_id == global_asset_id)
            .order_by(RelationRow.child_id)
        ).all()

    def parents(self, global_asset_id: str) -> Sequence[RelationRow]:
        return self._session.scalars(
            select(RelationRow)
            .where(RelationRow.child_id == global_asset_id)
            .order_by(RelationRow.parent_id)
        ).all()

    def relation_counts(self, global_asset_ids: Collection[str]) -> dict[str, tuple[int, int]]:
        """``(parents, children)`` per part, counting each counterpart once."""
        ids = list(global_asset_ids)
        counts = {gid: [0, 0] for gid in ids}
        if not ids:
            return {}
        pairs = (
            select(RelationRow.parent_id, RelationRow.child_id)
            .where(or_(RelationRow.parent_id.in_(ids), RelationRow.child_id.in_(ids)))
            .distinct()
        )
        for parent_id, child_id in self._session.execute(pairs):
            if child_id in counts:
                counts[child_id][0] += 1
            if parent_id in counts:
                counts[parent_id][1] += 1
        return {gid: (p, c) for gid, (p, c) in counts.items()}

    def stats(self, own_bpnl: str | None = None) -> dict:
        """Own parts and their links to suppliers and customers. A link between two own parts
        (a vehicle and its own battery, say) is internal: it counts for neither, nor does the
        company itself as a partner."""
        own_ids = select(PartRow.global_asset_id).where(PartRow.is_own.is_(True))
        # A link counts when its other end is not an own part and its partner is not the company.
        external = (
            true()
            if own_bpnl is None
            else or_(
                RelationRow.business_partner.is_(None), RelationRow.business_partner != own_bpnl
            )
        )
        partner = RelationRow.business_partner.is_not(None)
        if own_bpnl is not None:
            partner = and_(partner, RelationRow.business_partner != own_bpnl)

        def distinct_count(query) -> int:
            return self._session.scalar(select(func.count()).select_from(query.subquery())) or 0

        supplier_pairs = (
            select(RelationRow.parent_id, RelationRow.child_id)
            .where(
                RelationRow.parent_id.in_(own_ids), RelationRow.child_id.not_in(own_ids), external
            )
            .distinct()
        )
        customer_pairs = (
            select(RelationRow.parent_id, RelationRow.child_id)
            .where(
                RelationRow.child_id.in_(own_ids), RelationRow.parent_id.not_in(own_ids), external
            )
            .distinct()
        )
        suppliers = (
            select(RelationRow.business_partner)
            .where(
                RelationRow.parent_id.in_(own_ids), RelationRow.child_id.not_in(own_ids), partner
            )
            .distinct()
        )
        customers = (
            select(RelationRow.business_partner)
            .where(
                RelationRow.child_id.in_(own_ids), RelationRow.parent_id.not_in(own_ids), partner
            )
            .distinct()
        )
        by_kind = dict(
            self._session.execute(
                select(PartRow.kind, func.count())
                .where(PartRow.is_own.is_(True))
                .group_by(PartRow.kind)
            ).all()
        )
        by_semantic_id = dict(
            self._session.execute(
                select(PartRow.semantic_id, func.count())
                .where(PartRow.is_own.is_(True))
                .group_by(PartRow.semantic_id)
            ).all()
        )
        return {
            "own_parts": sum(by_kind.values()),
            "own_parts_by_kind": by_kind,
            "own_parts_by_semantic_id": by_semantic_id,
            "supplier_links": distinct_count(supplier_pairs),
            "suppliers": distinct_count(suppliers),
            "customer_links": distinct_count(customer_pairs),
            "customers": distinct_count(customers),
        }

    def bom_children_of_several(self) -> dict[str, list[RelationRow]]:
        """Parts declared in the bill of material of more than one own part: child → the BoM
        relations that declare it."""
        own_ids = select(PartRow.global_asset_id).where(PartRow.is_own.is_(True))
        in_own_bom = and_(RelationRow.source == "bom", RelationRow.parent_id.in_(own_ids))
        several = (
            select(RelationRow.child_id)
            .where(in_own_bom)
            .group_by(RelationRow.child_id)
            .having(func.count(func.distinct(RelationRow.parent_id)) > 1)
        )
        result: dict[str, list[RelationRow]] = {}
        for row in self._session.scalars(
            select(RelationRow)
            .where(in_own_bom, RelationRow.child_id.in_(several))
            .order_by(RelationRow.child_id, RelationRow.parent_id)
        ):
            result.setdefault(row.child_id, []).append(row)
        return result

    def bom_parents(self, global_asset_id: str) -> list[str]:
        """Own parts whose bill of material declares this part."""
        own_ids = select(PartRow.global_asset_id).where(PartRow.is_own.is_(True))
        return list(
            self._session.scalars(
                select(RelationRow.parent_id)
                .where(
                    RelationRow.child_id == global_asset_id,
                    RelationRow.source == "bom",
                    RelationRow.parent_id.in_(own_ids),
                )
                .distinct()
            )
        )

    def partner_counterparts(self) -> dict[str, dict[str, set[str]]]:
        """Direct partners of own parts and the counterpart twins each one owns.

        ``{bpnl: {"supplier": {child ids}, "customer": {parent ids}}}`` — children of own parts
        come from suppliers, parents of own parts belong to customers.
        """
        own_ids = select(PartRow.global_asset_id).where(PartRow.is_own.is_(True))
        result: dict[str, dict[str, set[str]]] = {}

        def add(bpnl: str, role: str, gid: str) -> None:
            roles = result.setdefault(bpnl, {"supplier": set(), "customer": set()})
            roles[role].add(gid)

        for bpnl, child in self._session.execute(
            select(RelationRow.business_partner, RelationRow.child_id).where(
                RelationRow.parent_id.in_(own_ids), RelationRow.business_partner.is_not(None)
            )
        ):
            add(bpnl, "supplier", child)
        for bpnl, parent in self._session.execute(
            select(RelationRow.business_partner, RelationRow.parent_id).where(
                RelationRow.child_id.in_(own_ids), RelationRow.business_partner.is_not(None)
            )
        ):
            add(bpnl, "customer", parent)
        return result

    def partner_part_counts(self) -> dict[str, int]:
        """Number of cached partner parts per partner BPNL."""
        return dict(
            self._session.execute(
                select(PartRow.manufacturer_id, func.count())
                .where(PartRow.is_own.is_(False))
                .group_by(PartRow.manufacturer_id)
            ).all()
        )

    def delete_partner_parts_except(self, manufacturer_id: str, keep: Collection[str]) -> int:
        """Remove a partner's cached parts that are no longer linked to an own part."""
        stale = [
            gid
            for gid in self._session.scalars(
                select(PartRow.global_asset_id).where(
                    PartRow.is_own.is_(False), PartRow.manufacturer_id == manufacturer_id
                )
            )
            if gid not in keep
        ]
        if stale:
            self._session.execute(delete(PartRow).where(PartRow.global_asset_id.in_(stale)))
        return len(stale)


class PartnerRepository:
    def __init__(self, session: Session):
        self._session = session

    def get(self, bpnl: str) -> PartnerRow | None:
        return self._session.get(PartnerRow, bpnl)

    def get_or_create(self, bpnl: str) -> PartnerRow:
        row = self.get(bpnl)
        if row is None:
            row = PartnerRow(bpnl=bpnl, twins_found=0, twins_missing=0)
            self._session.add(row)
        return row

    def all(self) -> Sequence[PartnerRow]:
        return self._session.scalars(select(PartnerRow).order_by(PartnerRow.bpnl)).all()

    def delete(self, row: PartnerRow) -> None:
        self._session.delete(row)


class PartnerCheckRepository:
    def __init__(self, session: Session):
        self._session = session

    def add(self, row: PartnerCheckRow) -> PartnerCheckRow:
        self._session.add(row)
        self._session.flush()
        return row

    def recent(self, bpnl: str | None = None, limit: int = 50) -> Sequence[PartnerCheckRow]:
        query = select(PartnerCheckRow)
        if bpnl:
            query = query.where(PartnerCheckRow.bpnl == bpnl)
        return self._session.scalars(
            query.order_by(PartnerCheckRow.started_at.desc(), PartnerCheckRow.id.desc()).limit(
                limit
            )
        ).all()

    def latest_by_partner(self) -> dict[str, PartnerCheckRow]:
        latest = (
            select(func.max(PartnerCheckRow.id)).group_by(PartnerCheckRow.bpnl).scalar_subquery()
        )
        rows = self._session.scalars(select(PartnerCheckRow).where(PartnerCheckRow.id.in_(latest)))
        return {row.bpnl: row for row in rows}


class SyncRunRepository:
    def __init__(self, session: Session):
        self._session = session

    def add(self, run: SyncRunRow) -> SyncRunRow:
        self._session.add(run)
        self._session.flush()
        return run

    def recent(self, limit: int = 20) -> Sequence[SyncRunRow]:
        return self._session.scalars(
            select(SyncRunRow)
            .order_by(SyncRunRow.started_at.desc(), SyncRunRow.id.desc())
            .limit(limit)
        ).all()


class NotificationRepository:
    def __init__(self, session: Session):
        self._session = session

    def add(self, row: NotificationRow) -> NotificationRow:
        self._session.add(row)
        self._session.flush()
        return row

    def get(self, pk: int) -> NotificationRow | None:
        return self._session.get(NotificationRow, pk)

    def find(self, partner_bpnl: str, notification_id: str) -> NotificationRow | None:
        return self._session.scalar(
            select(NotificationRow).where(
                NotificationRow.partner_bpnl == partner_bpnl,
                NotificationRow.notification_id == notification_id,
            )
        )

    def find_by_message(self, partner_bpnl: str, message_id: str) -> NotificationRow | None:
        """The partner's notification that a message ID refers to (its first message or any
        message logged for it)."""
        row = self._session.scalar(
            select(NotificationRow).where(
                NotificationRow.partner_bpnl == partner_bpnl,
                NotificationRow.initial_message_id == message_id,
            )
        )
        if row is not None:
            return row
        return self._session.scalar(
            select(NotificationRow)
            .join(
                NotificationMessageRow,
                NotificationMessageRow.notification_pk == NotificationRow.id,
            )
            .where(
                NotificationRow.partner_bpnl == partner_bpnl,
                NotificationMessageRow.message_id == message_id,
            )
            .limit(1)
        )

    def list(
        self,
        *,
        direction: str | None = None,
        type: str | None = None,
        status: str | None = None,
        partner_bpnl: str | None = None,
        open_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Sequence[NotificationRow], int]:
        query = select(NotificationRow)
        if direction:
            query = query.where(NotificationRow.direction == direction)
        if type:
            query = query.where(NotificationRow.type == type)
        if status:
            query = query.where(NotificationRow.status == status)
        if partner_bpnl:
            query = query.where(NotificationRow.partner_bpnl == partner_bpnl)
        if open_only:
            query = query.where(NotificationRow.status != "CLOSED")
        total = self._session.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = self._session.scalars(
            query.order_by(NotificationRow.updated_at.desc(), NotificationRow.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        return rows, total

    def forwarded_to(self, pk: int) -> Sequence[NotificationRow]:
        return self._session.scalars(
            select(NotificationRow)
            .where(NotificationRow.forwarded_from_id == pk)
            .order_by(NotificationRow.id)
        ).all()

    def log(self, message: NotificationMessageRow) -> None:
        self._session.add(message)

    def messages(self, pk: int) -> Sequence[NotificationMessageRow]:
        return self._session.scalars(
            select(NotificationMessageRow)
            .where(NotificationMessageRow.notification_pk == pk)
            .order_by(NotificationMessageRow.at, NotificationMessageRow.id)
        ).all()

    def counts(self) -> dict[str, int]:
        """Open notifications per direction, and inbound ones still waiting for us."""
        rows = self._session.execute(
            select(NotificationRow.direction, NotificationRow.status, func.count())
            .where(NotificationRow.status != "CLOSED")
            .group_by(NotificationRow.direction, NotificationRow.status)
        ).all()
        result = {"inbound_open": 0, "outbound_open": 0, "inbound_new": 0}
        for direction, status, count in rows:
            result[f"{direction}_open"] += count
            if direction == "inbound" and status == "RECEIVED":
                result["inbound_new"] += count
        return result
