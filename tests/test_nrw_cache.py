"""Tests for fheat_nrw.cache and the cached download in fheat_nrw.download.

All HTTP calls are mocked:
- a cache hit does not download again; a newer index timestamp does
- a failed or cancelled download leaves no broken file behind
- the cache folder comes from the argument, FHEAT_CACHE_DIR or ~/.cache/fheat
- read_layer_bbox reads only the features in the box, from a shapefile or a
  GeoPackage inside a ZIP
"""
from __future__ import annotations

import io
import json
import urllib.request
import zipfile

import geopandas as gpd
import pytest
from shapely.geometry import box

from fheat_core import cancel
from fheat_nrw import cache
from fheat_nrw import download as dl

CRS = "EPSG:25832"
URL = "https://fake/kwp/"


class _ChunkedResponse:
    """urlopen stand-in that hands out its content in pieces."""

    def __init__(self, content: bytes, fail_after: int | None = None):
        self._buf = io.BytesIO(content)
        self._fail_after = fail_after
        self._reads = 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, size=-1):
        self._reads += 1
        if self._fail_after is not None and self._reads > self._fail_after:
            raise TimeoutError("connection lost")
        return self._buf.read(size)


@pytest.fixture
def downloads(monkeypatch):
    """Serve ``content`` for every URL and count the calls."""
    calls: list[str] = []
    state = {"content": b"v1", "fail_after": None}

    def fake_urlopen(url, timeout=None):
        calls.append(url)
        return _ChunkedResponse(state["content"], state["fail_after"])

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return calls, state


class TestCacheDir:
    def test_argument_wins(self, tmp_path, monkeypatch):
        monkeypatch.setenv(cache.ENV_CACHE_DIR, str(tmp_path / "env"))
        assert cache.cache_dir(tmp_path / "arg") == tmp_path / "arg"
        assert (tmp_path / "arg").is_dir()

    def test_environment_variable(self, tmp_path, monkeypatch):
        monkeypatch.setenv(cache.ENV_CACHE_DIR, str(tmp_path / "env"))
        assert cache.cache_dir() == tmp_path / "env"

    def test_default_in_home(self, tmp_path, monkeypatch):
        monkeypatch.delenv(cache.ENV_CACHE_DIR, raising=False)
        monkeypatch.setattr(cache, "DEFAULT_CACHE_DIR", tmp_path / "home" / ".cache" / "fheat")
        assert cache.cache_dir() == tmp_path / "home" / ".cache" / "fheat"


class TestCachedDownload:
    def test_downloads_once_then_hits_the_cache(self, tmp_path, downloads):
        calls, _ = downloads
        first = cache.cached_download(URL + "a.zip", "a.zip", "2024-12-18T08:00:53", tmp_path)
        second = cache.cached_download(URL + "a.zip", "a.zip", "2024-12-18T08:00:53", tmp_path)
        assert first == second == tmp_path / "a.zip"
        assert first.read_bytes() == b"v1"
        assert len(calls) == 1
        meta = json.loads((tmp_path / "a.zip.json").read_text(encoding="utf-8"))
        assert meta == {"url": URL + "a.zip", "timestamp": "2024-12-18T08:00:53", "size": 2}

    def test_newer_timestamp_loads_again(self, tmp_path, downloads):
        calls, state = downloads
        cache.cached_download(URL + "a.zip", "a.zip", "2024-12-18T08:00:53", tmp_path)
        state["content"] = b"v2"
        path = cache.cached_download(URL + "a.zip", "a.zip", "2025-02-20T13:24:06.630887", tmp_path)
        assert path.read_bytes() == b"v2"
        assert len(calls) == 2

    def test_older_or_missing_timestamp_keeps_the_file(self, tmp_path, downloads):
        calls, _ = downloads
        cache.cached_download(URL + "a.zip", "a.zip", "2025-02-20T13:24:06", tmp_path)
        cache.cached_download(URL + "a.zip", "a.zip", "2024-01-01T00:00:00", tmp_path)
        cache.cached_download(URL + "a.zip", "a.zip", None, tmp_path)
        assert len(calls) == 1

    def test_other_url_loads_again(self, tmp_path, downloads):
        calls, _ = downloads
        cache.cached_download(URL + "a.zip", "a.zip", None, tmp_path)
        cache.cached_download("https://other/a.zip", "a.zip", None, tmp_path)
        assert len(calls) == 2

    def test_broken_download_leaves_no_file(self, tmp_path, downloads):
        _, state = downloads
        state["content"] = b"x" * (3 * cache.CHUNK_SIZE)
        state["fail_after"] = 1
        with pytest.raises(RuntimeError, match="fehlgeschlagen"):
            cache.cached_download(URL + "a.zip", "a.zip", None, tmp_path)
        assert list(tmp_path.iterdir()) == []

    def test_broken_update_keeps_the_old_file(self, tmp_path, downloads):
        _, state = downloads
        cache.cached_download(URL + "a.zip", "a.zip", "2024-01-01T00:00:00", tmp_path)
        state["content"], state["fail_after"] = b"v2", 0
        with pytest.raises(RuntimeError):
            cache.cached_download(URL + "a.zip", "a.zip", "2025-01-01T00:00:00", tmp_path)
        assert (tmp_path / "a.zip").read_bytes() == b"v1"
        assert sorted(p.name for p in tmp_path.iterdir()) == ["a.zip", "a.zip.json"]

    def test_cancel_stops_the_download_without_a_file(self, tmp_path, downloads):
        _, state = downloads
        state["content"] = b"x" * (3 * cache.CHUNK_SIZE)
        with cancel.cancellable(lambda: True):
            with pytest.raises(cancel.CalculationCancelled):
                cache.cached_download(URL + "a.zip", "a.zip", None, tmp_path)
        assert list(tmp_path.iterdir()) == []


