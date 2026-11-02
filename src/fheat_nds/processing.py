"""Buildings of Lower Saxony with a calculated heat demand.

Lower Saxony publishes no heat demand per building (the KEAN heat demand map
goes to municipalities only), so every building is calculated the way
:mod:`fheat_de.heat_demand` does for any state:

- the ALKIS buildings ("Gebäude") whose function is energetically relevant
  (``energetisch_relevant`` in ``building_functions.json``), without the
  annexes: a building without address that is residential or a generic
  "Gebäude für Wirtschaft oder Gewerbe", or has less than 50 m² footprint
  (garden sheds, garages; in the Gemarkung Bad Bentheim 3 054 such buildings
  with 15 GWh/a, the indoor pool or school halls without address stay);
- storeys from the eaves height of the LoD2 building the ALKIS building lies
  in (:func:`fheat_de.heat_demand.storeys_from_height`); without one, the
  median storeys of the residential buildings that have one (2 without any);
- net floor area = 0.7 × footprint × storeys;
- age class of the Zensus 2022 cell (:mod:`fheat_de.zensus`); without one,
  the most frequent class of the area (E, 1958–1968, without any);
- residential: EFH up to 280 m² net floor area, MFH above;
- heat demand = net floor area × specific heat demand of age class and type
  (residential) or of the function (others), load profile and full load
  hours of the function.

``data_source`` says how the storeys were found.
"""
from __future__ import annotations

from typing import Optional

import geopandas as gpd
import numpy as np
import pandas as pd

from fheat_core import columns as cols
from fheat_de import heat_demand as hd
from fheat_de.alkis import ADDRESS_COLUMN, RESIDENTIAL_FUNCTIONS

SOURCE_LOD2 = "alkis_lod2"        # storeys from the LoD2 eaves height
SOURCE_ASSUMED = "alkis_assumed"  # storeys assumed
#: Storeys of a building without LoD2 when no building of the area has one.
DEFAULT_STOREYS = 2
#: Age class when the Zensus gives none for the whole area (1958–1968).
DEFAULT_AGE_CLASS = "E"
#: Besides the residential functions, the function of an annex without
#: address: the generic "Gebäude für Wirtschaft oder Gewerbe".
ANNEX_FUNCTION = 2000
#: Footprint [m²] below which a building without address is an annex.
MIN_ANNEX_FREE_FOOTPRINT = 50.0
_HEAT = "_heat"


def process_buildings(
    alkis: gpd.GeoDataFrame,
    lod2: Optional[gpd.GeoDataFrame],
    age_classes: pd.Series,
    functions: pd.DataFrame,
    age_table: pd.DataFrame,
    storey_height: float = hd.STOREY_HEIGHT_M,
    efh_max: float = hd.EFH_MAX_FLOOR_AREA,
) -> gpd.GeoDataFrame:
    """BuildingsSchema-conformant buildings from ALKIS buildings (see the module docstring).

    ``age_classes`` is aligned with ``alkis`` (NaN where the Zensus has none).
    """
    function = alkis["gfkzshh"].astype("string").str[-4:]
    relevant = function.isin(_relevant_functions(functions)) & ~_annexes(alkis, function)
    bld = gpd.GeoDataFrame(
        {
            "citygml_fu": alkis["gfkzshh"].astype("string"),
            "Nutzung": alkis["funktion"],
            "Adresse": alkis[ADDRESS_COLUMN].fillna("").astype("string"),
            "BAK": age_classes.reindex(alkis.index),
            "_residential": pd.to_numeric(function, errors="coerce").between(*RESIDENTIAL_FUNCTIONS),
        },
        geometry=alkis.geometry.to_numpy(),
        crs=alkis.crs,
    )[relevant.to_numpy()].reset_index(drop=True)
    if bld.empty:
        raise ValueError("Keine ALKIS-Gebaeude mit energetisch relevanter Funktion im Gebiet.")

    storeys = hd.storeys_from_height(_eaves_heights(bld, lod2), storey_height)
    measured = storeys.notna()
    known = storeys[measured & bld["_residential"]]
    assumed = max(1, int(round(known.median()))) if not known.empty else DEFAULT_STOREYS
    bld["STKW"] = storeys.fillna(assumed)
    bld[cols.DATA_SOURCE] = np.where(measured, SOURCE_LOD2, SOURCE_ASSUMED)
    bld["NF"] = hd.net_floor_area(bld.geometry.area, bld["STKW"])
    fallback = bld["BAK"].mode().iloc[0] if bld["BAK"].notna().any() else DEFAULT_AGE_CLASS
    bld["BAK"] = bld["BAK"].fillna(fallback)
    bld["type"] = np.where(bld["_residential"], hd.residential_type(bld["NF"], efh_max), "NWG")

    bld = hd.add_full_load_hours_and_profile(bld, functions)
    bld = bld[bld["Lastprofil"].notna()].copy()
    bld[_HEAT] = 0.0
    bld = hd.add_calculated_heat_demand(bld, age_table, functions, _HEAT)
    bld = bld[bld[_HEAT] > 0].reset_index(drop=True)
    if bld.empty:
        raise ValueError("Keine Gebaeude mit Waermebedarf > 0 im Gebiet.")
    bld = hd.add_thermal_power(bld, _HEAT)
    return _to_schema(bld)


