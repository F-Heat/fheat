"""Local cache for large OpenGeoData NRW files.

Files such as the NRW-wide solar thermal geodatabase (63 MB) are downloaded
once and read from disk afterwards, only the part inside a bbox. A file is
loaded again when ``index.json`` of its folder lists a newer timestamp.

Cache folder: see :func:`fheat_core.cache.cache_dir`. Next to each file a small
``<file>.json`` keeps the URL, timestamp and size it was loaded with.

Reading straight from the server (``/vsizip//vsicurl/<url>``) works with a
bbox too, but took 12 s per run for the solar thermal file (cache: 1.5 s,
checked 2026-10-19), so it is not used.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import geopandas as gpd

from fheat_core import cancel
from fheat_core.cache import DEFAULT_CACHE_DIR, ENV_CACHE_DIR, PathLike, cache_dir  # noqa: F401 (re-exported)

HTTP_TIMEOUT = 120
CHUNK_SIZE = 1 << 20  # 1 MiB between two cancel checks


def _parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).strip())
    except ValueError:
        return None


def _read_meta(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _is_current(target: Path, meta: dict, url: str, expected_timestamp: Optional[str]) -> bool:
    if not target.exists() or meta.get("url") != url:
        return False
    expected = _parse_timestamp(expected_timestamp)
    if expected is None:
        return True
    stored = _parse_timestamp(meta.get("timestamp"))
    return stored is not None and stored >= expected


def cached_download(
    url: str,
    filename: str,
    expected_timestamp: Optional[str] = None,
    cache_dir_override: Optional[PathLike] = None,
    timeout: int = HTTP_TIMEOUT,
) -> Path:
    """Path of ``url`` in the cache, downloaded if missing or out of date.

    ``expected_timestamp`` is the ``timestamp`` of the file in ``index.json``;
    a newer one than the stored file loads it again. Without it a file in the
    cache is always used. The download goes into a ``.part`` file that is
    renamed at the end, so a failed or cancelled download leaves no broken
    file behind.
    """
    folder = cache_dir(cache_dir_override)
    target = folder / filename
    meta_path = folder / f"{filename}.json"
    if _is_current(target, _read_meta(meta_path), url, expected_timestamp):
        return target

    part = folder / f"{filename}.{os.getpid()}.part"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp, open(part, "wb") as out:
            while True:
                cancel.raise_if_cancelled()
                chunk = resp.read(CHUNK_SIZE)
                if not chunk:
                    break
                out.write(chunk)
        os.replace(part, target)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise RuntimeError(f"Download von '{url}' fehlgeschlagen: {e}") from e
    finally:
        # also on CalculationCancelled, which is no Exception
        if part.exists():
            part.unlink()
    meta = {"url": url, "timestamp": expected_timestamp, "size": target.stat().st_size}
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    return target


def vector_source(zip_path: PathLike, layer: Optional[str] = None) -> str:
    """GDAL path of the vector data inside a ZIP.

    A shapefile whose name contains ``layer`` wins (like
    ``Potenzial-ONG-MTG-Baublock_05566084`` in
    ``Potenzial-ONG-MTG-Baublock_05566084_Steinfurt.shp``); otherwise the
    first geodatabase or GeoPackage.
    """
    zip_path = Path(zip_path)
    try:
        names = zipfile.ZipFile(zip_path).namelist()
    except (OSError, zipfile.BadZipFile) as e:
        raise RuntimeError(f"ZIP-Datei '{zip_path}' ist nicht lesbar: {e}") from e
    if layer:
        shapes = [n for n in names if n.endswith(".shp") and layer in n.rsplit("/", 1)[-1]]
        if shapes:
            return f"/vsizip/{zip_path.as_posix()}/{shapes[0]}"
    gdbs = sorted({n.split(".gdb/")[0] + ".gdb" for n in names if ".gdb/" in n})
    packages = [n for n in names if n.endswith(".gpkg")]
    if not gdbs and not packages:
        raise RuntimeError(f"In ZIP '{zip_path.name}' gibt es keine Geodatabase/GeoPackage/Shape '{layer}'.")
    return f"/vsizip/{zip_path.as_posix()}/{(gdbs + packages)[0]}"


def read_layer_bbox(
    zip_path: PathLike,
    layer: Optional[str],
    bbox: tuple[float, float, float, float],
) -> gpd.GeoDataFrame:
    """Features of ``layer`` inside ``zip_path`` that intersect ``bbox``.

    ``bbox`` is (minx, miny, maxx, maxy) in the CRS of the data. ``layer`` is
    the layer of a geodatabase/GeoPackage, or the end of a shapefile name.
    Only the features in the box are read, the ZIP is not extracted.
    """
    source = vector_source(zip_path, layer)
    kwargs = {"bbox": tuple(float(v) for v in bbox)}
    if layer and not source.endswith(".shp"):
        kwargs["layer"] = layer
    try:
        return gpd.read_file(source, **kwargs)
    except Exception as e:
        raise RuntimeError(f"Layer '{layer}' aus '{Path(zip_path).name}' nicht lesbar: {e}") from e
