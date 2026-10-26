"""Heat source layers from the Fraunhofer ISI data of Manz et al. (2024).

Turns the raw Fordatis layers (:mod:`fheat_eu.download`) into frames with
the canonical columns of :mod:`fheat_core.columns`. Every value is a
technical potential of a climate-neutral 2050, for two scenarios of the
network temperature: HT (supply 70-90 °C) and LT (60-70 °C). The factors
below are those of the paper (section 2.3, table 1); field names and checks
against its tables: ``docs/potenzialdaten.md``.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box
from shapely.geometry.base import BaseGeometry

from fheat_core import columns as cols

#: maximum distance of a source to the district heating area [m] (paper, table 1)
DEFAULT_BUFFERS = {
    "wastewater": 2000.0,
    "industrial_heat": 20000.0,
    "waste_incineration": 20000.0,
    "river_heat": 5000.0,
    "hydrothermal": 15000.0,
}

#: wastewater plants: full load hours from ReUseHeat, seasonal performance
#: factor of the heat pump per scenario, cooling of the wastewater
WASTEWATER_FULL_LOAD_HOURS = 4421.0
WASTEWATER_SPF = {"ht": 2.7, "lt": 3.6}
WASTEWATER_COOLING_K = 5.0
WATER_HEAT_CAPACITY = 1.163  # kWh/(m³·K)
#: waste incineration: share of the theoretical excess heat a CHP plant recovers
WASTE_INCINERATION_RECOVERY = {"ht": 0.66, "lt": 0.76}
PJ_TO_MWH = 1e9 / 3600.0
#: rivers and lakes: heat pump of a typical project [MW] → (size class, full load hours)
RIVER_CLASSES = {30: ("small", 2000.0), 80: ("medium", 3000.0), 150: ("large", 3000.0)}
#: edge of a geothermal raster cell [m] (EPSG:3035)
GEOTHERMAL_CELL_SIZE = 1000.0

SOURCE_ISI = "Fraunhofer ISI (Manz et al. 2024)"
SOURCE_ISI_HOTMAPS = "Fraunhofer ISI (Manz et al. 2024), Hotmaps"

#: blocks of the sheet Matching_results: (scenario, kind) → first column; then
#: one column per heat source in STUDY_ORDER
_STUDY_BLOCKS = {("ht", "supply"): 4, ("ht", "utilization"): 12, ("lt", "supply"): 21, ("lt", "utilization"): 29}
_STUDY_DEMAND = {"ht": 3, "lt": 20}
STUDY_ORDER = ("biomass", "hydrothermal", "petrothermal", "rivers_lakes", "industrial_eh", "wte", "wwtp", "sludge")
#: left out of the table: biomass is a value of the whole NUTS 2 region,
#: petrothermal a flat estimate (docs/potenzialdaten.md)
STUDY_LEFT_OUT = ("biomass", "petrothermal")
_STUDY_HEADERS = ("Biomass", "Hydrothermal", "Petrothermal", "Rivers_and_lakes", "Industrial_EH", "WtE", "WWTP", "Sludge")
_STUDY_COLUMNS = {
    ("ht", "supply"): cols.STUDY_SUPPLY_HT_MWH,
    ("ht", "utilization"): cols.STUDY_UTILIZATION_HT_MWH,
    ("lt", "supply"): cols.STUDY_SUPPLY_LT_MWH,
    ("lt", "utilization"): cols.STUDY_UTILIZATION_LT_MWH,
}
GWH_TO_MWH = 1e3


def delivered_heat(extraction, spf: float):
    """Heat after a heat pump from the heat it takes from the source: Q · SPF / (SPF − 1)."""
    return extraction * spf / (spf - 1.0)


def distance_and_candidate(out: gpd.GeoDataFrame, area: BaseGeometry, candidate: bool = True) -> None:
    """Distance to ``area`` and (``candidate``) a WGS84 point inside every feature, in place."""
    out[cols.DISTANCE_TO_AREA] = out.geometry.distance(area).astype("float64")
    if candidate:
        centres = out.geometry.representative_point().to_crs("EPSG:4326")
        out[cols.SOURCE_CANDIDATE_LAT] = centres.y.round(6)
        out[cols.SOURCE_CANDIDATE_LON] = centres.x.round(6)


def _require(raw: pd.DataFrame, fields: Iterable[str], what: str) -> None:
    missing = [f for f in fields if f not in raw.columns]
    if missing:
        raise RuntimeError(f"Fordatis-Daten {what} ohne Felder {missing} (Feldnamen geändert?).")


def _numbers(series) -> np.ndarray:
    return pd.to_numeric(series, errors="coerce").astype("float64").values


def _finish(out: gpd.GeoDataFrame, ordered: list) -> gpd.GeoDataFrame:
    return out[ordered + ["geometry"]].sort_values(cols.DISTANCE_TO_AREA, kind="stable").reset_index(drop=True)


def _points(raw: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """One Point per row: the hydrothermal layers hold single-point MultiPoints."""
    if raw.empty or not raw.geom_type.eq("MultiPoint").any():
        return raw.reset_index(drop=True)
    return raw.explode(index_parts=False).reset_index(drop=True)


def wastewater_columns(out: gpd.GeoDataFrame, extraction_mwh) -> None:
    """Extraction power and the heat after the heat pump per scenario, in place.

    The power is the extraction spread over the full load hours of the paper,
    so a plant of this list and one of Hotmaps read the same way.
    """
    out[cols.HEAT_EXTRACTION_MWH] = extraction_mwh
    out[cols.HEAT_EXTRACTION_KW] = extraction_mwh * 1e3 / WASTEWATER_FULL_LOAD_HOURS
    out[cols.HEAT_HT_MWH] = delivered_heat(extraction_mwh, WASTEWATER_SPF["ht"])
    out[cols.HEAT_LT_MWH] = delivered_heat(extraction_mwh, WASTEWATER_SPF["lt"])


WASTEWATER_ORDER = [
    cols.SOURCE_NAME, cols.HEAT_EXTRACTION_KW, cols.HEAT_EXTRACTION_MWH, cols.HEAT_HT_MWH, cols.HEAT_LT_MWH,
    cols.DATA_SOURCE, cols.DISTANCE_TO_AREA, cols.SOURCE_CANDIDATE_LAT, cols.SOURCE_CANDIDATE_LON,
]


def process_wastewater(raw: gpd.GeoDataFrame, area: BaseGeometry) -> gpd.GeoDataFrame:
    """Fordatis wastewater plants (Hotmaps power, ``Power in k`` in kW) → canonical columns.

    Hotmaps derives the power from the design size (about 64 W per
    population equivalent, cooling by 5 K). Rows without a power (−999, 0)
    are left out. ``raw`` and ``area`` share one metric CRS.
    """
    _require(raw, ["Power in k"], "Kläranlagen")
    power = _numbers(raw["Power in k"])
    raw, power = raw[power > 0], power[power > 0]
    out = gpd.GeoDataFrame(geometry=raw.geometry.values, crs=raw.crs)
    out[cols.SOURCE_NAME] = pd.Series(pd.NA, index=out.index, dtype="string")
    wastewater_columns(out, power * WASTEWATER_FULL_LOAD_HOURS * 1e-3)
    out[cols.DATA_SOURCE] = SOURCE_ISI_HOTMAPS
    distance_and_candidate(out, area)
    return _finish(out, WASTEWATER_ORDER)


def process_industrial(
    raw: gpd.GeoDataFrame, area: BaseGeometry, names: Optional[pd.DataFrame] = None
) -> gpd.GeoDataFrame:
    """Fordatis industrial excess heat → canonical columns, with Hotmaps names.

    ``EH_95_GWh`` is the HT, ``EH_55_GWh`` the LT scenario (recovery at 95 /
    55 °C), both after the transformation of the industry until 2050.
    ``names`` (:func:`fheat_eu.download.hotmaps_industry_names`) gives name,
    operator and sector by ``ID_Site``; the coordinates stay those of
    Fordatis, which corrected some sites. Sites from 5000 on have no name.
    """
    _require(raw, ["ID_Site", "EH_55_GWh", "EH_95_GWh"], "Industrie-Abwärme")
    out = gpd.GeoDataFrame(geometry=raw.geometry.values, crs=raw.crs)
    out[cols.SITE_ID] = pd.to_numeric(raw["ID_Site"], errors="coerce").astype("Int64").values
    out[cols.HEAT_HT_MWH] = _numbers(raw["EH_95_GWh"]) * GWH_TO_MWH
    out[cols.HEAT_LT_MWH] = _numbers(raw["EH_55_GWh"]) * GWH_TO_MWH
    for column in (cols.SOURCE_NAME, cols.COMPANY, cols.SUBSECTOR):
        out[column] = pd.Series(pd.NA, index=out.index, dtype="string")
    if names is not None and not names.empty:
        by_id = names.set_index(names["SiteID"].astype("Int64"))
        for column, field in ((cols.SOURCE_NAME, "SiteName"), (cols.COMPANY, "CompanyName"),
                              (cols.SUBSECTOR, "Subsector")):
            out[column] = out[cols.SITE_ID].map(by_id[field]).astype("string")
    out[cols.DATA_SOURCE] = SOURCE_ISI_HOTMAPS
    distance_and_candidate(out, area)
    return _finish(out, [
        cols.SITE_ID, cols.SOURCE_NAME, cols.COMPANY, cols.SUBSECTOR, cols.HEAT_HT_MWH, cols.HEAT_LT_MWH,
        cols.DATA_SOURCE, cols.DISTANCE_TO_AREA, cols.SOURCE_CANDIDATE_LAT, cols.SOURCE_CANDIDATE_LON,
    ])


def repair_name(name, known_names: Iterable[str] = ()) -> Optional[str]:
    """Place name of Fordatis with its lost umlauts restored from ``known_names``.

    The file holds U+FFFD for every non-ASCII letter ("D\\ufffdsseldorf").
    A unique match in ``known_names`` (e.g. the NRW municipalities) replaces
    it; otherwise the letter shows as "?".
    """
    if name is None or (isinstance(name, float) and np.isnan(name)):
        return None
    name = str(name)
    if "�" not in name:
        return name
    pattern = re.compile("^" + ".".join(re.escape(part) for part in name.split("�")) + "$", re.IGNORECASE)
    matches = {k for k in known_names if pattern.match(k)}
    return matches.pop() if len(matches) == 1 else name.replace("�", "?")


def process_waste_incineration(
    raw: gpd.GeoDataFrame, area: BaseGeometry, known_names: Iterable[str] = ()
) -> gpd.GeoDataFrame:
    """Fordatis waste-to-energy plants → canonical columns.

    ``EH100PJ`` is the theoretical excess heat at 100 °C (60 % of the energy
    input, peta 5); a CHP plant recovers 66 % of it in the HT and 76 % in the
    LT scenario. The place name stands for the plant.
    """
    _require(raw, ["City", "EH100PJ"], "Müllverbrennung")
    known = list(known_names)
    out = gpd.GeoDataFrame(geometry=raw.geometry.values, crs=raw.crs)
    out[cols.SOURCE_NAME] = pd.array([repair_name(v, known) for v in raw["City"]], dtype="string")
    theoretical = _numbers(raw["EH100PJ"]) * PJ_TO_MWH
    out[cols.EXCESS_HEAT_THEORETICAL_MWH] = theoretical
    out[cols.HEAT_HT_MWH] = theoretical * WASTE_INCINERATION_RECOVERY["ht"]
    out[cols.HEAT_LT_MWH] = theoretical * WASTE_INCINERATION_RECOVERY["lt"]
    out[cols.DATA_SOURCE] = SOURCE_ISI
    distance_and_candidate(out, area)
    return _finish(out, [
        cols.SOURCE_NAME, cols.EXCESS_HEAT_THEORETICAL_MWH, cols.HEAT_HT_MWH, cols.HEAT_LT_MWH,
        cols.DATA_SOURCE, cols.DISTANCE_TO_AREA, cols.SOURCE_CANDIDATE_LAT, cols.SOURCE_CANDIDATE_LON,
    ])


def process_rivers(raw: gpd.GeoDataFrame, area: BaseGeometry) -> gpd.GeoDataFrame:
    """Fordatis zones of rivers and lakes → canonical columns.

    A zone (up to several thousand km²) marks water with a winter flow of at
    least 20 m³/s; ``Capa in MW`` is the heat pump of ONE typical project of
    its size class, not the potential of the zone. ``heat_mwh`` is that
    project at the full load hours of its class. No source candidate: the
    zone says nothing about where to take the water.
    """
    _require(raw, ["Capa in MW"], "Flüsse und Seen")
    capacity = _numbers(raw["Capa in MW"])
    known = np.isin(capacity, list(RIVER_CLASSES))
    raw, capacity = raw[known], capacity[known]
    out = gpd.GeoDataFrame(geometry=raw.geometry.values, crs=raw.crs)
    out[cols.HEAT_PUMP_CAPACITY_MW] = capacity
    out[cols.RIVER_SIZE_CLASS] = pd.array([RIVER_CLASSES[int(c)][0] for c in capacity], dtype="string")
    hours = np.array([RIVER_CLASSES[int(c)][1] for c in capacity], dtype="float64")
    out[cols.SOURCE_FULL_LOAD_HOURS] = hours
    out[cols.HEAT_MWH] = capacity * hours
    out[cols.DATA_SOURCE] = SOURCE_ISI
    distance_and_candidate(out, area, candidate=False)
    return _finish(out, [
        cols.HEAT_PUMP_CAPACITY_MW, cols.RIVER_SIZE_CLASS, cols.SOURCE_FULL_LOAD_HOURS, cols.HEAT_MWH,
        cols.DATA_SOURCE, cols.DISTANCE_TO_AREA,
    ])


def _cell_values(raw: gpd.GeoDataFrame, field: str) -> pd.Series:
    """Values of a geothermal raster, keyed by the rounded cell centre (EPSG:3035)."""
    points = _points(raw)
    if points.empty:
        return pd.Series(dtype="float64")
    keys = pd.MultiIndex.from_arrays([points.geometry.x.round().astype("int64"),
                                      points.geometry.y.round().astype("int64")], names=["x", "y"])
    values = pd.Series(_numbers(points[field]) * 1e6, index=keys)  # TWh/a → MWh/a
    return values[~values.index.duplicated()]


def process_geothermal_cells(
    raw_ht: gpd.GeoDataFrame, raw_lt: gpd.GeoDataFrame, field: str, area: BaseGeometry, crs
) -> gpd.GeoDataFrame:
    """Two Fordatis geothermal rasters (HT 85 °C, LT 65 °C) → 1 km cells in ``crs``.

    Each point holds the annual heat of its 1 km² (projects of 6.93 km² with
    two boreholes, risk factor and full load hours included), so the cells
    around an area add up. A cell found only in the LT raster has no HT
    value (NaN): the rock is not hot enough for 85 °C. ``raw_*`` are in
    EPSG:3035 (the raster grid), ``area`` in ``crs``.
    """
    for raw, what in ((raw_ht, "HT"), (raw_lt, "LT")):
        if not raw.empty:
            _require(raw, [field], f"Geothermie {what}")
    values = pd.concat({cols.HEAT_HT_MWH: _cell_values(raw_ht, field),
                        cols.HEAT_LT_MWH: _cell_values(raw_lt, field)}, axis=1)
    grid_crs = raw_ht.crs if raw_ht.crs is not None else raw_lt.crs
    half = GEOTHERMAL_CELL_SIZE / 2
    cells = [box(x - half, y - half, x + half, y + half) for x, y in values.index]
    out = gpd.GeoDataFrame(values.reset_index(drop=True), geometry=cells, crs=grid_crs).to_crs(crs)
    out[cols.DATA_SOURCE] = SOURCE_ISI
    distance_and_candidate(out, area)
    return _finish(out, [
        cols.HEAT_HT_MWH, cols.HEAT_LT_MWH, cols.DATA_SOURCE,
        cols.DISTANCE_TO_AREA, cols.SOURCE_CANDIDATE_LAT, cols.SOURCE_CANDIDATE_LON,
    ])


def study_dh_labels(mapping: pd.DataFrame, lau_id: str) -> list[int]:
    """Labels of the study's district heating areas of one municipality (``LAU_ID``, e.g. ``DE_05566084``)."""
    rows = mapping[mapping["LAU_ID"].astype(str) == str(lau_id)]
    return sorted(pd.to_numeric(rows["Label"], errors="coerce").dropna().astype(int).unique().tolist())


