"""Tests for fheat_nrw.osm_surface and fheat_nrw.civil_cost (cost tables + buffering)."""
from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import LineString, Polygon

from fheat_nrw.civil_cost import DEFAULT_ALKIS_COST_TABLE, annotate_landuse_costs
from fheat_nrw.osm_surface import (
    DEFAULT_OSM_HIGHWAY_FALLBACK,
    DEFAULT_OSM_SURFACE_COST_TABLE,
    annotate_osm_surface_costs,
    buffer_osm_lines,
)

CRS = "EPSG:25832"


def _osm_lines():
    return gpd.GeoDataFrame(
        {
            "highway": ["residential", "footway", "track", "service"],
            "surface": ["asphalt", "paving_stones", None, None],
            "geometry": [
                LineString([(0, 0), (50, 0)]),
                LineString([(0, 10), (50, 10)]),
                LineString([(0, 20), (50, 20)]),
                LineString([(0, 30), (50, 30)]),
            ],
        },
        crs=CRS, geometry="geometry",
    )


def test_surface_wins_over_highway_fallback():
    out = annotate_osm_surface_costs(_osm_lines())
    factors = list(out["civil_cost_factor"])
    # residential + asphalt → asphalt (the highway fallback 1.05 is ignored)
    assert factors[0] == pytest.approx(DEFAULT_OSM_SURFACE_COST_TABLE["asphalt"])
    assert factors[1] == pytest.approx(DEFAULT_OSM_SURFACE_COST_TABLE["paving_stones"])
    # no surface → highway fallback
    assert factors[2] == pytest.approx(DEFAULT_OSM_HIGHWAY_FALLBACK["track"])
    assert factors[3] == pytest.approx(DEFAULT_OSM_HIGHWAY_FALLBACK["service"])


def test_civil_class_is_the_surface_or_the_highway_class():
    out = annotate_osm_surface_costs(_osm_lines())
    assert out["civil_class"].tolist() == ["asphalt", "paving_stones", "highway:track", "highway:service"]


def test_unknown_class_uses_default():
    gdf = gpd.GeoDataFrame(
        {"highway": ["pyroclastic_lane"], "surface": ["lava"],
         "geometry": [LineString([(0, 0), (10, 0)])]},
        crs=CRS, geometry="geometry",
    )
    out = annotate_osm_surface_costs(gdf, default_factor=1.0)
    assert out["civil_cost_factor"].iloc[0] == 1.0


def test_missing_columns_use_default():
    gdf = gpd.GeoDataFrame({"geometry": [LineString([(0, 0), (10, 0)])]}, crs=CRS)
    out = annotate_osm_surface_costs(gdf)
    assert out["civil_cost_factor"].tolist() == [1.0]
    assert out["civil_class"].tolist() == [None]


def test_buffer_osm_lines_uses_class_width():
    polys = buffer_osm_lines(_osm_lines())
    # residential (half width 3.5 m) → 7 m wide; footway (1.0) → 2 m; flat caps
    assert polys.iloc[0].geometry.area == pytest.approx(50 * 7)
    assert polys.iloc[1].geometry.area == pytest.approx(50 * 2)


def test_buffer_osm_lines_falls_back_for_unknown_class():
    gdf = gpd.GeoDataFrame(
        {"highway": ["unknown", None], "geometry": [LineString([(0, 0), (10, 0)])] * 2}, crs=CRS
    )
    polys = buffer_osm_lines(gdf, fallback_m=2.0)
    assert polys.geometry.area.tolist() == pytest.approx([40.0, 40.0])


def test_landuse_factor_and_class_from_wfs_plain_text():
    gdf = gpd.GeoDataFrame(
        {"nutzart": ["Straßenverkehr", "Fließgewässer", "Unbekannt", None],
         "geometry": [Polygon([(i, 0), (i + 1, 0), (i + 1, 1), (i, 1)]) for i in range(4)]},
        crs=CRS,
    )
    out = annotate_landuse_costs(gdf)
    assert out["civil_cost_factor"].tolist() == pytest.approx(
        [DEFAULT_ALKIS_COST_TABLE["Strassenverkehr"], DEFAULT_ALKIS_COST_TABLE["Fliessgewaesser"], 1.0, 1.0]
    )
    assert out["civil_class"].tolist() == ["Straßenverkehr", "Fließgewässer", "Unbekannt", None]


def test_landuse_without_class_column_is_neutral():
    gdf = gpd.GeoDataFrame({"geometry": [Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])]}, crs=CRS)
    out = annotate_landuse_costs(gdf)
    assert out["civil_cost_factor"].tolist() == [1.0]
