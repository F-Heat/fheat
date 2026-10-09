"""Pipe investment per network edge.

Every edge gets its civil works factor ``f`` (from the civil works layers),
the standardised pipe costs ``c`` of its DN [€/m] — ``cost_main`` for routes,
``cost_h-connect`` for house connections — and with the civil works share
``s`` (``FHeatConfig.civil_cost_share``)::

    pipe_cost  = length · c · ((1 − s) + s · f)
    civil_cost = length · c · s · f

The same for every backend: Dijkstra builds a length-based topology, the
costs are written onto the finished net; topotherm already chose its
topology with the same multiplier and hands its factors over.
"""
from __future__ import annotations

import logging

import geopandas as gpd
import numpy as np
import pandas as pd

from fheat_core import columns as cols
from fheat_core.algorithms.civil_cost import civil_factors_for_lines, cost_multiplier

logger = logging.getLogger(__name__)

#: Cost columns of the pipe catalogue [€ per metre of trench].
COST_MAIN = "cost_main"
COST_HOUSE_CONNECTION = "cost_h-connect"


def civil_layers(state) -> list:
    """The civil works layers of a state in the order the overlay expects.

    The road surface comes last: :func:`civil_factors_for_lines` takes
    ``road_surface`` from the last layer.
    """
    return [state.landuse_gdf, state.osm_surface_gdf]


def _unit_costs(net: pd.DataFrame, pipe_info: pd.DataFrame | None) -> pd.Series:
    """Standardised pipe costs [€/m] per edge, NaN where unknown."""
    if pipe_info is None or not {"DN", COST_MAIN, COST_HOUSE_CONNECTION} <= set(pipe_info.columns):
        logger.warning(
            "The pipe catalogue has no cost columns (%s, %s): the net gets no pipe costs.",
            COST_MAIN, COST_HOUSE_CONNECTION,
        )
        return pd.Series(np.nan, index=net.index, dtype=float)

    catalogue = pipe_info.drop_duplicates("DN").set_index("DN")
    dn = net[cols.NOMINAL_DIAMETER]
    main = dn.map(pd.to_numeric(catalogue[COST_MAIN], errors="coerce"))
    house = dn.map(pd.to_numeric(catalogue[COST_HOUSE_CONNECTION], errors="coerce"))
    is_house = net[cols.TYPE] == cols.EDGE_TYPE_HOUSE_CONNECTION
    unit = house.where(is_house, main).astype(float)

    unknown = unit.isna() & dn.notna()
    if unknown.any():
        logger.warning("%d edge(s) have a DN without pipe costs in the catalogue.", int(unknown.sum()))
    return unit


def annotate_network_costs(
    net_gdf: gpd.GeoDataFrame,
    layers: list | None,
    pipe_info: pd.DataFrame | None,
    civil_cost_share: float,
) -> gpd.GeoDataFrame:
    """Add ``civil_cost_factor``, ``road_surface``, ``pipe_cost`` and ``civil_cost``.

    A ``civil_cost_factor`` the backend already set (topotherm, from its
    candidate edges) is kept; otherwise the edges are intersected with
    ``layers``. Without usable layers the factor is 1.0. Without cost columns
    in ``pipe_info`` the costs are NaN.
    """
    net = net_gdf.copy()
    has_factor = cols.CIVIL_COST_FACTOR in net.columns and net[cols.CIVIL_COST_FACTOR].notna().all()
    if not has_factor:
        factors = civil_factors_for_lines(net.geometry, layers, crs=net.crs)
        net[cols.CIVIL_COST_FACTOR] = factors[cols.CIVIL_COST_FACTOR].to_numpy(dtype=float)
        net[cols.ROAD_SURFACE] = factors[cols.ROAD_SURFACE].to_numpy()
    elif cols.ROAD_SURFACE not in net.columns:
        net[cols.ROAD_SURFACE] = None

    factor = net[cols.CIVIL_COST_FACTOR].astype(float)
    length = pd.to_numeric(net[cols.LENGTH], errors="coerce")
    base = length * _unit_costs(net, pipe_info)
    net[cols.PIPE_COST] = base * cost_multiplier(factor.to_numpy(), civil_cost_share)
    net[cols.CIVIL_COST] = base * float(civil_cost_share) * factor
    return net
