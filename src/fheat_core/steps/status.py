"""Step STATUS: WLD (Wärmeliniendichte) + Eignungspolygone."""
from __future__ import annotations

import numpy as np
import geopandas as gpd
import pandas as pd

from fheat_core import columns as cols
from fheat_core.schemas import PolygonsSchema, SchemaError, WLDSchema
from fheat_core.state import Phase, PipelineState


def run(state: PipelineState, config, adapter) -> PipelineState:
    buildings = state.buildings_gdf
    streets = state.streets_gdf
    parcels = state.parcels_gdf

    state.wld_gdf = _compute_wld(buildings, streets)
    state.polygons_gdf = _compute_polygons(
        parcels,
        state.wld_gdf,
        buildings,
        config.wld_threshold,
        config.buffer_distance,
    )

    WLDSchema.validate(state.wld_gdf)
    PolygonsSchema.validate(state.polygons_gdf)

    state.phase = Phase.STATUS
    return state


# ------------------------------------------------------------------
# WLD
# ------------------------------------------------------------------

def _compute_wld(buildings: gpd.GeoDataFrame, streets: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    streets = streets.copy().reset_index(drop=True)
    streets[cols.LENGTH] = streets.geometry.length

    if cols.BUILDING_ID not in buildings.columns:
        buildings = buildings.copy()
        buildings[cols.BUILDING_ID] = buildings.index.astype("int32")

    centroids = gpd.GeoDataFrame(
        {
            cols.BUILDING_ID: buildings[cols.BUILDING_ID].astype(int).values,
            cols.HEAT_DEMAND: buildings[cols.HEAT_DEMAND].values,
        },
        geometry=buildings.geometry.centroid.values,
        crs=buildings.crs,
    )
    nearest = gpd.sjoin_nearest(centroids, streets[["geometry"]], how="left")
    grouped = nearest.groupby("index_right").agg(
        wb=(cols.HEAT_DEMAND, "sum"),
        ids=(cols.BUILDING_ID, lambda s: ",".join(s.astype(int).astype(str))),
    )

    streets[cols.HEAT_DEMAND] = grouped["wb"].reindex(streets.index, fill_value=0.0).values
    streets[cols.CONNECTED_IDS] = grouped["ids"].reindex(streets.index, fill_value="").values
    streets[cols.HEAT_LINE_DENSITY] = np.where(
        streets[cols.LENGTH] != 0.0,
        streets[cols.HEAT_DEMAND] / streets[cols.LENGTH],
        np.nan,
    )
    return streets


# ------------------------------------------------------------------
# Eignungspolygone
# ------------------------------------------------------------------

def _compute_polygons(
    parcels: gpd.GeoDataFrame,
    wld: gpd.GeoDataFrame,
    buildings: gpd.GeoDataFrame,
    wld_threshold: float,
    buffer_distance: float,
) -> gpd.GeoDataFrame:
    crs = buildings.crs

    if parcels is None or parcels.empty or wld.empty or buildings.empty:
        return gpd.GeoDataFrame({"geometry": []}, geometry="geometry", crs=crs)

    filtered_wld = wld[wld[cols.HEAT_LINE_DENSITY] >= wld_threshold]
    if filtered_wld.empty or cols.CONNECTED_IDS not in filtered_wld.columns:
        return gpd.GeoDataFrame({"geometry": []}, geometry="geometry", crs=crs)

    connected_ids = [
        int(i)
        for sublist in filtered_wld[cols.CONNECTED_IDS].dropna().str.split(",")
        for i in sublist
        if i
    ]
    if not connected_ids:
        return gpd.GeoDataFrame({"geometry": []}, geometry="geometry", crs=crs)

    connected_bld = buildings[buildings[cols.BUILDING_ID].isin(connected_ids)].copy()
    if connected_bld.empty:
        return gpd.GeoDataFrame({"geometry": []}, geometry="geometry", crs=crs)

    connected_bld = connected_bld.copy().reset_index(drop=True)
    connected_bld["_area"] = connected_bld.geometry.area
    parcels = parcels.copy().reset_index(drop=True)
    for c in ("index_left", "index_right"):
        parcels = parcels.drop(columns=[c], errors="ignore")
        connected_bld = connected_bld.drop(columns=[c], errors="ignore")

    joined = gpd.sjoin(parcels, connected_bld, how="inner", predicate="intersects")
    parcel_geoms = parcels.geometry.iloc[joined.index.values].values
    bld_geoms = connected_bld.geometry.iloc[joined["index_right"].values].values
    joined["_overlap"] = [p.intersection(b).area for p, b in zip(parcel_geoms, bld_geoms)]
    joined["_ratio"] = joined["_overlap"] / joined["_area"]
    best = joined.sort_values("_ratio", ascending=False).groupby(joined.index).first()
    selected = best[best["_ratio"] >= 0.1]
    if selected.empty:
        return gpd.GeoDataFrame({"geometry": []}, geometry="geometry", crs=crs)

    selected = selected.copy()
    selected["geometry"] = selected.buffer(buffer_distance)
    dissolved = selected.dissolve()
    exploded = dissolved.explode(index_parts=True).reset_index(drop=True)
    exploded = exploded.set_crs(crs, allow_override=True)
    polygons = exploded[["geometry"]].copy()

    # add statistics
    polygons[cols.AREA] = polygons.geometry.area

    bld_heat = buildings[buildings[cols.HEAT_DEMAND] > 0]
    bld_in_poly = gpd.sjoin(
        bld_heat[["geometry", cols.HEAT_DEMAND, cols.THERMAL_POWER]],
        polygons[["geometry"]],
        how="inner",
        predicate="within",
    )
    g = bld_in_poly.groupby("index_right")
    polygons[cols.N_CONNECTIONS] = g.size().reindex(polygons.index, fill_value=0).astype(int).values
    polygons[cols.HEAT_DEMAND] = g[cols.HEAT_DEMAND].sum().reindex(polygons.index, fill_value=0.0).values
    polygons[cols.THERMAL_POWER] = g[cols.THERMAL_POWER].sum().reindex(polygons.index, fill_value=0.0).values

    polygons[cols.HEAT_DEMAND_DENSITY] = (
        10 * polygons[cols.HEAT_DEMAND] / polygons[cols.AREA]
    )
    polygons[cols.THERMAL_POWER_MEAN] = np.where(
        polygons[cols.N_CONNECTIONS] > 0,
        polygons[cols.THERMAL_POWER] / polygons[cols.N_CONNECTIONS],
        np.nan,
    )
    return polygons
