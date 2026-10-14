"""Own data of a Tier-1 battery module maker, mixing v3 and v4 publications."""

from __future__ import annotations

from builders import (
    BOM_V3,
    BOM_V4,
    PCF,
    SERIAL_PART_V3,
    SERIAL_PART_V4,
    USAGE_V4,
    bom_v3,
    bom_v4,
    part_v3,
    part_v4,
    shell_descriptor,
    usage_v4,
)

TIER1 = "BPNL000000000T1A"
TIER2 = "BPNL000000000T2A"
OEM = "BPNL000000000OEM"

MODULE_A = "urn:uuid:aaaaaaaa-0000-4000-8000-000000000001"
MODULE_B = "urn:uuid:aaaaaaaa-0000-4000-8000-000000000002"
CELL_1 = "urn:uuid:cccccccc-0000-4000-8000-000000000001"
CELL_2 = "urn:uuid:cccccccc-0000-4000-8000-000000000002"
CELL_3 = "urn:uuid:cccccccc-0000-4000-8000-000000000003"
VEHICLE = "urn:uuid:eeeeeeee-0000-4000-8000-000000000001"

BASE = "https://edc.tier1.example/api/public"


def _href(gid: str, aspect: str) -> str:
    return f"{BASE}/{gid}/{aspect}/submodel"


def shells() -> list[dict]:
    return [
        # Module A published with the latest models; installed in the OEM vehicle.
        shell_descriptor(
            MODULE_A,
            {
                SERIAL_PART_V4: _href(MODULE_A, "serialpart"),
                BOM_V4: _href(MODULE_A, "bom"),
                USAGE_V4: _href(MODULE_A, "usage"),
                PCF: _href(MODULE_A, "pcf"),
            },
            manufacturer_id=TIER1,
        ),
        # Module B still published with v3 models.
        shell_descriptor(
            MODULE_B,
            {SERIAL_PART_V3: _href(MODULE_B, "serialpart"), BOM_V3: _href(MODULE_B, "bom")},
            manufacturer_id=TIER1,
        ),
    ]


def payloads() -> dict:
    return {
        _href(MODULE_A, "serialpart") + "/$value": part_v4(MODULE_A, "Battery module", "MOD-1"),
        _href(MODULE_A, "bom") + "/$value": bom_v4(MODULE_A, [CELL_1, CELL_2], TIER2),
        _href(MODULE_A, "usage") + "/$value": usage_v4(MODULE_A, [VEHICLE], OEM),
        _href(MODULE_B, "serialpart") + "/$value": part_v3(
            MODULE_B, "Battery module", "MOD-1", serial="SN2"
        ),
        _href(MODULE_B, "bom") + "/$value": bom_v3(MODULE_B, [CELL_3], TIER2),
    }


# --- the Tier-2 supplier's registry, as seen through the dataspace -------------------------

TIER2_CONNECTOR = "https://edc.tier2.example/api/v1/dsp"
TIER2_BASE = "https://edc.tier2.example/api/public"


def _tier2_href(gid: str) -> str:
    return f"{TIER2_BASE}/{gid}/serialpart/submodel"


def tier2_twins() -> dict:
    """CELL_1 (v3) and CELL_3 (v4) are published; CELL_2 is not in Tier-2's registry."""
    return {
        (TIER2, CELL_1): shell_descriptor(CELL_1, {SERIAL_PART_V3: _tier2_href(CELL_1)}),
        (TIER2, CELL_3): shell_descriptor(CELL_3, {SERIAL_PART_V4: _tier2_href(CELL_3)}),
    }


def tier2_payloads() -> dict:
    return {
        _tier2_href(CELL_1) + "/$value": part_v3(CELL_1, "Li-ion cell", "CELL-21700", serial="C1"),
        _tier2_href(CELL_3) + "/$value": part_v4(CELL_3, "Li-ion cell", "CELL-21700", serial="C3"),
    }
