"""Step NETWORK: Straßengraph + Netzberechnung + Rohrdimensionierung."""
from __future__ import annotations

import geopandas as gpd

from fheat_core import columns as cols
from fheat_core.algorithms.geometry import (
    add_centroids,
    closest_points_to_streets,
    insert_connection_points,
)
from fheat_core.algorithms.network import (
    add_edge_lengths,
    build_street_graph,
    compute_network,
    connect_buildings_to_graph,
    connect_source_to_graph,
)
from fheat_core.resources import load_pipe_info
from fheat_core.schemas import NetSchema
from fheat_core.state import Phase, PipelineState


def run(state: PipelineState, config, adapter) -> PipelineState:
    pipe_info = adapter.provide_pipe_info()
    if pipe_info is None:
        pipe_info = load_pipe_info()

    buildings = state.buildings_gdf.copy()
    streets = state.streets_gdf.copy()
    source = state.source_gdf.copy()

    # restrict to connectable routes and buildings with heat connection
    if cols.ROUTABLE in streets.columns:
        streets = streets[streets[cols.ROUTABLE] == 1]
    if cols.CONNECT in buildings.columns:
        buildings = buildings[buildings[cols.CONNECT] == 1]

    # CRS: source to buildings CRS
    if source.crs != buildings.crs:
        source = source.to_crs(buildings.crs)

    # geometry enrichment
    buildings = add_centroids(buildings)
    buildings = closest_points_to_streets(buildings, streets, centroid_col="centroid")

    source = source.copy()
    source[cols.CENTROID] = source.geometry
    source = closest_points_to_streets(source, streets, centroid_col=cols.CENTROID)

    streets = insert_connection_points(streets, buildings)
    streets = insert_connection_points(streets, source)

    G = build_street_graph(streets, buildings.crs)
    G = connect_buildings_to_graph(G, buildings)
    G = connect_source_to_graph(G, source)
    G = add_edge_lengths(G)

    net_gdf = compute_network(
        G,
        buildings,
        source,
        pipe_info,
        power_att=cols.THERMAL_POWER,
        htemp=config.supply_temperature,
        ltemp=config.return_temperature,
        crs=buildings.crs,
    )

    NetSchema.validate(net_gdf)

    state.net_gdf = net_gdf
    state.phase = Phase.NETWORK
    return state
