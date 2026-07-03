"""Tests for fheat_core.algorithms.geometry.

Covers pure geometry helpers (no state, no IO):
- get_closest_point: orthogonal projection of point onto line
- add_centroids: centroid column added without mutating input
- closest_points_to_streets: nearest street + Anschlusspunkt per row
- insert_connection_points: connection point inserted into correct street segment
"""
from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString, Point, Polygon

from fheat_core import columns as cols
from fheat_core.algorithms.geometry import (
    add_centroids,
    closest_points_to_streets,
    get_closest_point,
    insert_connection_points,
)


CRS = "EPSG:25832"


# ---------------------------------------------------------------------------
# get_closest_point
# ---------------------------------------------------------------------------


class TestGetClosestPoint:
    def test_perpendicular_projection(self):
        """Point above midpoint of horizontal line projects to midpoint."""
        line = LineString([(0, 0), (10, 0)])
        result = get_closest_point(line, Point(5, 7))
        assert result.x == pytest.approx(5.0)
        assert result.y == pytest.approx(0.0)

    def test_point_on_line_returns_itself(self):
        line = LineString([(0, 0), (10, 0)])
        result = get_closest_point(line, Point(3, 0))
        assert result.x == pytest.approx(3.0)
        assert result.y == pytest.approx(0.0)

    def test_point_beyond_line_clamps_to_endpoint(self):
        """shapely.project clamps to endpoint when projection falls outside."""
        line = LineString([(0, 0), (10, 0)])
        result = get_closest_point(line, Point(20, 0))
        assert result.x == pytest.approx(10.0)
        assert result.y == pytest.approx(0.0)

    def test_diagonal_line(self):
        line = LineString([(0, 0), (10, 10)])
        result = get_closest_point(line, Point(0, 10))
        # projection onto y=x at (5, 5)
        assert result.x == pytest.approx(5.0)
        assert result.y == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# add_centroids
# ---------------------------------------------------------------------------


class TestAddCentroids:
    def test_centroid_column_added(self):
        polys = [
            Polygon([(0, 0), (10, 0), (10, 10), (0, 10)]),
            Polygon([(20, 0), (30, 0), (30, 10), (20, 10)]),
        ]
        gdf = gpd.GeoDataFrame({"geometry": polys}, crs=CRS, geometry="geometry")
        out = add_centroids(gdf)
        assert "centroid" in out.columns
        assert out["centroid"].iloc[0].x == pytest.approx(5.0)
        assert out["centroid"].iloc[0].y == pytest.approx(5.0)
        assert out["centroid"].iloc[1].x == pytest.approx(25.0)
        assert out["centroid"].iloc[1].y == pytest.approx(5.0)

    def test_input_not_mutated(self):
        polys = [Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])]
        gdf = gpd.GeoDataFrame({"geometry": polys}, crs=CRS, geometry="geometry")
        _ = add_centroids(gdf)
        assert "centroid" not in gdf.columns

    def test_preserves_other_columns(self):
        polys = [Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])]
        gdf = gpd.GeoDataFrame(
            {"id": [42], "geometry": polys}, crs=CRS, geometry="geometry"
        )
        out = add_centroids(gdf)
        assert out["id"].iloc[0] == 42


# ---------------------------------------------------------------------------
# closest_points_to_streets
# ---------------------------------------------------------------------------


class TestClosestPointsToStreets:
    def test_assigns_anschlusspunkt_and_street_id(self):
        # two parallel streets — buildings should each pick the nearer one
        streets = gpd.GeoDataFrame(
            {"geometry": [
                LineString([(0, 0), (100, 0)]),     # street id 0 (y=0)
                LineString([(0, 50), (100, 50)]),   # street id 1 (y=50)
            ]},
            crs=CRS,
            geometry="geometry",
        )
        # building A near y=0, building B near y=50
        points = gpd.GeoDataFrame(
            {"centroid": [Point(20, 5), Point(40, 45)],
             "geometry": [Point(20, 5), Point(40, 45)]},
            crs=CRS,
            geometry="geometry",
        )
        out = closest_points_to_streets(points, streets, centroid_col="centroid")
        assert cols.CONNECTION_POINT in out.columns
        assert "street_id" in out.columns

        assert int(out.loc[0, "street_id"]) == 0
        assert int(out.loc[1, "street_id"]) == 1

        ap0 = out.loc[0, cols.CONNECTION_POINT]
        ap1 = out.loc[1, cols.CONNECTION_POINT]
        assert ap0.x == pytest.approx(20.0) and ap0.y == pytest.approx(0.0)
        assert ap1.x == pytest.approx(40.0) and ap1.y == pytest.approx(50.0)

    def test_input_not_mutated(self):
        streets = gpd.GeoDataFrame(
            {"geometry": [LineString([(0, 0), (10, 0)])]},
            crs=CRS, geometry="geometry",
        )
        points = gpd.GeoDataFrame(
            {"centroid": [Point(5, 5)], "geometry": [Point(5, 5)]},
            crs=CRS, geometry="geometry",
        )
        _ = closest_points_to_streets(points, streets, centroid_col="centroid")
        assert cols.CONNECTION_POINT not in points.columns
        assert "street_id" not in points.columns


