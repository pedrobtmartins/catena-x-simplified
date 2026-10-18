"""Checks on the own parts' bills of material, run on the local cache.

A serialized unit is in one place at a time. Two patterns in the published BoMs contradict that:

- **two levels**: a part is declared in an assembly's BoM and again in the BoM of one of that
  assembly's own sub-assemblies (a BoM that was partly flattened);
- **two assemblies**: a part is declared in the BoMs of two own parts that do not contain one
  another. Normal for a batch, so it is not reported when the cached part is a batch.

Nothing here reaches the dataspace; the findings point the publishing team to the twins to fix.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Literal

from ..storage import PartRepository

MAX_DEPTH = 12

FindingKind = Literal["two_levels", "two_assemblies"]


@dataclass(frozen=True)
class DataFinding:
    """A part declared in more than one own bill of material, and how."""

    kind: FindingKind
    # The part declared more than once, and who makes it (from the BoM).
    global_asset_id: str
    business_partner: str | None
    # Own parts whose BoM declares it. For "two_levels": the assembly, then its sub-assembly.
    parents: tuple[str, ...]


def _ancestors(
    repository: PartRepository, global_asset_id: str, cache: dict[str, set[str]]
) -> set[str]:
    """Own parts that contain this one through their bills of material, at any depth."""
    if global_asset_id in cache:
        return cache[global_asset_id]
    seen: set[str] = set()
    frontier = [global_asset_id]
    for _ in range(MAX_DEPTH):
        frontier = [p for gid in frontier for p in repository.bom_parents(gid) if p not in seen]
        if not frontier:
            break
        seen.update(frontier)
    cache[global_asset_id] = seen
    return seen


def bom_findings(repository: PartRepository) -> list[DataFinding]:
    """Every finding in the cache: for each part declared in the BoMs of several own parts,
    the pairs where one contains the other (``two_levels``) and, unless the part is a
    batch, the own parts that do not (``two_assemblies``).
    """
    findings: list[DataFinding] = []
    ancestors: dict[str, set[str]] = {}
    for child_id, relations in repository.bom_children_of_several().items():
        parents = list(dict.fromkeys(r.parent_id for r in relations))
        partner = next((r.business_partner for r in relations if r.business_partner), None)
        nested: list[tuple[str, str]] = []
        unrelated: set[str] = set()
        for a, b in combinations(parents, 2):
            if a in _ancestors(repository, b, ancestors):
                nested.append((a, b))
            elif b in _ancestors(repository, a, ancestors):
                nested.append((b, a))
            else:
                unrelated.update((a, b))
        for assembly, sub_assembly in nested:
            findings.append(DataFinding("two_levels", child_id, partner, (assembly, sub_assembly)))
        if unrelated:
            cached = repository.get_part(child_id)
            if cached is None or cached.kind != "batch":
                findings.append(
                    DataFinding("two_assemblies", child_id, partner, tuple(sorted(unrelated)))
                )
    return findings
