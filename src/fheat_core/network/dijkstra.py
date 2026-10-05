"""Phase-0 backend: the original shortest-path (Dijkstra) network generation.

This is the historical fheat_core behaviour, moved verbatim out of
``steps/network.py`` so that the step itself only dispatches.
"""
from __future__ import annotations

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
from fheat_core.network.base import NetworkBackend
from fheat_core.resources import load_pipe_info


class DijkstraBackend(NetworkBackend):
    """Shortest path from the source to every building along the street graph."""

    name = "phase0"

    def build(self, buildings, streets, source, config, adapter):
        pipe_info = adapter.provide_pipe_info()
        if pipe_info is None:
            pipe_info = load_pipe_info()

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
        return net_gdf, buildings
