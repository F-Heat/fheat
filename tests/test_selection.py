"""Tests for fheat_core.selection (planning-area selection of buildings)."""
from __future__ import annotations

import geopandas as gpd
from shapely.geometry import LineString, box

from fheat_core import columns as cols
from fheat_core.selection import clip_to_area, connected_mask, in_planning_area

CRS = "EPSG:25832"


def _area(*boxes):
    return gpd.GeoDataFrame(geometry=[box(*b) for b in boxes], crs=CRS)


class TestInPlanningArea:
    def test_without_area_all_inside(self, buildings_gdf):
        assert in_planning_area(buildings_gdf, None).all()

    def test_empty_area_counts_as_no_area(self, buildings_gdf):
        empty = gpd.GeoDataFrame(geometry=[], crs=CRS)
        assert in_planning_area(buildings_gdf, empty).all()

    def test_point_inside(self, buildings_gdf):
        mask = in_planning_area(buildings_gdf, _area((-20, -20, 70, 20)))
        assert mask.tolist() == [True, True, False]

    def test_several_polygons(self, buildings_gdf):
        mask = in_planning_area(buildings_gdf, _area((-20, -20, 20, 20), (90, -20, 130, 20)))
        assert mask.tolist() == [True, False, True]

    def test_building_mostly_outside_is_outside(self, buildings_gdf):
        # the area touches only the left edge of the building at x=50..60
        mask = in_planning_area(buildings_gdf, _area((-20, -20, 51, 20)))
        assert mask.tolist() == [True, False, False]


class TestConnectedMask:
    def test_combines_connect_and_area(self, buildings_gdf):
        bld = buildings_gdf.copy()
        bld.loc[0, cols.CONNECT] = 0
        mask = connected_mask(bld, _area((-20, -20, 70, 20)))
        assert mask.tolist() == [False, True, False]

    def test_without_connect_column(self, buildings_gdf):
        bld = buildings_gdf.drop(columns=[cols.CONNECT])
        assert connected_mask(bld).all()


class TestClipToArea:
    def test_keeps_intersecting(self):
        lines = gpd.GeoDataFrame(
            geometry=[LineString([(0, 0), (10, 0)]), LineString([(100, 100), (110, 100)])],
            crs=CRS,
        )
        assert len(clip_to_area(lines, _area((-5, -5, 5, 5)))) == 1

    def test_without_area_unchanged(self, streets_gdf):
        assert clip_to_area(streets_gdf, None) is streets_gdf
