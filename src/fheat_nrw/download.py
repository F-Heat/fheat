"""NRW Open Geodata download helpers (NRW-specific)."""
from __future__ import annotations

import ast
import tempfile
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path
from typing import Optional
from zipfile import BadZipFile, ZipFile

import geopandas as gpd
import pandas as pd
from owslib.wfs import WebFeatureService

from fheat_core import cache, cancel
from fheat_de.alkis import ADDRESS_COLUMN, ALKIS_BUILDING_COLUMNS
from fheat_de.area import parse_bbox  # noqa: F401  (named here as before)
# OSM covers every state: the Overpass download lives in fheat_de, named here
# as before for the adapter
from fheat_de.osm_surface import (
    OSM_RETRIES,
    OSM_RETRY_WAIT,
    OSM_TIMEOUT,
    OVERPASS_URL,
    get_osm_surface_via_overpass,
)
from fheat_nrw.area import district_parcels

URL_BUILDINGS = "https://www.opengeodata.nrw.de/produkte/umwelt_klima/energie/kwp/"
# LANUK heat study, NRW-wide geodatabases in the same folder (index.json).
# Checked 2026-10-19 (docs/potenzialdaten.md): EPSG:25832, values in MW and
# GWh/a (doublet raster) or kWh/a (solar thermal). Licence: Datenlizenz
# Deutschland – Zero 2.0. Loaded through the cache (fheat_core.cache).
FILE_DEEP_GEOTHERMAL = "KWP-NRW-Potenzial_TG_Raster_EPSG25832_Geodatabase.zip"   # 2 MB
LAYER_DEEP_GEOTHERMAL = "MTG_TG_Raster_NRW"
FILE_SOLAR_THERMAL = "KWP-NRW-Potenzial_FF_Solarthermie_Flur_EPSG25832_Geodatabase.zip"  # 63 MB
LAYER_SOLAR_THERMAL = "FF_Solarthermie_Flur_NRW"
# LANUK "Kommunale Kläranlagen NRW" (ELKA), one point per discharge, with name,
# design size, connected population equivalents and the annual wastewater
# volume. Checked 2026-10-26: 703 rows / 601 sites, EPSG:25832, data of 2025.
# Licence: Datenlizenz Deutschland – Zero 2.0.
URL_WASTEWATER = "https://www.opengeodata.nrw.de/produkte/umwelt_klima/wasser/abwasser/abwasser_kom/"
FILE_WASTEWATER = "KomKlaeranlagen_EPSG25832_GeoPackage.zip"   # 0.5 MB
LAYER_WASTEWATER = "komm_ka"
URL_PARCELS = "https://www.wfs.nrw.de/geobasis/wfs_nw_inspire-flurstuecke_alkis"
LAYER_PARCELS = "cp:CadastralParcel"
# ALKIS "Tatsächliche Nutzung" (simplified ALKIS). Checked 2026-10-09 via
# GetCapabilities/DescribeFeatureType: the layer exists, default CRS
# EPSG:25832, the object type is in the column "nutzart" (plain text such as
# "Straßenverkehr", "Fließgewässer"). Licence: Datenlizenz Deutschland – Zero 2.0.
URL_LANDUSE = "https://www.wfs.nrw.de/geobasis/wfs_nw_alkis_vereinfacht"
LAYER_LANDUSE = "ave:Nutzung"
# ALKIS buildings of the same service, columns in fheat_de.alkis.
# Checked 2026-10-15: a 12 x 12 km box returned all 35 798 buildings in 8 s.
# Checked 2026-10-28: the columns of fheat_de.alkis.ALKIS_BUILDING_COLUMNS.
LAYER_ALKIS_BUILDINGS = "ave:GebaeudeBauwerk"

# 3D building model LoD2 NRW (CityGML 1.0), 1 x 1 km tiles named by the lower
# left corner in km (EPSG:25832), with index.json. Checked 2026-10-28: the
# tiles of Vreden are of 2026-05-26, footprints as of 2025-07-01
# ("Grundrissaktualitaet"); "measuredHeight" is about 0.8 m (median) above
# the height of WBM-NRW. Licence: Datenlizenz Deutschland – Zero 2.0.
URL_LOD2 = "https://www.opengeodata.nrw.de/produkte/geobasis/3dg/lod2_gml/lod2_gml/"
LOD2_TILE = "LoD2_32_{x}_{y}_1_NW.gml"

# GD NRW "INSPIRE IS GT 50" (shallow geothermal, scale 1:50,000). Checked
# 2026-10-19 (docs/potenzialdaten.md): "capacity" is the thermal conductivity
# for borehole heat exchangers (EWS, unit "W/m*K", "vext_scalar" = probe length
# in m) and the specific extraction for ground collectors (EWK, "W/m²@<h>h/a").
# The default CRS is EPSG:4258, so bbox and srsName name EPSG:25832; only the
# GEOJSON answer can be read. Areas without an assessment have no feature.
# Licence: Datenlizenz Deutschland – Namensnennung 2.0, source "Geologischer
# Dienst NRW".
URL_GEOTHERMAL = "https://www.wfs.nrw.de/gd/wfs_nw_inspire-gt50"
LAYERS_GEOTHERMAL = {
    "ews40": "er:Geothermie_EWS40",
    "ews60": "er:Geothermie_EWS60",
    "ews80": "er:Geothermie_EWS80",
    "ews100": "er:Geothermie_EWS100",
    "ewk1800": "er:Geothermie_EWK1800",
    "ewk2400": "er:Geothermie_EWK2400",
}
GEOTHERMAL_SRS = "urn:ogc:def:crs:EPSG::25832"
GEOTHERMAL_OUTPUT_FORMAT = "GEOJSON"
#: expected "capacity_uom" per layer kind
GEOTHERMAL_UNIT_EWS = "W/m*K"
GEOTHERMAL_UNIT_EWK = "W/m²@{hours}h/a"
WFS_VERSION = "2.0.0"
WFS_OUTPUT_FORMAT = "text/xml"
HTTP_TIMEOUT = 120


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


