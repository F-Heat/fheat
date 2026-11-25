"""Tests for fheat_core.network.recalculate.

Covers: an untouched net stays as the network step made it, a moved pipe
gets its length, losses and costs, a deleted house connection lowers power
and DN on its way to the source, a part without connection to the source
carries nothing and keeps its DN, a DN chosen by hand stays or is raised,
and ends a web map moved by millimetres stay connected.
"""
from __future__ import annotations

import geopandas as gpd
import networkx as nx
import pandas as pd
import pytest
from shapely.geometry import LineString, Point

from fheat_core import columns as cols
from fheat_core.algorithms.network import add_edge_lengths, compute_network
from fheat_core.network.costs import annotate_network_costs
from fheat_core.network.recalculate import recalculate_net
from fheat_core.resources import load_pipe_info

CRS = "EPSG:25832"
SUPPLY, RETURN, SHARE = 80, 50, 0.6
PIPES = load_pipe_info()
SOURCE = Point(0, 0)
HOUSE, STREET = cols.EDGE_TYPE_HOUSE_CONNECTION, cols.EDGE_TYPE_STREET
# source S(0,0) — A(100,0) — B(200,0); houses H1 at A, H2 and H3 at B
NODES = {"S": (0, 0), "A": (100, 0), "B": (200, 0), "H1": (100, 20), "H2": (200, 20), "H3": (200, -20)}
POWER = {"H1": 40.0, "H2": 60.0, "H3": 80.0}


def _net():
    """The net the network step builds, with civil works factor 1.25 and costs."""
    G = nx.Graph()
    for u, v, edge_type in (("S", "A", STREET), ("A", "B", STREET), ("A", "H1", HOUSE), ("B", "H2", HOUSE), ("B", "H3", HOUSE)):
        G.add_edge(NODES[u], NODES[v], **{cols.TYPE: edge_type})
    add_edge_lengths(G)
    buildings = gpd.GeoDataFrame(
        {cols.CENTROID: [Point(NODES[h]) for h in POWER], cols.THERMAL_POWER: list(POWER.values())},
        geometry=[Point(NODES[h]).buffer(5) for h in POWER], crs=CRS,
    )
    source = gpd.GeoDataFrame(geometry=[SOURCE], crs=CRS)
    net = compute_network(G, buildings, source, PIPES, cols.THERMAL_POWER, SUPPLY, RETURN, CRS)
    net[cols.CIVIL_COST_FACTOR] = 1.25
    return annotate_network_costs(net, None, PIPES, SHARE)


def _row(net, a, b):
    """Index of the pipe between the nodes ``a`` and ``b``."""
    ends = {NODES[a], NODES[b]}
    return next(i for i, line in net.geometry.items() if {line.coords[0], line.coords[-1]} == ends)


def _recalculate(net):
    return recalculate_net(net, SOURCE, PIPES, SUPPLY, RETURN, SHARE)


def test_an_untouched_net_stays_as_the_network_step_made_it():
    net = _net()
    out, report = _recalculate(net)
    assert report == {"disconnected": 0, "raised_manual": 0}
    pd.testing.assert_frame_equal(pd.DataFrame(out), pd.DataFrame(net), check_like=True, check_dtype=False)


def test_a_moved_pipe_gets_its_length_losses_and_costs():
    net = _net()
    h1 = _row(net, "A", "H1")
    before = net.loc[h1].copy()
    net.loc[h1, "geometry"] = LineString([(100, 0), (130, 0), (130, 20), (100, 20)])  # around an obstacle, 80 m
    out, _ = _recalculate(net)
    after = out.loc[h1]
    assert after[cols.LENGTH] == pytest.approx(80.0)
    for column in (cols.HEAT_LOSS, cols.HEAT_LOSS_EXTRA_INSULATION, cols.PIPE_COST, cols.CIVIL_COST):
        assert after[column] == pytest.approx(before[column] * 4)
    assert after[cols.NOMINAL_DIAMETER] == before[cols.NOMINAL_DIAMETER]
    others = out.drop(index=h1)
    pd.testing.assert_frame_equal(pd.DataFrame(others), pd.DataFrame(_net().drop(index=h1)), check_like=True, check_dtype=False)


