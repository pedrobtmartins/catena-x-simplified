"""The as-built structure of a part through every own level, and where a part is used.

Inside the company every level is known locally, so the structure opens all the way down through
own parts. A part of another company stays a leaf: its contents are that company's, and travel
hop by hop through notifications (the KIT's one-level rule). Where-used walks the other way, from
a part up to the products that contain it, which is the question behind a quality alert.

Both are answered from the local cache; nothing reaches the dataspace.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from ..storage import PartRepository, PartRow
from .tree import merge_relations

# A structure beyond this is not read on one page; the client says so.
MAX_PARTS = 2_000
MAX_PATHS = 200
MAX_DEPTH = 12


@dataclass
class StructureLink:
    """A parent contains a child, as declared by the parent's BoM and/or the child's usage."""

    parent: str
    child: str
    business_partner: str | None
    quantity: float | None
    unit: str | None
    declared_in: list[str]


@dataclass
class PartStructure:
    """A part and everything under it: own parts at every level, other companies' parts as
    leaves."""

    root: str
    parts: dict[str, PartRow | None]
    links: list[StructureLink]
    truncated: bool = False


@dataclass
class WhereUsed:
    """Every path from a part up to a product nothing contains (``paths``: part first)."""

    part: str
    parts: dict[str, PartRow | None]
    paths: list[list[str]] = field(default_factory=list)
    truncated: bool = False


def _is_own(row: PartRow | None, partner: str | None, own_bpnl: str) -> bool:
    return (row is not None and row.is_own) or partner == own_bpnl


def part_structure(
    repository: PartRepository, global_asset_id: str, own_bpnl: str, max_parts: int = MAX_PARTS
) -> PartStructure | None:
    """The structure under a cached part, breadth first, or ``None`` if the part is not cached.
    A part reached twice (declared in two places) is linked twice but listed once."""
    root = repository.get_part(global_asset_id)
    if root is None:
        return None
    structure = PartStructure(root=global_asset_id, parts={global_asset_id: root}, links=[])
    queue = deque([global_asset_id])
    while queue:
        current = queue.popleft()
        nodes = merge_relations(repository.children(current), "child_id")
        known = repository.get_parts([n.global_asset_id for n in nodes])
        for node in nodes:
            child = node.global_asset_id
            if child not in structure.parts and len(structure.parts) >= max_parts:
                structure.truncated = True
                continue
            structure.links.append(
                StructureLink(
                    current,
                    child,
                    node.business_partner,
                    node.quantity,
                    node.unit,
                    node.declared_in,
                )
            )
            if child in structure.parts:
                continue
            row = known.get(child)
            structure.parts[child] = row
            # Only own cached parts have contents here; another company's are its own.
            if row is not None and _is_own(row, node.business_partner, own_bpnl):
                queue.append(child)
    return structure


def where_used(
    repository: PartRepository, global_asset_id: str, max_paths: int = MAX_PATHS
) -> WhereUsed:
    """Every path from the part up to a part nothing contains (a product, or a customer's part
    as far as the cache knows it)."""
    result = WhereUsed(part=global_asset_id, parts={})
    parents_of: dict[str, list[str]] = {}

    def parents(gid: str) -> list[str]:
        if gid not in parents_of:
            parents_of[gid] = [
                n.global_asset_id for n in merge_relations(repository.parents(gid), "parent_id")
            ]
        return parents_of[gid]

    def walk(path: list[str]) -> None:
        if len(result.paths) >= max_paths:
            result.truncated = True
            return
        ups = [p for p in parents(path[-1]) if p not in path]  # a cycle ends the path
        if not ups or len(path) > MAX_DEPTH:
            result.paths.append(path)
            return
        for parent in ups:
            walk([*path, parent])

    walk([global_asset_id])
    ids = {gid for path in result.paths for gid in path}
    known = repository.get_parts(ids)
    result.parts = {gid: known.get(gid) for gid in ids}
    return result