def find_file(files: list, name: str) -> Optional[dict]:
    """Entry of ``name`` in a file list of :func:`file_list_from_url`.

    The entry carries ``name``, ``size`` (text, bytes) and ``timestamp``
    (ISO time) as listed in ``index.json``. None if the file is not listed.
    """
    for item in files:
        if item.get("name") == name:
            return item
    return None


def cached_file(
    url: str, name: str, cache_dir: Optional[Path] = None, files: Optional[list] = None
) -> Path:
    """Local copy of ``url + name`` from the cache (:mod:`fheat_core.cache`).

    Loads the file again when ``index.json`` of the folder lists a newer
    timestamp (``files``: the index if it is already loaded). If the index
    cannot be read, a file already in the cache is used as it is.
    """
    try:
        if files is None:
            files = file_list_from_url(url + "index.json")
        entry = find_file(files, name)
    except RuntimeError:
        local = cache.cache_dir(cache_dir) / name
        if local.exists():
            return local
        raise
    if entry is None:
        raise RuntimeError(f"Datei '{name}' ist im OpenGeoData-NRW-Index ({url}) nicht gelistet.")
    return cache.cached_download(url + name, name, entry.get("timestamp"), cache_dir)


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

    :func:`fheat_de.alkis.annotate_landuse_costs` maps the object type
    to a civil works factor.
    """
    try:
        wfs = WebFeatureService(wfs_url, version=WFS_VERSION, timeout=timeout)
        response = wfs.getfeature(typename=layer_name, outputFormat=WFS_OUTPUT_FORMAT, bbox=bbox)
        response.seek(0)
        return gpd.read_file(response)
    except Exception as e:
        raise RuntimeError(f"WFS-Anfrage (Nutzung) an '{wfs_url}' fehlgeschlagen: {e}") from e


def get_alkis_buildings_from_wfs(wfs_url: str, bbox, layer_name: str, timeout: int = HTTP_TIMEOUT) -> gpd.GeoDataFrame:
    """ALKIS building outlines in a bbox (EPSG:25832) with :data:`ALKIS_BUILDING_COLUMNS`."""
    try:
        wfs = WebFeatureService(wfs_url, version=WFS_VERSION, timeout=timeout)
        response = wfs.getfeature(typename=layer_name, outputFormat=WFS_OUTPUT_FORMAT, bbox=bbox)
        response.seek(0)
        gdf = gpd.read_file(response)
    except Exception as e:
        raise RuntimeError(f"WFS-Anfrage (ALKIS-Gebäude) an '{wfs_url}' fehlgeschlagen: {e}") from e
    for column in ALKIS_BUILDING_COLUMNS:
        if column not in gdf.columns:
            gdf[column] = None
    return gdf[[*ALKIS_BUILDING_COLUMNS, "geometry"]]


def get_geothermal_from_wfs(
    wfs_url: str, bbox, layer: str, timeout: int = HTTP_TIMEOUT
) -> gpd.GeoDataFrame:
    """One IS GT 50 layer (e.g. ``er:Geothermie_EWS40``) in a bbox, EPSG:25832.

    Raw WFS attributes (``capacity``, ``capacity_uom``, ``vext_scalar``). The
    service returns whole polygons, not cut at the bbox.
    """
    try:
        wfs = WebFeatureService(wfs_url, version=WFS_VERSION, timeout=timeout)
        response = wfs.getfeature(
            typename=layer,
            bbox=(*(float(v) for v in bbox), GEOTHERMAL_SRS),
            srsname=GEOTHERMAL_SRS,
            outputFormat=GEOTHERMAL_OUTPUT_FORMAT,
        )
        gdf = gpd.read_file(response)
    except Exception as e:
        raise RuntimeError(f"WFS-Anfrage (Geothermie {layer}) an '{wfs_url}' fehlgeschlagen: {e}") from e
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:25832")
    return gdf


def check_geothermal_unit(gdf: gpd.GeoDataFrame, key: str) -> None:
    """Raise if ``capacity_uom`` is not the unit expected for layer ``key``.

    EWS layers carry a thermal conductivity, EWK layers a specific extraction
    at the hours in the key. A different unit is never converted silently.
    """
    if gdf.empty:
        return
    if key.startswith("ews"):
        expected = GEOTHERMAL_UNIT_EWS
    else:
        expected = GEOTHERMAL_UNIT_EWK.format(hours=key.removeprefix("ewk"))
    if "capacity_uom" not in gdf.columns:
        raise RuntimeError(f"Geothermie-Layer '{key}' hat keine Spalte 'capacity_uom'.")
    units = set(gdf["capacity_uom"].dropna().astype(str).str.strip())
    if units != {expected}:
        raise RuntimeError(
            f"Geothermie-Layer '{key}' hat die Einheit {sorted(units)}, erwartet '{expected}'."
        )
