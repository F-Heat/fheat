"""Steiner backend: shortest total network on the Phase 0 street graph."""
from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import LineString, Point, box

from fheat_core import columns as cols
from fheat_core.config import FHeatConfig, NetworkMode
from fheat_core.network import SteinerBackend, get_backend
from fheat_core.schemas import NetSchema
from fheat_core.state import Phase, PipelineState
from fheat_core.steps import network as network_step
from tests.conftest import CRS, StubAdapter


def test_get_backend_steiner():
    assert isinstance(get_backend(NetworkMode.STEINER.value), SteinerBackend)


def _run(mode, parcels_gdf, pipe_info_df, temperature_series, landuse=None, path_weight=0.0):
    net = _state(mode, parcels_gdf, pipe_info_df, temperature_series, landuse, path_weight).net_gdf
    NetSchema.validate(net)
    return net


def _state(mode, parcels_gdf, pipe_info_df, temperature_series, landuse=None, path_weight=0.0):
    # Source near (0, 0). A sits at the end of the straight street, B at the end
    # of the diagonal one, and a 20 m link joins the two ends. Shortest paths
    # use both streets (~202 m); the shortest network is straight street + link
    # (120 m). C lies on a street the source cannot reach.
    streets = gpd.GeoDataFrame(
        {
            cols.ROUTABLE: 1,
            "geometry": [
                LineString([(0, 0), (100, 0)]),
                LineString([(0, 0), (100, 20)]),
                LineString([(100, 0), (100, 20)]),
                LineString([(200, 0), (300, 0)]),
            ],
        },
        crs=CRS,
    )
    buildings = gpd.GeoDataFrame(
        {
            cols.BUILDING_ID: [0, 1, 2],
            cols.CONNECT: 1,
            cols.HEAT_DEMAND: 20000.0,
            cols.THERMAL_POWER: 12.0,
            cols.FULL_LOAD_HOURS: 1600.0,
            cols.LOAD_PROFILE: "EFH",
            "geometry": [box(104, -3, 110, 3), box(104, 17, 110, 23), box(247, 5, 253, 11)],
        },
        crs=CRS,
    )
    source = gpd.GeoDataFrame({"geometry": [Point(-5, -5)]}, crs=CRS)
    adapter = StubAdapter(
        buildings, streets, parcels_gdf, source,
        pipe_info=pipe_info_df, temperature=temperature_series, holidays={},
    )
    state = PipelineState(
        phase=Phase.STATUS, buildings_gdf=buildings, streets_gdf=streets,
        parcels_gdf=parcels_gdf, source_gdf=source, landuse_gdf=landuse,
    )
    return network_step.run(state, FHeatConfig(network_mode=mode, steiner_path_weight=path_weight), adapter)


def _street_length(net):
    return net.loc[net[cols.TYPE] == cols.EDGE_TYPE_STREET, cols.LENGTH].sum()


def test_steiner_builds_shorter_network_than_phase0(parcels_gdf, pipe_info_df, temperature_series):
    phase0 = _run(NetworkMode.PHASE0.value, parcels_gdf, pipe_info_df, temperature_series)
    steiner = _run(NetworkMode.STEINER.value, parcels_gdf, pipe_info_df, temperature_series)

    assert _street_length(phase0) == pytest.approx(100 + (100**2 + 20**2) ** 0.5)
    assert _street_length(steiner) == pytest.approx(120.0)
    # A and B connected in both, unreachable C skipped in both
    for net in (phase0, steiner):
        assert (net[cols.TYPE] == cols.EDGE_TYPE_HOUSE_CONNECTION).sum() == 2


def test_steiner_avoids_expensive_civil_works(parcels_gdf, pipe_info_df, temperature_series):
    # factor 10 on the 20 m link: 20 m · (0.4 + 0.6 · 10) = 128 > the 102 m diagonal
    landuse = gpd.GeoDataFrame({cols.CIVIL_COST_FACTOR: [10.0]}, geometry=[box(98, 3, 102, 17)], crs=CRS)
    steiner = _run(NetworkMode.STEINER.value, parcels_gdf, pipe_info_df, temperature_series, landuse)

    assert _street_length(steiner) == pytest.approx(100 + (100**2 + 20**2) ** 0.5)
    assert "weight" not in steiner.columns


def test_path_weight_1_gives_every_building_its_shortest_route(parcels_gdf, pipe_info_df, temperature_series):
    steiner = _run(NetworkMode.STEINER.value, parcels_gdf, pipe_info_df, temperature_series, path_weight=1.0)
    assert _street_length(steiner) == pytest.approx(100 + (100**2 + 20**2) ** 0.5)


def test_path_weight_is_between_0_and_1():
    for bad in (-0.1, 1.1):
        with pytest.raises(ValueError, match="steiner_path_weight"):
            FHeatConfig(steiner_path_weight=bad)


def test_grow_tree_trades_length_against_route():
    # Source s, buildings a and b. a lies 10 out, b 10 past a: with c = 0 b hangs
    # off a (20 in total); its own direct edge from s costs 15.
    from fheat_core.network.steiner import grow_tree
    import networkx as nx

    G = nx.Graph([("s", "a"), ("a", "b"), ("s", "b")])
    cost = {}
    for (u, v), w in {("s", "a"): 10, ("a", "b"): 10, ("s", "b"): 15}.items():
        cost[u, v] = cost[v, u] = w
    def edges(c):
        return {frozenset(e) for e in grow_tree(G, cost, "s", {"a", "b"}, c)}
    assert edges(0.0) == {frozenset("sa"), frozenset("ab")}
    # c·10 + 10 > 15 from c = 0.5 on: b gets its own, shorter route
    assert edges(0.4) == {frozenset("sa"), frozenset("ab")}
    assert edges(0.6) == edges(1.0) == {frozenset("sa"), frozenset("sb")}
    # unreachable terminals are skipped
    G.add_node("x")
    assert len(grow_tree(G, cost, "s", {"a", "b", "x"}, 0.0)) == 2


def test_auto_path_weight_keeps_the_cheapest_net(parcels_gdf, pipe_info_df, temperature_series):
    priced = pipe_info_df.assign(**{
        "cost_main": [300.0, 350.0, 400.0, 500.0, 600.0, 800.0, 1000.0],
        "cost_h-connect": [200.0, 230.0, 260.0, 300.0, 350.0, 450.0, 550.0],
    })

    def total(mode, weight):
        return _run(mode, parcels_gdf, priced, temperature_series, path_weight=weight)[cols.PIPE_COST].sum()

    candidates = [total(NetworkMode.STEINER.value, w) for w in (0.0, 0.5, 1.0)]
    candidates.append(total(NetworkMode.PHASE0.value, None))
    assert total(NetworkMode.STEINER.value, None) == pytest.approx(min(candidates))


def test_auto_path_weight_without_pipe_costs_takes_the_shortest_net(parcels_gdf, pipe_info_df, temperature_series):
    state = _state(NetworkMode.STEINER.value, parcels_gdf, pipe_info_df, temperature_series, path_weight=None)
    assert _street_length(state.net_gdf) == pytest.approx(120.0)
    # the chosen weight is reported; 0 is the first weight that gives the shortest net
    assert state.network_analysis["path_weight"] == 0.0
    # a fixed weight reports none, it is in the config
    fixed = _state(NetworkMode.STEINER.value, parcels_gdf, pipe_info_df, temperature_series, path_weight=0.5)
    assert "path_weight" not in fixed.network_analysis


def test_auto_path_weight_is_the_default():
    assert FHeatConfig().steiner_path_weight is None
