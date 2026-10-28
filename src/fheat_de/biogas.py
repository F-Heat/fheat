"""Biogas CHP units of the Marktstammdatenregister as heat sources.

Method of the master thesis of J. Föcker (FH Münster, 2026), scripts
``mastr_biogas_extrakt.py`` and ``Anlagenclusterung in QGIS_edit.py``:

- units with main fuel biogas, in operation or planned, from 250 kW net
  electric power, with a Höchstbemessungsleistung (HBL) of their EEG plant;
  the HBL only exists for plants commissioned before August 2014, the rest
  is left out
- electricity of the EEG plant = HBL × 8760 h, split among its units by net
  power (among all its biogas units, so a small or distant unit keeps its
  share instead of handing it to the others)
- heat = electricity × P_th/P_el of the unit's CHP plant in the MaStR; the
  flat efficiencies 0.45/0.41 of the thesis where the CHP data is missing or
  implausible
- clusters: units linked by chains of at most 3 km (single linkage); area =
  convex hull + 500 m, a single unit a circle of half the chain distance

All values are today's stock and the heat is what the CHP produces: an
upper bound, part of it heats the digester or is already sold.
"""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import MultiPoint
from shapely.geometry.base import BaseGeometry

from fheat_core import columns as cols
from fheat_core.algorithms.geometry import cluster_points
from fheat_de.mastr import MastrTables
from fheat_eu.heat_sources import distance_and_candidate

#: catalogue value of ``Hauptbrennstoff`` "Biogas" (Biomethan, Klärgas and Deponiegas are others)
FUEL_BIOGAS = "2445"
#: catalogue values of ``EinheitBetriebsstatus`` taken
OPERATING_STATUS = {"35": "in Betrieb", "31": "in Planung"}
MIN_ELECTRIC_POWER_KW = 250.0
HOURS_PER_YEAR = 8760.0
#: flat CHP efficiencies of the thesis
ETA_EL = 0.41
ETA_TH = 0.45
#: P_th/P_el of the CHP data taken as plausible; outside (4 % of the units,
#: mostly W or kWh entered as kW) the flat ratio is used
KWK_RATIO_RANGE = (0.5, 2.0)
CLUSTER_DISTANCE = 3000.0  # [m]
CLUSTER_BUFFER = 500.0  # [m]

SOURCE_MASTR = "Bundesnetzagentur, Marktstammdatenregister"

PLANT_ORDER = [
    cols.MASTR_UNIT_ID, cols.SOURCE_NAME, cols.MUNICIPALITY, cols.OPERATING_STATUS,
    cols.COMMISSIONING_DATE, cols.EEG_COMMISSIONING_DATE, cols.FLEX_PREMIUM,
    cols.ELECTRIC_POWER_KW, cols.THERMAL_POWER_KW, cols.MAX_RATED_POWER_KW,
    cols.ELECTRICITY_MWH, cols.CHP_HEAT_MWH, cols.THERMAL_BASIS, cols.MASTR_EEG_ID,
    cols.DATA_SOURCE, cols.DISTANCE_TO_AREA, cols.SOURCE_CANDIDATE_LAT, cols.SOURCE_CANDIDATE_LON,
]
CLUSTER_ORDER = [
    cols.CLUSTER_ID, cols.N_UNITS, cols.ELECTRIC_POWER_KW, cols.THERMAL_POWER_KW,
    cols.ELECTRICITY_MWH, cols.CHP_HEAT_MWH, cols.MAX_INTERNAL_DISTANCE,
    cols.MUNICIPALITY, cols.MASTR_UNIT_IDS, cols.DATA_SOURCE,
]


