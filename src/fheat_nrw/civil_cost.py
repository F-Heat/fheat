"""ALKIS "Tatsächliche Nutzung" → civil works factor (NRW-specific).

The factors scale the **civil works share** of the pipe costs (€/m). They are
deliberately moderate (close to 1.0), because ALKIS describes only the
legal/planning axis (ownership, permits, restoration standard, closures).
The physical axis — which material actually lies on top — comes from the OSM
``surface`` layer and is multiplied in. Without it, ALKIS alone
differentiates the costs, only moderately (about 0.85…2.50).

Classes: AdV ALKIS object type catalogue (GeoInfoDok), group "Tatsächliche
Nutzung". Table taken unchanged from the previous F|Heat package; calibration
with values from practice is pending.
"""
from __future__ import annotations

import geopandas as gpd

from fheat_core.algorithms.civil_cost import (
    CIVIL_CLASS_COLUMN,
    CIVIL_FACTOR_COLUMN,
    apply_cost_table,
)

#: Factor for areas without a known class.
DEFAULT_LANDUSE_FACTOR: float = 1.0

#: ALKIS object type (or part of it) → civil works factor. Matched with
#: ``match="contains"``, so export variants such as ``"AX_Strassenverkehr"``
#: or the WFS plain text ``"Straßenverkehr"`` hit the same entry.
DEFAULT_ALKIS_COST_TABLE: dict[str, float] = {
    # traffic — moderate surcharge (permits, traffic management, restoration
    # standard); the material comes from OSM `surface`
    "Strassenverkehr": 1.25,
    "Platz": 1.10,
    "Weg": 0.95,
    # crossings — clear surcharge, ALKIS is the only source for
    # "drilling/pressing instead of an open trench" here
    "Bahnverkehr": 2.50,
    "Flugverkehr": 1.80,
    "Schiffsverkehr": 2.20,
    "Fliessgewaesser": 2.50,
    "Hafenbecken": 2.50,
    "StehendesGewaesser": 2.50,
    # settlement — sensitivity/permits, not material
    "Wohnbauflaeche": 0.95,
    "IndustrieUndGewerbeflaeche": 1.05,
    "FlaecheGemischterNutzung": 1.00,
    "FlaecheBesondererFunktionalerPraegung": 1.05,
    "SportFreizeitUndErholungsflaeche": 0.90,
    "Friedhof": 1.40,
    # mining / unstable ground
    "Halde": 1.30,
    "Bergbaubetrieb": 1.30,
    "TagebauGrubeSteinbruch": 1.50,
    # vegetation — small surcharge/discount, OSM refines
    "Landwirtschaft": 0.85,
    "Wald": 1.20,
    "Gehoelz": 0.95,
    "Heide": 0.95,
    # bog/marsh stays a special case (dewatering, sheet piling)
    "Moor": 1.60,
    "Sumpf": 1.60,
    "UnlandVegetationsloseFlaeche": 1.00,
}

#: Columns under which ALKIS exports carry the object type (the first one
#: present is used). The NRW WFS "ave:Nutzung" uses ``nutzart``.
_CLASS_COLUMN_CANDIDATES: tuple[str, ...] = (
    "objektart_txt", "objektart", "OBJART_TXT", "OBJART",
    "nutzart_txt", "nutzart", "NUTZART", "nutzung",
    "klasse", "art", "AdV_klasse",
)


def _pick_class_column(gdf: gpd.GeoDataFrame) -> str | None:
    lower = {str(c).lower(): c for c in gdf.columns}
    for cand in _CLASS_COLUMN_CANDIDATES:
        if cand in gdf.columns:
            return cand
        if cand.lower() in lower:
            return lower[cand.lower()]
    return None


def annotate_landuse_costs(
    landuse_gdf: gpd.GeoDataFrame,
    *,
    class_column: str | None = None,
    cost_table: dict | None = None,
    default_factor: float = DEFAULT_LANDUSE_FACTOR,
) -> gpd.GeoDataFrame:
    """Add ``civil_cost_factor`` and ``civil_class`` (the object type) to ALKIS land use.

    ``class_column`` is detected automatically when not given.
    """
    table = cost_table if cost_table is not None else DEFAULT_ALKIS_COST_TABLE
    col = class_column or _pick_class_column(landuse_gdf)
    if col is None:
        out = landuse_gdf.copy()
        out[CIVIL_FACTOR_COLUMN] = float(default_factor)
        out[CIVIL_CLASS_COLUMN] = None
        return out
    out = apply_cost_table(
        landuse_gdf,
        class_column=col,
        cost_table=table,
        default_factor=default_factor,
        match="contains",
    )
    out[CIVIL_CLASS_COLUMN] = out[col].astype(object).where(out[col].notna(), None)
    return out