def test_a_deleted_house_connection_lowers_power_and_dn_to_the_source():
    full = _net()
    net = full.drop(index=_row(full, "B", "H3"))
    out, report = _recalculate(net)
    assert report["disconnected"] == 0
    ab, sa = out.loc[_row(full, "A", "B")], out.loc[_row(full, "S", "A")]
    assert (ab[cols.N_BUILDINGS], ab[cols.THERMAL_POWER]) == (1, 60.0)
    assert (sa[cols.N_BUILDINGS], sa[cols.THERMAL_POWER]) == (2, 100.0)
    assert ab[cols.VOLUME_FLOW] < full.loc[_row(full, "A", "B"), cols.VOLUME_FLOW]
    assert list(PIPES["DN"]).index(ab[cols.NOMINAL_DIAMETER]) < list(PIPES["DN"]).index(full.loc[_row(full, "A", "B"), cols.NOMINAL_DIAMETER])


def test_a_part_without_connection_to_the_source_carries_nothing_and_keeps_its_dn():
    full = _net()
    net = full.drop(index=_row(full, "A", "B"))
    out, report = _recalculate(net)
    assert report["disconnected"] == 2
    for a, b in (("B", "H2"), ("B", "H3")):
        row = out.loc[_row(full, a, b)]
        assert row[cols.VOLUME_FLOW] == 0 and row[cols.VELOCITY] == 0 and row[cols.THERMAL_POWER_GLF] == 0
        assert row[cols.NOMINAL_DIAMETER] == full.loc[_row(full, a, b), cols.NOMINAL_DIAMETER]
        assert row[cols.THERMAL_POWER] == POWER[b]  # the building's power stays for a later reconnection
    assert out.loc[_row(full, "S", "A"), cols.N_BUILDINGS] == 1


def test_a_dn_chosen_by_hand_stays_while_it_carries_the_flow():
    net = _net()
    sa = _row(net, "S", "A")
    net[cols.NOMINAL_DIAMETER_MANUAL] = False
    net.loc[sa, [cols.NOMINAL_DIAMETER, cols.NOMINAL_DIAMETER_MANUAL]] = [PIPES["DN"].iloc[-1], True]
    out, report = _recalculate(net)
    assert report["raised_manual"] == 0
    assert out.loc[sa, cols.NOMINAL_DIAMETER] == PIPES["DN"].iloc[-1] and out.loc[sa, cols.NOMINAL_DIAMETER_MANUAL]


def test_a_dn_chosen_by_hand_that_became_too_small_is_raised():
    net = _net()
    sa = _row(net, "S", "A")
    net[cols.NOMINAL_DIAMETER_MANUAL] = False
    net.loc[sa, [cols.NOMINAL_DIAMETER, cols.NOMINAL_DIAMETER_MANUAL]] = [PIPES["DN"].iloc[0], True]
    out, report = _recalculate(net)
    assert report["raised_manual"] == 1
    assert out.loc[sa, cols.NOMINAL_DIAMETER] == _net().loc[sa, cols.NOMINAL_DIAMETER]
    assert not out.loc[sa, cols.NOMINAL_DIAMETER_MANUAL]


def test_ends_moved_by_millimetres_stay_connected():
    net = _net()
    ab = _row(net, "A", "B")
    net.loc[ab, "geometry"] = LineString([(100.002, -0.001), (199.998, 0.0)])
    out, report = _recalculate(net)
    assert report["disconnected"] == 0
    assert out.loc[ab, cols.N_BUILDINGS] == 2


def test_without_a_pipe_at_the_source_every_pipe_is_disconnected():
    full = _net()
    out, report = _recalculate(full.drop(index=_row(full, "S", "A")))
    assert report["disconnected"] == len(full) - 1
    assert (out[cols.VOLUME_FLOW] == 0).all()


def test_street_vertices_millimetres_apart_stay_apart():
    # two street nodes 6 mm apart, each joining two pipes (as in a real OSM street net)
    from fheat_core.network.recalculate import _nodes

    lines = [
        LineString([(0, 0), (1, 0)]), LineString([(1, 0), (2, 0)]),
        LineString([(1, 0.006), (1, 5)]), LineString([(0, 5), (1, 0.006)]),
    ]
    first, last, _ = _nodes(lines, SOURCE)
    assert first[1] == last[0]
    assert first[2] == last[3]
    assert first[1] != first[2]
