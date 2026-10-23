"""Tests for fheat_core.algorithms.expansion.

Covers:
- expansion_potential: connectable power from the GLF fixed point, power and buildings
  limited by the edges towards the source, house connections left out,
  full DN, DN missing in the catalogue, line direction and node tolerance,
  the count-based GLF artefact, invalid input, a net from compute_network.
- mean_building_power: mean power of the house connections.
"""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, Point, Polygon

from fheat_core import columns as cols
from fheat_core.algorithms.expansion import expansion_potential, mean_building_power
from fheat_core.algorithms.network import (
    add_edge_lengths,
    build_street_graph,
    calculate_diameter_velocity_loss,
    calculate_glf,
    calculate_volumeflow,
    compute_network,
    connect_buildings_to_graph,
    connect_source_to_graph,
)
from fheat_core.resources import load_pipe_info

CRS = "EPSG:25832"
SUPPLY, RETURN = 80, 50
STREET = "Straßenleitung"
SOURCE = Point(0, 0)
PIPES = load_pipe_info()


def _edge(start, end, n, power, edge_type=STREET):
    """An edge sized like the network step: GLF, volume flow and DN from n and power."""
    power_glf = power * calculate_glf(n)
    flow = calculate_volumeflow(power_glf, SUPPLY, RETURN)
    dn, *_ = calculate_diameter_velocity_loss(flow, SUPPLY, RETURN, 1.0, PIPES, edge_type)
    return {
        cols.TYPE: edge_type,
        cols.N_BUILDINGS: n,
        cols.THERMAL_POWER: power,
        cols.THERMAL_POWER_GLF: power_glf,
        cols.VOLUME_FLOW: flow,
        cols.NOMINAL_DIAMETER: dn,
        "geometry": LineString([start, end]),
    }


def _net(*edges):
    return gpd.GeoDataFrame(list(edges), geometry="geometry", crs=CRS)


def _capacity(edge):
    """kW the DN of an edge holds, at the temperatures of its calculation."""
    max_flow = PIPES.set_index("DN").loc[edge[cols.NOMINAL_DIAMETER], "max_volumeFlow"]
    return max_flow * edge[cols.THERMAL_POWER_GLF] / edge[cols.VOLUME_FLOW]


