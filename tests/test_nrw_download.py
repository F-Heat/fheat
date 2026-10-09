"""Tests for fheat_nrw.download.

Covers (with HTTP and WFS calls mocked):
- parse_bbox: tuple/list/string parsing, error paths
- file_list_from_url: index parsing, network error path
- search_filename: hit, miss, multiple files
- read_shapefile_from_zip: ZIP extraction, missing-pattern error
- get_parcels_from_wfs: nationalCadastralReference filter uses "0" + key
  (regression for the bug fixed in NRW filter logic).
"""
from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
import zipfile
from io import BytesIO
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Polygon

from fheat_nrw import download as nrw_download
from fheat_nrw.download import (
    file_list_from_url,
    get_parcels_from_wfs,
    parse_bbox,
    read_shapefile_from_zip,
    search_filename,
)


CRS = "EPSG:25832"


# ---------------------------------------------------------------------------
# parse_bbox
# ---------------------------------------------------------------------------


class TestParseBbox:
    def test_parses_tuple_string(self):
        assert parse_bbox("(1.0, 2.0, 3.0, 4.0)") == [1.0, 2.0, 3.0, 4.0]

    def test_parses_plain_string(self):
        assert parse_bbox("1, 2, 3, 4") == [1.0, 2.0, 3.0, 4.0]

    def test_parses_with_spaces_and_braces(self):
        assert parse_bbox(" ( 5.5 , 6.5 , 7.5 , 8.5 ) ") == [5.5, 6.5, 7.5, 8.5]

    def test_nan_raises(self):
        with pytest.raises(ValueError, match="leer/NaN"):
            parse_bbox(float("nan"))

    def test_wrong_count_raises(self):
        with pytest.raises(ValueError, match="4 Komponenten"):
            parse_bbox("1, 2, 3")

    def test_non_numeric_raises(self):
        with pytest.raises(ValueError):
            parse_bbox("a, b, c, d")


# ---------------------------------------------------------------------------
# file_list_from_url
# ---------------------------------------------------------------------------


class _FakeResponse:
    """Minimal stand-in for the urlopen context-manager response."""

    def __init__(self, content: bytes):
        self._content = content

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._content


class TestFileListFromUrl:
    def test_parses_well_formed_index(self, monkeypatch):
        index_payload = (
            "{'datasets': ["
            "{'files': [{'name': 'kwp_05154000.zip'}, {'name': 'kwp_05158020.zip'}]}, "
            "{'files': [{'name': 'kwp_05566000.zip'}]}"
            "]}"
        )

        def fake_urlopen(url, timeout=120):
            return _FakeResponse(index_payload.encode("latin1"))

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        files = file_list_from_url("https://fake/")
        assert {"name": "kwp_05154000.zip"} in files
        assert {"name": "kwp_05158020.zip"} in files
        assert {"name": "kwp_05566000.zip"} in files
        assert len(files) == 3

    def test_unreachable_url_raises_runtime(self, monkeypatch):
        def fake_urlopen(url, timeout=120):
            raise urllib.error.URLError("boom")

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        with pytest.raises(RuntimeError, match="nicht erreichbar"):
            file_list_from_url("https://fake/")

    def test_malformed_payload_raises_runtime(self, monkeypatch):
        def fake_urlopen(url, timeout=120):
            return _FakeResponse(b"<<not python literal>>")

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        with pytest.raises(RuntimeError, match="unerwartetes Format"):
            file_list_from_url("https://fake/")


# ---------------------------------------------------------------------------
# search_filename
# ---------------------------------------------------------------------------


class TestSearchFilename:
    def test_finds_matching_file(self):
        files = [{"name": "kwp_05154000.zip"}, {"name": "kwp_05566000.zip"}]
        assert search_filename(files, "05566000") == "kwp_05566000.zip"

    def test_returns_no_data_when_missing(self):
        assert search_filename([{"name": "x.zip"}], "99999999") == "No data found"

    def test_first_match_wins(self):
        files = [{"name": "kwp_055.zip"}, {"name": "kwp_055_v2.zip"}]
        assert search_filename(files, "055") == "kwp_055.zip"


