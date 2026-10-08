"""Step ADJUSTED: validate schemas and normalize geometries."""
from __future__ import annotations

import geopandas as gpd
import pandas as pd

from fheat_core import columns as cols
from fheat_core.schemas import (
    BuildingsSchema,
    ParcelsSchema,
    SchemaError,
    StreetsSchema,
    SourceSchema,
)
from fheat_core.state import Phase, PipelineState


def run(state: PipelineState, config, adapter) -> PipelineState:
    BuildingsSchema.validate(state.buildings_gdf)
    StreetsSchema.validate(state.streets_gdf)
    ParcelsSchema.validate(state.parcels_gdf)
    # The heat source is only needed from the NETWORK step on.
    if state.source_gdf is not None:
        SourceSchema.validate(state.source_gdf)

    state.buildings_gdf = _fix_geom(state.buildings_gdf)
    state.streets_gdf = _fix_geom(state.streets_gdf)
    state.parcels_gdf = _fix_geom(state.parcels_gdf)
    state.buildings_gdf = _apply_heat_demand_basis(state.buildings_gdf, config.heat_demand_basis)

    state.phase = Phase.ADJUSTED
    return state


#: Building column each ``FHeatConfig.heat_demand_basis`` selects.
_HEAT_DEMAND_COLUMNS = {
    "calculated": cols.HEAT_DEMAND_CALCULATED,
    "dataset": cols.HEAT_DEMAND_DATASET,
}
#: Full load hours assumed for a building without any (as fheat_nrw.processing).
_DEFAULT_FULL_LOAD_HOURS = 1600


def _apply_heat_demand_basis(gdf: gpd.GeoDataFrame, basis: str) -> gpd.GeoDataFrame:
    """Use the heat demand chosen by ``basis`` and derive the thermal power from it.

    Frames without the chosen column (adapters that provide one heat demand
    only) stay unchanged. Where the chosen value is missing or not positive,
    the data source value is used, then the current heat demand.
    """
    column = _HEAT_DEMAND_COLUMNS[basis]
    if gdf is None or gdf.empty or column not in gdf.columns:
        return gdf
    gdf = gdf.copy()
    heat = pd.to_numeric(gdf[column], errors="coerce")
    for fallback in (cols.HEAT_DEMAND_DATASET, cols.HEAT_DEMAND):
        if fallback in gdf.columns:
            heat = heat.where(heat > 0, pd.to_numeric(gdf[fallback], errors="coerce"))
    gdf[cols.HEAT_DEMAND] = heat.astype("float64")
    hours = pd.to_numeric(gdf[cols.FULL_LOAD_HOURS], errors="coerce")
    gdf[cols.THERMAL_POWER] = gdf[cols.HEAT_DEMAND] / hours.where(hours > 0, _DEFAULT_FULL_LOAD_HOURS)
    return gdf


def _fix_geom(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if gdf is None or gdf.empty:
        return gdf
    gdf = gdf.copy()
    col = gdf.geometry.name
    poly_mask = gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    if poly_mask.any():
        gdf.loc[poly_mask, col] = gdf.loc[poly_mask].geometry.buffer(0)
    return gdf
