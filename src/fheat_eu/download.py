"""Downloads of the Europe-wide heat source data (Fordatis, Hotmaps).

Fraunhofer ISI dataset to Manz et al. (2024), "Spatial analysis of renewable
and excess heat potentials for climate-neutral district heating in Europe",
Renewable Energy 224, 120111: Fordatis handle 341.5, DOI
10.24406/fordatis/280.5, licence CC BY 4.0. Checked 2026-10-26
(docs/potenzialdaten.md): GeoPackages in EPSG:3035, values for a
climate-neutral 2050. The handle names a fixed version, so a file in the
cache is never loaded again.

Hotmaps Industrial Database (Fraunhofer ISI et al., CC BY 4.0): names and
sectors of the industrial sites; ``SiteID`` is ``ID_Site`` of Fordatis.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import geopandas as gpd
import pandas as pd

from fheat_core import cache

FORDATIS_URL = "https://fordatis.fraunhofer.de/bitstream/fordatis/341.5/"
FORDATIS_CRS = "EPSG:3035"
#: file → number of its bitstream in version 341.5; not used: biomass_nuts2
#: (1, a value of the whole NUTS 2 region) and petrothermal_65/85 (4, 7, a
#: flat estimate), see docs/potenzialdaten.md
FORDATIS_FILES = {
    "dh_areas.gpkg": 2,
    "industrial_eh.gpkg": 3,
    "rivers_lakes.gpkg": 5,
    "wte.gpkg": 6,
    "wwtp.gpkg": 8,
    "hydrothermal_65.gpkg": 9,
    "hydrothermal_85.gpkg": 10,
    "Results_DH_Matching_Cluster.xlsx": 11,
}
FILE_DH_AREAS = "dh_areas.gpkg"                    # 13 MB
FILE_INDUSTRIAL = "industrial_eh.gpkg"             # 0.3 MB
FILE_RIVERS = "rivers_lakes.gpkg"                  # 0.7 MB
FILE_WASTE_INCINERATION = "wte.gpkg"               # 0.2 MB
FILE_WASTEWATER = "wwtp.gpkg"                      # 3 MB
#: (high-, low-temperature scenario): 85 / 65 °C minimum underground temperature
FILES_HYDROTHERMAL = ("hydrothermal_85.gpkg", "hydrothermal_65.gpkg")   # 71 + 103 MB
FILE_STUDY_RESULTS = "Results_DH_Matching_Cluster.xlsx"  # 2 MB

URL_HOTMAPS_INDUSTRY = (
    "https://gitlab.com/hotmaps/industrial_sites/industrial_sites_Industrial_Database"
    "/-/raw/master/data/Industrial_Database.csv"
)
FILE_HOTMAPS_INDUSTRY = "hotmaps_Industrial_Database.csv"  # 1 MB
HOTMAPS_COLUMNS = ("SiteID", "CompanyName", "SiteName", "City", "Subsector")


def fordatis_file(name: str, cache_dir: Optional[Path] = None, folder: Optional[Path] = None) -> Path:
    """Local path of a Fordatis file: from ``folder`` (own copy) or the cache."""
    if folder is not None:
        path = Path(folder) / name
        if not path.exists():
            raise RuntimeError(f"Fordatis-Datei '{name}' fehlt im Ordner '{folder}'.")
        return path
    if name not in FORDATIS_FILES:
        raise ValueError(f"Unbekannte Fordatis-Datei '{name}'. Bekannt: {sorted(FORDATIS_FILES)}")
    url = f"{FORDATIS_URL}{FORDATIS_FILES[name]}/{name}"
    return cache.cached_download(url, f"fordatis-341.5_{name}", None, cache_dir)


def read_fordatis(
    name: str,
    bbox: tuple[float, float, float, float],
    cache_dir: Optional[Path] = None,
    folder: Optional[Path] = None,
) -> gpd.GeoDataFrame:
    """Features of a Fordatis GeoPackage that intersect ``bbox`` (EPSG:3035)."""
    path = fordatis_file(name, cache_dir, folder)
    try:
        return gpd.read_file(str(path), bbox=tuple(float(v) for v in bbox))
    except Exception as e:
        raise RuntimeError(f"Fordatis-Datei '{name}' nicht lesbar: {e}") from e


def read_study_results(
    cache_dir: Optional[Path] = None, folder: Optional[Path] = None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Sheets ``DH_LAU_Mapping`` and ``Matching_results`` of the study workbook.

    The matching sheet has two header rows (scenario/kind, heat source); it
    comes back without headers, :func:`fheat_eu.heat_sources.study_table`
    reads it. Needs openpyxl (``fheat[excel]``).
    """
    path = fordatis_file(FILE_STUDY_RESULTS, cache_dir, folder)
    try:
        sheets = pd.read_excel(path, sheet_name=["DH_LAU_Mapping", "Matching_results"], header=None)
    except ImportError as e:
        raise RuntimeError('Die Studienwerte brauchen openpyxl: pip install "fheat[excel]"') from e
    mapping = sheets["DH_LAU_Mapping"]
    mapping = mapping.iloc[1:].set_axis([str(c) for c in mapping.iloc[0]], axis=1).reset_index(drop=True)
    return mapping, sheets["Matching_results"]


def hotmaps_industry_names(cache_dir: Optional[Path] = None) -> pd.DataFrame:
    """Names and sectors of the Hotmaps industrial sites (``HOTMAPS_COLUMNS``)."""
    path = cache.cached_download(URL_HOTMAPS_INDUSTRY, FILE_HOTMAPS_INDUSTRY, None, cache_dir)
    try:
        table = pd.read_csv(path, sep=";", usecols=list(HOTMAPS_COLUMNS), dtype={"SiteID": "Int64"})
    except (ValueError, OSError) as e:
        raise RuntimeError(f"Hotmaps-Industriedatenbank nicht lesbar: {e}") from e
    return table.dropna(subset=["SiteID"]).drop_duplicates("SiteID")