# ---------------------------------------------------------------------------
# insert_connection_points
# ---------------------------------------------------------------------------


class TestInsertConnectionPoints:
    def test_point_inserted_into_correct_segment(self):
        # straight street; connection point at x=5 must be inserted between (0,0) and (10,0)
        streets = gpd.GeoDataFrame(
            {"geometry": [LineString([(0, 0), (10, 0)])]},
            crs=CRS, geometry="geometry",
        )
        conn = gpd.GeoDataFrame(
            {"street_id": [0], cols.CONNECTION_POINT: [Point(5, 0)],
             "geometry": [Point(5, 0)]},
            crs=CRS, geometry="geometry",
        )
        out = insert_connection_points(streets, conn)
        coords = list(out.at[0, "geometry"].coords)
        assert coords == [(0.0, 0.0), (5.0, 0.0), (10.0, 0.0)]

    def test_multiple_connection_points_into_polyline(self):
        # polyline with 3 segments; insert 2 points at different segments
        streets = gpd.GeoDataFrame(
            {"geometry": [LineString([(0, 0), (10, 0), (10, 10), (20, 10)])]},
            crs=CRS, geometry="geometry",
        )
        conn = gpd.GeoDataFrame(
            {
                "street_id": [0, 0],
                cols.CONNECTION_POINT: [Point(5, 0), Point(15, 10)],
                "geometry": [Point(5, 0), Point(15, 10)],
            },
            crs=CRS, geometry="geometry",
        )
        out = insert_connection_points(streets, conn)
        coords = list(out.at[0, "geometry"].coords)
        assert (5.0, 0.0) in coords
        assert (15.0, 10.0) in coords
        # original endpoints preserved
        assert coords[0] == (0.0, 0.0)
        assert coords[-1] == (20.0, 10.0)

    def test_point_already_present_is_skipped(self):
        streets = gpd.GeoDataFrame(
            {"geometry": [LineString([(0, 0), (5, 0), (10, 0)])]},
            crs=CRS, geometry="geometry",
        )
        conn = gpd.GeoDataFrame(
            {"street_id": [0], cols.CONNECTION_POINT: [Point(5, 0)],
             "geometry": [Point(5, 0)]},
            crs=CRS, geometry="geometry",
        )
        out = insert_connection_points(streets, conn)
        coords = list(out.at[0, "geometry"].coords)
        # point already at (5,0); no duplicate insertion
        assert coords.count((5.0, 0.0)) == 1
        assert len(coords) == 3

    def test_nan_street_id_skipped(self):
        streets = gpd.GeoDataFrame(
            {"geometry": [LineString([(0, 0), (10, 0)])]},
            crs=CRS, geometry="geometry",
        )
        conn = gpd.GeoDataFrame(
            {
                "street_id": [pd.NA],
                cols.CONNECTION_POINT: [Point(5, 0)],
                "geometry": [Point(5, 0)],
            },
            crs=CRS, geometry="geometry",
        )
        out = insert_connection_points(streets, conn)
        # geometry untouched
        assert list(out.at[0, "geometry"].coords) == [(0.0, 0.0), (10.0, 0.0)]

    def test_input_not_mutated(self):
        streets = gpd.GeoDataFrame(
            {"geometry": [LineString([(0, 0), (10, 0)])]},
            crs=CRS, geometry="geometry",
        )
        conn = gpd.GeoDataFrame(
            {"street_id": [0], cols.CONNECTION_POINT: [Point(5, 0)],
             "geometry": [Point(5, 0)]},
            crs=CRS, geometry="geometry",
        )
        _ = insert_connection_points(streets, conn)
        # original streets still has 2 coords
        assert len(list(streets.at[0, "geometry"].coords)) == 2
