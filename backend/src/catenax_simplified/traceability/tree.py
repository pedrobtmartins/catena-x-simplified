"""One-level as-built tree of a part, answered from the local cache."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from ..storage import PartRepository, PartRow, RelationRow


@dataclass
class TreeNode:
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
    part: PartRow
    parents: list[TreeNode]
    children: list[TreeNode]


def _merge(relations: Iterable[RelationRow], counterpart: str) -> list[TreeNode]:
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
    part = repository.get_part(global_asset_id)
    if part is None:
        return None
    parents = _merge(repository.parents(global_asset_id), "parent_id")
    children = _merge(repository.children(global_asset_id), "child_id")
    known = repository.get_parts([n.global_asset_id for n in parents + children])
    for node in parents + children:
        node.part = known.get(node.global_asset_id)
    return PartTree(part=part, parents=parents, children=children)
