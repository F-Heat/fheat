"""Tests for fheat_core.algorithms.network.

Covers:
- calculate_glf: simultaneity factor curve (BDEW-style fit)
- calculate_volumeflow: P_th → V̇ via density/cp interpolation
- calculate_diameter_velocity_loss: pipe sizing, velocity, U-value loss
- build_street_graph: streets → NetworkX nodes/edges
- connect_buildings_to_graph / connect_source_to_graph: Hausanschluss/Quellenanschluss edges
- add_edge_lengths: length attribute per edge
- compute_network: full shortest-path network producing the schema-conformant GeoDataFrame
"""
from __future__ import annotations

import math

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, Point, Polygon

from fheat_core import columns as cols
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


CRS = "EPSG:25832"


# ---------------------------------------------------------------------------
# calculate_glf
# ---------------------------------------------------------------------------


class TestCalculateGlf:
    """GLF: a + b / (1 + (n/c)^d) with a=0.4497, b=0.5512, c=53.8483, d=1.7627."""

    def test_glf_at_n_1_close_to_a_plus_b(self):
        # for n=1, (1/c)^d is tiny → glf ≈ a + b
        glf = calculate_glf(1)
        assert glf == pytest.approx(0.4497 + 0.5512, abs=0.001)

    def test_glf_large_n_approaches_a(self):
        glf = calculate_glf(100_000)
        assert glf == pytest.approx(0.4497, abs=0.001)

    def test_glf_monotonically_decreasing(self):
        values = [calculate_glf(n) for n in (1, 5, 10, 50, 100, 500, 1000)]
        for a, b in zip(values, values[1:]):
            assert a > b

    def test_glf_at_c_is_a_plus_half_b(self):
        """at n = c, (n/c)^d = 1 → glf = a + b/2."""
        glf = calculate_glf(53.8483)
        assert glf == pytest.approx(0.4497 + 0.5512 / 2, abs=1e-4)


# ---------------------------------------------------------------------------
# calculate_volumeflow
# ---------------------------------------------------------------------------


class TestCalculateVolumeflow:
    def test_volumeflow_zero_power_is_zero(self):
        assert calculate_volumeflow(0.0, 80, 50) == pytest.approx(0.0)

    def test_volumeflow_at_80_50(self):
        """V̇ = P / (ρ · cp · ΔT). Reference values at 80 °C: ρ≈0.97182, cp≈4.1963."""
        vf = calculate_volumeflow(100.0, 80, 50)
        expected = 100.0 / (0.97182 * 4.1963 * 30)
        assert vf == pytest.approx(expected, rel=1e-6)

    def test_volumeflow_scales_linearly_with_power(self):
        v1 = calculate_volumeflow(50.0, 80, 50)
        v2 = calculate_volumeflow(150.0, 80, 50)
        assert v2 == pytest.approx(3 * v1, rel=1e-9)

    def test_volumeflow_inversely_proportional_to_dt(self):
        v_small_dt = calculate_volumeflow(100.0, 80, 60)   # ΔT=20
        v_large_dt = calculate_volumeflow(100.0, 80, 40)   # ΔT=40
        # double ΔT → half flow (density/cp shift slightly so allow ~3 % tolerance)
        assert v_large_dt == pytest.approx(v_small_dt / 2, rel=0.03)


# ---------------------------------------------------------------------------
# calculate_diameter_velocity_loss
# ---------------------------------------------------------------------------


@pytest.fixture
def small_pipe_info():
    """Three-row pipe catalogue covering the start-index behaviour."""
    return pd.DataFrame(
        {
            "DN": [20, 25, 32, 40, 50],
            "di": [22.0, 28.0, 37.2, 43.1, 54.5],
            "U-Value": [0.20, 0.21, 0.23, 0.25, 0.27],
            "U-Value_extra_insulation": [0.13, 0.14, 0.15, 0.16, 0.17],
            "max_volumeFlow": [0.10, 0.20, 0.40, 0.70, 1.20],
        }
    )


