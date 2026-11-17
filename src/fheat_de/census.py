"""Census 2022 (Zensus 2022) 100 m grid: heating type and energy carrier.

Source: Statistische Ämter des Bundes und der Länder, Zensus 2022, grid
data ("Gitterdaten") at destatis.de; copying and distribution with source
reference allowed. Like the QGIS plugin of F|Heat, two tables are read:
dwellings per 100 m cell by the main heating type and by the energy
carrier of the heating of their building (the one heating most of its
living space), Stichtag 15.05.2022. Dwellings, not buildings: a block of
flats counts many times.

Checked 2026-11-13: two ZIPs of 22 and 24 MB (last changed 08.10.2024), each
with a CSV (``;``, Latin-1) of the same 2.63 million cells, cell midpoint in
EPSG:3035. "–" means none; the values carry the noise of the census secrecy
procedure, so the categories need not add up to the total. A value belongs
to the cell of its address point, so a building may count in a neighbouring
cell; cells without dwellings are missing. The ZIPs are fixed, so a file in the cache is never loaded again.
"""
from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Optional

import geopandas as gpd
import pandas as pd
import shapely
from shapely.geometry.base import BaseGeometry

from fheat_core import cache, cancel
from fheat_core import columns as cols

CENSUS_URL = "https://www.destatis.de/static/DE/zensus/gitterdaten/"
CENSUS_CRS = "EPSG:3035"
CELL_SIZE = 100.0  # [m]
SOURCE_CENSUS = "Zensus 2022, Statistische Ämter des Bundes und der Länder (Stichtag 15.05.2022)"

HEATING_COLUMNS = (
    cols.HEATING_TOTAL, cols.HEATING_DISTRICT, cols.HEATING_FLOOR, cols.HEATING_BLOCK,
    cols.HEATING_CENTRAL, cols.HEATING_STOVES, cols.HEATING_NONE,
)
CARRIER_COLUMNS = (
    cols.CARRIER_TOTAL, cols.CARRIER_GAS, cols.CARRIER_OIL, cols.CARRIER_WOOD, cols.CARRIER_BIOMASS,
    cols.CARRIER_SOLAR_HEAT_PUMP, cols.CARRIER_ELECTRICITY, cols.CARRIER_COAL, cols.CARRIER_DISTRICT_HEAT,
    cols.CARRIER_NONE,
)
#: (ZIP, CSV in it, value columns)
TABLES = (
    ("Zensus2022_Heizungsart.zip", "Zensus2022_Heizungsart_100m-Gitter.csv", HEATING_COLUMNS),
    ("Zensus2022_Energietraeger.zip", "Zensus2022_Energietraeger_100m-Gitter.csv", CARRIER_COLUMNS),
)
COLUMN_ORDER = [cols.CENSUS_CELL_ID, *HEATING_COLUMNS, *CARRIER_COLUMNS, cols.DATA_SOURCE]

_CELL_ID, _X, _Y = "GITTER_ID_100m", "x_mp_100m", "y_mp_100m"
_NONE = "\x96"  # "–" in Latin-1
_CHUNK_ROWS = 100_000  # about 50 MB of strings per chunk


def read_census(area: BaseGeometry, crs, cache_dir: Optional[Path] = None) -> gpd.GeoDataFrame:
    """Census cells (100 m squares) that intersect ``area`` (given in ``crs``), returned in ``crs``."""
    outline = gpd.GeoSeries([area], crs=crs).to_crs(CENSUS_CRS).iloc[0]
    heating, carrier = (_read_table(zip_name, csv_name, columns, outline.bounds, cache_dir)
                        for zip_name, csv_name, columns in TABLES)
    cells = heating.merge(carrier.drop(columns=[_X, _Y]), on=cols.CENSUS_CELL_ID)  # both tables have the same cells
    half = CELL_SIZE / 2
    squares = shapely.box(cells[_X] - half, cells[_Y] - half, cells[_X] + half, cells[_Y] + half)
    gdf = gpd.GeoDataFrame(cells.drop(columns=[_X, _Y]), geometry=squares, crs=CENSUS_CRS)
    gdf = gdf[gdf.intersects(outline)]
    gdf[cols.DATA_SOURCE] = SOURCE_CENSUS
    return gdf[[*COLUMN_ORDER, "geometry"]].to_crs(crs).reset_index(drop=True)


def _read_table(zip_name: str, csv_name: str, columns, bounds, cache_dir: Optional[Path]) -> pd.DataFrame:
    """Rows of one census table whose cell touches ``bounds`` (EPSG:3035), values as int."""
    path = cache.cached_download(CENSUS_URL + zip_name, zip_name, None, cache_dir)
    half = CELL_SIZE / 2
    xmin, ymin, xmax, ymax = bounds
    rename = {cols.LABELS_DE[column]: column for column in columns}
    parts = []
    with zipfile.ZipFile(path) as archive, archive.open(csv_name) as csv:
        # in chunks: all 2.6 million rows as strings would take over 1 GB
        for chunk in pd.read_csv(csv, sep=";", encoding="latin1", dtype=str, chunksize=_CHUNK_ROWS):
            cancel.raise_if_cancelled()
            x, y = chunk[_X].astype(float), chunk[_Y].astype(float)
            parts.append(chunk[x.between(xmin - half, xmax + half) & y.between(ymin - half, ymax + half)])
    table = pd.concat(parts).rename(columns={_CELL_ID: cols.CENSUS_CELL_ID, **rename})
    # a missing column raises KeyError; an unknown special character raises instead of silently counting as 0
    values = table[list(rename.values())].replace(_NONE, "0").astype("int64")
    return pd.concat([table[[cols.CENSUS_CELL_ID]], table[[_X, _Y]].astype(float), values], axis=1)
