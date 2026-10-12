from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import asdict
from datetime import datetime

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from ..aspects import Part, Relations
from .tables import PartRow, RelationRow


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
        own_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Sequence[PartRow], int]:
        query = select(PartRow)
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