class TestCalculateDiameterVelocityLoss:
    def test_hausanschluss_uses_full_catalogue(self, small_pipe_info):
        """Hausanschluss starts at index 0 — small flows pick small DN."""
        dn, vel, loss, loss_extra = calculate_diameter_velocity_loss(
            volumeflow=0.05, htemp=80, ltemp=50, length=10.0,
            pipe_info=small_pipe_info, edge_type="Hausanschluss",
        )
        assert dn == 20

    def test_strassenleitung_starts_at_index_2(self, small_pipe_info):
        """Non-Hausanschluss starts at index 2 → minimum DN is 32."""
        dn, *_ = calculate_diameter_velocity_loss(
            volumeflow=0.05, htemp=80, ltemp=50, length=10.0,
            pipe_info=small_pipe_info, edge_type="Straßenleitung",
        )
        assert dn == 32

    def test_idx_clamped_to_last_row(self, small_pipe_info):
        """Volume flow exceeding the largest max_volumeFlow → use last row."""
        dn, *_ = calculate_diameter_velocity_loss(
            volumeflow=99.0, htemp=80, ltemp=50, length=10.0,
            pipe_info=small_pipe_info, edge_type="Hausanschluss",
        )
        assert dn == 50  # last row

    def test_loss_formula(self, small_pipe_info):
        """loss = 8760 * 2 * U * (mtemp-10) * length / 1000."""
        _, _, loss, loss_extra = calculate_diameter_velocity_loss(
            volumeflow=0.05, htemp=80, ltemp=50, length=10.0,
            pipe_info=small_pipe_info, edge_type="Hausanschluss",
        )
        u = 0.20
        u_extra = 0.13
        K = (80 + 50) / 2 - 10  # 55
        expected = 8760 * 2 * u * K * 10.0 / 1000
        expected_extra = 8760 * 2 * u_extra * K * 10.0 / 1000
        assert loss == pytest.approx(expected, rel=1e-9)
        assert loss_extra == pytest.approx(expected_extra, rel=1e-9)
        assert loss_extra < loss  # extra insulation reduces loss

    def test_loss_proportional_to_length(self, small_pipe_info):
        _, _, loss10, _ = calculate_diameter_velocity_loss(
            0.05, 80, 50, 10.0, small_pipe_info, "Hausanschluss"
        )
        _, _, loss30, _ = calculate_diameter_velocity_loss(
            0.05, 80, 50, 30.0, small_pipe_info, "Hausanschluss"
        )
        assert loss30 == pytest.approx(3 * loss10, rel=1e-9)

    def test_velocity_formula(self, small_pipe_info):
        """v = volumeflow * 1000 / (π * (di/2)^2)."""
        dn, vel, *_ = calculate_diameter_velocity_loss(
            0.05, 80, 50, 10.0, small_pipe_info, "Hausanschluss"
        )
        di = 22.0
        expected = 0.05 * 1000 / (math.pi * (di / 2) ** 2)
        assert vel == pytest.approx(expected, rel=1e-9)


# ---------------------------------------------------------------------------
# build_street_graph
# ---------------------------------------------------------------------------


class TestBuildStreetGraph:
    def test_single_two_point_line(self):
        streets = gpd.GeoDataFrame(
            {"geometry": [LineString([(0, 0), (10, 0)])]},
            crs=CRS, geometry="geometry",
        )
        G = build_street_graph(streets, CRS)
        assert (0.0, 0.0) in G.nodes
        assert (10.0, 0.0) in G.nodes
        assert G.has_edge((0.0, 0.0), (10.0, 0.0))
        assert G.edges[(0.0, 0.0), (10.0, 0.0)]["type"] == "Straßenleitung"

    def test_polyline_creates_chain_of_edges(self):
        streets = gpd.GeoDataFrame(
            {"geometry": [LineString([(0, 0), (10, 0), (10, 10)])]},
            crs=CRS, geometry="geometry",
        )
        G = build_street_graph(streets, CRS)
        assert G.number_of_nodes() == 3
        assert G.number_of_edges() == 2

    def test_two_intersecting_streets_share_node(self):
        streets = gpd.GeoDataFrame(
            {"geometry": [
                LineString([(0, 0), (10, 0)]),
                LineString([(10, 0), (10, 10)]),
            ]},
            crs=CRS, geometry="geometry",
        )
        G = build_street_graph(streets, CRS)
        assert G.number_of_nodes() == 3
        assert G.has_edge((0, 0), (10, 0))
        assert G.has_edge((10, 0), (10, 10))


