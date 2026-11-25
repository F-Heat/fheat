"""A calculated net recalculated after a planner edited it.

An application may move, delete and restore pipes of a calculated net. This
module brings every value that follows from length and topology back in line
with the edited geometry, with the formulas of the network step:

* ``length`` from the geometry,
* buildings and power per edge from the paths source → house connection
  (as :func:`fheat_core.algorithms.network.compute_network`),
* GLF, volume flow, DN, velocity, heat losses and pipe costs.

A house connection is input: its ``thermal_power`` is the power of its
building and stays. Every other edge carries what flows behind it, by the
rule of the backend that built the net (:func:`heat_loss_rule`): the sum of
the house connections behind it (Dijkstra), or that plus topotherm's heat
losses of every pipe on the way, ``(a · P_in + b) · length`` (topotherm). A DN chosen by hand (``nominal_diameter_manual``) stays
while it carries the flow, else it is raised to the sized one. Pipes without
a connection to the source carry nothing and keep their DN.

Not done here: the civil works factor and ``length_under_buildings`` need
the civil works layers and the buildings; the application recalculates them
for the edited pipes (:func:`fheat_core.algorithms.civil_cost.civil_factors_for_lines`,
:func:`fheat_core.algorithms.under_buildings.mark_length_under_buildings`).
"""
from __future__ import annotations

import logging
from collections import defaultdict

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
import shapely

from fheat_core import columns as cols
from fheat_core.algorithms.network import (
    calculate_glf,
    calculate_velocity_loss,
    calculate_volumeflow,
    pipe_index,
)
from fheat_core.algorithms.under_buildings import line_ends
from fheat_core.config import NetworkMode
from fheat_core.network.base import NetworkBackendError
from fheat_core.network.costs import annotate_network_costs

logger = logging.getLogger(__name__)

#: Distance [m] within which a pipe end that meets no other end joins the
#: nearest one: an edit in a web map moves an untouched end by millimetres
#: (projected → WGS84 → projected). Ends that meet exactly are never moved
#: apart or together: street vertices of a net can be millimetres apart.
NODE_TOLERANCE = 0.05


def recalculate_net(
    net: gpd.GeoDataFrame,
    source,
    pipe_info: pd.DataFrame,
    supply_temperature: float,
    return_temperature: float,
    civil_cost_share: float,
    heat_losses: dict | None = None,
) -> tuple[gpd.GeoDataFrame, dict]:
    """``net`` with length, flows, DN, losses and costs following its geometry.

    ``heat_losses`` are the coefficients ``a``, ``b`` of :func:`heat_loss_rule`
    for a net of topotherm; without them an edge carries the plain sum.

    ``source`` is the heat source (a shapely point in the CRS of the net); the
    net starts at the pipe ends on it (``NODE_TOLERANCE``), without one every
    pipe is disconnected. Rows keep their order and index.
    The report counts the pipes without a connection to the source
    (``disconnected``) and the DN chosen by hand that had to be raised
    (``raised_manual``).
    """
    out = net.copy()
    report = {"disconnected": 0, "raised_manual": 0}
    if out.empty:
        return out, report

    lines = out.geometry.to_numpy(dtype=object)
    length = shapely.length(lines)
    a, b, root = _nodes(lines, source)
    is_house = (out[cols.TYPE] == cols.EDGE_TYPE_HOUSE_CONNECTION).to_numpy()

    graph = nx.Graph()
    for row in np.argsort(length, kind="stable"):  # parallel pipes: the shorter one carries the flow
        if a[row] != b[row] and not graph.has_edge(a[row], b[row]):
            graph.add_edge(a[row], b[row], row=row, length=length[row])
    distance, paths = nx.single_source_dijkstra(graph, root, weight="length") if root in graph else ({}, {})

    n_buildings = np.zeros(len(out), dtype=int)
    power = np.zeros(len(out))
    stored_power = pd.to_numeric(out[cols.THERMAL_POWER], errors="coerce").fillna(0.0).to_numpy()
    connected = np.array([a[row] in distance for row in range(len(out))])
    for row in np.flatnonzero(is_house & connected):
        near = a[row] if distance[a[row]] <= distance.get(b[row], np.inf) else b[row]
        path = paths[near]
        for u, v in zip(path, path[1:]):
            edge = graph.edges[u, v]["row"]
            n_buildings[edge] += 1
            power[edge] += stored_power[row]
    n_buildings[is_house] = 1
    power[is_house] = stored_power[is_house]
    if heat_losses is not None:
        stored_length = pd.to_numeric(out[cols.LENGTH], errors="coerce").to_numpy(float)
        lossy, carried = _power_with_losses(graph, distance, paths, is_house, stored_power, stored_length, length, heat_losses)
        power[carried] = lossy[carried]

    catalogue = list(pipe_info["DN"])
    manual = (
        out[cols.NOMINAL_DIAMETER_MANUAL].eq(True).to_numpy(copy=True)  # written below; read-only under copy-on-write
        if cols.NOMINAL_DIAMETER_MANUAL in out.columns else np.zeros(len(out), dtype=bool)
    )
    values, raised = [], []
    for row in range(len(out)):
        glf = calculate_glf(int(n_buildings[row]))
        power_glf = power[row] * glf if connected[row] else 0.0
        flow = calculate_volumeflow(power_glf, supply_temperature, return_temperature)
        dn = out[cols.NOMINAL_DIAMETER].iloc[row]
        current = catalogue.index(dn) if dn in catalogue else None
        if connected[row] or current is None:
            sized = pipe_index(flow, pipe_info, out[cols.TYPE].iloc[row])
            if connected[row] and manual[row] and current is not None and current < sized:
                raised.append(row)
                manual[row] = False
            if not (manual[row] and current is not None):
                current = sized
        _, velocity, loss, loss_extra = calculate_velocity_loss(
            flow, supply_temperature, return_temperature, float(length[row]), pipe_info.iloc[current]
        )
        values.append((glf, power_glf, flow, pipe_info["DN"].iloc[current], velocity, loss, loss_extra))

    report["disconnected"] = int((~connected).sum())
    report["raised_manual"] = len(raised)
    out[cols.LENGTH] = length
    out[cols.N_BUILDINGS] = n_buildings
    out[cols.THERMAL_POWER] = power
    for k, column in enumerate((
        cols.GLF, cols.THERMAL_POWER_GLF, cols.VOLUME_FLOW, cols.NOMINAL_DIAMETER,
        cols.VELOCITY, cols.HEAT_LOSS, cols.HEAT_LOSS_EXTRA_INSULATION,
    )):
        out[column] = [v[k] for v in values]
    if raised:  # only the raised pipes lose the mark; pipes without one stay without
        out.loc[out.index[raised], cols.NOMINAL_DIAMETER_MANUAL] = False
    return annotate_network_costs(out, None, pipe_info, civil_cost_share), report


