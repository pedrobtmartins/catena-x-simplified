"""The label a person knows one unit or lot by, from a part's local identifiers.

It is a label only: the app identifies every part by its Catena-X ID (``globalAssetId``) and never
by its local identifiers, which are unique only within their publisher's dataspace. The API sends
it as ``serial`` and the UI shows it; the UI does not compute it itself.
"""

from __future__ import annotations

from collections.abc import Mapping

from .model import PartKind

# Who made the part, not which one it is.
MANUFACTURER_KEY = "manufacturerId"
# The identifier that names one serialized unit or one lot, most telling first.
INSTANCE_KEYS = ("partInstanceId", "van", "batchId")
# A just-in-sequence part is "uniquely identified by means of a combination of several IDs
# related to a just-in-sequence process" (JustInSequencePart 3.0.0 and 4.0.0): no one key is
# unique on its own, so the label is all of those present, in this order (the JIS number first,
# so it is what stays when the UI cuts a long label).
JIS_KEYS = ("jisNumber", "parentOrderNumber", "jisCallDate")
JIS_SEPARATOR = " / "
# A JIS part without JIS keys: a unit's own identifier. Never its batch, which names the lot
# the unit comes from, not the unit.
JIS_FALLBACK_KEYS = ("partInstanceId", "van")


def instance_id(local_identifiers: Mapping[str, str], kind: str | None = None) -> str | None:
    """The identifier that names one unit or lot, for a person to recognize it; ``None`` if
    the part has none beyond its manufacturer.

    - Serialized part or batch: ``partInstanceId``, ``van`` or ``batchId``, else any other than
      ``manufacturerId`` (in the order published).
    - Just-in-sequence part (``kind="jis"``): ``jisNumber / parentOrderNumber / jisCallDate``, those
      present, in that order whatever the published order; without any of them,
      ``partInstanceId`` or ``van``, else any other than ``manufacturerId`` and ``batchId``.
    """
    if kind == PartKind.JIS:
        jis = [local_identifiers[k] for k in JIS_KEYS if local_identifiers.get(k)]
        if jis:
            return JIS_SEPARATOR.join(jis)
        for key in JIS_FALLBACK_KEYS:
            if local_identifiers.get(key):
                return local_identifiers[key]
        return next(
            (
                v
                for k, v in local_identifiers.items()
                if k not in (MANUFACTURER_KEY, "batchId") and v
            ),
            None,
        )
    for key in INSTANCE_KEYS:
        if local_identifiers.get(key):
            return local_identifiers[key]
    return next((v for k, v in local_identifiers.items() if k != MANUFACTURER_KEY), None)