# ---------------------------------------------------------------------------
# connect_buildings_to_graph / connect_source_to_graph
# ---------------------------------------------------------------------------


class TestConnectToGraph:
    def test_buildings_get_hausanschluss_edges(self):
        G = nx.Graph()
        G.add_edge((0, 0), (10, 0), type="Straßenleitung")
        bld = gpd.GeoDataFrame(
            {
                cols.CENTROID:[Point(5, 5)],
                cols.CONNECTION_POINT: [Point(5, 0)],
                "geometry": [Point(5, 5)],
            },
            crs=CRS, geometry="geometry",
        )
        G2 = connect_buildings_to_graph(G, bld)
        assert G2.has_edge((5.0, 5.0), (5.0, 0.0))
        assert G2.edges[(5.0, 5.0), (5.0, 0.0)]["type"] == "Hausanschluss"

    def test_building_with_nan_anschlusspunkt_skipped(self):
        G = nx.Graph()
        G.add_edge((0, 0), (10, 0), type="Straßenleitung")
        bld = gpd.GeoDataFrame(
            {
                cols.CENTROID:[Point(5, 5)],
                cols.CONNECTION_POINT: [float("nan")],
                "geometry": [Point(5, 5)],
            },
            crs=CRS, geometry="geometry",
        )
        n_edges_before = G.number_of_edges()
        G2 = connect_buildings_to_graph(G, bld)
        assert G2.number_of_edges() == n_edges_before

    def test_source_gets_quellenanschluss_edge(self):
        G = nx.Graph()
        G.add_edge((0, 0), (10, 0), type="Straßenleitung")
        src = gpd.GeoDataFrame(
            {
                cols.CONNECTION_POINT: [Point(0, 0)],
                "geometry": [Point(-5, 0)],
            },
            crs=CRS, geometry="geometry",
        )
        G2 = connect_source_to_graph(G, src)
        assert G2.has_edge((-5.0, 0.0), (0.0, 0.0))
        assert G2.edges[(-5.0, 0.0), (0.0, 0.0)]["type"] == "Quellenanschluss"


# ---------------------------------------------------------------------------
# add_edge_lengths
# ---------------------------------------------------------------------------


class TestAddEdgeLengths:
    def test_lengths_computed_from_node_coords(self):
        G = nx.Graph()
        G.add_edge((0, 0), (3, 4))     # 5
        G.add_edge((0, 0), (10, 0))    # 10
        G2 = add_edge_lengths(G)
        assert G2.edges[(0, 0), (3, 4)][cols.LENGTH] == pytest.approx(5.0)
        assert G2.edges[(0, 0), (10, 0)][cols.LENGTH] == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# compute_network — integration test
# ---------------------------------------------------------------------------