def heat_loss_rule(config) -> dict | None:
    """How an edge's power grows with the pipes behind it, for the backend of ``config``.

    topotherm's heat losses ``{"a", "b"}`` (:func:`~fheat_core.network.topotherm_backend.heat_loss_regression`)
    for its nets, None (the plain sum) for every other backend.
    """
    if config.network_mode != NetworkMode.EXPERT.value:
        return None
    from fheat_core.network.topotherm_backend import heat_loss_regression

    try:
        return heat_loss_regression(config)
    except NetworkBackendError as exc:  # an edit must not fail: the sum is the next best rule
        logger.warning("topotherm not available, the net is recalculated without its heat losses: %s", exc)
        return None


def _power_with_losses(graph, distance, paths, is_house, stored_power, stored_length, length, losses):
    """topotherm's power of every edge on the way from the source, and which edges got one.

    From the far end to the source: a pipe carries what flows into the pipes
    behind its end and its own losses, ``P_in = (P_out + b·l) / (1 − a·l)``.
    A house connection's building demand comes from its stored power and
    length, so a new length changes its own losses too.
    """
    a, b = losses["a"], losses["b"]
    power = np.zeros(len(length))
    carried = np.zeros(len(length), dtype=bool)
    behind = defaultdict(float)  # power flowing into the pipes behind a node
    for node in sorted(distance, key=distance.get, reverse=True):
        path = paths[node]
        if len(path) < 2:
            continue  # the source
        row = graph.edges[path[-2], node]["row"]
        p_out = behind[node]
        if is_house[row]:
            old = stored_length[row] if np.isfinite(stored_length[row]) else length[row]
            p_out += stored_power[row] * (1 - a * old) - b * old
        power[row] = (p_out + b * length[row]) / (1 - a * length[row])
        carried[row] = True
        behind[path[-2]] += power[row]
    return power, carried


def _nodes(lines, source) -> tuple[np.ndarray, np.ndarray, int | None]:
    """Node of the first and last end of each line, and the node at the source (None: no end there).

    Ends at the same coordinates are one node; an end that meets no other
    joins the nearest end within ``NODE_TOLERANCE``.
    """
    first, last = line_ends(lines)
    ends = np.concatenate([first, last])
    _, exact, count = np.unique(shapely.get_coordinates(ends), axis=0, return_inverse=True, return_counts=True)
    exact = exact.ravel()
    joined = nx.Graph()
    joined.add_nodes_from(range(len(count)))
    alone = np.flatnonzero(count[exact] == 1)
    if len(alone):
        hit, other = shapely.STRtree(ends).query_nearest(
            ends[alone], max_distance=NODE_TOLERANCE, exclusive=True, all_matches=False
        )
        joined.add_edges_from(zip(exact[alone[hit]].tolist(), exact[other].tolist()))
    merged = np.empty(len(count), dtype=int)
    for k, members in enumerate(nx.connected_components(joined)):
        merged[list(members)] = k
    node = merged[exact]
    distance = shapely.distance(ends, source)
    nearest = int(np.argmin(distance))
    root = int(node[nearest]) if distance[nearest] <= NODE_TOLERANCE else None
    return node[: len(lines)], node[len(lines):], root
