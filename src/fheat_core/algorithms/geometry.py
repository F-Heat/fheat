"""Geometry helper functions — no state, no side effects."""
from __future__ import annotations

import numpy as np
import geopandas as gpd
import networkx as nx
import pandas as pd
import shapely
from shapely.geometry import LineString, Point

from fheat_core import columns as cols


def get_closest_point(line: LineString, point: Point) -> Point:
    return line.interpolate(line.project(point))


def add_centroids(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    gdf = gdf.copy()
    gdf[cols.CENTROID] = gdf.geometry.centroid
    return gdf


def closest_points_to_streets(
    points_gdf: gpd.GeoDataFrame,
    streets_gdf: gpd.GeoDataFrame,
    centroid_col: str = cols.CENTROID,
) -> gpd.GeoDataFrame:
    """Add connection_point and street_id to each row of points_gdf."""
    gdf = points_gdf.copy()
    sindex = streets_gdf.sindex

    for idx, row in gdf.iterrows():
        centroid = row[centroid_col]
        raw = sindex.nearest(centroid)
        arr = np.asarray(raw)
        tree_idx = arr[1] if arr.ndim == 2 else arr
        candidates = streets_gdf.iloc[tree_idx]
        closest_id = candidates.geometry.distance(centroid).idxmin()
        gdf.loc[idx, cols.CONNECTION_POINT] = get_closest_point(
            streets_gdf.at[closest_id, "geometry"], centroid
        )
        gdf.loc[idx, cols.STREET_ID] = int(closest_id)
    return gdf


def insert_connection_points(
    streets_gdf: gpd.GeoDataFrame,
    connection_gdf: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """Insert connection_point values from connection_gdf into the matching street lines."""
    streets = streets_gdf.copy()
    for _, row in connection_gdf.iterrows():
        street_id = row.get(cols.STREET_ID)
        if pd.isna(street_id):
            continue
        street_id = int(street_id)
        anschlusspunkt = row[cols.CONNECTION_POINT]
        line = streets.at[street_id, "geometry"]
        line_coords = (
            [coord for geom in line.geoms for coord in geom.coords]
            if line.geom_type == "MultiLineString"
            else list(line.coords)
        )
        if (anschlusspunkt.x, anschlusspunkt.y) in line_coords:
            continue
        min_dist = float("inf")
        pos = None
        for i in range(1, len(line_coords)):
            seg = LineString([line_coords[i - 1], line_coords[i]])
            d = seg.distance(anschlusspunkt)
            if d < min_dist:
                min_dist = d
                pos = i
        line_coords.insert(pos, (anschlusspunkt.x, anschlusspunkt.y))
        streets.at[street_id, "geometry"] = LineString(line_coords)
    return streets


def cluster_points(points: gpd.GeoSeries, max_distance: float) -> np.ndarray:
    """Single-linkage clusters of points: a label per point, 0, 1, ...

    Two points share a cluster when a chain of points connects them whose
    neighbours are at most ``max_distance`` apart (connected components of
    the graph of all pairs within that distance), so a cluster can be wider
    than ``max_distance``. Labels follow the first point of each cluster.
    ``points`` lie in a metric CRS.
    """
    geoms = np.asarray(points.values)
    graph = nx.Graph()
    graph.add_nodes_from(range(len(geoms)))
    if len(geoms):
        left, right = shapely.STRtree(geoms).query(geoms, predicate="dwithin", distance=max_distance)
        graph.add_edges_from(zip(left.tolist(), right.tolist()))
    labels = np.empty(len(geoms), dtype="int64")
    for label, members in enumerate(sorted(nx.connected_components(graph), key=min)):
        labels[list(members)] = label
    return labels