class TestCachedFile:
    def _index(self, monkeypatch, entries):
        monkeypatch.setattr(dl, "file_list_from_url", lambda url: entries)

    def test_uses_the_index_timestamp(self, tmp_path, monkeypatch):
        self._index(monkeypatch, [{"name": "a.zip", "size": "2", "timestamp": "2024-12-18T08:00:53"}])
        seen = {}

        def fake_cached_download(url, name, timestamp, folder):
            seen.update(url=url, name=name, timestamp=timestamp, folder=folder)
            return tmp_path / name

        monkeypatch.setattr(dl.cache, "cached_download", fake_cached_download)
        assert dl.cached_file(URL, "a.zip", tmp_path) == tmp_path / "a.zip"
        assert seen == {"url": URL + "a.zip", "name": "a.zip",
                        "timestamp": "2024-12-18T08:00:53", "folder": tmp_path}

    def test_unlisted_file_raises(self, tmp_path, monkeypatch):
        self._index(monkeypatch, [{"name": "b.zip"}])
        with pytest.raises(RuntimeError, match="nicht gelistet"):
            dl.cached_file(URL, "a.zip", tmp_path)

    def test_without_index_a_cached_file_is_used(self, tmp_path, monkeypatch):
        (tmp_path / "a.zip").write_bytes(b"v1")

        def unreachable(url):
            raise RuntimeError("Index nicht erreichbar")

        monkeypatch.setattr(dl, "file_list_from_url", unreachable)
        assert dl.cached_file(URL, "a.zip", tmp_path) == tmp_path / "a.zip"

    def test_without_index_and_cache_the_error_stays(self, tmp_path, monkeypatch):
        def unreachable(url):
            raise RuntimeError("Index nicht erreichbar")

        monkeypatch.setattr(dl, "file_list_from_url", unreachable)
        with pytest.raises(RuntimeError, match="nicht erreichbar"):
            dl.cached_file(URL, "a.zip", tmp_path)

    def test_find_file(self):
        files = [{"name": "a.zip", "size": "2", "timestamp": "t"}, {"name": "b.zip"}]
        assert dl.find_file(files, "a.zip") == {"name": "a.zip", "size": "2", "timestamp": "t"}
        assert dl.find_file(files, "c.zip") is None


def _squares() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"value": [1, 2, 3]},
        geometry=[box(0, 0, 10, 10), box(100, 0, 110, 10), box(1000, 0, 1010, 10)],
        crs=CRS,
    )


class TestReadLayerBbox:
    def test_shapefile_in_zip(self, tmp_path):
        folder = tmp_path / "shp"
        folder.mkdir()
        _squares().to_file(folder / "Potenzial-TG-Raster_05566084_Steinfurt.shp")
        zip_path = tmp_path / "gemeinde.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            for f in folder.iterdir():
                zf.write(f, arcname=f.name)
        gdf = cache.read_layer_bbox(zip_path, "Potenzial-TG-Raster_05566084_Steinfurt", (-5, -5, 105, 5))
        assert sorted(gdf["value"]) == [1, 2]

    def test_geopackage_layer_in_zip(self, tmp_path):
        gpkg = tmp_path / "data.gpkg"
        _squares().to_file(gpkg, layer="cells", driver="GPKG")
        zip_path = tmp_path / "nrw.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.write(gpkg, arcname="data.gpkg")
        gdf = cache.read_layer_bbox(zip_path, "cells", (900, -5, 2000, 5))
        assert list(gdf["value"]) == [3]

    def test_zip_without_vector_data_raises(self, tmp_path):
        zip_path = tmp_path / "empty.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("readme.txt", "x")
        with pytest.raises(RuntimeError, match="keine Geodatabase"):
            cache.read_layer_bbox(zip_path, "cells", (0, 0, 1, 1))

    def test_no_zip_raises(self, tmp_path):
        path = tmp_path / "broken.zip"
        path.write_bytes(b"no zip")
        with pytest.raises(RuntimeError, match="nicht lesbar"):
            cache.read_layer_bbox(path, "cells", (0, 0, 1, 1))