class TestExpansionPotential:
    def test_reserve_divided_by_a_falling_glf(self):
        """20 buildings of 15 kW on PEX 50: 80 kW reserve, 106.5 kW and 7 buildings with the GLF loop."""
        edge = _edge((0, 0), (100, 0), 20, 300.0)
        assert edge[cols.NOMINAL_DIAMETER] == "PEX 50"
        result = expansion_potential(_net(edge), SOURCE, PIPES, 15.0).iloc[0]
        assert result[cols.EXPANDABLE_POWER] == pytest.approx(106.48, abs=0.01)
        assert result[cols.POTENTIAL_BUILDINGS] == 7
        # 7 more buildings keep the DN, 8 do not
        assert calculate_glf(27) * (300 + 7 * 15) < _capacity(edge) < calculate_glf(28) * (300 + 8 * 15)

    def test_more_buildings_of_smaller_power(self):
        edge = _edge((0, 0), (100, 0), 20, 300.0)
        small = expansion_potential(_net(edge), SOURCE, PIPES, 5.0).iloc[0]
        large = expansion_potential(_net(edge), SOURCE, PIPES, 60.0).iloc[0]
        assert small[cols.EXPANDABLE_POWER] > large[cols.EXPANDABLE_POWER]
        assert (small[cols.POTENTIAL_BUILDINGS], large[cols.POTENTIAL_BUILDINGS]) == (43, 1)

    def test_limited_by_the_edges_towards_the_source(self):
        """A branch with room for 6 buildings behind a main line with room for 1 gets the main line's power and 1."""
        main = _edge((0, 0), (100, 0), 26, 390.0)
        branch = _edge((100, 0), (100, 50), 1, 15.0)
        alone = expansion_potential(_net(branch), Point(100, 0), PIPES, 15.0).iloc[0]
        result = expansion_potential(_net(main, branch), SOURCE, PIPES, 15.0)
        assert alone[cols.POTENTIAL_BUILDINGS] == 6
        assert result[cols.POTENTIAL_BUILDINGS].tolist() == [1, 1]
        assert result[cols.EXPANDABLE_POWER].iloc[1] == pytest.approx(result[cols.EXPANDABLE_POWER].iloc[0])
        assert result[cols.EXPANDABLE_POWER].iloc[1] < alone[cols.EXPANDABLE_POWER]

    def test_the_edge_before_is_found_whatever_the_line_direction(self):
        """Lines drawn towards the source and ends a few millimetres apart still form one way."""
        main = _edge((100, 0), (0, 0), 26, 390.0)
        branch = _edge((100, 50), (100.003, 0), 1, 15.0)
        result = expansion_potential(_net(branch, main), SOURCE, PIPES, 15.0)
        assert result[cols.POTENTIAL_BUILDINGS].tolist() == [1, 1]

    def test_house_connections_get_no_values(self):
        source_connection = _edge((0, 0), (0, 5), 2, 30.0, "Quellenanschluss")
        street = _edge((0, 5), (50, 5), 2, 30.0)
        houses = [_edge((50, 5), end, 1, 15.0, cols.EDGE_TYPE_HOUSE_CONNECTION) for end in ((50, 15), (60, 5))]
        result = expansion_potential(_net(source_connection, street, *houses), SOURCE, PIPES, 15.0)
        assert result[cols.EXPANDABLE_POWER].iloc[:2].gt(0).all()
        assert result[cols.POTENTIAL_BUILDINGS].iloc[:2].notna().all()
        assert result[cols.EXPANDABLE_POWER].iloc[2:].isna().all()
        assert result[cols.POTENTIAL_BUILDINGS].iloc[2:].isna().all()

    def test_full_largest_dn_has_nothing_left(self):
        edge = _edge((0, 0), (100, 0), 2000, 80_000.0)
        assert edge[cols.NOMINAL_DIAMETER] == "KMR 300"
        assert edge[cols.THERMAL_POWER_GLF] > _capacity(edge)
        result = expansion_potential(_net(edge), SOURCE, PIPES, 15.0).iloc[0]
        assert (result[cols.EXPANDABLE_POWER], result[cols.POTENTIAL_BUILDINGS]) == (0.0, 0)

    def test_dn_missing_in_the_catalogue(self):
        edge = _edge((0, 0), (100, 0), 20, 300.0) | {cols.NOMINAL_DIAMETER: "KMR 999"}
        result = expansion_potential(_net(edge), SOURCE, PIPES, 15.0).iloc[0]
        assert pd.isna(result[cols.EXPANDABLE_POWER])
        assert pd.isna(result[cols.POTENTIAL_BUILDINGS])

    def test_stops_where_the_pipe_is_first_full(self):
        """Few large buildings, small new ones: the count-based GLF lets the load sink again later.

        8 buildings of 200 kW; with 4 new ones of 10 kW the DN is full. Far
        more would fit again on paper (137), the potential is the first 3.
        """
        n, power, building_power = 8, 1600.0, 10.0
        capacity = calculate_glf(n + 3.5) * (power + 3.5 * building_power)
        edge = _edge((0, 0), (100, 0), n, power) | {cols.NOMINAL_DIAMETER: "KMR 100"}
        max_flow = PIPES.set_index("DN").loc["KMR 100", "max_volumeFlow"]
        edge[cols.VOLUME_FLOW] = edge[cols.THERMAL_POWER_GLF] * max_flow / capacity
        assert calculate_glf(n + 137) * (power + 137 * building_power) < capacity
        result = expansion_potential(_net(edge), SOURCE, PIPES, building_power).iloc[0]
        assert result[cols.POTENTIAL_BUILDINGS] == 3

    @pytest.mark.parametrize("building_power", [0.0, -5.0, np.nan, np.inf])
    def test_rejects_an_invalid_building_power(self, building_power):
        with pytest.raises(ValueError):
            expansion_potential(_net(_edge((0, 0), (100, 0), 20, 300.0)), SOURCE, PIPES, building_power)

    def test_empty_net(self):
        empty = gpd.GeoDataFrame({cols.TYPE: []}, geometry=[], crs=CRS)
        result = expansion_potential(empty, SOURCE, PIPES, 15.0)
        assert result.empty
        assert list(result.columns) == [cols.EXPANDABLE_POWER, cols.POTENTIAL_BUILDINGS]

    def test_net_of_the_network_step(self):
        """Source → street → 3 buildings: fewer buildings the further from the source, none on house connections."""
        streets = gpd.GeoDataFrame(geometry=[LineString([(0, 0), (50, 0), (100, 0), (150, 0)])], crs=CRS)
        buildings = gpd.GeoDataFrame(
            {
                cols.THERMAL_POWER: [10.0, 20.0, 30.0],
                cols.CENTROID: [Point(x, 5) for x in (50, 100, 150)],
                cols.CONNECTION_POINT: [Point(x, 0) for x in (50, 100, 150)],
            },
            geometry=[Polygon([(x - 2, 4), (x + 2, 4), (x + 2, 6), (x - 2, 6)]) for x in (50, 100, 150)],
            crs=CRS,
        )
        source = gpd.GeoDataFrame(
            {cols.CONNECTION_POINT: [Point(0, 0)], cols.CENTROID: [Point(-5, 0)]}, geometry=[Point(-5, 0)], crs=CRS
        )
        graph = build_street_graph(streets, CRS)
        graph = connect_buildings_to_graph(graph, buildings)
        graph = connect_source_to_graph(graph, source)
        graph = add_edge_lengths(graph)
        net = compute_network(graph, buildings, source, PIPES, cols.THERMAL_POWER, SUPPLY, RETURN, CRS)

        result = expansion_potential(net, Point(-5, 0), PIPES, 15.0)
        house = net[cols.TYPE] == cols.EDGE_TYPE_HOUSE_CONNECTION
        assert result.loc[house].isna().all().all()
        route = result.loc[~house].assign(x=net.loc[~house].geometry.bounds["minx"]).sort_values("x")
        powers = route[cols.EXPANDABLE_POWER].tolist()
        assert powers == sorted(powers, reverse=True)
        assert route[cols.POTENTIAL_BUILDINGS].tolist() == [int(p // 15) for p in powers]
        # the last street pipe alone would take more than the pipes before it allow
        alone = expansion_potential(net.loc[[route.index[-1]]], Point(100, 0), PIPES, 15.0)
        assert alone[cols.EXPANDABLE_POWER].iloc[0] > powers[-1]
        assert mean_building_power(net) == pytest.approx(20.0)


class TestMeanBuildingPower:
    def test_mean_of_the_house_connections(self):
        street = _edge((0, 0), (50, 0), 3, 60.0)
        houses = [_edge((x, 0), (x, 10), 1, p, cols.EDGE_TYPE_HOUSE_CONNECTION) for x, p in ((10, 10.0), (20, 20.0), (30, 30.0))]
        assert mean_building_power(_net(street, *houses)) == pytest.approx(20.0)

    def test_none_without_house_connections(self):
        assert mean_building_power(_net(_edge((0, 0), (50, 0), 3, 60.0))) is None