# ---------------------------------------------------------------------------
# read_shapefile_from_zip
# ---------------------------------------------------------------------------


def _make_shapefile_zip_bytes(tmp_path: Path, pattern: str) -> bytes:
    """Build a real ZIP archive containing a real shapefile of one polygon."""
    gdf = gpd.GeoDataFrame(
        {"id": [1], "geometry": [Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])]},
        crs=CRS, geometry="geometry",
    )
    shp_dir = tmp_path / "shp"
    shp_dir.mkdir()
    shp_path = shp_dir / f"{pattern}.shp"
    gdf.to_file(str(shp_path))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
            f = shp_path.with_suffix(ext)
            if f.exists():
                zf.write(f, arcname=f.name)
    buf.seek(0)
    return buf.read()


class TestReadShapefileFromZip:
    def test_reads_shapefile_from_zip(self, monkeypatch, tmp_path):
        zip_bytes = _make_shapefile_zip_bytes(tmp_path, "Gebaeude")

        def fake_urlopen(url, timeout=120):
            return _FakeResponse(zip_bytes)

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        gdf = read_shapefile_from_zip(
            url="https://fake/",
            zipfile_name="kwp_test.zip",
            file_pattern="Gebaeude",
        )
        assert isinstance(gdf, gpd.GeoDataFrame)
        assert len(gdf) == 1
        assert gdf.geometry.iloc[0].is_valid

    def test_missing_pattern_raises(self, monkeypatch, tmp_path):
        zip_bytes = _make_shapefile_zip_bytes(tmp_path, "Other")

        def fake_urlopen(url, timeout=120):
            return _FakeResponse(zip_bytes)

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        with pytest.raises(RuntimeError, match="kein Shapefile"):
            read_shapefile_from_zip(
                url="https://fake/", zipfile_name="kwp_test.zip",
                file_pattern="DoesNotExist",
            )

    def test_corrupt_zip_raises_runtime(self, monkeypatch):
        def fake_urlopen(url, timeout=120):
            return _FakeResponse(b"not a real zip")

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        with pytest.raises(RuntimeError, match="beschaedigt"):
            read_shapefile_from_zip(
                url="https://fake/", zipfile_name="kwp.zip",
                file_pattern="X",
            )


# ---------------------------------------------------------------------------
# get_parcels_from_wfs — regression test for "0" + key prefix bug
# ---------------------------------------------------------------------------


class _FakeWfsResponse(io.BytesIO):
    def __init__(self, content: bytes):
        super().__init__(content)


