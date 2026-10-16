"""House connections that pass under another building.

Every building is connected at right angles to the nearest street. In dense
areas that line can pass under another building, which no real pipe does.
The network step measures that length for every house connection
(``length_under_buildings``), so an application can point the planner to
the places to check; the routing itself stays unchanged.
"""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import shapely

from fheat_core import columns as cols


def mark_length_under_buildings(
    net: gpd.GeoDataFrame,
    buildings: gpd.GeoDataFrame,
    obstacles: gpd.GeoDataFrame | None,
) -> gpd.GeoDataFrame:
    """Write ``length_under_buildings`` onto the net: how far a house connection runs under other buildings.

    ``buildings`` are the connected buildings: a house connection starts at the
    centroid of one of them, and that building does not count. ``obstacles``
    are all buildings. Every other edge gets 0.
    """
    net = net.copy()
    length = np.zeros(len(net))
    house = (net[cols.TYPE] == cols.EDGE_TYPE_HOUSE_CONNECTION).to_numpy()
    if house.any() and obstacles is not None and not obstacles.empty and not buildings.empty:
        lines = net.geometry.to_numpy(dtype=object)[house]
        own = np.full(len(lines), shapely.GeometryCollection(), dtype=object)
        centroids = shapely.STRtree(buildings.geometry.centroid.to_numpy(dtype=object))
        building_geoms = buildings.geometry.to_numpy(dtype=object)
        for end in (0, -1):
            line_idx, building_idx = centroids.query_nearest(
                shapely.get_point(lines, end), max_distance=1e-3, all_matches=False
            )
            own[line_idx] = building_geoms[building_idx]
        length[house] = _length_under(lines, own, obstacles.geometry.to_numpy(dtype=object))
    net[cols.LENGTH_UNDER_BUILDINGS] = np.round(length, 2)
    return net


def _length_under(lines, own, obstacles) -> np.ndarray:
    """Length of each line under ``obstacles`` other than its ``own`` building."""
    obstacles = obstacles[~shapely.is_missing(obstacles) & ~shapely.is_empty(obstacles)]
    invalid = ~shapely.is_valid(obstacles)
    if invalid.any():
        obstacles = obstacles.copy()
        obstacles[invalid] = shapely.make_valid(obstacles[invalid])
    out = np.zeros(len(lines))
    line_idx, obstacle_idx = shapely.STRtree(obstacles).query(lines, predicate="intersects")
    if len(line_idx):
        parts = shapely.difference(shapely.intersection(lines[line_idx], obstacles[obstacle_idx]), own[line_idx])
        np.add.at(out, line_idx, shapely.length(parts))
    return out
