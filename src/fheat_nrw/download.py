"""NRW Open Geodata download helpers (NRW-specific)."""
from __future__ import annotations

import ast
import json
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from importlib.metadata import PackageNotFoundError, version
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

import geopandas as gpd
import pandas as pd
from owslib.wfs import WebFeatureService
from shapely.geometry import LineString

from fheat_nrw.area import district_parcels

URL_BUILDINGS = "https://www.opengeodata.nrw.de/produkte/umwelt_klima/energie/kwp/"
URL_PARCELS = "https://www.wfs.nrw.de/geobasis/wfs_nw_inspire-flurstuecke_alkis"
LAYER_PARCELS = "cp:CadastralParcel"
# ALKIS "Tatsächliche Nutzung" (simplified ALKIS). Checked 2026-10-09 via
# GetCapabilities/DescribeFeatureType: the layer exists, default CRS
# EPSG:25832, the object type is in the column "nutzart" (plain text such as
# "Straßenverkehr", "Fließgewässer"). Licence: Datenlizenz Deutschland – Zero 2.0.
URL_LANDUSE = "https://www.wfs.nrw.de/geobasis/wfs_nw_alkis_vereinfacht"
LAYER_LANDUSE = "ave:Nutzung"
WFS_VERSION = "2.0.0"
WFS_OUTPUT_FORMAT = "text/xml"
HTTP_TIMEOUT = 120

#: Default Overpass endpoint; NRWDataAdapter(osm_overpass_url=...) selects a mirror.
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OSM_TIMEOUT = 90
# The public instance is often busy (HTTP 504/429). On 2026-10-09 two of three
# requests for Burgsteinfurt failed that way, and a whole-municipality request
# for Steinfurt failed three times in a row while the next one answered in
# 1.3 s (3.8 MB) - the size is no problem, the instance is just busy at times.
# So busy answers are retried with growing pauses (5+10+15+20 s).
OSM_RETRIES = 5
OSM_RETRY_WAIT = 5  # s, multiplied by the attempt number
_OSM_RETRY_STATUS = frozenset({429, 502, 503, 504})
_OSM_COLUMNS = ("osm_id", "highway", "surface", "tracktype", "width", "lanes")


def _user_agent() -> str:
    # overpass-api.de answers 406 to requests without a meaningful User-Agent.
    try:
        v = version("fheat")
    except PackageNotFoundError:
        v = "dev"
    return f"fheat/{v} (+https://github.com/F-Heat/fheat)"


def parse_bbox(value) -> list[float]:
    if pd.isna(value):
        raise ValueError("bbox-Wert ist leer/NaN")
    s = str(value).strip().replace("(", "").replace(")", "")
    parts = [p.strip() for p in s.split(",")]
    if len(parts) != 4:
        raise ValueError(f"bbox muss 4 Komponenten haben, gefunden {len(parts)}: '{value}'")
    return [float(p) for p in parts]


def file_list_from_url(url: str) -> list:
    try:
        with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT) as resp:
            content = resp.read().decode("latin1").strip()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise RuntimeError(f"OpenGeoData NRW Index ({url}) nicht erreichbar: {e}") from e
    try:
        data = ast.literal_eval(content)
    except (ValueError, SyntaxError) as e:
        raise RuntimeError(f"OpenGeoData NRW Index ({url}) hat unerwartetes Format: {e}") from e
    files = []
    for ds in data.get("datasets", []):
        files.extend(ds.get("files", []))
    return files


def search_filename(files: list, city_id: str) -> str:
    for item in files:
        if str(city_id) in item.get("name", ""):
            return item["name"]
    return "No data found"


def read_shapefile_from_zip(
    url: str,
    zipfile_name: str,
    file_pattern: str,
    encoding: str = "utf-8",
) -> gpd.GeoDataFrame:
    full_url = url + zipfile_name
    try:
        with urllib.request.urlopen(full_url, timeout=HTTP_TIMEOUT) as resp:
            zip_bytes = resp.read()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise RuntimeError(f"ZIP-Download von '{full_url}' fehlgeschlagen: {e}") from e
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            with ZipFile(BytesIO(zip_bytes)) as z:
                z.extractall(temp_dir)
                matching = [f for f in z.namelist() if file_pattern in f and f.endswith(".shp")]
                if not matching:
                    raise RuntimeError(
                        f"In ZIP '{zipfile_name}' wurde kein Shapefile mit "
                        f"Muster '{file_pattern}.shp' gefunden."
                    )
                return gpd.read_file(str(Path(temp_dir) / matching[0]), encoding=encoding)
    except BadZipFile as e:
        raise RuntimeError(f"ZIP-Datei '{zipfile_name}' ist beschaedigt: {e}") from e


