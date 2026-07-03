"""Step ADJUSTED: validate schemas and normalize geometries."""
from __future__ import annotations

import geopandas as gpd

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
    SourceSchema.validate(state.source_gdf)

    state.buildings_gdf = _fix_geom(state.buildings_gdf)
    state.streets_gdf = _fix_geom(state.streets_gdf)
    state.parcels_gdf = _fix_geom(state.parcels_gdf)

    state.phase = Phase.ADJUSTED
    return state


def _fix_geom(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if gdf is None or gdf.empty:
        return gdf
    gdf = gdf.copy()
    col = gdf.geometry.name
    poly_mask = gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    if poly_mask.any():
        gdf.loc[poly_mask, col] = gdf.loc[poly_mask].geometry.buffer(0)
    return gdf
