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


#: Distance [m] within which a house connection end still counts as the
#: centroid of its building: an edit in a web map moves an untouched end by
#: millimetres (projected → WGS84 → projected).
CENTROID_TOLERANCE = 0.05


def mark_length_under_buildings(
    net: gpd.GeoDataFrame,
    buildings: gpd.GeoDataFrame,
    obstacles: gpd.GeoDataFrame | None,
) -> gpd.GeoDataFrame:
    """Write ``length_under_buildings`` onto the net: how far a house connection runs under other buildings.

    ``buildings`` are the connected buildings. A house connection's own
    building, which does not count, is the one of them an end of the line
    lies in, else the one whose centroid an end meets (``CENTROID_TOLERANCE``).
    So a planner may move the building end within the building. ``obstacles``
    are all buildings. Every other edge gets 0.
    """
    net = net.copy()
    length = np.zeros(len(net))
    house = (net[cols.TYPE] == cols.EDGE_TYPE_HOUSE_CONNECTION).to_numpy()
    if house.any() and obstacles is not None and not obstacles.empty and not buildings.empty:
        lines = net.geometry.to_numpy(dtype=object)[house]
        own = np.full(len(lines), shapely.GeometryCollection(), dtype=object)
        building_geoms = buildings.geometry.to_numpy(dtype=object)
        centroids = shapely.STRtree(shapely.centroid(building_geoms))
        outlines = shapely.STRtree(building_geoms)
        for end in line_ends(lines):
            line_idx, building_idx = centroids.query_nearest(
                end, max_distance=CENTROID_TOLERANCE, all_matches=False
            )
            own[line_idx] = building_geoms[building_idx]
        for end in line_ends(lines):  # containment wins over a centroid
            line_idx, building_idx = outlines.query(end, predicate="within")
            own[line_idx] = building_geoms[building_idx]
        length[house] = _length_under(lines, own, obstacles.geometry.to_numpy(dtype=object))
    net[cols.LENGTH_UNDER_BUILDINGS] = np.round(length, 2)
    return net


def line_ends(lines) -> tuple[np.ndarray, np.ndarray]:
    """First and last point of each (Multi)LineString."""
    coords, index = shapely.get_coordinates(lines, return_index=True)
    first = np.searchsorted(index, np.arange(len(lines)), side="left")
    last = np.searchsorted(index, np.arange(len(lines)), side="right") - 1
    return shapely.points(coords[first]), shapely.points(coords[last])


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
