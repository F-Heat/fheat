"""Potential layers of the NRW adapter: geothermal and solar thermal.

Turns the raw sources (GD NRW WFS IS GT 50, LANUK heat study) into frames
with the canonical columns of :mod:`fheat_core.columns`. Field names and
units of the sources: ``docs/potenzialdaten.md``.
"""
from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import Mapping, Optional

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry.base import BaseGeometry

from fheat_core import columns as cols

#: GD NRW layer key → column of its "capacity" value
GEOTHERMAL_COLUMNS = {
    "ews40": cols.GROUND_CONDUCTIVITY_40,
    "ews60": cols.GROUND_CONDUCTIVITY_60,
    "ews80": cols.GROUND_CONDUCTIVITY_80,
    "ews100": cols.GROUND_CONDUCTIVITY_100,
    "ewk1800": cols.COLLECTOR_EXTRACTION_1800,
    "ewk2400": cols.COLLECTOR_EXTRACTION_2400,
}
#: probe length [m] → conductivity column
CONDUCTIVITY_BY_DEPTH = {
    40: cols.GROUND_CONDUCTIVITY_40,
    60: cols.GROUND_CONDUCTIVITY_60,
    80: cols.GROUND_CONDUCTIVITY_80,
    100: cols.GROUND_CONDUCTIVITY_100,
}
BOREHOLE_COLUMNS = {1800: cols.BOREHOLE_EXTRACTION_1800, 2400: cols.BOREHOLE_EXTRACTION_2400}

#: LANUK ONG/MTG field → (column, factor); kWh/a → MWh/a like the other results
BLOCK_FIELDS = {
    "ON_kWh_ist": (cols.ONG_POTENTIAL_MWH, 1e-3),
    "ON_kWh_45": (cols.ONG_POTENTIAL_2045_MWH, 1e-3),
    "MT_kWh_ist": (cols.MTG_POTENTIAL_MWH, 1e-3),
    "MT_kWh_45": (cols.MTG_POTENTIAL_2045_MWH, 1e-3),
    "Heizlast": (cols.BLOCK_HEATING_LOAD, 1.0),
    "Heizlast45": (cols.BLOCK_HEATING_LOAD_2045, 1.0),
}
BLOCK_ID_FIELD = "block_id"

#: pieces of the overlay smaller than this are slivers [m²]
MIN_PIECE_AREA = 1.0


def load_borehole_table(path: Optional[Path] = None) -> dict:
    """Extraction table for borehole heat exchangers (package default: VDI 4640-2:2001)."""
    if path is not None:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    with files("fheat_nrw.data").joinpath("borehole_extraction.json").open("r", encoding="utf-8") as f:
        return json.load(f)


def borehole_extraction(conductivity: pd.Series, table: Mapping, hours: int) -> pd.Series:
    """Screening value of the borehole extraction [W/m] from the conductivity.

    Classes of ``table`` in order; a class takes every conductivity up to its
    ``max`` (``max_inclusive`` decides the bound, ``max: null`` is open).
    Missing conductivity → NaN. Not for the design of a plant.
    """
    lam = pd.to_numeric(conductivity, errors="coerce")
    conditions, values = [], []
    for item in table["classes"]:
        upper = item.get("max")
        if upper is None:
            cond = lam.notna()
        elif item.get("max_inclusive", False):
            cond = lam <= float(upper)
        else:
            cond = lam < float(upper)
        conditions.append(cond.to_numpy())
        values.append(float(item[f"extraction_{hours}"]))
    out = np.select(conditions, values, default=np.nan)
    return pd.Series(np.where(lam.notna(), out, np.nan), index=conductivity.index, dtype="float64")


def _first_available(frame: pd.DataFrame, columns: list[str]) -> pd.Series:
    values = pd.Series(np.nan, index=frame.index, dtype="float64")
    for column in columns:
        values = values.fillna(frame[column])
    return values


def _value_polygons(raw: gpd.GeoDataFrame, column: str, area: BaseGeometry, crs) -> gpd.GeoDataFrame:
    layer = raw.to_crs(crs) if raw.crs is not None and raw.crs != crs else raw
    layer = gpd.GeoDataFrame(
        {column: pd.to_numeric(layer["capacity"], errors="coerce").astype("float64")},
        geometry=layer.geometry.buffer(0).intersection(area).values,
        crs=crs,
    )
    layer = layer[~layer.geometry.is_empty & layer[column].notna()]
    if layer.empty:
        return layer
    # one (multi)polygon per value keeps the overlay small
    return layer.dissolve(by=column, as_index=False)[[column, "geometry"]]