class TestGetParcelsFromWfs:
    def _build_parcels_geopackage_bytes(self, tmp_path) -> bytes:
        """Write a tiny GPKG with two parcels and read it back as bytes."""
        gdf = gpd.GeoDataFrame(
            {
                "nationalCadastralReference": ["055190001", "099999001"],
                "geometry": [
                    Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
                    Polygon([(2, 2), (3, 2), (3, 3), (2, 3)]),
                ],
            },
            crs=CRS, geometry="geometry",
        )
        path = tmp_path / "parcels.gpkg"
        gdf.to_file(str(path), driver="GPKG")
        return path.read_bytes()

    def test_filters_by_zero_prefixed_key(self, monkeypatch, tmp_path):
        """Cities.xlsx schluessel '55190' must match nationalCadastralReference '055190…'.

        Regression test: pre-fix, this code used .startswith(key) and returned
        an empty frame because the WFS response prefixes keys with '0'.
        """
        gpkg_bytes = self._build_parcels_geopackage_bytes(tmp_path)

        class FakeWFS:
            def __init__(self, *a, **kw):
                pass

            def getfeature(self, typename, outputFormat, bbox):
                return io.BytesIO(gpkg_bytes)

        monkeypatch.setattr(nrw_download, "WebFeatureService", FakeWFS)

        result = get_parcels_from_wfs(
            wfs_url="https://fake/",
            key="55190",
            bbox=(0, 0, 10, 10),
            layer_name="cp:CadastralParcel",
        )
        assert len(result) == 1
        assert result["nationalCadastralReference"].iloc[0].startswith("055190")

    def test_empty_when_no_match(self, monkeypatch, tmp_path):
        gpkg_bytes = self._build_parcels_geopackage_bytes(tmp_path)

        class FakeWFS:
            def __init__(self, *a, **kw):
                pass

            def getfeature(self, typename, outputFormat, bbox):
                return io.BytesIO(gpkg_bytes)

        monkeypatch.setattr(nrw_download, "WebFeatureService", FakeWFS)

        result = get_parcels_from_wfs(
            wfs_url="https://fake/",
            key="00000",  # no parcel reference starts with "000000"
            bbox=(0, 0, 10, 10),
            layer_name="cp:CadastralParcel",
        )
        assert len(result) == 0

    def test_missing_reference_column_returns_empty(self, monkeypatch, tmp_path):
        """Some WFS responses lack nationalCadastralReference altogether."""
        gdf = gpd.GeoDataFrame(
            {"geometry": [Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])]},
            crs=CRS, geometry="geometry",
        )
        path = tmp_path / "no_ref.gpkg"
        gdf.to_file(str(path), driver="GPKG")
        gpkg_bytes = path.read_bytes()

        class FakeWFS:
            def __init__(self, *a, **kw):
                pass

            def getfeature(self, typename, outputFormat, bbox):
                return io.BytesIO(gpkg_bytes)

        monkeypatch.setattr(nrw_download, "WebFeatureService", FakeWFS)

        result = get_parcels_from_wfs(
            wfs_url="https://fake/", key="55190",
            bbox=(0, 0, 10, 10), layer_name="cp:CadastralParcel",
        )
        assert len(result) == 0

    def test_wfs_failure_raises_runtime(self, monkeypatch):
        class FakeWFS:
            def __init__(self, *a, **kw):
                raise OSError("simulated network failure")

        monkeypatch.setattr(nrw_download, "WebFeatureService", FakeWFS)

        with pytest.raises(RuntimeError, match="WFS-Anfrage"):
            get_parcels_from_wfs(
                wfs_url="https://fake/", key="55190",
                bbox=(0, 0, 10, 10), layer_name="cp:CadastralParcel",
            )


# ---------------------------------------------------------------------------
# get_landuse_from_wfs
# ---------------------------------------------------------------------------


class TestGetLanduseFromWfs:
    def test_returns_raw_attributes(self, monkeypatch, tmp_path):
        gdf = gpd.GeoDataFrame(
            {"nutzart": ["Straßenverkehr"], "geometry": [Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])]},
            crs=CRS, geometry="geometry",
        )
        path = tmp_path / "landuse.gpkg"
        gdf.to_file(str(path), driver="GPKG")
        payload = path.read_bytes()
        calls = {}

        class FakeWFS:
            def __init__(self, *a, **kw):
                pass

            def getfeature(self, typename, outputFormat, bbox):
                calls["typename"], calls["bbox"] = typename, bbox
                return io.BytesIO(payload)

        monkeypatch.setattr(nrw_download, "WebFeatureService", FakeWFS)
        result = nrw_download.get_landuse_from_wfs("https://fake/", (0, 0, 10, 10), "ave:Nutzung")
        assert result["nutzart"].tolist() == ["Straßenverkehr"]
        assert calls == {"typename": "ave:Nutzung", "bbox": (0, 0, 10, 10)}

    def test_wfs_failure_raises_runtime(self, monkeypatch):
        class FakeWFS:
            def __init__(self, *a, **kw):
                raise OSError("simulated network failure")

        monkeypatch.setattr(nrw_download, "WebFeatureService", FakeWFS)
        with pytest.raises(RuntimeError, match="Nutzung"):
            nrw_download.get_landuse_from_wfs("https://fake/", (0, 0, 10, 10), "ave:Nutzung")


# ---------------------------------------------------------------------------
# get_osm_surface_via_overpass
# ---------------------------------------------------------------------------

