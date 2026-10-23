"""Nominal diameters chosen by hand for edges of a calculated net.

A planner may give pipes a larger DN than the sizing chose, e.g. to remove a
bottleneck of the expansion potential. Possible are the DN the sizing of the
network step would choose for the edge and every larger one. The edges keep
their buildings, power and volume flow; velocity, heat losses and pipe costs
follow the new DN with the formulas of the network step.
"""
from __future__ import annotations

import geopandas as gpd
import pandas as pd

from fheat_core import columns as cols
from fheat_core.algorithms.network import calculate_velocity_loss, pipe_index
from fheat_core.network.costs import annotate_network_costs


def possible_diameters(net: pd.DataFrame, pipe_info: pd.DataFrame) -> list:
    """The DN of ``pipe_info`` that carry every edge of ``net``, in catalogue order.

    For each edge the one the sizing would choose and every larger one; an
    edge beyond the largest DN leaves only the largest.
    """
    if net.empty:
        return []
    smallest = max(
        pipe_index(float(flow), pipe_info, edge_type)
        for flow, edge_type in zip(net[cols.VOLUME_FLOW], net[cols.TYPE])
    )
    return list(pipe_info["DN"].iloc[smallest:])


def resize_pipes(
    net: gpd.GeoDataFrame,
    nominal_diameter: str,
    pipe_info: pd.DataFrame,
    supply_temperature: float,
    return_temperature: float,
    civil_cost_share: float,
) -> gpd.GeoDataFrame:
    """``net`` with every edge in the pipe ``nominal_diameter`` of ``pipe_info``.

    Velocity, heat losses, ``pipe_cost`` and ``civil_cost`` are computed
    again; the civil works factor of each edge stays. Raises ValueError for a
    DN that is not one of :func:`possible_diameters`.
    """
    if nominal_diameter not in possible_diameters(net, pipe_info):
        raise ValueError(f"{nominal_diameter!r} is not a possible nominal diameter for these pipes.")
    pipe = pipe_info[pipe_info["DN"] == nominal_diameter].iloc[0]
    out = net.copy()
    values = [
        calculate_velocity_loss(float(flow), supply_temperature, return_temperature, float(length), pipe)
        for flow, length in zip(out[cols.VOLUME_FLOW], out[cols.LENGTH])
    ]
    out[cols.NOMINAL_DIAMETER] = nominal_diameter
    out[cols.VELOCITY] = [v[1] for v in values]
    out[cols.HEAT_LOSS] = [v[2] for v in values]
    out[cols.HEAT_LOSS_EXTRA_INSULATION] = [v[3] for v in values]
    return annotate_network_costs(out, None, pipe_info, civil_cost_share)
