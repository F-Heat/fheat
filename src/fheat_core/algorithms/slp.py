"""BDEW standard load profile (SLP) generation."""
from __future__ import annotations

import datetime

import numpy as np
import pandas as pd

from fheat_core import columns as cols
from fheat_core.errors import PipelineInputError

# first hour of 29 February in a leap year (31 + 28 days)
_LEAP_DAY_HOUR = 59 * 24


def build_load_profile(
    buildings_gdf,
    net_gdf: pd.DataFrame,
    year: int,
    temperature: pd.Series,
    holidays: dict,
    building_class: int,
    wind_class: int,
) -> pd.DataFrame:
    """Generate the hourly load profile DataFrame of ``year`` (8760 or 8784 h).

    ``temperature`` is aligned to the hours of the year, see
    :func:`align_temperature`.

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
    temperature = align_temperature(temperature, demand_ts)

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
    demand[cols.LOSS] = loss_mwh / len(demand_ts)
    demand[cols.LOSS_EXTRA_INSULATION] = loss_extra_mwh / len(demand_ts)

    demand[cols.TOTAL] = demand[cols.BUILDING_DEMAND_SUM] + demand[cols.LOSS]
    demand[cols.TOTAL_EXTRA_INSULATION] = demand[cols.BUILDING_DEMAND_SUM] + demand[cols.LOSS_EXTRA_INSULATION]
    return demand.round(decimals=3)


def align_temperature(temperature: pd.Series, demand_ts: pd.DatetimeIndex) -> pd.Series:
    """Temperatures in the order of the hours ``demand_ts`` of one year.

    A series with a DatetimeIndex (DWD year) is matched by time and must
    cover every hour. Without one (the example year, older adapters) the
    values are taken by position; 8760 values for a leap year get 29 February
    as a copy of 28 February.
    """
    if isinstance(temperature.index, pd.DatetimeIndex):
        aligned = temperature.reindex(demand_ts)
        missing = int(aligned.isna().sum())
        if missing:
            raise PipelineInputError(
                f"The temperature series lacks {missing} of the {len(demand_ts)} hours of {demand_ts[0].year}."
            )
        return aligned
    values = pd.to_numeric(temperature, errors="coerce").to_numpy(dtype=float)
    if len(values) == 8760 and len(demand_ts) == 8784:
        feb_28 = values[_LEAP_DAY_HOUR - 24:_LEAP_DAY_HOUR]
        values = np.concatenate([values[:_LEAP_DAY_HOUR], feb_28, values[_LEAP_DAY_HOUR:]])
    if len(values) != len(demand_ts):
        raise PipelineInputError(
            f"{len(values)} temperatures do not fit the {len(demand_ts)} hours of {demand_ts[0].year}."
        )
    return pd.Series(values, index=demand_ts, name=temperature.name)
