"""Potential layers on the buildings and in the result summary.

The layers come from the adapter (``DataAdapter.fetch_geothermal_*``,
``fetch_solar_thermal``). They inform the planner and are no input of the
network calculation.
"""
from __future__ import annotations

from typing import Optional

import geopandas as gpd
import numpy as np
import pandas as pd

from fheat_core import columns as cols

#: block columns copied onto the buildings (a value of the whole block)
BLOCK_COLUMNS = (
    cols.ONG_POTENTIAL_MWH,
    cols.ONG_POTENTIAL_2045_MWH,
    cols.MTG_POTENTIAL_MWH,
    cols.MTG_POTENTIAL_2045_MWH,
    cols.BLOCK_POTENTIAL_STATUS,
)
#: columns of the shallow geothermal layer copied onto the buildings
SHALLOW_COLUMNS = (
    cols.BOREHOLE_EXTRACTION_1800,
    cols.BOREHOLE_EXTRACTION_2400,
    cols.COLLECTOR_EXTRACTION_1800,
    cols.COLLECTOR_EXTRACTION_2400,
    cols.GEOTHERMAL_STATUS,
)


def _inner_points(buildings: gpd.GeoDataFrame, crs) -> gpd.GeoDataFrame:
    points = gpd.GeoDataFrame(geometry=buildings.geometry.representative_point(), crs=buildings.crs)
    return points.to_crs(crs) if crs is not None and points.crs != crs else points


def _layer_row_of(buildings: gpd.GeoDataFrame, layer: gpd.GeoDataFrame) -> pd.Series:
    """Index of the ``layer`` feature each building's inner point lies in (NaN: none)."""
    joined = gpd.sjoin(_inner_points(buildings, layer.crs), layer[["geometry"]], how="left", predicate="within")
    return joined.groupby(level=0)["index_right"].first().reindex(buildings.index)


def _block_row_of(buildings: gpd.GeoDataFrame, blocks: gpd.GeoDataFrame) -> pd.Series:
    """Block of each building: by ``block_id``, else by the location of the building."""
    rows = pd.Series(np.nan, index=buildings.index, dtype="float64")
    if cols.BLOCK_ID in buildings.columns and cols.BLOCK_ID in blocks.columns:
        known = blocks[blocks[cols.BLOCK_ID].notna()]
        by_id = pd.Series(known.index, index=known[cols.BLOCK_ID].astype("string").values)
        by_id = by_id[~by_id.index.duplicated()]
        ids = buildings[cols.BLOCK_ID].astype("string")
        rows = pd.Series(ids.map(by_id).astype("float64").values, index=buildings.index)
    missing = rows.isna()
    if missing.any():
        rows[missing] = _layer_row_of(buildings[missing], blocks).astype("float64")
    return rows


def _copy(buildings: pd.DataFrame, layer: pd.DataFrame, rows: pd.Series, columns) -> None:
    for column in columns:
        if column in layer.columns:
            buildings[column] = rows.map(layer[column].to_dict())


def attach_potentials(
    buildings: gpd.GeoDataFrame,
    blocks: Optional[gpd.GeoDataFrame] = None,
    shallow: Optional[gpd.GeoDataFrame] = None,
) -> gpd.GeoDataFrame:
    """Buildings with the potential of their block and the shallow geothermal values.

    The block potential (``ong_*``, ``mtg_*``) is the value of the whole
    building block, repeated on each of its buildings and never split: sum it
    per block, not per building. A building outside every block gets NaN and
    ``not_assessed``. Without layers the buildings come back unchanged.
    """
    if buildings is None or buildings.empty:
        return buildings
    out = buildings.drop(columns=[c for c in (*BLOCK_COLUMNS, *SHALLOW_COLUMNS) if c in buildings.columns])
    if blocks is not None and not blocks.empty:
        _copy(out, blocks, _block_row_of(out, blocks), BLOCK_COLUMNS)
        if cols.BLOCK_POTENTIAL_STATUS in out.columns:
            out[cols.BLOCK_POTENTIAL_STATUS] = out[cols.BLOCK_POTENTIAL_STATUS].fillna(cols.STATUS_NOT_ASSESSED)
    if shallow is not None and not shallow.empty:
        _copy(out, shallow, _layer_row_of(out, shallow), SHALLOW_COLUMNS)
        if cols.GEOTHERMAL_STATUS in out.columns:
            out[cols.GEOTHERMAL_STATUS] = out[cols.GEOTHERMAL_STATUS].fillna(cols.STATUS_NOT_ASSESSED)
    return out


def potential_summary(
    buildings: gpd.GeoDataFrame,
    blocks: Optional[gpd.GeoDataFrame] = None,
    deep: Optional[gpd.GeoDataFrame] = None,
    solar: Optional[gpd.GeoDataFrame] = None,
) -> dict:
    """Short sums of the potential layers for the result summary.

    ONG/MTG: sum over the blocks of ``buildings`` (each block once). Deep
    geothermal: the largest cell value around the area (one plant per cell,
    an upper bound). Solar thermal: sum of the flat plate yield of all Flure
    around the area. A key is left out when its layer is missing.
    """
    out: dict = {}
    if blocks is not None and not blocks.empty and buildings is not None and not buildings.empty:
        rows = _block_row_of(buildings, blocks).dropna().unique().astype(int)
        mine = blocks.loc[rows]
        for key, column in (("ong_potential_mwh_a", cols.ONG_POTENTIAL_MWH),
                            ("mtg_potential_mwh_a", cols.MTG_POTENTIAL_MWH)):
            if column in mine.columns and mine[column].notna().any():
                out[key] = round(float(mine[column].sum()), 3)
    if deep is not None and not deep.empty and cols.DEEP_POTENTIAL_MWH in deep.columns:
        out["deep_potential_max_mwh_a"] = round(float(deep[cols.DEEP_POTENTIAL_MWH].max()), 3)
    if solar is not None and not solar.empty and cols.SOLAR_FLAT_PLATE_MWH in solar.columns:
        out["solar_thermal_flat_plate_mwh_a"] = round(float(solar[cols.SOLAR_FLAT_PLATE_MWH].sum()), 3)
        out["solar_thermal_area_m2"] = round(float(solar[cols.SOLAR_USABLE_AREA].sum()), 1)
    return out