def merge_geothermal_layers(
    raw: Mapping[str, Optional[gpd.GeoDataFrame]],
    area: BaseGeometry,
    crs,
    table: Optional[Mapping] = None,
) -> gpd.GeoDataFrame:
    """The GD NRW layers of ``raw`` (key → WFS frame) overlaid inside ``area``.

    Every piece of ``area`` carries the conductivities, the collector
    extraction and the derived borehole screening values. Where a layer has
    no feature the value is NaN, never 0; :data:`cols.GEOTHERMAL_STATUS` says
    whether all, some or none of the layers assess the piece.
    """
    table = table or load_borehole_table()
    merged = gpd.GeoDataFrame(geometry=[area], crs=crs)
    for key, column in GEOTHERMAL_COLUMNS.items():
        layer = raw.get(key)
        polygons = None if layer is None or layer.empty else _value_polygons(layer, column, area, crs)
        if polygons is None or polygons.empty:
            merged[column] = np.nan
            continue
        merged = gpd.overlay(merged, polygons, how="identity", keep_geom_type=True)
    merged = merged.explode(index_parts=False).reset_index(drop=True)
    merged = merged[merged.geometry.area >= MIN_PIECE_AREA].reset_index(drop=True)

    depths = [int(d) for d in table.get("conductivity_depth_m", [100, 80, 60, 40])]
    conductivity = _first_available(merged, [CONDUCTIVITY_BY_DEPTH[d] for d in depths])
    for hours, column in BOREHOLE_COLUMNS.items():
        merged[column] = borehole_extraction(conductivity, table, hours)

    n_assessed = merged[list(GEOTHERMAL_COLUMNS.values())].notna().sum(axis=1)
    merged[cols.GEOTHERMAL_STATUS] = np.select(
        [n_assessed == len(GEOTHERMAL_COLUMNS), n_assessed > 0],
        [cols.STATUS_ASSESSED, cols.STATUS_PARTLY_ASSESSED],
        default=cols.STATUS_NOT_ASSESSED,
    )
    ordered = [*GEOTHERMAL_COLUMNS.values(), *BOREHOLE_COLUMNS.values(), cols.GEOTHERMAL_STATUS]
    return gpd.GeoDataFrame(merged[ordered + ["geometry"]], geometry="geometry", crs=crs)


def _block_ids_from_buildings(blocks: gpd.GeoDataFrame, buildings: gpd.GeoDataFrame) -> pd.Series:
    """Most frequent ``block_id`` of the buildings whose inner point lies in a block."""
    ids = pd.Series(pd.NA, index=blocks.index, dtype="string")
    if buildings is None or buildings.empty or cols.BLOCK_ID not in buildings.columns:
        return ids
    known = buildings[buildings[cols.BLOCK_ID].notna()]
    if known.empty:
        return ids
    points = gpd.GeoDataFrame(
        {"_block": known[cols.BLOCK_ID].astype("string").values},
        geometry=known.geometry.representative_point().values,
        crs=known.crs,
    )
    if points.crs != blocks.crs:
        points = points.to_crs(blocks.crs)
    joined = gpd.sjoin(points, blocks[["geometry"]], how="inner", predicate="within")
    if joined.empty:
        return ids
    mode = joined.groupby("index_right")["_block"].agg(lambda s: s.value_counts().index[0])
    ids.loc[mode.index] = mode.values
    return ids


def process_blocks(
    raw: gpd.GeoDataFrame, buildings: Optional[gpd.GeoDataFrame] = None
) -> gpd.GeoDataFrame:
    """LANUK ONG/MTG per building block → canonical columns.

    ``block_id`` comes from the source if it has one (NRW geodatabase),
    otherwise from the buildings inside the block (municipality shapefile).
    A block without values is ``not_assessed`` with NaN, a 0 stays 0.
    """
    missing = [field for field in BLOCK_FIELDS if field not in raw.columns]
    if missing:
        raise RuntimeError(f"LANUK-Baublockdaten ohne Felder {missing} (Feldnamen geändert?).")
    out = gpd.GeoDataFrame(geometry=raw.geometry.values, crs=raw.crs, index=raw.index)
    if BLOCK_ID_FIELD in raw.columns:
        out[cols.BLOCK_ID] = raw[BLOCK_ID_FIELD].astype("string")
    else:
        out[cols.BLOCK_ID] = _block_ids_from_buildings(out, buildings)
    for field, (column, factor) in BLOCK_FIELDS.items():
        out[column] = pd.to_numeric(raw[field], errors="coerce").astype("float64") * factor
    out[cols.BLOCK_POTENTIAL_STATUS] = np.where(
        out[cols.ONG_POTENTIAL_MWH].notna() | out[cols.MTG_POTENTIAL_MWH].notna(),
        cols.STATUS_ASSESSED, cols.STATUS_NOT_ASSESSED,
    )
    ordered = [cols.BLOCK_ID, *(c for c, _ in BLOCK_FIELDS.values()), cols.BLOCK_POTENTIAL_STATUS]
    return out[ordered + ["geometry"]].reset_index(drop=True)


