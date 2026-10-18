"""One-level as-built tree of a part, answered from the local cache."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from ..storage import PartRepository, PartRow, RelationRow


@dataclass
class TreeNode:
    """A direct parent or child of a part, merged from every aspect that declared the link."""

    global_asset_id: str
    part: PartRow | None
    business_partner: str | None = None
    quantity: float | None = None
    unit: str | None = None
    is_only_potential_parent: bool = False
    # Which aspects declared the relation: "bom" (parent's BoM), "usage" (child's usage).
    declared_in: list[str] = field(default_factory=list)


@dataclass
class PartTree:
    """A part with its direct parents (where it is used) and children (what it is built from)."""

    part: PartRow
    parents: list[TreeNode]
    children: list[TreeNode]


def merge_relations(relations: Iterable[RelationRow], counterpart: str) -> list[TreeNode]:
    """One node per counterpart (``parent_id`` or ``child_id``) of these relations, merging the
    BoM and usage declarations of the same link."""
    nodes: dict[str, TreeNode] = {}
    for relation in relations:
        other = getattr(relation, counterpart)
        node = nodes.setdefault(other, TreeNode(global_asset_id=other, part=None))
        node.declared_in.append(relation.source)
        # The first declaration wins for attributes; later ones only fill gaps.
        node.business_partner = node.business_partner or relation.business_partner
        node.quantity = node.quantity if node.quantity is not None else relation.quantity
        node.unit = node.unit or relation.unit
        node.is_only_potential_parent = (
            node.is_only_potential_parent or relation.is_only_potential_parent
        )
    for node in nodes.values():
        node.declared_in.sort()
    return list(nodes.values())


def part_tree(repository: PartRepository, global_asset_id: str) -> PartTree | None:
    """The one-level as-built tree of a cached part, or ``None`` if the part is not cached.
    Counterparts are filled in from the cache where known.
    """
    part = repository.get_part(global_asset_id)
    if part is None:
        return None
    parents = merge_relations(repository.parents(global_asset_id), "parent_id")
    children = merge_relations(repository.children(global_asset_id), "child_id")
    known = repository.get_parts([n.global_asset_id for n in parents + children])
    for node in parents + children:
        node.part = known.get(node.global_asset_id)
    return PartTree(part=part, parents=parents, children=children)
