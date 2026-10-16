"""Usage policies compared by meaning, across Jupiter (DSP 0.8) and Saturn (DSP 2025-1).

The same Catena-X policy reaches the app in several spellings: a Saturn connector offers
``{"leftOperand": "FrameworkAgreement", "operator": "eq", ...}`` (or the operand's full IRI), a
Jupiter connector ``{"odrl:leftOperand": {"@id": "cx-policy:FrameworkAgreement"}, "odrl:operator":
{"@id": "odrl:eq"}, ...}``. ``canonical`` reduces each to one form, so an accepted policy written
in either spelling matches an offer in either.
"""

from __future__ import annotations

import json
from typing import Any

# Prefixes and namespaces of ODRL terms and Catena-X policy operands, removed for comparison.
_ODRL = ("odrl:", "http://www.w3.org/ns/odrl/2/")
_CATENAX = (
    "cx-policy:",
    "https://w3id.org/catenax/policy/",
    "https://w3id.org/catenax/2025/9/policy/",
)
_METADATA = ("@id", "@type", "@context")


def _strip(value: str, prefixes: tuple[str, ...]) -> str:
    for prefix in prefixes:
        if value.startswith(prefix):
            return value[len(prefix) :]
    return value


def _term(value: Any) -> Any:
    """A term (key, action, operator, operand) without its ODRL or Catena-X prefix."""
    if isinstance(value, dict) and set(value) <= {"@id", "@type"} and "@id" in value:
        value = value["@id"]
    if isinstance(value, str):
        return _strip(_strip(value, _ODRL), _CATENAX)
    return value


def canonical(value: Any) -> Any:
    """``value`` with prefixes, ``@id``/``@type`` and single-element lists removed and lists
    sorted, so that equal policies compare equal."""
    if isinstance(value, dict):
        if set(value) <= {"@id", "@type"} and "@id" in value:
            return _term(value)
        result = {}
        for key, item in value.items():
            if key in _METADATA:
                continue
            name = _term(key)
            item = canonical(item)
            if item == []:
                continue  # "prohibition": [] is the same as no prohibition
            if name in ("action", "leftOperand", "operator"):
                item = _term(item)
            result[name] = item
        return result
    if isinstance(value, list):
        items = [canonical(item) for item in value]
        if len(items) == 1:
            return items[0]
        return sorted(items, key=lambda item: json.dumps(item, sort_keys=True))
    return value


def same_policy(a: Any, b: Any) -> bool:
    return canonical(a) == canonical(b)


def offers_of(dataset: dict) -> list[dict]:
    """The policies (``hasPolicy``) a catalog dataset offers."""
    for key in ("odrl:hasPolicy", "hasPolicy", "http://www.w3.org/ns/odrl/2/hasPolicy"):
        if key in dataset:
            offers = dataset[key]
            return [o for o in (offers if isinstance(offers, list) else [offers]) if o]
    return []


def describe(policy: Any) -> str:
    """A short form for messages: ``FrameworkAgreement=DataExchangeGovernance:1.0, …``."""
    constraints: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            if "leftOperand" in node:
                right = node.get("rightOperand")
                right = "|".join(map(str, right)) if isinstance(right, list) else right
                operator = node.get("operator")
                sign = "=" if operator == "eq" else f" {operator} "
                constraints.append(f"{node['leftOperand']}{sign}{right}")
            else:
                for item in node.values():
                    walk(item)

    walk(canonical(policy))
    return ", ".join(sorted(constraints)) or "no constraints"
