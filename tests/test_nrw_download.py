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