def get_parcels_from_wfs(wfs_url: str, key: str, bbox, layer_name: str) -> gpd.GeoDataFrame:
    try:
        wfs = WebFeatureService(wfs_url, version=WFS_VERSION)
        response = wfs.getfeature(typename=layer_name, outputFormat=WFS_OUTPUT_FORMAT, bbox=bbox)
        response.seek(0)
        gdf = gpd.read_file(response)
    except Exception as e:
        raise RuntimeError(f"WFS-Anfrage an '{wfs_url}' fuer Schluessel '{key}' fehlgeschlagen: {e}") from e
    # the bbox also returns parcels of neighbouring districts
    return district_parcels(gdf, key).reset_index(drop=True)


def get_landuse_from_wfs(wfs_url: str, bbox, layer_name: str, timeout: int = HTTP_TIMEOUT) -> gpd.GeoDataFrame:
    """ALKIS "Tatsächliche Nutzung" in a bbox (EPSG:25832), raw WFS attributes.

    :func:`fheat_nrw.civil_cost.annotate_landuse_costs` maps the object type
    to a civil works factor.
    """
    try:
        wfs = WebFeatureService(wfs_url, version=WFS_VERSION, timeout=timeout)
        response = wfs.getfeature(typename=layer_name, outputFormat=WFS_OUTPUT_FORMAT, bbox=bbox)
        response.seek(0)
        return gpd.read_file(response)
    except Exception as e:
        raise RuntimeError(f"WFS-Anfrage (Nutzung) an '{wfs_url}' fehlgeschlagen: {e}") from e


def get_osm_surface_via_overpass(
    bbox_wgs84: tuple[float, float, float, float],
    overpass_url: str = OVERPASS_URL,
    timeout: int = OSM_TIMEOUT,
    retries: int = OSM_RETRIES,
) -> gpd.GeoDataFrame:
    """OSM ``highway`` lines in a bbox via the Overpass API.

    ``bbox_wgs84`` = (south, west, north, east) in EPSG:4326. Returns a
    GeoDataFrame in EPSG:4326 with the columns ``osm_id``, ``highway``,
    ``surface`` (often missing), ``tracktype``, ``width`` and ``lanes``.
    """
    south, west, north, east = bbox_wgs84
    query = (
        f"[out:json][timeout:{int(timeout)}];"
        f'way["highway"]({south},{west},{north},{east});'
        "out tags geom;"
    )
    data = urllib.parse.urlencode({"data": query}).encode("utf-8")
    req = urllib.request.Request(
        overpass_url, data=data, headers={"User-Agent": _user_agent()}
    )
    for attempt in range(1, max(1, retries) + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            if e.code in _OSM_RETRY_STATUS and attempt < retries:
                time.sleep(OSM_RETRY_WAIT * attempt)
                continue
            raise RuntimeError(f"Overpass-Anfrage an '{overpass_url}' fehlgeschlagen: {e}") from e
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
            raise RuntimeError(f"Overpass-Anfrage an '{overpass_url}' fehlgeschlagen: {e}") from e

    rows: list[dict] = []
    geoms: list = []
    for el in payload.get("elements", []):
        if el.get("type") != "way":
            continue
        geom = el.get("geometry")
        if not geom or len(geom) < 2:
            continue
        line = LineString([(pt["lon"], pt["lat"]) for pt in geom])
        if line.is_empty:
            continue
        tags = el.get("tags", {}) or {}
        rows.append({"osm_id": el.get("id"), **{c: tags.get(c) for c in _OSM_COLUMNS[1:]}})
        geoms.append(line)
    if not rows:
        return gpd.GeoDataFrame({c: [] for c in _OSM_COLUMNS}, geometry=[], crs="EPSG:4326")
    return gpd.GeoDataFrame(rows, geometry=geoms, crs="EPSG:4326")