#: LANUK doublet raster field → (column, factor); GWh/a → MWh/a
DEEP_FIELDS = {
    "MT_P10_MW": (cols.DOUBLET_MT_P10_MW, 1.0),
    "MT_P50_MW": (cols.DOUBLET_MT_P50_MW, 1.0),
    "MT_P90_MW": (cols.DOUBLET_MT_P90_MW, 1.0),
    "T_P10_MW": (cols.DOUBLET_T_P10_MW, 1.0),
    "T_P50_MW": (cols.DOUBLET_T_P50_MW, 1.0),
    "T_P90_MW": (cols.DOUBLET_T_P90_MW, 1.0),
    "MT_P10_GWh": (cols.DOUBLET_MT_P10_MWH, 1e3),
    "MT_P50_GWh": (cols.DOUBLET_MT_P50_MWH, 1e3),
    "MT_P90_GWh": (cols.DOUBLET_MT_P90_MWH, 1e3),
    "T_P10_GWh": (cols.DOUBLET_T_P10_MWH, 1e3),
    "T_P50_GWh": (cols.DOUBLET_T_P50_MWH, 1e3),
    "T_P90_GWh": (cols.DOUBLET_T_P90_MWH, 1e3),
    "Volllastst": (cols.DOUBLET_FULL_LOAD_HOURS, 1.0),
    "fraction": (cols.CELL_SHARE, 1.0),
}
DEEP_NOTES = {"Hinweis1": cols.DEEP_NOTE_DEPTH, "Hinweis2": cols.DEEP_NOTE_SURVEY}


def _distance_and_candidate(out: gpd.GeoDataFrame, area: BaseGeometry) -> None:
    """Distance to ``area`` and a WGS84 point inside every feature (in place)."""
    out[cols.DISTANCE_TO_AREA] = out.geometry.distance(area).astype("float64")
    centres = out.geometry.representative_point().to_crs("EPSG:4326")
    out[cols.SOURCE_CANDIDATE_LAT] = centres.y.round(6)
    out[cols.SOURCE_CANDIDATE_LON] = centres.x.round(6)


def process_deep_cells(raw: gpd.GeoDataFrame, area: BaseGeometry) -> gpd.GeoDataFrame:
    """LANUK doublet raster cells → canonical columns.

    ``deep_potential_mwh`` is the P50 yield of the better reservoir of the
    cell (medium-deep or deep): one hypothetical plant per cell, so an upper
    bound, not a sum. The cell centre is a candidate for ``source_coordinates``
    — nothing is placed automatically. ``area`` (same CRS) gives the distance.
    """
    missing = [field for field in DEEP_FIELDS if field not in raw.columns]
    if missing:
        raise RuntimeError(f"LANUK-Rasterdaten tiefe Geothermie ohne Felder {missing} (Feldnamen geändert?).")
    out = gpd.GeoDataFrame(geometry=raw.geometry.values, crs=raw.crs)
    for field, (column, factor) in DEEP_FIELDS.items():
        out[column] = pd.to_numeric(raw[field], errors="coerce").astype("float64").values * factor
    for field, column in DEEP_NOTES.items():
        out[column] = raw[field].astype("string").values if field in raw.columns else pd.NA
    out[cols.DEEP_POTENTIAL_MWH] = out[[cols.DOUBLET_MT_P50_MWH, cols.DOUBLET_T_P50_MWH]].max(axis=1)
    _distance_and_candidate(out, area)
    ordered = [
        cols.DEEP_POTENTIAL_MWH, *(c for c, _ in DEEP_FIELDS.values()), *DEEP_NOTES.values(),
        cols.DISTANCE_TO_AREA, cols.SOURCE_CANDIDATE_LAT, cols.SOURCE_CANDIDATE_LON,
    ]
    return out[ordered + ["geometry"]].sort_values(cols.DISTANCE_TO_AREA, kind="stable").reset_index(drop=True)


