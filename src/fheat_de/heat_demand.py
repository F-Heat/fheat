"""Heat demand of buildings from their ALKIS function and age class.

What a state adapter needs when its data source has no heat demand of its
own, or to recalculate one: the ALKIS building function (AdV, the same in
every state) gives full load hours, load profile and, for non-residential
buildings, a specific heat demand; the age class gives the specific heat
demand of single- and multi-family houses. Heat demand = net floor area ×
specific heat demand.

The functions work on the raw building columns of the adapters:

- ``citygml_fu``: ALKIS function code, the last four digits count
  ("31001_1010" → "1010");
- ``validFrom``: date whose year gives the age class (NRW: the INSPIRE
  ``validFrom`` of the parcel);
- ``BAK``: age class ("B" … "J");
- ``NF``: net floor area [m²];
- ``type``: building type (EFH, MFH, GMFH, RH, NWG …);
- ``Lastprofil``, ``Vlh``: BDEW load profile and full load hours;
- ``Waermebedarf``: the calculated heat demand [kWh/a], ``power_th`` the
  thermal power [kW].

The tables ship as ``fheat_de/data/building_functions.json`` (keyed by
function code) and ``building_age_classes.json`` (keyed by age class).
"""
from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import Optional

import geopandas as gpd
import numpy as np
import pandas as pd

# BAK-Klassifikation (Baualtersklassen nach DIN/BDEW)
BAK_BINS = [0, 1918, 1948, 1957, 1968, 1978, 1983, 1994, 2001, 9999]
BAK_LABELS = ["B", "C", "D", "E", "F", "G", "H", "I", "J"]

#: Full load hours of a building without any.
DEFAULT_FULL_LOAD_HOURS = 1600

#: Net floor area per m² footprint and storey, as WBM-NRW computes it (exact
#: for all residential buildings of Vreden, see fheat_nrw.building_gaps).
NET_FLOOR_FACTOR = 0.7
#: Height [m] of one storey, to count the storeys below the eaves.
STOREY_HEIGHT_M = 3.0
#: Largest net floor area [m²] of a single-family house: the largest EFH of
#: WBM-NRW in Vreden has 280 m². A residential building above it is an MFH.
EFH_MAX_FLOOR_AREA = 280.0


def storeys_from_height(height: pd.Series, storey_height: float = STOREY_HEIGHT_M) -> pd.Series:
    """Full storeys below a height (eaves height above ground): rounded, at least 1; NaN without height."""
    storeys = np.round(pd.to_numeric(height, errors="coerce") / storey_height).clip(lower=1)
    return storeys.astype("float64")


def net_floor_area(footprint_area, storeys):
    """Net floor area [m²] of a building: :data:`NET_FLOOR_FACTOR` × footprint × storeys."""
    return NET_FLOOR_FACTOR * footprint_area * storeys


def residential_type(floor_area: pd.Series, efh_max: float = EFH_MAX_FLOOR_AREA) -> pd.Series:
    """EFH up to ``efh_max`` m² net floor area, MFH above it."""
    return pd.Series(np.where(floor_area > efh_max, "MFH", "EFH"), index=floor_area.index)


def load_building_functions(path: Optional[Path] = None) -> pd.DataFrame:
    """Table of the ALKIS building functions, one row per code (column ``Funktion``).

    ``Lastprofil``, ``Vlh`` and ``WVBRpEBF`` (specific heat demand of a
    non-residential building [kWh/(m²·a)]) among others. ``path``: an own
    JSON of the same form instead of the shipped one.
    """
    return _keyed_json_to_df(_read_json(path, "building_functions.json"), "Funktion")


def load_age_classes(path: Optional[Path] = None) -> pd.DataFrame:
    """Table of the age classes, one row per class (column ``Baualtersklasse``).

    ``waerme_efh_kwh_m2a`` and ``waerme_mfh_kwh_m2a``: specific heat demand
    of single- and multi-family houses. ``path``: an own JSON of the same form.
    """
    return _keyed_json_to_df(_read_json(path, "building_age_classes.json"), "Baualtersklasse")


def extract_year(date_str):
    """Year of a date (``datetime``, or text starting with the year); NaN without one."""
    if pd.isna(date_str):
        return np.nan
    if hasattr(date_str, "year"):
        return int(date_str.year)
    try:
        return int(str(date_str)[:4])
    except Exception:
        return np.nan