def process_study_dh_areas(raw: gpd.GeoDataFrame, labels: Iterable[int]) -> gpd.GeoDataFrame:
    """The study's district heating areas with the given labels → canonical columns."""
    _require(raw, ["Label", "Dem_GWh"], "Wärmenetzgebiete")
    raw = raw[pd.to_numeric(raw["Label"], errors="coerce").isin(list(labels))]
    out = gpd.GeoDataFrame(geometry=raw.geometry.values, crs=raw.crs)
    out[cols.DH_AREA_ID] = pd.to_numeric(raw["Label"], errors="coerce").astype("Int64").values
    out[cols.DH_DEMAND_2050_MWH] = _numbers(raw["Dem_GWh"]) * GWH_TO_MWH
    out[cols.DATA_SOURCE] = SOURCE_ISI
    return out[[cols.DH_AREA_ID, cols.DH_DEMAND_2050_MWH, cols.DATA_SOURCE, "geometry"]].reset_index(drop=True)


def study_table(matching: pd.DataFrame, lau_id: str) -> Optional[pd.DataFrame]:
    """Supply and utilization potentials of one municipality from the sheet Matching_results.

    ``dh_demand`` first, whose value stands in the supply columns, then one
    row per heat source of ``STUDY_ORDER`` with a supply in one of the
    scenarios (a source without one is not there), except ``STUDY_LEFT_OUT``.
    GWh → MWh. None if the study has no district heating area in the
    municipality.
    """
    names = [str(v).strip() for v in matching.iloc[1]]
    for (scenario, kind), first in _STUDY_BLOCKS.items():
        if tuple(names[first:first + len(_STUDY_HEADERS)]) != _STUDY_HEADERS:
            raise RuntimeError(f"Studientabelle: Spalten {scenario}/{kind} nicht wie erwartet (Aufbau geändert?).")
    rows = matching[matching.iloc[:, 0].astype(str) == str(lau_id)]
    if rows.empty:
        return None
    values = pd.to_numeric(rows.iloc[0], errors="coerce")
    table = pd.DataFrame({cols.STUDY_SOURCE: ["dh_demand", *STUDY_ORDER]})
    for (scenario, kind), column in _STUDY_COLUMNS.items():
        first = _STUDY_BLOCKS[(scenario, kind)]
        demand = values.iloc[_STUDY_DEMAND[scenario]] if kind == "supply" else np.nan
        table[column] = np.array([demand, *values.iloc[first:first + len(STUDY_ORDER)]], dtype="float64") * GWH_TO_MWH
    source = table[cols.STUDY_SOURCE]
    supply = table[[cols.STUDY_SUPPLY_HT_MWH, cols.STUDY_SUPPLY_LT_MWH]].fillna(0.0).max(axis=1)
    keep = (source == "dh_demand") | (~source.isin(STUDY_LEFT_OUT) & (supply > 0))
    return table[keep].reset_index(drop=True)
