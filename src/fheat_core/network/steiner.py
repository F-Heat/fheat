"""Steiner-tree backend: a cheap total network instead of the shortest paths.

Same street graph and pipe sizing as Phase 0. Only the route choice differs.
The tree grows from the source (Prim–Dijkstra trade-off, Alpert et al. 1995,
on the street graph): the next building is the one with the lowest

    c · (route cost from the source to the tree node it attaches to)
      + cost of the new branch

with c = ``FHeatConfig.steiner_path_weight``; with None the backend builds the
net for c = 0, 0.1, …, 1 and Phase 0's own net and keeps the one with the
lowest pipe costs, so it never costs more than Phase 0. c = 0 is the Takahashi–Matsuyama
Steiner heuristic (at most twice the cheapest network): a building may hang
off its neighbour. c = 1 gives every building its cheapest route from the
source, as Phase 0. In between it trades network length against the long
routes that need larger pipes.

Every edge costs its length times the civil works multiplier
m = (1 − s) + s·f (s = ``civil_cost_share``, f from the civil works layers),
the same multiplier topotherm and the net's ``pipe_cost`` use. The pipe's own
€/m is left out: it depends on the DN, which is only known after routing.
Without civil works layers the cost is the length.
"""
from __future__ import annotations

import heapq
import logging
import math

import geopandas as gpd
import numpy as np
from shapely.geometry import LineString

from fheat_core import columns as cols
from fheat_core.algorithms.civil_cost import civil_factors_for_lines, cost_multiplier, usable_layers
from fheat_core.cancel import raise_if_cancelled
from fheat_core.network.costs import _unit_costs
from fheat_core.network.dijkstra import DijkstraBackend

logger = logging.getLogger(__name__)


#: weights tried when ``steiner_path_weight`` is None
AUTO_PATH_WEIGHTS = tuple(i / 10 for i in range(11))


class SteinerBackend(DijkstraBackend):
    """Tree over source and buildings along the street graph, cheap in total."""

    name = "steiner"

    def _network(self, G, buildings, source, pipe_info, civil_layers, config):
        start = (source.geometry.iloc[0].x, source.geometry.iloc[0].y)
        if start not in G:
            return super()._network(G, buildings, source, pipe_info, civil_layers, config)  # empty, as Phase 0
        edges = list(G.edges(data=cols.LENGTH))
        multiplier = np.ones(len(edges))
        if usable_layers(civil_layers):
            lines = gpd.GeoSeries([LineString([u, v]) for u, v, _ in edges], crs=buildings.crs)
            factor = civil_factors_for_lines(lines, civil_layers, crs=buildings.crs)[cols.CIVIL_COST_FACTOR]
            multiplier = np.atleast_1d(cost_multiplier(factor.to_numpy(), config.civil_cost_share))
        mult, cost = {}, {}
        for (u, v, length), m in zip(edges, multiplier):
            mult[u, v] = mult[v, u] = m
            cost[u, v] = cost[v, u] = length * m
        terminals = {(c.x, c.y) for c in buildings[cols.CENTROID]} - {start}

        if config.steiner_path_weight is not None:
            tree = grow_tree(G, cost, start, terminals, config.steiner_path_weight)
            # edge_subgraph view keeps the edge attributes compute_network reads
            return super()._network(G.edge_subgraph(tree), buildings, source, pipe_info, civil_layers, config)

        # Phase 0's own net too: c = 1 routes by length × civil works, Phase 0
        # by length, so only this keeps the result from costing more than Phase 0
        phase0 = super()._network(G, buildings, source, pipe_info, civil_layers, config)
        best = (pipe_cost(phase0, pipe_info, mult), "phase0", phase0)
        seen = set()
        for c in AUTO_PATH_WEIGHTS:
            tree = grow_tree(G, cost, start, terminals, c)
            if frozenset(tree) in seen:  # neighbouring weights often give the same tree
                continue
            seen.add(frozenset(tree))
            net = super()._network(G.edge_subgraph(tree), buildings, source, pipe_info, civil_layers, config)
            total = pipe_cost(net, pipe_info, mult)
            if total < best[0]:
                best = (total, c, net)
        logger.info("Steiner: cheapest net with path weight %s, pipe cost %.0f", best[1], best[0])
        return best[2]


def pipe_cost(net, pipe_info, mult):
    """Pipe costs of the net as ``annotate_network_costs`` will write them.

    Without pipe costs in the catalogue: the length weighted with the civil
    works multiplier, so the cheapest net is then the shortest.
    """
    m = np.array([mult[line.coords[0], line.coords[-1]] for line in net.geometry])
    length = net[cols.LENGTH].to_numpy(dtype=float) * m
    total = float(np.sum(length * _unit_costs(net, pipe_info).to_numpy(dtype=float)))
    return float(np.sum(length)) if np.isnan(total) else total


def grow_tree(G, cost, start, terminals, c):
    """Edges of the tree from ``start`` to every reachable terminal.

    One search for the whole tree: a node's label is the cheapest
    ``c · route(t) + dist(t, node)`` over the tree nodes t found so far. Labels
    only fall as the tree grows (c ≤ 1), so a decrease-only Dijkstra from each
    new branch keeps them right. Terminals the source cannot reach are skipped.
    """
    route = {start: 0.0}  # route cost from the source of every tree node
    label = {start: 0.0}
    pred = {start: None}
    heap = [(0.0, start)]
    remaining = set(terminals)
    tree = []
    while heap and remaining:
        lab, v = heapq.heappop(heap)
        if lab > label[v]:
            continue
        if v in remaining:
            raise_if_cancelled()
            branch = [v]
            while branch[-1] not in route:
                branch.append(pred[branch[-1]])
            branch.reverse()  # tree node first
            for a, b in zip(branch, branch[1:]):
                tree.append((a, b))
                route[b] = route[a] + cost[a, b]
                label[b], pred[b] = c * route[b], None
                heapq.heappush(heap, (label[b], b))
                remaining.discard(b)
            continue
        for u in G[v]:
            new = lab + cost[v, u]
            if new < label.get(u, math.inf):
                label[u], pred[u] = new, v
                heapq.heappush(heap, (new, u))
    return tree
