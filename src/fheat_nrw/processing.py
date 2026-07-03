"""NRW-specific building/street processing.

Transforms raw NRW data (ALKIS + LANUV) into BuildingsSchema-compliant output.
"""
from __future__ import annotations

from collections import Counter

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString, MultiLineString

from fheat_core import columns as cols

# BAK-Klassifikation (Baualtersklassen nach DIN/BDEW)
BAK_BINS = [0, 1918, 1948, 1957, 1968, 1978, 1983, 1994, 2001, 9999]
BAK_LABELS = ["B", "C", "D", "E", "F", "G", "H", "I", "J"]


# ============================================================
# Streets
# ============================================================

def process_streets(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Round coordinates to 3 decimals, force LineString, add Moegliche_Route=1."""
    gdf = gdf.copy()

    def to_linestring(geom):
        if isinstance(geom, MultiLineString):
            return LineString(list(geom.geoms)[0].coords)
        return geom

    def round_coords(line):
        return LineString([(round(x, 3), round(y, 3)) for x, y in line.coords])

    gdf["geometry"] = gdf["geometry"].apply(to_linestring).apply(round_coords)
    gdf[cols.ROUTABLE] = 1
    return gdf


# ============================================================
# Buildings
# ============================================================

def process_buildings(
    raw: gpd.GeoDataFrame,
    parcels: gpd.GeoDataFrame,
    building_info_db: pd.DataFrame,
    wg_demand_data: pd.DataFrame,
    heat_attribute: str,
) -> gpd.GeoDataFrame:
    """Full NRW building processing pipeline → BuildingsSchema-compliant.

    Steps: filter heat>0 → LANUV type/age → merge → spatial-join with parcels →
    BAK → Vlh + Lastprofil → custom heat demand → power → Anschluss → rename.
    """
    bld = raw.copy()

    # Resolve heat attribute (with [kWh/a] suffix fallback)
    heat_col = _resolve_heat_col(bld, heat_attribute)

    # Filter heat > 0
    bld = bld[bld[heat_col] > 0].reset_index(drop=True)
    if bld.empty:
        raise ValueError("Keine Gebaeude mit Waermebedarf > 0 nach Filterung uebrig.")

    has_alkis = "citygml_fu" in bld.columns

    if has_alkis:
        bld = _add_lanuv_age_and_type(bld)
        bld = _merge_buildings(bld, heat_col)
        bld["new_ID"] = bld.index.astype("int32")
        if "nationalCadastralReference" in parcels.columns and "Flurstueck" in bld.columns:
            bld = _spatial_join_parcels(bld, parcels, ["validFrom"])
        bld = _add_bak(bld)
        bld = _add_vlh_loadprofile(bld, building_info_db)
        if "Lastprofil" in bld.columns:
            bld = bld[bld["Lastprofil"].notna()].copy()
        # heat_col may be renamed by merge; re-resolve
        heat_col = _resolve_heat_col(bld, heat_attribute)
        bld = _add_custom_heat_demand(bld, wg_demand_data, building_info_db, heat_col)
        bld = _add_power(bld, heat_col)
    else:
        bld["new_ID"] = bld.index.astype("int32")
        bld["Lastprofil"] = pd.NA
        bld["Vlh"] = 1600
        bld["power_th"] = bld[heat_col] / bld["Vlh"]

    bld["Anschluss"] = 1
    bld = _rename_to_schema(bld, heat_col)
    return bld


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _resolve_heat_col(gdf: gpd.GeoDataFrame, heat_att: str) -> str:
    if heat_att in gdf.columns:
        return heat_att
    suffixed = f"{heat_att} [kWh/a]"
    if suffixed in gdf.columns:
        return suffixed
    raise KeyError(
        f"heat_attribute '{heat_att}' nicht in Gebaeudedaten gefunden "
        f"(weder '{heat_att}' noch '{suffixed}')."
    )


def _extract_year(date_str):
    if pd.isna(date_str):
        return np.nan
    if hasattr(date_str, "year"):
        return int(date_str.year)
    try:
        return int(str(date_str)[:4])
    except Exception:
        return np.nan


def _add_lanuv_age_and_type(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if "GEBAEUDETY" not in gdf.columns:
        gdf["type"] = pd.NA
        gdf["age_LANUV"] = pd.NA
        return gdf
    split = gdf["GEBAEUDETY"].astype(str).str.split("_", expand=True)
    if split.shape[1] < 2:
        gdf["type"] = split[0]
        gdf["age_LANUV"] = pd.NA
    else:
        gdf[["type", "age_LANUV"]] = split.iloc[:, :2]
    if "WG_NWG" in gdf.columns:
        gdf.loc[gdf["WG_NWG"] == "NWG", "type"] = "NWG"
    return gdf


def _merge_buildings(gdf: gpd.GeoDataFrame, heat_col: str) -> gpd.GeoDataFrame:
    """Dissolve by Flurstueck/citygml_fu/Fortschrei/type with weighted-mean aggregations."""
    by_all = ["Flurstueck", "citygml_fu", "Fortschrei", "type"]
    by_cols = [c for c in by_all if c in gdf.columns]
    if len(by_cols) != len(by_all):
        return gdf

    def weighted_mean(s, weights):
        return (s * weights).sum() / weights.sum() if weights.sum() else np.nan

    def mode_or_string(x):
        counts = Counter(x)
        max_count = max(counts.values())
        max_list = [v for v, c in counts.items() if c == max_count]
        if len(max_list) == 1:
            return str(max_list[0])
        return ", ".join(map(str, sorted(max_list)))

    aggfunc_all = {
        "Fest_ID": "first",
        "Nutzung": "first",
        "NF": "sum",
        "RW_spez": lambda x: weighted_mean(x, gdf.loc[x.index, "NF"]),
        "RW": "sum",
        "WW_spez": lambda x: weighted_mean(x, gdf.loc[x.index, "NF"]),
        "WW": "sum",
        "RW_WW_spez": lambda x: weighted_mean(x, gdf.loc[x.index, "NF"]),
        "RW_WW": "sum",
        "age_LANUV": mode_or_string,
        "Vlh": "first",
    }
    if heat_col in gdf.columns:
        aggfunc_all[heat_col] = "sum"

    aggfunc = {k: v for k, v in aggfunc_all.items() if k in gdf.columns}
    return gdf.dissolve(by=by_cols, as_index=False, aggfunc=aggfunc)


def _spatial_join_parcels(
    bld: gpd.GeoDataFrame, parcels: gpd.GeoDataFrame, attributes: list[str]
) -> gpd.GeoDataFrame:
    """Add validFrom (and similar) attributes from the best-fitting parcel."""
    bld = bld.copy().reset_index(drop=True)

    attrs_in_parcels = [a for a in attributes if a in parcels.columns]
    parcels_work = parcels[["geometry"] + attrs_in_parcels].copy().reset_index(drop=True)
    for col in ("index_left", "index_right"):
        bld = bld.drop(columns=[col], errors="ignore")
        parcels_work = parcels_work.drop(columns=[col], errors="ignore")

    joined = gpd.sjoin(bld, parcels_work, how="inner", predicate="intersects")

    # List comprehension avoids the apply()/DataFrame expansion bug when index labels
    # are non-sequential — iloc[] needs positional ints, which reset_index guarantees.
    parcel_geoms = parcels_work.geometry.iloc[joined["index_right"].values].values
    joined["_int_area"] = [
        bg.intersection(pg).area
        for bg, pg in zip(joined.geometry.values, parcel_geoms)
    ]

    best = joined.sort_values("_int_area", ascending=False).groupby(joined.index).first()
    for attr in attributes:
        if attr in best.columns:
            bld[attr] = best[attr]
        elif f"{attr}_left" in best.columns:
            bld[attr] = best[f"{attr}_left"]
    return bld


def _add_bak(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if "validFrom" not in gdf.columns:
        gdf["BAK"] = pd.NA
        return gdf
    gdf["_jahr"] = gdf["validFrom"].apply(_extract_year)
    gdf["BAK"] = pd.cut(gdf["_jahr"], bins=BAK_BINS, labels=BAK_LABELS, right=True).astype(str)
    return gdf.drop(columns=["_jahr"])


def _add_vlh_loadprofile(gdf: gpd.GeoDataFrame, info_db: pd.DataFrame) -> gpd.GeoDataFrame:
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


def _add_custom_heat_demand(
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


def _add_power(gdf: gpd.GeoDataFrame, heat_col: str) -> gpd.GeoDataFrame:
    if "Vlh" not in gdf.columns:
        gdf["Vlh"] = 1600
    vlh = gdf["Vlh"].where(gdf["Vlh"] != 0, 1600)
    gdf["power_th"] = gdf[heat_col] / vlh
    return gdf


def _rename_to_schema(gdf: gpd.GeoDataFrame, heat_col: str) -> gpd.GeoDataFrame:
    """Build a final GeoDataFrame matching BuildingsSchema (canonical column names).

    Maps the NRW-internal intermediate columns onto the canonical schema
    identifiers defined in :mod:`fheat_core.columns`.
    """
    out = {}
    out[cols.BUILDING_ID] = gdf["new_ID"].astype("int32") if "new_ID" in gdf.columns else gdf.index.astype("int32")
    out[cols.CONNECT] = gdf["Anschluss"].astype("int32") if "Anschluss" in gdf.columns else 1
    out[cols.HEAT_DEMAND] = gdf[heat_col].astype("float64")
    if "power_th" in gdf.columns:
        out[cols.THERMAL_POWER] = gdf["power_th"].astype("float64")
    elif cols.THERMAL_POWER in gdf.columns:
        out[cols.THERMAL_POWER] = gdf[cols.THERMAL_POWER].astype("float64")
    else:
        out[cols.THERMAL_POWER] = 0.0
    out[cols.FULL_LOAD_HOURS] = gdf["Vlh"].astype("float64") if "Vlh" in gdf.columns else 1600.0
    out[cols.LOAD_PROFILE] = gdf["Lastprofil"].astype("string") if "Lastprofil" in gdf.columns else pd.NA

    # Optional columns
    if "citygml_fu" in gdf.columns:
        out[cols.FUNCTION] = gdf["citygml_fu"]
    if "type" in gdf.columns:
        out[cols.BUILDING_TYPE] = gdf["type"]
    if "Nutzung" in gdf.columns:
        out[cols.USAGE] = gdf["Nutzung"]
    if "NF" in gdf.columns:
        out[cols.FLOOR_AREA] = gdf["NF"]
    if "age_LANUV" in gdf.columns:
        out[cols.AGE] = gdf["age_LANUV"]
    if "BAK" in gdf.columns:
        out[cols.CONSTRUCTION_CLASS] = gdf["BAK"]

    out["geometry"] = gdf["geometry"]
    df = pd.DataFrame(out)
    return gpd.GeoDataFrame(df, geometry="geometry", crs=gdf.crs)
