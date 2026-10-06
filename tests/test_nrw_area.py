"""Tests for fheat_nrw.area (district selection and outline from parcels)."""
from __future__ import annotations

import geopandas as gpd
from shapely.geometry import LineString, box

from fheat_nrw.area import (
    boundary_from_parcels,
    clip_to_boundary,
    district_boundary,
    district_parcels,
    parcel_key_prefix,
)

CRS = "EPSG:25832"


def _parcels():
    return gpd.GeoDataFrame(
        {
            "nationalCadastralReference": ["055190001", "055190002", "055001001"],
            "geometry": [box(0, 0, 10, 10), box(10, 0, 20, 10), box(100, 0, 110, 10)],
        },
        crs=CRS,
    )


def test_prefix():
    assert parcel_key_prefix("55190") == "055190"
    assert parcel_key_prefix(55190) == "055190"


def test_district_parcels():
    assert len(district_parcels(_parcels(), "55190")) == 2
    assert len(district_parcels(_parcels(), "55001")) == 1
    assert district_parcels(_parcels(), "99999").empty


def test_district_parcels_without_reference_column():
    parcels = _parcels().drop(columns=["nationalCadastralReference"])
    assert district_parcels(parcels, "55190").empty


def test_boundary_is_one_geometry():
    boundary = district_boundary(_parcels(), "55190")
    assert len(boundary) == 1
    assert boundary.geometry.iloc[0].area == 200
    assert boundary.crs == CRS


def test_boundary_of_no_parcels_is_empty():
    assert boundary_from_parcels(_parcels().iloc[0:0]).empty


def test_clip_keeps_features_crossing_the_border():
    boundary = district_boundary(_parcels(), "55190")
    lines = gpd.GeoDataFrame(
        geometry=[
            LineString([(5, 5), (50, 5)]),  # crosses the border
            LineString([(100, 5), (105, 5)]),  # other district
        ],
        crs=CRS,
    )
    clipped = clip_to_boundary(lines, boundary)
    assert len(clipped) == 1
    assert clipped.geometry.iloc[0].length == 45  # kept whole
    assert "index_right" not in clipped.columns


def test_clip_with_several_boundary_rows_has_no_duplicates():
    boundary = gpd.GeoDataFrame(geometry=[box(0, 0, 10, 10), box(5, 0, 15, 10)], crs=CRS)
    lines = gpd.GeoDataFrame(geometry=[LineString([(6, 5), (8, 5)])], crs=CRS)
    assert len(clip_to_boundary(lines, boundary)) == 1