def _numbers(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").astype("float64")


def data_source(tables: MastrTables) -> str:
    return f"{SOURCE_MASTR} (Stand {tables.date})" if tables.date else SOURCE_MASTR


def _kwk_ratio(units: pd.DataFrame, kwk: pd.DataFrame) -> pd.Series:
    """P_th/P_el of each unit's CHP plant; NaN without plausible CHP data."""
    kwk = kwk.drop_duplicates("KwkMastrNummer").set_index("KwkMastrNummer")
    ratio = _numbers(kwk["ThermischeNutzleistung"]) / _numbers(kwk["ElektrischeKwkLeistung"])
    ratio = ratio.where(ratio.between(*KWK_RATIO_RANGE))
    return units["KwkMaStRNummer"].map(ratio).astype("float64")


def process_biogas(
    tables: MastrTables,
    area: BaseGeometry,
    crs,
    max_distance: float = 0.0,
    min_power_kw: float = MIN_ELECTRIC_POWER_KW,
) -> gpd.GeoDataFrame:
    """Biogas CHP units within ``max_distance`` of ``area`` → canonical columns.

    ``area`` lies in ``crs`` (a metric CRS); 0 keeps the units inside it.
    One row per unit, see the module docstring for the method.
    """
    units = tables.units
    units = units[(units["Hauptbrennstoff"] == FUEL_BIOGAS)
                  & units["EinheitBetriebsstatus"].isin(OPERATING_STATUS)].reset_index(drop=True)
    power = _numbers(units["Nettonennleistung"]).fillna(_numbers(units["Bruttoleistung"]))

    # share of each unit in the HBL of its EEG plant
    plant = units["EegMaStRNummer"].where(units["EegMaStRNummer"] != "", "unit " + units["EinheitMastrNummer"])
    total = power.fillna(0.0).groupby(plant).transform("sum")
    count = power.groupby(plant).transform("size")
    share = (power / total).where(total > 0, 1.0 / count)
    eeg = tables.eeg.drop_duplicates("EegMaStRNummer").set_index("EegMaStRNummer")
    hbl = units["EegMaStRNummer"].map(_numbers(eeg["BiogasHoechstbemessungsleistung"]))
    ratio = _kwk_ratio(units, tables.kwk)

    lon, lat = _numbers(units["Laengengrad"]), _numbers(units["Breitengrad"])
    keep = (power >= min_power_kw) & hbl.notna() & lon.notna() & lat.notna()
    units, power, share, hbl, ratio = units[keep], power[keep], share[keep], hbl[keep], ratio[keep]
    geometry = gpd.points_from_xy(lon[keep], lat[keep], crs="EPSG:4326").to_crs(crs)

    out = gpd.GeoDataFrame(geometry=geometry, crs=crs)
    out[cols.MASTR_UNIT_ID] = units["EinheitMastrNummer"].astype("string").values
    out[cols.SOURCE_NAME] = units["NameStromerzeugungseinheit"].replace("", pd.NA).astype("string").values
    out[cols.MUNICIPALITY] = units["Gemeinde"].replace("", pd.NA).astype("string").values
    out[cols.OPERATING_STATUS] = units["EinheitBetriebsstatus"].map(OPERATING_STATUS).astype("string").values
    out[cols.COMMISSIONING_DATE] = units["Inbetriebnahmedatum"].replace("", pd.NA).astype("string").values
    eeg_rows = units["EegMaStRNummer"]
    out[cols.EEG_COMMISSIONING_DATE] = eeg_rows.map(eeg["EegInbetriebnahmedatum"]).replace("", pd.NA).astype("string").values
    flex = eeg_rows.map(eeg["BiogasInanspruchnahmeFlexiPraemie"]).map({"1": True, "0": False})
    out[cols.FLEX_PREMIUM] = flex.astype("boolean").values
    out[cols.ELECTRIC_POWER_KW] = power.values
    out[cols.THERMAL_POWER_KW] = (power * ratio.fillna(ETA_TH / ETA_EL)).values
    out[cols.MAX_RATED_POWER_KW] = hbl.values
    electricity = hbl * HOURS_PER_YEAR * share / 1e3
    out[cols.ELECTRICITY_MWH] = electricity.values
    out[cols.CHP_HEAT_MWH] = (electricity * ratio.fillna(ETA_TH / ETA_EL)).values
    out[cols.THERMAL_BASIS] = pd.array(np.where(ratio.notna(), "kwk", "factor"), dtype="string")
    out[cols.MASTR_EEG_ID] = eeg_rows.astype("string").values
    out[cols.DATA_SOURCE] = data_source(tables)

    out = out[out.geometry.distance(area) <= max_distance].copy()
    distance_and_candidate(out, area)
    return out[PLANT_ORDER + ["geometry"]].sort_values(
        [cols.DISTANCE_TO_AREA, cols.MASTR_UNIT_ID], kind="stable").reset_index(drop=True)


def _largest_distance(points: gpd.GeoSeries) -> float:
    xy = np.column_stack([points.x, points.y])
    return float(np.sqrt(((xy[:, None, :] - xy[None, :, :]) ** 2).sum(axis=-1)).max())


def _joined(values: pd.Series) -> str:
    return "; ".join(sorted(set(values.dropna().astype(str))))


def biogas_clusters(
    plants: gpd.GeoDataFrame,
    max_distance: float = CLUSTER_DISTANCE,
    buffer: float = CLUSTER_BUFFER,
) -> gpd.GeoDataFrame:
    """Clusters of the units of :func:`process_biogas`, the one with the most heat first.

    Sums of power and energy per cluster; the area is the convex hull of its
    units plus ``buffer``, for a single unit a circle of ``max_distance`` / 2.
    """
    if plants.empty:
        return gpd.GeoDataFrame(columns=CLUSTER_ORDER + ["geometry"], geometry="geometry", crs=plants.crs)
    rows, areas = [], []
    for _, members in plants.groupby(cluster_points(plants.geometry, max_distance), sort=False):
        points = members.geometry
        if len(members) == 1:
            areas.append(points.iloc[0].buffer(max_distance / 2))
        else:
            areas.append(MultiPoint(list(points)).convex_hull.buffer(buffer))
        rows.append({
            cols.N_UNITS: len(members),
            cols.ELECTRIC_POWER_KW: members[cols.ELECTRIC_POWER_KW].sum(),
            cols.THERMAL_POWER_KW: members[cols.THERMAL_POWER_KW].sum(),
            cols.ELECTRICITY_MWH: members[cols.ELECTRICITY_MWH].sum(),
            cols.CHP_HEAT_MWH: members[cols.CHP_HEAT_MWH].sum(),
            cols.MAX_INTERNAL_DISTANCE: _largest_distance(points),
            cols.MUNICIPALITY: _joined(members[cols.MUNICIPALITY]),
            cols.MASTR_UNIT_IDS: _joined(members[cols.MASTR_UNIT_ID]),
            cols.DATA_SOURCE: members[cols.DATA_SOURCE].iloc[0],
        })
    out = gpd.GeoDataFrame(rows, geometry=areas, crs=plants.crs)
    out = out.sort_values(cols.CHP_HEAT_MWH, ascending=False, kind="stable").reset_index(drop=True)
    out[cols.CLUSTER_ID] = np.arange(1, len(out) + 1)
    out[cols.N_UNITS] = out[cols.N_UNITS].astype("int64")
    for column in (cols.MUNICIPALITY, cols.MASTR_UNIT_IDS):
        out[column] = out[column].astype("string")
    return out[CLUSTER_ORDER + ["geometry"]]
