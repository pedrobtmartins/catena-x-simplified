import re

_URN_UUID_PREFIX = "urn:uuid:"
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def normalize_global_asset_id(value: str) -> str:
    """Return the Catena-X ID in ``urn:uuid:<uuid>`` form.

    Some publishers omit the ``urn:uuid:`` prefix. The case of the UUID is kept as published,
    because partners look IDs up verbatim.
    """
    value = value.strip()
    if _UUID.match(value):
        return _URN_UUID_PREFIX + value
    return value
