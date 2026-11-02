"""Age class of buildings from the Zensus 2022 grid (construction years by decade).

Destatis publishes, for every 100 m and 1 km cell of Germany, the residential
buildings by decade of construction ("Gebäude mit Wohnraum nach Baujahr
(Jahrzehnte)", stand 15.05.2022, EPSG:3035). A building gets the age class
of the most frequent decade of its 100 m cell; where that cell has no count
(no residential building, or "–": zero or set to zero for secrecy), the one
of its 1 km cell. One value per cell, not per building.

Licence: Datenlizenz Deutschland – Namensnennung – Version 2.0, source
"© Statistische Ämter des Bundes und der Länder, Zensus 2022". The ZIP (23 MB,
208 MB of CSV) is loaded once into the cache (:mod:`fheat_core.cache`).
"""
from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Optional

import geopandas as gpd
import numpy as np
import pandas as pd

from fheat_core import cache, cancel

URL = "https://www.destatis.de/static/DE/zensus/gitterdaten/Gebaeude_nach_Baujahr_Jahrzehnte.zip"
FILE = "Zensus2022_Gebaeude_nach_Baujahr_Jahrzehnte.zip"
CSV_100M = "Gebaeude_nach_Baujahr/Zensus2022_Baujahr_JZ_100m-Gitter.csv"
CSV_1KM = "Gebaeude_nach_Baujahr/Zensus2022_Baujahr_JZ_1km-Gitter.csv"
GRID_CRS = "EPSG:3035"
SOURCE = "© Statistische Ämter des Bundes und der Länder, Zensus 2022 (dl-de/by-2-0)"

#: Decade column → age class of ``fheat_de/data/building_age_classes.json``.
#: A decade spanning two classes takes the one it shares most years with
#: (1980–89: G 1979–1987; 1990–99: I 1994–2001).
DECADE_CLASSES = {
    "Vor1919": "B",
    "a1919bis1949": "C",
    "a1950bis1959": "D",
    "a1960bis1969": "E",
    "a1970bis1979": "F",
    "a1980bis1989": "G",
    "a1990bis1999": "I",
    "a2000bis2009": "J",
    "a2010bis2015": "K",
    "a2016undspaeter": "L",
}
_CHUNK_ROWS = 500_000


def construction_classes(points: gpd.GeoSeries, cache_dir: Optional[Path] = None) -> pd.Series:
    """Age class of the Zensus cell each point lies in (NaN without one), aligned with ``points``."""
    out = pd.Series(np.nan, index=points.index, dtype="object")
    if points.empty:
        return out
    zip_path = cache.cached_download(URL, FILE, None, cache_dir)
    grid = points.to_crs(GRID_CRS)
    x, y = grid.x.to_numpy(), grid.y.to_numpy()
    for member, size in ((CSV_100M, 100), (CSV_1KM, 1000)):
        missing = out.isna().to_numpy()
        if not missing.any():
            break
        cells = dominant_classes(read_cells(zip_path, member, grid[missing].total_bounds, size))
        keys = pd.MultiIndex.from_arrays([_centre(x[missing], size), _centre(y[missing], size)])
        out[missing] = cells.reindex(keys).to_numpy()
    return out


def read_cells(zip_path: Path, member: str, bounds, size: int) -> pd.DataFrame:
    """Cells of one grid CSV whose centre lies within ``bounds`` (EPSG:3035) widened by a cell."""
    minx, miny, maxx, maxy = bounds
    frames = []
    with zipfile.ZipFile(zip_path) as z, z.open(member) as f:
        for chunk in pd.read_csv(f, sep=";", encoding="utf-8", chunksize=_CHUNK_ROWS, dtype=str):
            cancel.raise_if_cancelled()
            xs = pd.to_numeric(chunk.iloc[:, 1], errors="coerce")
            ys = pd.to_numeric(chunk.iloc[:, 2], errors="coerce")
            inside = xs.between(minx - size, maxx + size) & ys.between(miny - size, maxy + size)
            if inside.any():
                frames.append(chunk[inside].assign(_x=xs[inside], _y=ys[inside]))
    if not frames:
        return pd.DataFrame(columns=["_x", "_y", *DECADE_CLASSES])
    return pd.concat(frames, ignore_index=True)


def dominant_classes(cells: pd.DataFrame) -> pd.Series:
    """Age class of the most frequent decade per cell, indexed by the cell centre (x, y).

    "–" (zero or set to zero) counts as 0; a cell without any count is left out.
    """
    counts = cells.reindex(columns=list(DECADE_CLASSES)).apply(pd.to_numeric, errors="coerce").fillna(0)
    has_count = counts.sum(axis=1) > 0
    counts = counts[has_count]
    index = pd.MultiIndex.from_arrays([cells.loc[has_count, "_x"].astype(int), cells.loc[has_count, "_y"].astype(int)])
    return pd.Series(counts.idxmax(axis=1).map(DECADE_CLASSES).to_numpy(), index=index)


def _centre(values: np.ndarray, size: int) -> np.ndarray:
    """Centre coordinate of the cell of edge ``size`` a coordinate lies in."""
    return (np.floor(values / size) * size + size // 2).astype(int)
