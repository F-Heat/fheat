"""Tests for fheat_de.lod2: tiles of any state, reading a CityGML LoD2 tile."""
from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import box

from fheat_de import lod2

CRS = "EPSG:25832"
TILE = (
    '<core:CityModel xmlns:core="http://www.opengis.net/citygml/1.0" '
    'xmlns:bldg="http://www.opengis.net/citygml/building/1.0" xmlns:gml="http://www.opengis.net/gml">'
    '<core:cityObjectMember><bldg:Building gml:id="DENI03AL0001ABCD">'
    "<bldg:measuredHeight>6.0</bldg:measuredHeight>"
    "<bldg:boundedBy><bldg:GroundSurface><bldg:lod2MultiSurface><gml:MultiSurface><gml:surfaceMember>"
    "<gml:Polygon><gml:exterior><gml:LinearRing><gml:posList>{ring}</gml:posList>"
    "</gml:LinearRing></gml:exterior></gml:Polygon>"
    "</gml:surfaceMember></gml:MultiSurface></bldg:lod2MultiSurface></bldg:GroundSurface></bldg:boundedBy>"
    "</bldg:Building></core:cityObjectMember>"
    # a building without height is left out
    '<core:cityObjectMember><bldg:Building gml:id="NOHEIGHT"><bldg:boundedBy><bldg:GroundSurface>'
    "<bldg:lod2MultiSurface><gml:MultiSurface><gml:surfaceMember><gml:Polygon><gml:exterior><gml:LinearRing>"
    "<gml:posList>{ring}</gml:posList></gml:LinearRing></gml:exterior></gml:Polygon></gml:surfaceMember>"
    "</gml:MultiSurface></bldg:lod2MultiSurface></bldg:GroundSurface></bldg:boundedBy>"
    "</bldg:Building></core:cityObjectMember></core:CityModel>"
)


class TestTileNames:
    def _geoms(self):
        return gpd.GeoSeries([box(349800, 5766300, 349810, 5766310), box(350500, 5767100, 350510, 5767110)], crs=CRS)

    def test_one_km_tiles(self):
        assert lod2.tile_names(self._geoms(), "LoD2_32_{x}_{y}_1_NW.gml") == [
            "LoD2_32_349_5766_1_NW.gml", "LoD2_32_350_5767_1_NW.gml",
        ]

    def test_two_km_tiles_are_named_by_their_even_corner(self):
        assert lod2.tile_names(self._geoms(), "LoD2_32_{x}_{y}_2.gml", size_km=2) == [
            "LoD2_32_348_5766_2.gml", "LoD2_32_350_5766_2.gml",
        ]

    def test_a_tile_is_named_once(self):
        geoms = gpd.GeoSeries([box(349100, 5766100, 349110, 5766110), box(349800, 5766800, 349810, 5766810)], crs=CRS)
        assert lod2.tile_names(geoms, "{x}_{y}") == ["349_5766"]


class TestReadLod2:
    def test_reads_buildings_with_height_and_footprint(self, tmp_path):
        path = tmp_path / "tile.gml"
        path.write_text(TILE.format(ring="0 0 30 12 0 30 12 10 30 0 10 30 0 0 30"), encoding="utf-8")
        out = lod2.read_lod2(path)
        assert out["lod2_id"].tolist() == ["DENI03AL0001ABCD"]
        assert out["height"].iloc[0] == 6.0
        assert out.geometry.iloc[0].area == pytest.approx(120.0)
        assert out.crs == CRS

    def test_crs_of_a_state_in_zone_33(self, tmp_path):
        path = tmp_path / "tile.gml"
        path.write_text(TILE.format(ring="0 0 30 12 0 30 12 10 30 0 10 30 0 0 30"), encoding="utf-8")
        assert lod2.read_lod2(path, crs="EPSG:25833").crs == "EPSG:25833"

    def test_without_eaves_attribute_no_eaves_height(self, tmp_path):
        path = tmp_path / "tile.gml"
        path.write_text(TILE.format(ring="0 0 30 12 0 30 12 10 30 0 10 30 0 0 30"), encoding="utf-8")
        assert lod2.read_lod2(path)["eaves_height"].isna().all()

    def test_eaves_height_above_the_lowest_ground_point(self, tmp_path):
        eaves = '<gen:stringAttribute name="MittlereTraufHoehe"><gen:value>36.4</gen:value></gen:stringAttribute>'
        text = TILE.format(ring="0 0 30.2 12 0 30 12 10 30.5 0 10 30.1 0 0 30.2").replace(
            "<bldg:measuredHeight>", eaves + "<bldg:measuredHeight>", 1
        ).replace('xmlns:gml="http://www.opengis.net/gml"',
                  'xmlns:gml="http://www.opengis.net/gml" xmlns:gen="http://www.opengis.net/citygml/generics/1.0"')
        path = tmp_path / "tile.gml"
        path.write_text(text, encoding="utf-8")
        assert lod2.read_lod2(path)["eaves_height"].tolist() == pytest.approx([6.4])

    def test_empty_frame_keeps_the_columns(self):
        out = lod2.lod2_frame([])
        assert out.empty and list(out.columns) == ["lod2_id", "height", "eaves_height", "geometry"]
