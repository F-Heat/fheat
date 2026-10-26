"""Tests for fheat_core.network.resize.

Covers: the possible DN of a selection, velocity, heat losses and pipe costs
follow a hand-picked DN, power and volume flow stay, house connections are
priced as such, the civil works factor stays, unknown and too small DN, and a
larger DN removes a bottleneck of the expansion potential.
"""
from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import LineString, Point

from fheat_core import columns as cols
from fheat_core.algorithms.expansion import expansion_potential
from fheat_core.algorithms.network import calculate_diameter_velocity_loss, calculate_glf, calculate_volumeflow
from fheat_core.network.costs import annotate_network_costs
from fheat_core.network.resize import possible_diameters, resize_pipes
from fheat_core.resources import load_pipe_info

CRS = "EPSG:25832"
SUPPLY, RETURN, SHARE = 80, 50, 0.6
PIPES = load_pipe_info()


def _net(*edges):
    """edges: (start, end, n, power, type); sized and priced like the network step, civil works factor 1.25"""
    rows = []
    for start, end, n, power, edge_type in edges:
        length = LineString([start, end]).length
        power_glf = power * calculate_glf(n)
        flow = calculate_volumeflow(power_glf, SUPPLY, RETURN)
        dn, velocity, loss, loss_extra = calculate_diameter_velocity_loss(flow, SUPPLY, RETURN, length, PIPES, edge_type)
        rows.append({
            cols.TYPE: edge_type, cols.LENGTH: length, cols.N_BUILDINGS: n, cols.THERMAL_POWER: power,
            cols.THERMAL_POWER_GLF: power_glf, cols.VOLUME_FLOW: flow, cols.NOMINAL_DIAMETER: dn,
            cols.VELOCITY: velocity, cols.HEAT_LOSS: loss, cols.HEAT_LOSS_EXTRA_INSULATION: loss_extra,
            cols.CIVIL_COST_FACTOR: 1.25, "geometry": LineString([start, end]),
        })
    return annotate_network_costs(gpd.GeoDataFrame(rows, crs=CRS), None, PIPES, SHARE)


def _pipe(dn):
    return PIPES.set_index("DN").loc[dn]


def test_values_follow_the_new_dn():
    net = _net(((0, 0), (100, 0), 5, 113.0, "Straßenleitung"))
    assert net[cols.NOMINAL_DIAMETER].iloc[0] == "PEX 32"
    resized = resize_pipes(net, "PEX 40", PIPES, SUPPLY, RETURN, SHARE).iloc[0]
    before = net.iloc[0]
    assert resized[cols.NOMINAL_DIAMETER] == "PEX 40"
    # same water through a wider pipe
    assert resized[cols.VOLUME_FLOW] == before[cols.VOLUME_FLOW]
    assert resized[cols.THERMAL_POWER_GLF] == before[cols.THERMAL_POWER_GLF]
    assert resized[cols.VELOCITY] == pytest.approx(before[cols.VELOCITY] * (_pipe("PEX 32")["di"] / _pipe("PEX 40")["di"]) ** 2)
    assert resized[cols.HEAT_LOSS] == pytest.approx(before[cols.HEAT_LOSS] * _pipe("PEX 40")["U-Value"] / _pipe("PEX 32")["U-Value"])
    assert resized[cols.HEAT_LOSS_EXTRA_INSULATION] == pytest.approx(
        before[cols.HEAT_LOSS_EXTRA_INSULATION] * _pipe("PEX 40")["U-Value_extra_insulation"] / _pipe("PEX 32")["U-Value_extra_insulation"]
    )
    # length · cost_main · ((1 − s) + s · f), the civil works factor stays
    assert resized[cols.CIVIL_COST_FACTOR] == 1.25
    assert resized[cols.PIPE_COST] == pytest.approx(100 * _pipe("PEX 40")["cost_main"] * (0.4 + 0.6 * 1.25))
    assert resized[cols.CIVIL_COST] == pytest.approx(100 * _pipe("PEX 40")["cost_main"] * 0.6 * 1.25)


def test_house_connection_keeps_its_price_list():
    net = _net(((0, 0), (0, 10), 1, 15.0, cols.EDGE_TYPE_HOUSE_CONNECTION))
    resized = resize_pipes(net, "PEX 25", PIPES, SUPPLY, RETURN, SHARE).iloc[0]
    assert resized[cols.PIPE_COST] == pytest.approx(10 * _pipe("PEX 25")["cost_h-connect"] * (0.4 + 0.6 * 1.25))


def test_possible_diameters_start_at_the_sized_one():
    street = _net(((0, 0), (100, 0), 5, 113.0, "Straßenleitung"))
    house = _net(((0, 0), (0, 10), 1, 15.0, cols.EDGE_TYPE_HOUSE_CONNECTION))
    catalogue = list(PIPES["DN"])
    assert possible_diameters(street, PIPES) == catalogue[catalogue.index("PEX 32"):]
    assert possible_diameters(house, PIPES) == catalogue[catalogue.index(house[cols.NOMINAL_DIAMETER].iloc[0]):]
    # a selection starts at the DN of its largest pipe
    selection = _net(((0, 0), (100, 0), 1, 15.0, "Straßenleitung"), ((100, 0), (200, 0), 30, 600.0, "Straßenleitung"))
    assert selection[cols.NOMINAL_DIAMETER].tolist() == ["PEX 32", "PEX 65"]
    assert possible_diameters(selection, PIPES)[0] == "PEX 65"
    # beyond the largest DN only the largest is left
    assert possible_diameters(_net(((0, 0), (100, 0), 2000, 80_000.0, "Straßenleitung")), PIPES) == ["KMR 300"]
    assert possible_diameters(street.iloc[:0], PIPES) == []


def test_too_small_dn():
    with pytest.raises(ValueError):
        resize_pipes(_net(((0, 0), (100, 0), 5, 113.0, "Straßenleitung")), "PEX 25", PIPES, SUPPLY, RETURN, SHARE)


def test_unknown_dn():
    with pytest.raises(ValueError):
        resize_pipes(_net(((0, 0), (100, 0), 5, 113.0, "Straßenleitung")), "PEX 33", PIPES, SUPPLY, RETURN, SHARE)


def test_a_larger_dn_removes_a_bottleneck():
    """A full PEX 32 before a branch leaves it nothing; as PEX 40 it lets the branch use its own room."""
    net = _net(((0, 0), (100, 0), 5, 113.0, "Straßenleitung"), ((100, 0), (150, 0), 1, 13.0, "Straßenleitung"))
    full = expansion_potential(net, Point(0, 0), PIPES, 10.0)
    assert full[cols.POTENTIAL_BUILDINGS].tolist() == [0, 0]
    net.loc[[0]] = resize_pipes(net.loc[[0]], "PEX 40", PIPES, SUPPLY, RETURN, SHARE)
    resized = expansion_potential(net, Point(0, 0), PIPES, 10.0)
    assert resized[cols.POTENTIAL_BUILDINGS].iloc[1] > 0
