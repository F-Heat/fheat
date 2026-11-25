"""Start solution for topotherm: a prize-collecting Steiner tree (PCST).

pcst_fast picks a tree on topotherm's candidate graph that collects building
prizes for edge costs. Its built edges, directed away from the source, become
topotherm's ``lambda_`` (see :mod:`fheat_core.network.topotherm_backend`).

Prize of a building: (heat price − source price) · power · full load hours
minus the source investment annuity · power (€/a); in forced mode a prize above
the cost of every edge together, so every building is taken. Cost of an edge:
topotherm's fixed pipe cost b · length · civil works multiplier, as annuity.
shortcut: the power-dependent pipe cost a·P and the heat losses are left out of
the PCST (topotherm's model prices them afterwards); add an estimate of P per
edge if the start is too optimistic.
"""
from __future__ import annotations

from collections import deque

import numpy as np

from fheat_core.network.base import PCST_UNAVAILABLE, NetworkBackendError


def pcst_lambda(mat, economics, regression_inst, forced: bool):
    """``(lambda_ij, lambda_ji)`` per candidate edge from the PCST, or None for an empty tree."""
    try:
        import pcst_fast
    except ImportError as exc:
        raise NetworkBackendError(
            "The start solution 'pcst' requires pcst_fast: pip install pcst_fast",
            code=PCST_UNAVAILABLE,
        ) from exc
    from topotherm.models.calc import annuity

    a_i = np.asarray(mat["a_i"])
    n_nodes, n_edges = a_i.shape
    start = np.argmax(a_i == 1, axis=0)
    end = np.argmax(a_i == -1, axis=0)
    multiplier = np.asarray(mat["civil_m"], dtype=float) if "civil_m" in mat else 1.0
    costs = (
        float(regression_inst["b"])
        * float(annuity(economics.pipes_c_irr, economics.pipes_lifetime))
        * np.asarray(mat["l_i"], dtype=float).ravel()
        * multiplier
    )

    power = np.asarray(mat["q_c"], dtype=float)[:, 0]
    if forced:
        value = np.full(len(power), 2 * costs.sum() + 1)
    else:
        # shortcut: the first source's prices stand for all sources; fine while F|Heat has one source
        value = (
            (economics.heat_price - economics.source_price[0][0]) * power * np.asarray(mat["flh_sinks"], dtype=float)[:, 0]
            - economics.source_c_inv[0] * annuity(economics.source_c_irr[0], economics.source_lifetime[0]) * power
        )
    prizes = np.zeros(n_nodes + 1)
    np.add.at(prizes, np.argmax(np.asarray(mat["a_c"]) != 0, axis=0), np.clip(value, 0, None))

    # a virtual root joins every source at no cost
    root = n_nodes
    sources = np.flatnonzero(np.asarray(mat["a_p"]).any(axis=1))
    edges = np.vstack([
        np.column_stack([start, end]),
        np.column_stack([np.full(len(sources), root), sources]),
    ]).astype(np.int64)
    vertices, chosen = pcst_fast.pcst_fast(edges, prizes, np.concatenate([costs, np.zeros(len(sources))]), root, 1, "strong", 0)
    if root not in vertices or len(set(chosen.tolist())) != len(chosen):
        # the manylinux wheels of pcst_fast 1.0.10 return garbage under numpy 2 (seen 2026-11-25, Python 3.12)
        raise NetworkBackendError(
            "pcst_fast returns an invalid tree; build it from source: "
            "pip install --no-binary pcst_fast --force-reinstall pcst_fast",
            code=PCST_UNAVAILABLE,
        )
    if not np.any(chosen < n_edges):
        return None

    neighbours: dict[int, list[tuple[int, int]]] = {}
    for e in chosen:
        u, v = edges[e]
        neighbours.setdefault(int(u), []).append((int(v), int(e)))
        neighbours.setdefault(int(v), []).append((int(u), int(e)))
    lam_ij, lam_ji = np.zeros(n_edges), np.zeros(n_edges)
    seen, queue = {root}, deque([root])
    while queue:
        u = queue.popleft()
        for v, e in neighbours.get(u, ()):
            if v in seen:
                continue
            seen.add(v)
            queue.append(v)
            if e < n_edges:
                (lam_ij if start[e] == u else lam_ji)[e] = 1
    return lam_ij, lam_ji
