"""Tests for the NDSDataAdapter and fheat_nds.download, with every download faked."""
from __future__ import annotations

import io
from importlib.resources import files
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString, box

from fheat_core import columns as cols
from fheat_core.schemas import BuildingsSchema, ParcelsSchema, StreetsSchema
from fheat_de import zensus
from fheat_de.area import read_catalog
from fheat_nds import download as dl
from fheat_nds.adapter.data_adapter import NDSDataAdapter

CRS = "EPSG:25832"
CATALOG = (
    "name,schluessel,gemeinde,gmdschl,bbox\n"
    "Bad Bentheim,34204,\"Bad Bentheim, Stadt\",3456001,\"(0.0, 0.0, 300.0, 100.0)\"\n"
    "Gildehaus,34203,\"Bad Bentheim, Stadt\",3456001,\"(300.0, 0.0, 600.0, 100.0)\"\n"
)


def _parcels():
    return gpd.GeoDataFrame(
        {"gemaschl": ["034204", "034204", "034203"], "gmdschl": ["03456001"] * 3},
        geometry=[box(0, 0, 150, 100), box(150, 0, 300, 100), box(300, 0, 600, 100)],
        crs=CRS,
    )


def _alkis(bbox, municipality_key=None):
    return gpd.GeoDataFrame(
        {"gfkzshh": ["31001_1000", "31001_1000", "31001_1000"], "funktion": ["Wohngebäude"] * 3,
         "lagebeztxt": ["A 1", "A 2", "B 1"], "gmdschl": ["03456001"] * 3, "gebnutzbez": ["Gebäude"] * 3},
        geometry=[box(10, 10, 20, 20), box(160, 10, 170, 20), box(400, 10, 410, 20)],
        crs=CRS,
    )


@pytest.fixture
def adapter(monkeypatch, tmp_path):
    path = tmp_path / "cities.csv"
    path.write_text(CATALOG, encoding="utf-8")
    calls = {}

    def get_parcels(bbox, district_key=None):
        calls["bbox"] = bbox
        parcels = _parcels()
        return parcels if district_key is None else dl.district_parcels(parcels, district_key)

    monkeypatch.setattr(dl, "get_parcels", get_parcels)
    monkeypatch.setattr(dl, "get_alkis_buildings", _alkis)
    monkeypatch.setattr(dl, "get_streets", lambda bbox: gpd.GeoDataFrame(
        geometry=[LineString([(0, 30), (600, 30)]), LineString([(5000, 0), (5100, 0)])], crs=CRS))
    monkeypatch.setattr(dl, "load_lod2", lambda geoms, cache_dir=None, keep_tiles=False: None)
    monkeypatch.setattr(zensus, "construction_classes", lambda points, cache_dir=None: pd.Series("F", index=points.index))

    def make(**kw):
        return NDSDataAdapter(cities_path=path, download_landuse=False, download_osm_surface=False, **kw)

    make.calls = calls
    return make


class TestAdapter:
    def test_needs_an_area(self):
        with pytest.raises(ValueError, match="municipality_name"):
            NDSDataAdapter()

    def test_municipality_loads_all_its_districts(self, adapter):
        a = adapter(municipality_name="Bad Bentheim, Stadt")
        assert len(a.fetch_buildings()) == 3 and len(a.fetch_parcels()) == 3
        assert adapter.calls["bbox"] == (0.0, 0.0, 600.0, 100.0)
        BuildingsSchema.validate(a.fetch_buildings())
        StreetsSchema.validate(a.fetch_streets())
        ParcelsSchema.validate(a.fetch_parcels())
        assert len(a.fetch_streets()) == 1                    # the street far away is left out
        assert (a.fetch_streets()[cols.ROUTABLE] == 1).all()
        assert a.municipality_key == "03456001"

    def test_district_is_cut_to_its_parcels(self, adapter):
        a = adapter(district_key="34204")
        assert len(a.fetch_parcels()) == 2
        assert a.fetch_buildings()[cols.ADDRESS].tolist() == ["A 1", "A 2"]
        assert a.provide_boundary().geometry.iloc[0].bounds == (0.0, 0.0, 300.0, 100.0)

    def test_heat_source_in_the_crs_of_the_buildings(self, adapter):
        a = adapter(municipality_name="Bad Bentheim, Stadt", source_coordinates=(52.3, 7.16))
        assert a.fetch_source().crs == a.fetch_buildings().crs

    def test_unknown_area_raises(self, adapter):
        with pytest.raises(RuntimeError, match="Gebietskatalog"):
            adapter(municipality_name="Nirgendwo").fetch_buildings()

    def test_a_failed_zensus_download_keeps_the_buildings(self, adapter, monkeypatch):
        def fail(points, cache_dir=None):
            raise RuntimeError("offline")

        monkeypatch.setattr(zensus, "construction_classes", fail)
        out = adapter(district_key="34204").fetch_buildings()
        assert len(out) == 2 and set(out[cols.CONSTRUCTION_CLASS]) == {"E"}

    def test_optional_layers_with_area_bbox_without_the_buildings(self, monkeypatch, tmp_path):
        landuse = gpd.GeoDataFrame({"nutzart": ["Wald"]}, geometry=[box(0, 0, 10, 10)], crs=CRS)
        monkeypatch.setattr(dl, "get_landuse", lambda bbox: landuse)
        a = NDSDataAdapter(municipality_name="x", area_bbox=(0, 0, 10, 10), download_osm_surface=False)
        monkeypatch.setattr(a, "_ensure_loaded", lambda: pytest.fail("buildings must not be loaded"))
        out = a.fetch_landuse()
        assert out["civil_cost_factor"].tolist() == [1.2]
        assert a.fetch_osm_surface() is None