class TestComputeNetwork:
    """Tiny end-to-end network: source → street → 2 buildings."""

    def _scenario(self):
        streets = gpd.GeoDataFrame(
            {"geometry": [LineString([(0, 0), (50, 0), (100, 0)])]},
            crs=CRS, geometry="geometry",
        )
        # two building centroids 5 m above the street, with explicit Anschlusspunkt
        bld = gpd.GeoDataFrame(
            {
                cols.THERMAL_POWER: [10.0, 20.0],
                cols.CENTROID:[Point(50, 5), Point(100, 5)],
                cols.CONNECTION_POINT: [Point(50, 0), Point(100, 0)],
                "geometry": [Polygon([(48, 4), (52, 4), (52, 6), (48, 6)]),
                             Polygon([(98, 4), (102, 4), (102, 6), (98, 6)])],
            },
            crs=CRS, geometry="geometry",
        )
        src = gpd.GeoDataFrame(
            {
                cols.CONNECTION_POINT: [Point(0, 0)],
                cols.CENTROID:[Point(0, 0)],
                "geometry": [Point(0, 0)],
            },
            crs=CRS, geometry="geometry",
        )

        G = build_street_graph(streets, CRS)
        G = connect_buildings_to_graph(G, bld)
        G = connect_source_to_graph(G, src)
        G = add_edge_lengths(G)
        return G, bld, src

    def test_compute_network_columns_and_dtypes(self, small_pipe_info):
        G, bld, src = self._scenario()
        net = compute_network(
            G, bld, src, small_pipe_info,
            power_att=cols.THERMAL_POWER, htemp=80, ltemp=50, crs=CRS,
        )
        for col in (
            cols.TYPE, cols.LENGTH, cols.THERMAL_POWER, cols.N_BUILDINGS,
            cols.THERMAL_POWER_GLF, cols.VOLUME_FLOW, cols.NOMINAL_DIAMETER,
            cols.VELOCITY, cols.HEAT_LOSS,
            cols.HEAT_LOSS_EXTRA_INSULATION,
        ):
            assert col in net.columns, col
        assert isinstance(net, gpd.GeoDataFrame)
        assert (net.geometry.geom_type == "LineString").all()

    def test_compute_network_aggregates_power(self, small_pipe_info):
        """The first street segment carries power for both buildings."""
        G, bld, src = self._scenario()
        net = compute_network(
            G, bld, src, small_pipe_info,
            power_att=cols.THERMAL_POWER, htemp=80, ltemp=50, crs=CRS,
        )
        # at least one Strassenleitung edge must carry the full 30 kW
        sl = net[net[cols.TYPE] == "Straßenleitung"]
        assert sl[cols.THERMAL_POWER].max() == pytest.approx(30.0)

    def test_compute_network_glf_applied(self, small_pipe_info):
        """GLF strictly < 1 for segments aggregating ≥ 2 buildings.

        Note: the BDEW fit gives GLF ≈ 1.0004 at n=1 (slightly > 1), so the
        check only applies to Straßenleitung segments where multiple buildings
        share a pipe.
        """
        G, bld, src = self._scenario()
        net = compute_network(
            G, bld, src, small_pipe_info,
            power_att=cols.THERMAL_POWER, htemp=80, ltemp=50, crs=CRS,
        )
        aggregated = net[net[cols.N_BUILDINGS] >= 2]
        assert (aggregated[cols.THERMAL_POWER_GLF] < aggregated[cols.THERMAL_POWER]).all()
        assert (aggregated[cols.GLF] < 1.0).all()

    def test_compute_network_loss_extra_smaller(self, small_pipe_info):
        G, bld, src = self._scenario()
        net = compute_network(
            G, bld, src, small_pipe_info,
            power_att=cols.THERMAL_POWER, htemp=80, ltemp=50, crs=CRS,
        )
        assert (
            net[cols.HEAT_LOSS_EXTRA_INSULATION]
            < net[cols.HEAT_LOSS] + 1e-9
        ).all()

    def test_compute_network_total_length_matches_street_plus_branches(
        self, small_pipe_info
    ):
        G, bld, src = self._scenario()
        net = compute_network(
            G, bld, src, small_pipe_info,
            power_att=cols.THERMAL_POWER, htemp=80, ltemp=50, crs=CRS,
        )
        # 100 m street + 2 × 5 m Hausanschluss = 110 m
        assert net[cols.LENGTH].sum() == pytest.approx(110.0, rel=1e-9)
