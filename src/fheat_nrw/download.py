"""NRW Open Geodata download helpers (NRW-specific)."""
from __future__ import annotations

import ast
import tempfile
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

import geopandas as gpd
import pandas as pd
from owslib.wfs import WebFeatureService

URL_BUILDINGS = "https://www.opengeodata.nrw.de/produkte/umwelt_klima/energie/kwp/"
URL_PARCELS = "https://www.wfs.nrw.de/geobasis/wfs_nw_inspire-flurstuecke_alkis"
LAYER_PARCELS = "cp:CadastralParcel"
WFS_VERSION = "2.0.0"
WFS_OUTPUT_FORMAT = "text/xml"
HTTP_TIMEOUT = 120


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
    if "nationalCadastralReference" not in gdf.columns:
        return gdf.iloc[0:0]
    # nationalCadastralReference starts with "0" + schluessel (e.g. "55190" → "055190...")
    return gdf[gdf["nationalCadastralReference"].str.startswith("0" + key)].reset_index(drop=True)