class _FakeWFS:
    pages = []

    def __init__(self, url, version, timeout):
        self.requests = []

    def getfeature(self, **kw):
        _FakeWFS.pages.append(kw)
        start = kw["startindex"]
        n = min(kw["maxfeatures"], 5 - start)
        gdf = gpd.GeoDataFrame({"i": list(range(start, start + n))},
                               geometry=[box(i, 0, i + 1, 1) for i in range(start, start + n)], crs=CRS)
        return io.BytesIO(gdf.to_json().encode())


class TestDownload:
    def test_features_are_paged(self, monkeypatch):
        _FakeWFS.pages = []
        monkeypatch.setattr(dl, "WebFeatureService", _FakeWFS)
        out = dl.get_features("https://fake/", "ave:Flurstueck", (0, 0, 10, 10), page_size=2)
        assert out["i"].tolist() == [0, 1, 2, 3, 4]
        assert [p["startindex"] for p in _FakeWFS.pages] == [0, 2, 4]

    def test_a_failed_request_raises_runtime(self, monkeypatch):
        def broken(*a, **kw):
            raise OSError("down")

        monkeypatch.setattr(dl, "WebFeatureService", broken)
        with pytest.raises(RuntimeError, match="ave:Flurstueck"):
            dl.get_features("https://fake/", "ave:Flurstueck", (0, 0, 1, 1))

    def test_district_parcels_by_the_six_digit_key(self):
        assert len(dl.district_parcels(_parcels(), "34204")) == 2
        assert len(dl.district_parcels(_parcels(), "034203")) == 1

    def test_buildings_without_parts_and_of_the_municipality(self, monkeypatch):
        raw = gpd.GeoDataFrame(
            {"gebnutzbez": ["Gebäude", "Bauteil", "Gebäude"], "gmdschl": ["03456001", "03456001", "03456002"]},
            geometry=[box(0, 0, 1, 1)] * 3, crs=CRS,
        )
        monkeypatch.setattr(dl, "get_features", lambda *a, **kw: raw)
        assert len(dl.get_alkis_buildings((0, 0, 1, 1), "3456001")) == 1
        assert len(dl.get_alkis_buildings((0, 0, 1, 1))) == 2

    def test_lod2_tiles_outside_the_state_are_skipped(self, monkeypatch):
        import urllib.error

        def download(url, name, timestamp, cache_dir):
            raise RuntimeError("404") from urllib.error.HTTPError(url, 404, "missing", {}, None)

        monkeypatch.setattr(dl.cache, "cached_download", download)
        geoms = gpd.GeoSeries([box(375100, 5796100, 375110, 5796110)], crs=CRS)
        assert dl.lod2_tiles(geoms) == ["LoD2_32_375_5796_1_ni.gml"]
        assert dl.load_lod2(geoms).empty

    def test_lod2_tiles_are_deleted_after_reading_unless_kept(self, monkeypatch, tmp_path):
        from fheat_de.lod2 import lod2_frame

        saved = []

        def download(url, name, timestamp, cache_dir):
            path = Path(cache_dir) / name
            path.write_text("<gml/>", encoding="utf-8")
            saved.append(path)
            return path

        monkeypatch.setattr(dl.cache, "cached_download", download)
        monkeypatch.setattr(dl, "read_lod2", lambda path: lod2_frame([]))
        geoms = gpd.GeoSeries([box(375100, 5796100, 375110, 5796110)], crs=CRS)
        dl.load_lod2(geoms, cache_dir=tmp_path)
        assert saved[-1].parent != tmp_path and not saved[-1].exists()
        dl.load_lod2(geoms, cache_dir=tmp_path, keep_tiles=True)
        assert saved[-1] == tmp_path / "LoD2_32_375_5796_1_ni.gml" and saved[-1].exists()


class TestCatalog:
    def test_shipped_catalogue(self):
        with files("fheat_nds.data").joinpath("cities.csv").open("rb") as f:
            cities = read_catalog(f)
        assert cities["schluessel"].is_unique
        municipalities = cities.drop_duplicates("gmdschl")
        assert municipalities["gemeinde"].is_unique
        assert cities["gmdschl"].str.zfill(8).str.startswith("03").all()
        bentheim = cities[cities["schluessel"] == "34204"].iloc[0]
        assert (bentheim["name"], bentheim["gemeinde"], bentheim["gmdschl"]) == ("Bad Bentheim", "Bad Bentheim, Stadt", "3456001")

    def test_no_key_of_nrw(self):
        with files("fheat_nds.data").joinpath("cities.csv").open("rb") as f:
            nds = read_catalog(f)
        with files("fheat_nrw.data").joinpath("cities.csv").open("rb") as f:
            nrw = read_catalog(f)
        assert not set(nds["schluessel"]) & set(nrw["schluessel"])
        assert not set(nds["gmdschl"]) & set(nrw["gmdschl"])


@pytest.mark.network
def test_live_district_bad_bentheim():
    """The real services: Gemarkung Bad Bentheim (LGLN WFS, LoD2, Zensus 2022)."""
    a = NDSDataAdapter(district_key="34204", download_landuse=False, download_osm_surface=False)
    buildings = a.fetch_buildings()
    BuildingsSchema.validate(buildings)
    StreetsSchema.validate(a.fetch_streets())
    assert len(buildings) > 2000
    assert (buildings[cols.DATA_SOURCE] == "alkis_lod2").mean() > 0.8
    residential = buildings[buildings[cols.BUILDING_TYPE].isin(["EFH", "MFH"])]
    specific = residential[cols.HEAT_DEMAND] / residential[cols.FLOOR_AREA]
    assert 80 < specific.median() < 220