def add_construction_class(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """``BAK`` from the year of ``validFrom`` (NA without the column)."""
    if "validFrom" not in gdf.columns:
        gdf["BAK"] = pd.NA
        return gdf
    gdf["_jahr"] = gdf["validFrom"].apply(extract_year)
    gdf["BAK"] = pd.cut(gdf["_jahr"], bins=BAK_BINS, labels=BAK_LABELS, right=True).astype(str)
    return gdf.drop(columns=["_jahr"])


def add_full_load_hours_and_profile(gdf: gpd.GeoDataFrame, info_db: pd.DataFrame) -> gpd.GeoDataFrame:
    """Merge in Vlh + Lastprofil from building_functions.json (lookup by Funktion)."""
    if "citygml_fu" not in gdf.columns:
        return gdf
    info_db = info_db.copy()
    info_db["Funktion"] = info_db["Funktion"].astype(str)
    gdf = gdf.copy()
    gdf["GFK_last_four"] = gdf["citygml_fu"].astype(str).str[-4:]
    gdf = gdf.merge(
        info_db[["Funktion", "Lastprofil", "Vlh"]],
        left_on="GFK_last_four",
        right_on="Funktion",
        how="left",
    )
    gdf = gdf.drop(columns=["GFK_last_four", "Funktion"], errors="ignore")
    if "type" in gdf.columns:
        gdf["Lastprofil"] = np.where(
            (gdf["Lastprofil"] == "EFH") & (gdf["type"] != "EFH"),
            "MFH",
            gdf["Lastprofil"],
        )
    return gdf


def add_calculated_heat_demand(
    gdf: gpd.GeoDataFrame,
    wg_data: pd.DataFrame,
    info_db: pd.DataFrame,
    heat_col: str,
) -> gpd.GeoDataFrame:
    """Recompute Waermebedarf based on WG/NWG-specific factors × NF."""
    if "NF" not in gdf.columns or "Lastprofil" not in gdf.columns:
        return gdf
    if "BAK" not in gdf.columns:
        gdf["BAK"] = pd.NA
    if "citygml_fu" not in gdf.columns:
        gdf["citygml_fu"] = pd.NA

    wg_cols = ["Baualtersklasse", "waerme_mfh_kwh_m2a", "waerme_efh_kwh_m2a"]
    if not all(c in wg_data.columns for c in wg_cols):
        return gdf
    nwg_cols = ["Funktion", "WVBRpEBF"]
    if not all(c in info_db.columns for c in nwg_cols):
        return gdf

    merged = gdf.merge(wg_data[wg_cols], left_on="BAK", right_on="Baualtersklasse", how="left")
    merged["GFK_last_four"] = merged["citygml_fu"].astype(str).str[-4:]
    nwg_lookup = info_db[nwg_cols].copy()
    nwg_lookup["Funktion"] = nwg_lookup["Funktion"].astype(str)
    merged = merged.merge(nwg_lookup, left_on="GFK_last_four", right_on="Funktion", how="left")

    merged["Spez_Waermebedarf"] = np.where(
        merged["Lastprofil"] == "MFH",
        merged["waerme_mfh_kwh_m2a"],
        np.where(
            merged["Lastprofil"] == "EFH",
            merged["waerme_efh_kwh_m2a"],
            merged["WVBRpEBF"],
        ),
    )
    merged = merged.drop(
        columns=[
            "Baualtersklasse",
            "waerme_mfh_kwh_m2a",
            "waerme_efh_kwh_m2a",
            "Funktion",
            "WVBRpEBF",
            "GFK_last_four",
        ],
        errors="ignore",
    )
    merged["Waermebedarf"] = merged["NF"] * merged["Spez_Waermebedarf"]
    # Override original heat column with custom value where it's available
    mask = merged["Waermebedarf"].notna() & (merged["Waermebedarf"] > 0)
    merged.loc[mask, heat_col] = merged.loc[mask, "Waermebedarf"]
    return merged


def add_thermal_power(gdf: gpd.GeoDataFrame, heat_col: str) -> gpd.GeoDataFrame:
    """``power_th`` = heat demand / full load hours (the default where there are none)."""
    if "Vlh" not in gdf.columns:
        gdf["Vlh"] = DEFAULT_FULL_LOAD_HOURS
    vlh = gdf["Vlh"].where(gdf["Vlh"] != 0, DEFAULT_FULL_LOAD_HOURS)
    gdf["power_th"] = gdf[heat_col] / vlh
    return gdf


def _read_json(path: Optional[Path], name: str) -> dict:
    if path is not None:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    with files("fheat_de.data").joinpath(name).open("r", encoding="utf-8") as f:
        return json.load(f)


def _keyed_json_to_df(raw: dict, key_name: str) -> pd.DataFrame:
    """Object-keyed JSON (TEASER-Stil) → DataFrame mit Schlüssel als Spalte."""
    return pd.DataFrame.from_dict(raw, orient="index").reset_index(names=key_name)
