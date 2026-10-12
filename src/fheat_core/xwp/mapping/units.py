"""Unit conversions from F|Heat to XWaermeplan, in one place.

F|Heat computes heat in kWh/a, heat line density in kWh/(a·m) and areas in
m²; XWaermeplan expects MWh/a, MWh/(m·a), MWh/(ha·a) and ha (see the units
of the model attributes). Results are rounded to a precision that keeps the
files readable without losing anything a heat plan reports.
"""
from __future__ import annotations

KWH_PER_MWH = 1000.0
M2_PER_HA = 10_000.0


def mwh(kwh: float) -> float:
    """kWh/a -> MWh/a."""
    return round(float(kwh) / KWH_PER_MWH, 3)


def mwh_per_m(kwh_per_m: float) -> float:
    """kWh/(a·m) -> MWh/(m·a)."""
    return round(float(kwh_per_m) / KWH_PER_MWH, 4)


def hectares(m2: float) -> float:
    """m² -> ha."""
    return round(float(m2) / M2_PER_HA, 4)


def mwh_per_ha(kwh: float, area_m2: float) -> float | None:
    """Heat density MWh/(ha·a) from kWh/a and an area in m²; None for an empty area."""
    if area_m2 <= 0:
        return None
    return round((float(kwh) / KWH_PER_MWH) / (float(area_m2) / M2_PER_HA), 3)


def percent(part: float, whole: float) -> float:
    """Share in % (0 for an empty whole)."""
    return round(100.0 * part / whole, 2) if whole else 0.0


def metres(m: float) -> float:
    return round(float(m), 2)