_OVERPASS_PAYLOAD = {
    "elements": [
        {
            "type": "way", "id": 1,
            "tags": {"highway": "residential", "surface": "asphalt", "lanes": "2"},
            "geometry": [{"lat": 52.15, "lon": 7.33}, {"lat": 52.151, "lon": 7.331}],
        },
        {
            "type": "way", "id": 2,
            "tags": {"highway": "track"},
            "geometry": [{"lat": 52.16, "lon": 7.34}, {"lat": 52.161, "lon": 7.341}],
        },
        {"type": "way", "id": 3, "tags": {"highway": "path"}, "geometry": [{"lat": 52.1, "lon": 7.3}]},
        {"type": "node", "id": 4, "lat": 52.1, "lon": 7.3},
    ]
}
_EMPTY_OVERPASS = json.dumps({"elements": []}).encode()


def _http_error(code):
    return urllib.error.HTTPError("https://fake/", code, "busy", {}, None)


class TestGetOsmSurfaceViaOverpass:
    def test_parses_ways_into_lines(self, monkeypatch):
        seen = {}

        def fake_urlopen(req, timeout=None):
            seen["ua"] = req.get_header("User-agent")
            seen["data"] = req.data.decode()
            return _FakeResponse(json.dumps(_OVERPASS_PAYLOAD).encode())

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        out = nrw_download.get_osm_surface_via_overpass((52.0, 7.0, 52.5, 7.5), overpass_url="https://fake/")

        assert out.crs == "EPSG:4326"
        assert {"osm_id", "highway", "surface", "tracktype", "width", "lanes"} <= set(out.columns)
        assert out["osm_id"].tolist() == [1, 2]          # one-point way and node dropped
        assert out["surface"].iloc[0] == "asphalt"
        assert pd.isna(out["surface"].iloc[1])
        assert out.geometry.geom_type.tolist() == ["LineString", "LineString"]
        assert seen["ua"].startswith("fheat/")
        assert "52.0%2C7.0%2C52.5%2C7.5" in seen["data"]

    def test_empty_answer_gives_empty_frame_with_columns(self, monkeypatch):
        monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: _FakeResponse(_EMPTY_OVERPASS))
        out = nrw_download.get_osm_surface_via_overpass((52.0, 7.0, 52.5, 7.5))
        assert out.empty
        assert "surface" in out.columns
        assert out.crs == "EPSG:4326"

    def test_http_error_raises_runtime(self, monkeypatch):
        def fake_urlopen(req, timeout=None):
            raise _http_error(400)

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        with pytest.raises(RuntimeError, match="Overpass"):
            nrw_download.get_osm_surface_via_overpass((52.0, 7.0, 52.5, 7.5))

    def test_busy_server_is_retried(self, monkeypatch):
        attempts = []

        def fake_urlopen(req, timeout=None):
            attempts.append(1)
            if len(attempts) < 3:
                raise _http_error(504)
            return _FakeResponse(_EMPTY_OVERPASS)

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        monkeypatch.setattr(nrw_download.time, "sleep", lambda s: None)
        nrw_download.get_osm_surface_via_overpass((52.0, 7.0, 52.5, 7.5), retries=3)
        assert len(attempts) == 3

    def test_gives_up_after_the_retries(self, monkeypatch):
        attempts = []

        def fake_urlopen(req, timeout=None):
            attempts.append(1)
            raise _http_error(504)

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        monkeypatch.setattr(nrw_download.time, "sleep", lambda s: None)
        with pytest.raises(RuntimeError, match="Overpass"):
            nrw_download.get_osm_surface_via_overpass((52.0, 7.0, 52.5, 7.5), retries=2)
        assert len(attempts) == 2

    def test_unreachable_raises_runtime(self, monkeypatch):
        def fake_urlopen(req, timeout=None):
            raise urllib.error.URLError("no route")

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        with pytest.raises(RuntimeError, match="Overpass"):
            nrw_download.get_osm_surface_via_overpass((52.0, 7.0, 52.5, 7.5))
