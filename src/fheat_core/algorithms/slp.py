"""BDEW standard load profile (SLP) generation."""
from __future__ import annotations

import datetime

import pandas as pd

from fheat_core import columns as cols


def build_load_profile(
    buildings_gdf,
    net_gdf: pd.DataFrame,
    year: int,
    temperature: pd.Series,
    holidays: dict,
    building_class: int,
    wind_class: int,
) -> pd.DataFrame:
    """Generate 8760-h load profile DataFrame.

    Columns produced (canonical names, see fheat_core.columns):
      - one column per load profile type (EFH, MFH, …)
      - building_demand_sum
      - loss
      - loss_extra_insulation
      - total
      - total_extra_insulation
    """
    try:
        import demandlib.bdew as bdew
    except ImportError as e:
        raise ImportError("demandlib is required for load profile generation") from e

    demand_ts = pd.date_range(
        start=datetime.datetime(year, 1, 1, 0),
        end=datetime.datetime(year, 12, 31, 23),
        freq="h",
    )
    demand = pd.DataFrame(index=demand_ts)

    if cols.LOAD_PROFILE in buildings_gdf.columns and buildings_gdf[cols.LOAD_PROFILE].notna().any():
        summary = (
            buildings_gdf[buildings_gdf[cols.LOAD_PROFILE].notna()]
            .groupby(cols.LOAD_PROFILE)[cols.HEAT_DEMAND]
            .sum()
        )
        for btype, annual_mwh in summary.items():
            bclass = building_class if btype.upper() in ("EFH", "MFH") else 0
            profile = bdew.HeatBuilding(
                demand_ts,
                holidays=holidays,
                temperature=temperature,
                shlp_type=btype,
                building_class=bclass,
                wind_class=wind_class,
                ww_incl=True,
                annual_heat_demand=annual_mwh / 1000,  # kWh → MWh
                name=btype,
            ).get_bdew_profile()
            demand[btype] = profile

    demand[cols.BUILDING_DEMAND_SUM] = demand.sum(axis=1)

    # hourly loss from network
    loss_mwh = net_gdf[cols.HEAT_LOSS].sum() / 1000 if cols.HEAT_LOSS in net_gdf.columns else 0.0
    loss_extra_mwh = (
        net_gdf[cols.HEAT_LOSS_EXTRA_INSULATION].sum() / 1000
        if cols.HEAT_LOSS_EXTRA_INSULATION in net_gdf.columns
        else 0.0
    )
    demand[cols.LOSS] = loss_mwh / 8760
    demand[cols.LOSS_EXTRA_INSULATION] = loss_extra_mwh / 8760

    demand[cols.TOTAL] = demand[cols.BUILDING_DEMAND_SUM] + demand[cols.LOSS]
    demand[cols.TOTAL_EXTRA_INSULATION] = demand[cols.BUILDING_DEMAND_SUM] + demand[cols.LOSS_EXTRA_INSULATION]
    return demand.round(decimals=3)