def _annexes(alkis: gpd.GeoDataFrame, function: pd.Series) -> pd.Series:
    """Buildings without address that are annexes (see :data:`ANNEX_FUNCTION`, :data:`MIN_ANNEX_FREE_FOOTPRINT`)."""
    no_address = alkis[ADDRESS_COLUMN].fillna("").astype(str).str.strip() == ""
    code = pd.to_numeric(function, errors="coerce")
    annex_function = code.between(*RESIDENTIAL_FUNCTIONS) | (code == ANNEX_FUNCTION)
    small = alkis.geometry.area < MIN_ANNEX_FREE_FOOTPRINT
    return (no_address & (annex_function | small)).fillna(False)


def _relevant_functions(functions: pd.DataFrame) -> set[str]:
    """Function codes (last four digits) of energetically relevant buildings."""
    if "energetisch_relevant" not in functions.columns:
        return set(functions["Funktion"].astype(str))
    relevant = pd.to_numeric(functions["energetisch_relevant"], errors="coerce") == 1
    return set(functions.loc[relevant, "Funktion"].astype(str))


def _eaves_heights(bld: gpd.GeoDataFrame, lod2: Optional[gpd.GeoDataFrame]) -> pd.Series:
    """Eaves height above ground of the LoD2 building each building's point lies in (NaN without)."""
    heights = pd.Series(np.nan, index=bld.index)
    if lod2 is None or lod2.empty or lod2["eaves_height"].isna().all():
        return heights
    lod2 = lod2.to_crs(bld.crs) if lod2.crs != bld.crs else lod2
    points = gpd.GeoDataFrame(geometry=bld.geometry.representative_point(), crs=bld.crs)
    hit = gpd.sjoin(points, lod2[["eaves_height", "geometry"]], predicate="within")
    hit = hit[~hit.index.duplicated()]
    heights.loc[hit.index] = hit["eaves_height"].to_numpy()
    return heights


def _to_schema(bld: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """The canonical columns of :mod:`fheat_core.columns`."""
    out = {
        cols.BUILDING_ID: np.arange(len(bld), dtype="int32"),
        cols.CONNECT: np.ones(len(bld), dtype="int32"),
        cols.HEAT_DEMAND: bld[_HEAT].astype("float64"),
        cols.THERMAL_POWER: bld["power_th"].astype("float64"),
        cols.FULL_LOAD_HOURS: bld["Vlh"].astype("float64"),
        cols.LOAD_PROFILE: bld["Lastprofil"].astype("string"),
        cols.HEAT_DEMAND_CALCULATED: bld["Waermebedarf"].astype("float64"),
        cols.FUNCTION: bld["citygml_fu"],
        cols.BUILDING_TYPE: bld["type"],
        cols.USAGE: bld["Nutzung"],
        cols.ADDRESS: bld["Adresse"].astype("string"),
        cols.FLOOR_AREA: bld["NF"].astype("float64"),
        cols.CONSTRUCTION_CLASS: bld["BAK"],
        cols.DATA_SOURCE: bld[cols.DATA_SOURCE].astype("string"),
    }
    return gpd.GeoDataFrame(out, geometry=bld.geometry.to_numpy(), crs=bld.crs)
