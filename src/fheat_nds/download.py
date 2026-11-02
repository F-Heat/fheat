"""Open geodata of Lower Saxony (LGLN), checked 2026-11-02 at Bad Bentheim.

All of it is open under Creative Commons Namensnennung 4.0 (CC BY 4.0),
source "LGLN (year)"; the LoD2 tiles under Datenlizenz Deutschland –
Namensnennung 2.0. Default CRS EPSG:25832.
"""
from __future__ import annotations

import tempfile
import urllib.error
from pathlib import Path
from typing import Optional

import geopandas as gpd
import pandas as pd
from owslib.wfs import WebFeatureService

from fheat_core import cache, cancel
from fheat_de.lod2 import lod2_frame, read_lod2, tile_names

# ALKIS "vereinfacht" of the LGLN, the same layers and columns as in NRW.
# A request returns at most 10 000 features ("CountDefault"), so they are
# paged. A 1 x 1 km box of Bad Bentheim has 2 274 GebaeudeBauwerk rows (2.4 s),
# of which "gebnutzbez" says "Gebäude" or "Bauteil" (parts such as arcades,
# without function); statewide 4 592 Gemarkungen and 973 municipalities.
URL_ALKIS = "https://opendata.lgln.niedersachsen.de/doorman/noauth/alkis_wfs_einfach"
LAYER_PARCELS = "ave:Flurstueck"
LAYER_BUILDINGS = "ave:GebaeudeBauwerk"
LAYER_LANDUSE = "ave:Nutzung"
LAYER_DISTRICTS = "ave:KatasterBezirk"
LAYER_UNITS = "ave:VerwaltungsEinheit"
#: "gebnutzbez" of a whole building
BUILDING = "Gebäude"
#: parcel attribute with the 6-digit Gemarkung key ("034204"), and the municipality's AGS
PARCEL_DISTRICT_COLUMN = "gemaschl"
MUNICIPALITY_COLUMN = "gmdschl"

# ATKIS Basis-DLM of the LGLN: the street axes ("AX_Strassenachse", lines
# with the number of lanes and the carriageway width).
URL_BASIS_DLM = "https://opendata.lgln.niedersachsen.de/doorman/noauth/atkisbdlm_wfs_sf"
LAYER_STREETS = "adv:AX_Strassenachse"

# 3D building model LoD2 (CityGML 1.0), 1 x 1 km tiles named by the lower left
# corner in km, listed by the STAC API https://lod.stac.lgln.niedersachsen.de
# (collection "lod2"). Stand 2024-06-03, about 17 MB a tile. The ids are
# "DENILD…", not the ALKIS ids "DENIAL…": buildings are matched by location.
URL_LOD2 = "https://lod2.s3.eu-de.cloud-object-storage.appdomain.cloud/"
LOD2_TILE = "LoD2_32_{x}_{y}_1_ni.gml"

WFS_VERSION = "2.0.0"
WFS_OUTPUT_FORMAT = "text/xml"
PAGE_SIZE = 10_000
HTTP_TIMEOUT = 120
CRS = "EPSG:25832"


def get_features(
    url: str, layer: str, bbox, page_size: int = PAGE_SIZE, timeout: int = HTTP_TIMEOUT
) -> gpd.GeoDataFrame:
    """All features of ``layer`` in ``bbox`` (EPSG:25832), page by page."""
    frames = []
    try:
        wfs = WebFeatureService(url, version=WFS_VERSION, timeout=timeout)
        start = 0
        while True:
            cancel.raise_if_cancelled()
            response = wfs.getfeature(
                typename=layer, bbox=tuple(float(v) for v in bbox), outputFormat=WFS_OUTPUT_FORMAT,
                maxfeatures=page_size, startindex=start,
            )
            page = gpd.read_file(response)
            frames.append(page)
            if len(page) < page_size:
                break
            start += page_size
    except Exception as e:
        raise RuntimeError(f"WFS-Anfrage ({layer}) an '{url}' fehlgeschlagen: {e}") from e
    gdf = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), geometry="geometry")
    return gdf.set_crs(CRS) if gdf.crs is None else gdf


def get_parcels(bbox, district_key=None) -> gpd.GeoDataFrame:
    """ALKIS parcels in ``bbox``; with ``district_key`` only those of that Gemarkung."""
    parcels = get_features(URL_ALKIS, LAYER_PARCELS, bbox)
    if district_key is None or parcels.empty:
        return parcels
    return district_parcels(parcels, district_key).reset_index(drop=True)


def district_parcels(parcels: gpd.GeoDataFrame, district_key) -> gpd.GeoDataFrame:
    """Parcels of one Gemarkung (key as in the catalogue, the leading 0 may be missing)."""
    if parcels.empty or PARCEL_DISTRICT_COLUMN not in parcels.columns:
        return parcels.iloc[0:0]
    key = str(district_key).zfill(6)
    return parcels[parcels[PARCEL_DISTRICT_COLUMN].astype(str).str.zfill(6) == key]


def get_alkis_buildings(bbox, municipality_key: Optional[str] = None) -> gpd.GeoDataFrame:
    """Whole ALKIS buildings in ``bbox``, without parts; with ``municipality_key`` (AGS) only its own."""
    buildings = get_features(URL_ALKIS, LAYER_BUILDINGS, bbox)
    if buildings.empty:
        return buildings
    keep = buildings["gebnutzbez"].astype(str) == BUILDING
    if municipality_key is not None:
        keep &= buildings[MUNICIPALITY_COLUMN].astype(str).str.zfill(8) == str(municipality_key).zfill(8)
    return buildings[keep].reset_index(drop=True)


def get_landuse(bbox) -> gpd.GeoDataFrame:
    """ALKIS "Tatsächliche Nutzung" in ``bbox``; the object type in ``nutzart``."""
    return get_features(URL_ALKIS, LAYER_LANDUSE, bbox)


def get_streets(bbox) -> gpd.GeoDataFrame:
    """Street axes of the Basis-DLM in ``bbox``."""
    return get_features(URL_BASIS_DLM, LAYER_STREETS, bbox)


def lod2_tiles(geometries: gpd.GeoSeries) -> list[str]:
    """Names of the LoD2 tiles the points of ``geometries`` (EPSG:25832) lie in."""
    return tile_names(geometries, LOD2_TILE)


def load_lod2(
    geometries: gpd.GeoSeries, cache_dir: Optional[Path] = None, keep_tiles: bool = False
) -> gpd.GeoDataFrame:
    """LoD2 buildings of the tiles ``geometries`` lie in.

    Every building of a municipality needs its tile, about 17 MB per km², so
    a tile is read from a temporary folder and deleted again; ``keep_tiles``
    keeps them in the cache (``cache_dir``) for the next run. A tile the LGLN
    does not have (outside Lower Saxony) is skipped.
    """
    frames = []
    for name in lod2_tiles(geometries):
        cancel.raise_if_cancelled()
        with tempfile.TemporaryDirectory() as temp:
            try:
                path = cache.cached_download(URL_LOD2 + name, name, None, cache_dir if keep_tiles else temp)
            except RuntimeError as e:
                if isinstance(e.__cause__, urllib.error.HTTPError) and e.__cause__.code == 404:
                    continue
                raise
            frames.append(read_lod2(path))
    if not frames:
        return lod2_frame([])
    return gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), geometry="geometry", crs=CRS)
