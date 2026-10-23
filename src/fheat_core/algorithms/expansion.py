"""Expansion potential of the pipes of a calculated net.

How much more building power a pipe can take before its DN would have to
go up to the next size of the pipe catalogue, and how many buildings of a
given average power that is. Computed on request from a calculated net;
nothing of it is stored or exported.

A pipe carrying n buildings of together P [kW] (without GLF) keeps its DN
as long as the diversified power stays below the capacity C [kW] of the
DN. k more buildings of p kW each fit while

    GLF(n + k) · (P + k·p) < C

The connectable power ΔP = k·p is the fixed point of

    ΔP = C / GLF(n + ΔP / p) − P

iterated from ΔP = 0: the first step is the reserve divided by today's
GLF, every further step lowers the GLF with the buildings just added. The
map rises with ΔP, so the iteration rises to the first ΔP at which the pipe
is full and every step stays on the safe side — also where the count-based
GLF would let the diversified power sink again for many small buildings
behind a few large ones.

k new buildings on a pipe are k more buildings on every pipe towards the
source as well. All of them are computed with the same p, so the power
connectable at a pipe is the smallest ΔP along its way to the source, and
the number of buildings is that power divided by p, rounded down.
"""
from __future__ import annotations

from collections import deque

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
import shapely

from fheat_core import columns as cols
from fheat_core.algorithms.network import calculate_glf

_MAX_ITERATIONS = 1000
_TOLERANCE = 1e-6       # kW — the fixed point iteration stops below this step
_NODE_TOLERANCE = 0.01  # m — line ends closer than this are one node


def mean_building_power(net: pd.DataFrame) -> float | None:
    """Mean thermal power [kW] of the buildings connected to the net.

    Every house connection carries exactly one building, so this is the mean
    power of the house connections; None without any.
    """
    house = net[cols.TYPE] == cols.EDGE_TYPE_HOUSE_CONNECTION
    power = pd.to_numeric(net.loc[house, cols.THERMAL_POWER], errors="coerce").dropna()
    return float(power.mean()) if len(power) else None


def expansion_potential(
    net: gpd.GeoDataFrame,
    source: shapely.Point,
    pipe_info: pd.DataFrame,
    building_power: float,
) -> pd.DataFrame:
    """Expandable power and potential buildings of every edge of ``net``.

    ``source`` is the heat source in the CRS of the net, ``building_power``
    the average power [kW] of a new building. Returns ``expandable_power``
    [kW] and ``potential_buildings`` on the index of the net, both for
    connecting at that edge, so through all edges towards the source. Both
    are missing for house connections and where an edge on the way has a DN
    that is not in ``pipe_info``. An edge already beyond the largest DN gets 0.
    """
    if not np.isfinite(building_power) or building_power <= 0:
        raise ValueError(f"building_power must be a positive number of kW, not {building_power!r}.")
    if net.empty:
        return pd.DataFrame(
            {cols.EXPANDABLE_POWER: pd.Series(dtype=float), cols.POTENTIAL_BUILDINGS: pd.Series(dtype="Int64")},
            index=net.index,
        )

    n = pd.to_numeric(net[cols.N_BUILDINGS], errors="coerce").to_numpy(float)
    power = pd.to_numeric(net[cols.THERMAL_POWER], errors="coerce").to_numpy(float)
    added = _connectable_power(n, power, _capacity(net, pipe_info), building_power)

    parent, order = _way_to_source(net, source)
    for edge in order:  # an edge comes after the edge before it
        if parent[edge] >= 0:
            added[edge] = np.minimum(added[edge], added[parent[edge]])

    buildings = np.floor(added / building_power)
    house = (net[cols.TYPE] == cols.EDGE_TYPE_HOUSE_CONNECTION).to_numpy()
    added[house] = np.nan
    buildings[house] = np.nan
    return pd.DataFrame(
        {
            cols.EXPANDABLE_POWER: added,
            cols.POTENTIAL_BUILDINGS: pd.array(buildings, dtype="Float64").astype("Int64"),
        },
        index=net.index,
    )


def _capacity(net: pd.DataFrame, pipe_info: pd.DataFrame) -> np.ndarray:
    """Power [kW] the DN of each edge holds before the next DN would be needed.

    ``max_volumeFlow`` of the DN, converted with the kW per l/s of the net's
    own calculation (thermal_power_glf / volume_flow, the same for every edge
    of a net). The capacity so belongs to the temperatures the DN was chosen
    with. NaN for a DN missing in the catalogue.
    """
    max_flow = pipe_info.drop_duplicates("DN").set_index("DN")["max_volumeFlow"]
    flow = pd.to_numeric(net[cols.VOLUME_FLOW], errors="coerce")
    power_glf = pd.to_numeric(net[cols.THERMAL_POWER_GLF], errors="coerce")
    kw_per_flow = (power_glf / flow)[flow > 0].median()
    return net[cols.NOMINAL_DIAMETER].map(max_flow).to_numpy(float) * kw_per_flow


def _connectable_power(n: np.ndarray, power: np.ndarray, capacity: np.ndarray, building_power: float) -> np.ndarray:
    """Fixed point ΔP = C / GLF(n + ΔP/p) − P of every edge, approached from below; 0 for a full DN."""
    added = np.zeros_like(power)
    for _ in range(_MAX_ITERATIONS):
        step = np.maximum(capacity / calculate_glf(n + added / building_power) - power, 0.0)
        converged = np.isnan(step) | (np.abs(step - added) < _TOLERANCE)
        added = step
        if converged.all():
            break
    return added


def _way_to_source(net: gpd.GeoDataFrame, source: shapely.Point) -> tuple[np.ndarray, list[int]]:
    """The edge before each edge on its way to the source, and the edges from the source outwards.

    Line ends closer than ``_NODE_TOLERANCE`` are one node, so a net works
    whatever the direction of its lines. The edges at the source have no
    edge before them (-1).
    """
    lines = net.geometry.to_numpy()
    ends = np.concatenate([shapely.get_point(lines, 0), shapely.get_point(lines, -1)])
    close = shapely.STRtree(ends).query(ends, predicate="dwithin", distance=_NODE_TOLERANCE)
    same = nx.Graph()
    same.add_nodes_from(range(len(ends)))
    same.add_edges_from(zip(*close))
    node = np.empty(len(ends), dtype=int)
    for label, members in enumerate(nx.connected_components(same)):
        node[list(members)] = label

    edges_at: dict[int, list[tuple[int, int]]] = {}
    for edge, (start, end) in enumerate(zip(node[: len(lines)], node[len(lines):])):
        edges_at.setdefault(start, []).append((edge, end))
        edges_at.setdefault(end, []).append((edge, start))

    root = node[int(np.argmin(shapely.distance(ends, source)))]
    parent = np.full(len(lines), -1)
    seen = np.zeros(len(lines), dtype=bool)
    order: list[int] = []
    reached = {root}
    queue = deque([(root, -1)])
    while queue:
        at, via = queue.popleft()
        for edge, other in edges_at[at]:
            if seen[edge]:
                continue
            seen[edge] = True
            parent[edge] = via
            order.append(edge)
            if other not in reached:
                reached.add(other)
                queue.append((other, edge))
    return parent, order