#: LANUK solar thermal field → (column, factor); kWh/a → MWh/a. The field
#: names differ from the LANUK documentation (Pot_FK_kWh, not Po_FK_kWh).
SOLAR_FIELDS = {
    "Pot_FK_kWh": (cols.SOLAR_FLAT_PLATE_MWH, cols.SOLAR_FLAT_PLATE_SPECIFIC),
    "Pot_VR_kWh": (cols.SOLAR_VACUUM_TUBE_MWH, cols.SOLAR_VACUUM_TUBE_SPECIFIC),
    "Po_PNS_kWh": (cols.SOLAR_TROUGH_NS_MWH, cols.SOLAR_TROUGH_NS_SPECIFIC),
    "Po_POW_kWh": (cols.SOLAR_TROUGH_EW_MWH, cols.SOLAR_TROUGH_EW_SPECIFIC),
}
SOLAR_AREA_FIELD = "Nutzfl_m2"
SOLAR_ID_FIELD = "Flur_id"


def distance_to_demand(gdf: gpd.GeoDataFrame, buildings: Optional[gpd.GeoDataFrame]) -> pd.Series:
    """Distance of every feature to the nearest building with heat demand [m] (NaN without)."""
    out = pd.Series(np.nan, index=gdf.index, dtype="float64")
    if buildings is None or buildings.empty or cols.HEAT_DEMAND not in buildings.columns or gdf.empty:
        return out
    demand = buildings[pd.to_numeric(buildings[cols.HEAT_DEMAND], errors="coerce") > 0]
    if demand.empty:
        return out
    demand = demand[["geometry"]].to_crs(gdf.crs) if demand.crs != gdf.crs else demand[["geometry"]]
    nearest = gpd.sjoin_nearest(gdf[["geometry"]], demand, distance_col="_distance")
    out.loc[:] = nearest.groupby(level=0)["_distance"].min().reindex(gdf.index).values
    return out


def process_solar_thermal(
    raw: gpd.GeoDataFrame, area: BaseGeometry, buildings: Optional[gpd.GeoDataFrame] = None
) -> gpd.GeoDataFrame:
    """LANUK ground-mounted solar thermal per Flur → canonical columns.

    Yields in MWh/a per collector type and the specific yield in kWh/(m²·a)
    from the usable area. Flure without usable area (no suitable land, all
    yields 0) are left out. Distances to ``area`` and to the nearest building
    with heat demand let near fields come first.
    """
    missing = [f for f in (*SOLAR_FIELDS, SOLAR_AREA_FIELD, SOLAR_ID_FIELD) if f not in raw.columns]
    if missing:
        raise RuntimeError(f"LANUK-Daten Freiflaechen-Solarthermie ohne Felder {missing} (Feldnamen geändert?).")
    usable = pd.to_numeric(raw[SOLAR_AREA_FIELD], errors="coerce").astype("float64")
    raw = raw[usable > 0]
    usable = usable[usable > 0]
    out = gpd.GeoDataFrame(geometry=raw.geometry.values, crs=raw.crs)
    out[cols.FLUR_ID] = raw[SOLAR_ID_FIELD].astype("string").values
    out[cols.SOLAR_USABLE_AREA] = usable.values
    for field, (column, specific) in SOLAR_FIELDS.items():
        kwh = pd.to_numeric(raw[field], errors="coerce").astype("float64").values
        out[column] = kwh * 1e-3
        out[specific] = kwh / usable.values
    _distance_and_candidate(out, area)
    out[cols.DISTANCE_TO_DEMAND] = distance_to_demand(out, buildings)
    ordered = [
        cols.FLUR_ID, cols.SOLAR_USABLE_AREA, *(c for c, _ in SOLAR_FIELDS.values()),
        *(s for _, s in SOLAR_FIELDS.values()), cols.DISTANCE_TO_AREA, cols.DISTANCE_TO_DEMAND,
        cols.SOURCE_CANDIDATE_LAT, cols.SOURCE_CANDIDATE_LON,
    ]
    return out[ordered + ["geometry"]].sort_values(cols.DISTANCE_TO_AREA, kind="stable").reset_index(drop=True)
