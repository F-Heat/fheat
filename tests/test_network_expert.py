"""Tests for the expert network mode (topotherm STS backend).

Almost everything here runs without topotherm installed: the
backend's mapping steps are static methods, so they are exercised against a
synthetic topotherm result. Only the tests that actually solve a MILP need the
extra, and they skip via the :func:`tt` fixture.
"""
from __future__ import annotations

import builtins
import subprocess
import sys
import warnings

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Point

from fheat_core import columns as cols
from fheat_core.algorithms.network import calculate_glf
from fheat_core.config import FHeatConfig, NetworkMode, TopothermConfig
from fheat_core.network import DijkstraBackend, get_backend
from fheat_core.network.base import (
    EMPTY_NETWORK,
    NO_ROUTABLE_STREETS,
    SOLVER_UNAVAILABLE,
    SOURCE_ON_STREET,
    TOPOTHERM_UNAVAILABLE,
    NetworkBackend,
    NetworkBackendError,
)
from fheat_core.network.topotherm_backend import (
    TopothermBackend,
    _as_2d_float,
    _require_topotherm,
)
from fheat_core.resources import load_pipe_info
from fheat_core.schemas import NetSchema
from fheat_core.state import Phase, PipelineState
from fheat_core.steps import network as network_step
from tests.conftest import CRS, StubAdapter


# ---------------------------------------------------------------------------
# Config — no topotherm needed
# ---------------------------------------------------------------------------


def test_network_mode_defaults_to_phase0():
    config = FHeatConfig()
    assert config.network_mode == NetworkMode.PHASE0.value
    assert config.topotherm is None


def test_expert_mode_creates_default_topotherm_config():
    config = FHeatConfig(network_mode=NetworkMode.EXPERT.value)
    assert isinstance(config.topotherm, TopothermConfig)
    assert config.topotherm.optimization_mode == "economic"


def test_expert_mode_keeps_explicit_topotherm_config():
    tcfg = TopothermConfig(optimization_mode="forced", solver="highs")
    config = FHeatConfig(network_mode=NetworkMode.EXPERT.value, topotherm=tcfg)
    assert config.topotherm is tcfg
    assert config.topotherm.optimization_mode == "forced"


def test_enum_member_is_accepted_as_network_mode():
    """``NetworkMode.EXPERT`` and its ``.value`` must behave identically.

    ``NetworkMode`` is a str-mixin enum, so the member hashes and compares
    equal to its value — users may pass either form.
    """
    config = FHeatConfig(network_mode=NetworkMode.EXPERT)
    assert config.network_mode == NetworkMode.EXPERT.value
    assert isinstance(config.topotherm, TopothermConfig)
    assert get_backend(config.network_mode).name == "expert"


def test_invalid_network_mode_raises():
    with pytest.raises(ValueError, match="network_mode"):
        FHeatConfig(network_mode="dijkstra")


def test_invalid_optimization_mode_raises():
    with pytest.raises(ValueError, match="optimization_mode"):
        TopothermConfig(optimization_mode="cheapest")


@pytest.mark.parametrize(
    "kwargs, match",
    [
        ({"mip_gap": -1e-3}, "mip_gap"),
        ({"time_limit": 0}, "time_limit"),
        ({"connection_buffer": 0.0}, "connection_buffer"),
    ],
)
def test_topotherm_config_rejects_invalid_numbers(kwargs, match):
    with pytest.raises(ValueError, match=match):
        TopothermConfig(**kwargs)


# ---------------------------------------------------------------------------
# Registry — phase 0 must work without the optional dependency
# ---------------------------------------------------------------------------


def test_get_backend_phase0_without_topotherm_installed():
    backend = get_backend("phase0")
    assert isinstance(backend, DijkstraBackend)
    assert backend.name == "phase0"


def test_get_backend_unknown_mode_raises():
    with pytest.raises(ValueError, match="Unknown network_mode"):
        get_backend("nope")


# ---------------------------------------------------------------------------
# Expert mode — requires topotherm itself (not just the [topotherm] extra,
# which ships only the solver and the pandas pin; see pyproject.toml)
# ---------------------------------------------------------------------------


@pytest.fixture
def tt():
    """The topotherm module, or skip the test.

    Deliberately *not* ``pytest.importorskip``: that only catches ImportError,
    while topotherm 0.6.0 raises **SyntaxError** on Python < 3.12 (its PEP 701
    f-string). pip happily installs it there — topotherm's own metadata claims
    ``requires-python = ">=3.10"`` — so an installed-but-unimportable
    topotherm is a real state, and it must skip rather than fail.
    """
    try:
        import topotherm
    except (ImportError, SyntaxError) as exc:
        pytest.skip(f"topotherm not usable on this interpreter: {exc}")
    pytest.importorskip("pyomo")
    return topotherm


@pytest.fixture
def source_off_street():
    """Heat source clear of the street geometry (see the on-street blocker)."""
    return gpd.GeoDataFrame(
        {"geometry": [Point(-10, -15)]},
        crs=CRS,
        geometry="geometry",
    )


@pytest.fixture
def expert_state(buildings_gdf, streets_gdf, parcels_gdf, source_off_street):
    return PipelineState(
        phase=Phase.STATUS,
        buildings_gdf=buildings_gdf,
        streets_gdf=streets_gdf,
        parcels_gdf=parcels_gdf,
        source_gdf=source_off_street,
    )


@pytest.fixture
def expert_adapter(buildings_gdf, streets_gdf, parcels_gdf, source_off_street,
                   pipe_info_df, temperature_series):
    return StubAdapter(
        buildings_gdf, streets_gdf, parcels_gdf, source_off_street,
        pipe_info=pipe_info_df, temperature=temperature_series, holidays={},
    )


def _forced_config():
    return FHeatConfig(
        supply_temperature=80.0,
        return_temperature=50.0,
        network_mode=NetworkMode.EXPERT.value,
        topotherm=TopothermConfig(optimization_mode="forced"),
    )


@pytest.fixture
def solved_expert_net(tt, expert_state, expert_adapter):
    state = network_step.run(expert_state, _forced_config(), expert_adapter)
    return state


def test_expert_net_satisfies_net_schema(solved_expert_net):
    net = solved_expert_net.net_gdf
    NetSchema.validate(net)
    expected = {
        "geometry",
        cols.TYPE,
        cols.LENGTH,
        cols.THERMAL_POWER,
        cols.N_BUILDINGS,
        cols.GLF,
        cols.THERMAL_POWER_GLF,
        cols.VOLUME_FLOW,
        cols.NOMINAL_DIAMETER,
        cols.VELOCITY,
        cols.HEAT_LOSS,
        cols.HEAT_LOSS_EXTRA_INSULATION,
        # written by the network step for every backend
        cols.CIVIL_COST_FACTOR,
        cols.ROAD_SURFACE,
        cols.PIPE_COST,
        cols.CIVIL_COST,
    }
    assert expected == set(net.columns)
    assert not net.empty
    assert solved_expert_net.phase == Phase.NETWORK


def test_expert_net_geometry_and_types(solved_expert_net):
    net = solved_expert_net.net_gdf
    assert set(net.geometry.geom_type.unique()) == {"LineString"}
    assert set(net[cols.TYPE].unique()) <= {"Hausanschluss", "Straßenleitung"}
    assert (net[cols.LENGTH] > 0).all()
    # DN is a catalogue label, not a number ("PEX 50" in the shipped catalogue)
    assert net[cols.NOMINAL_DIAMETER].notna().all()
    assert (net[cols.VELOCITY] > 0).all()


def test_glf_is_applied_after_optimisation(solved_expert_net):
    """thermal_power stays undiversified; glf kicks in on shared edges."""
    net = solved_expert_net.net_gdf
    # calculate_glf(1) is the maximum of the curve — and marginally above 1.0
    glf_single = calculate_glf(1)
    assert (net[cols.GLF] > 0).all()
    assert (net[cols.GLF] <= glf_single).all()
    # thermal_power_glf == thermal_power * glf, elementwise
    assert (
        (net[cols.THERMAL_POWER_GLF] - net[cols.THERMAL_POWER] * net[cols.GLF])
        .abs()
        .max()
        < 1e-9
    )
    # single-building edges are exactly the undiversified case
    single = net[net[cols.N_BUILDINGS] == 1]
    if not single.empty:
        assert (single[cols.GLF] - glf_single).abs().max() < 1e-12
    # edges carrying more than one building must be diversified
    shared = net[net[cols.N_BUILDINGS] > 1]
    if not shared.empty:
        assert (shared[cols.GLF] < glf_single).all()
        assert (
            shared[cols.THERMAL_POWER_GLF] < shared[cols.THERMAL_POWER] * glf_single
        ).all()


def test_forced_mode_connects_all_buildings(solved_expert_net, buildings_gdf):
    connected = solved_expert_net.buildings_gdf[cols.CONNECT]
    assert int(connected.sum()) == len(buildings_gdf)


def test_source_on_street_raises_actionable_error(
    tt, buildings_gdf, streets_gdf, parcels_gdf, source_gdf, pipe_info_df,
    temperature_series,
):
    """The conftest source_gdf sits exactly on the street start — blocker 3."""
    adapter = StubAdapter(
        buildings_gdf, streets_gdf, parcels_gdf, source_gdf,
        pipe_info=pipe_info_df, temperature=temperature_series, holidays={},
    )
    state = PipelineState(
        phase=Phase.STATUS,
        buildings_gdf=buildings_gdf,
        streets_gdf=streets_gdf,
        parcels_gdf=parcels_gdf,
        source_gdf=source_gdf,
    )
    with pytest.raises(NetworkBackendError, match="lies exactly on the street network") as excinfo:
        network_step.run(state, _forced_config(), adapter)
    assert excinfo.value.code == SOURCE_ON_STREET


def test_economic_mode_without_profitability_names_the_knobs(
    tt, expert_state, expert_adapter
):
    """Heat price far below production cost — nothing is worth building."""
    config = FHeatConfig(
        network_mode=NetworkMode.EXPERT.value,
        topotherm=TopothermConfig(
            optimization_mode="economic",
            heat_price=1e-6,
            source_price=10.0,
            pipes_c_irr=0.5,
        ),
    )
    with pytest.raises(NetworkBackendError, match="empty network") as excinfo:
        network_step.run(expert_state, config, expert_adapter)
    assert excinfo.value.code == EMPTY_NETWORK


def test_economic_mode_with_profitability_connects_buildings(
    tt, expert_state, expert_adapter
):
    config = FHeatConfig(
        network_mode=NetworkMode.EXPERT.value,
        topotherm=TopothermConfig(
            optimization_mode="economic",
            heat_price=10.0,
            source_price=1e-3,
            pipes_c_irr=0.01,
        ),
    )
    state = network_step.run(expert_state, config, expert_adapter)
    NetSchema.validate(state.net_gdf)
    assert int(state.buildings_gdf[cols.CONNECT].sum()) >= 1


# ---------------------------------------------------------------------------
# Phase 0 must be unaffected by the dispatcher rewrite
# ---------------------------------------------------------------------------


def test_phase0_dispatch_leaves_buildings_frame_untouched(
    buildings_gdf, streets_gdf, parcels_gdf, source_gdf, stub_adapter
):
    state = PipelineState(
        phase=Phase.STATUS,
        buildings_gdf=buildings_gdf,
        streets_gdf=streets_gdf,
        parcels_gdf=parcels_gdf,
        source_gdf=source_gdf,
    )
    out = network_step.run(state, FHeatConfig(), stub_adapter)

    NetSchema.validate(out.net_gdf)
    assert out.phase == Phase.NETWORK
    # the original frame object survives: no helper columns, no dropped rows
    assert out.buildings_gdf is buildings_gdf
    assert cols.CENTROID not in out.buildings_gdf.columns
    assert cols.CONNECTION_POINT not in out.buildings_gdf.columns
    assert len(out.buildings_gdf) == 3


def test_phase0_never_imports_topotherm():
    """The lazy import is the reason the core runs without the extra.

    Checked in a subprocess so the result holds even in an environment where
    topotherm *is* installed and another test has already imported it.
    """
    code = (
        "import sys\n"
        "from fheat_core.network import get_backend\n"
        "assert 'topotherm' not in sys.modules, 'imported at module level'\n"
        "get_backend('phase0')\n"
        "assert 'topotherm' not in sys.modules, 'imported by the phase0 branch'\n"
        # even resolving the expert backend must not pull the package in
        "get_backend('expert')\n"
        "assert 'fheat_core.network.topotherm_backend' in sys.modules\n"
        "assert 'topotherm' not in sys.modules, 'imported by get_backend'\n"
        "print('ok')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr
    assert "ok" in proc.stdout


def test_expert_backend_resolves_without_topotherm_installed(monkeypatch):
    """``get_backend('expert')`` works; only ``build()`` needs the package."""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "topotherm":
            raise ImportError("No module named 'topotherm'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    backend = get_backend("expert")
    assert backend.name == "expert"
    with pytest.raises(NetworkBackendError, match=r"git\+https://github\.com/jylambert/topotherm") as excinfo:
        _require_topotherm()
    assert excinfo.value.code == TOPOTHERM_UNAVAILABLE


def test_require_topotherm_explains_the_python_version_blocker(monkeypatch):
    """topotherm 0.6.0 uses PEP 701 f-strings — a SyntaxError below 3.12."""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "topotherm":
            raise SyntaxError("invalid syntax")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(NetworkBackendError, match="requires Python 3.12") as excinfo:
        _require_topotherm()
    assert excinfo.value.code == TOPOTHERM_UNAVAILABLE


# ---------------------------------------------------------------------------
# _as_2d_float — the object-dtype matrices topotherm hands back
# ---------------------------------------------------------------------------


def test_as_2d_float_normalises_object_array_of_scalars():
    arr = np.empty(3, dtype=object)
    arr[:] = [10.0, 15.0, 20.0]
    out = _as_2d_float(arr)
    assert out.shape == (3, 1)
    assert out.dtype == float
    assert out.ravel().tolist() == [10.0, 15.0, 20.0]


def test_as_2d_float_normalises_object_array_of_rows():
    arr = np.empty(2, dtype=object)
    arr[:] = [np.array([1.0, 2.0]), np.array([3.0, 4.0])]
    out = _as_2d_float(arr)
    assert out.shape == (2, 2)
    assert out.tolist() == [[1.0, 2.0], [3.0, 4.0]]


@pytest.mark.parametrize(
    "value, shape",
    [
        (np.array([1.0, 2.0, 3.0]), (3, 1)),          # 1-D float
        (np.array([[1.0, 2.0], [3.0, 4.0]]), (2, 2)),  # already 2-D
    ],
)
def test_as_2d_float_passes_numeric_arrays_through(value, shape):
    out = _as_2d_float(value)
    assert out.shape == shape
    assert out.dtype == float


# ---------------------------------------------------------------------------
# _to_net_gdf — topology to NetSchema, without needing a solver
# ---------------------------------------------------------------------------
# A synthetic topotherm result, shaped exactly like postprocessing.to_dataframe:
#
#     0 ──e0──▶ 1 ──e1──▶ 2 ──e3──▶ 4 (sink)
#               │         └──e4──▶ 5 (sink)
#               └──e2──▶ 3 (sink)
#
# Downstream sink counts: e0 → 3, e1 → 2, e2/e3/e4 → 1.


_NODE_XY = {
    0: (0.0, 0.0),      # source
    1: (100.0, 0.0),    # internal
    2: (200.0, 0.0),    # internal
    3: (100.0, 50.0),   # sink
    4: (200.0, 50.0),   # sink
    5: (300.0, 0.0),    # sink
}
_EDGES = [
    # start, end, power [kW], to_consumer
    (0, 1, 45.0, False),
    (1, 2, 35.0, False),
    (1, 3, 10.0, True),
    (2, 4, 15.0, True),
    (2, 5, 20.0, True),
]
_EXPECTED_N_BUILDINGS = [3, 2, 1, 1, 1]


@pytest.fixture
def fake_nodes_df():
    types = ["source", "internal", "internal", "sink", "sink", "sink"]
    return pd.DataFrame(
        {
            "type_": types,
            "x": [_NODE_XY[i][0] for i in range(6)],
            "y": [_NODE_XY[i][1] for i in range(6)],
        },
        index=range(6),
    )


@pytest.fixture
def fake_edges_df():
    rows = []
    for start, end, power, to_consumer in _EDGES:
        (xs, ys), (xe, ye) = _NODE_XY[start], _NODE_XY[end]
        rows.append(
            {
                "start_node": start,
                "end_node": end,
                "x_start": xs,
                "y_start": ys,
                "x_end": xe,
                "y_end": ye,
                "length": float(np.hypot(xe - xs, ye - ys)),
                "power": power,
                "to_consumer": to_consumer,
            }
        )
    return pd.DataFrame(rows)


def test_to_net_gdf_works_with_the_shipped_string_dn_catalogue(
    fake_edges_df, fake_nodes_df, buildings_gdf
):
    """Regression: fheat's catalogue labels DN "PEX 50"/"KMR 100", not a number.

    Coercing that column to float crashed the real Burgsteinfurt run.
    """
    pipe_info = load_pipe_info()
    # dtype-agnostic on purpose: pandas 2 reads this as object, pandas 3 as
    # StringDtype. What matters is that DN is *not* numeric.
    assert not pd.api.types.is_numeric_dtype(pipe_info["DN"]), (
        "fixture assumes non-numeric DN labels"
    )

    net = TopothermBackend._to_net_gdf(
        fake_edges_df, fake_nodes_df, buildings_gdf, pipe_info, FHeatConfig()
    )

    NetSchema.validate(net)
    assert net[cols.NOMINAL_DIAMETER].notna().all()
    assert all(isinstance(v, str) for v in net[cols.NOMINAL_DIAMETER])
    assert set(net[cols.NOMINAL_DIAMETER]) <= set(pipe_info["DN"])


def test_to_net_gdf_counts_downstream_buildings(
    fake_edges_df, fake_nodes_df, buildings_gdf, pipe_info_df
):
    net = TopothermBackend._to_net_gdf(
        fake_edges_df, fake_nodes_df, buildings_gdf, pipe_info_df, FHeatConfig()
    )
    assert net[cols.N_BUILDINGS].tolist() == _EXPECTED_N_BUILDINGS
    # GLF follows straight from that count
    assert net[cols.GLF].tolist() == [calculate_glf(n) for n in _EXPECTED_N_BUILDINGS]


def test_to_net_gdf_keeps_power_undiversified(
    fake_edges_df, fake_nodes_df, buildings_gdf, pipe_info_df
):
    """thermal_power is topotherm's flow as-is; the GLF only feeds *_glf."""
    net = TopothermBackend._to_net_gdf(
        fake_edges_df, fake_nodes_df, buildings_gdf, pipe_info_df, FHeatConfig()
    )
    assert net[cols.THERMAL_POWER].tolist() == [e[2] for e in _EDGES]
    expected_glf = [p * calculate_glf(n) for (_, _, p, _), n in
                    zip(_EDGES, _EXPECTED_N_BUILDINGS)]
    assert net[cols.THERMAL_POWER_GLF].tolist() == pytest.approx(expected_glf)
    # the shared trunk really is diversified relative to the raw flow
    assert net[cols.THERMAL_POWER_GLF].iloc[0] < net[cols.THERMAL_POWER].iloc[0]


def test_to_net_gdf_maps_edge_type_and_geometry(
    fake_edges_df, fake_nodes_df, buildings_gdf, pipe_info_df
):
    net = TopothermBackend._to_net_gdf(
        fake_edges_df, fake_nodes_df, buildings_gdf, pipe_info_df, FHeatConfig()
    )
    assert net[cols.TYPE].tolist() == [
        "Hausanschluss" if e[3] else "Straßenleitung" for e in _EDGES
    ]
    assert net.crs == buildings_gdf.crs
    first = net.geometry.iloc[0]
    assert list(first.coords) == [_NODE_XY[0], _NODE_XY[1]]
    assert net[cols.LENGTH].tolist() == pytest.approx(
        fake_edges_df["length"].tolist()
    )


def test_expert_net_exports_with_german_labels(
    fake_edges_df, fake_nodes_df, buildings_gdf, pipe_info_df
):
    """The export boundary needs no special-casing for the expert mode."""
    net = TopothermBackend._to_net_gdf(
        fake_edges_df, fake_nodes_df, buildings_gdf, pipe_info_df, FHeatConfig()
    )
    labelled = cols.to_display(net)
    for label in ("Typ", "Laenge [m]", "GLF", "DN [mm]", "Verlust [kWh/a]",
                  "Verlust bei extra Daemmung [kWh/a]"):
        assert label in labelled.columns


def test_net_schema_still_validates_without_the_optional_glf_column(
    fake_edges_df, fake_nodes_df, buildings_gdf, pipe_info_df
):
    """``glf`` is optional, so externally produced nets keep validating."""
    net = TopothermBackend._to_net_gdf(
        fake_edges_df, fake_nodes_df, buildings_gdf, pipe_info_df, FHeatConfig()
    )
    NetSchema.validate(net.drop(columns=[cols.GLF]))


# ---------------------------------------------------------------------------
# _to_topotherm_inputs — the FHeat → topotherm column contract
# ---------------------------------------------------------------------------


def test_to_topotherm_inputs_maps_columns_undiversified(
    buildings_gdf, streets_gdf, source_off_street
):
    sinks, roads, srcs = TopothermBackend._to_topotherm_inputs(
        buildings_gdf, streets_gdf, source_off_street
    )
    assert sinks["ts_0"].tolist() == buildings_gdf[cols.THERMAL_POWER].tolist()
    assert sinks["flh_0"].tolist() == buildings_gdf[cols.FULL_LOAD_HOURS].tolist()
    assert sinks.crs == buildings_gdf.crs
    assert list(roads.columns) == ["geometry"]
    assert list(srcs.columns) == ["geometry"]


def test_to_topotherm_inputs_filters_non_routable_streets(
    buildings_gdf, source_off_street, crs
):
    from shapely.geometry import LineString

    streets = gpd.GeoDataFrame(
        {
            cols.ROUTABLE: [1, 0],
            "geometry": [
                LineString([(-10, -5), (200, -5)]),
                LineString([(-10, -60), (200, -60)]),
            ],
        },
        crs=crs,
        geometry="geometry",
    )
    _, roads, _ = TopothermBackend._to_topotherm_inputs(
        buildings_gdf, streets, source_off_street
    )
    assert len(roads) == 1


def test_to_topotherm_inputs_rejects_an_empty_street_frame(
    buildings_gdf, source_off_street, crs
):
    from shapely.geometry import LineString

    streets = gpd.GeoDataFrame(
        {cols.ROUTABLE: [0], "geometry": [LineString([(-10, -5), (200, -5)])]},
        crs=crs,
        geometry="geometry",
    )
    with pytest.raises(NetworkBackendError, match="No routable streets") as excinfo:
        TopothermBackend._to_topotherm_inputs(buildings_gdf, streets, source_off_street)
    assert excinfo.value.code == NO_ROUTABLE_STREETS


def test_to_topotherm_inputs_rejects_a_source_on_the_street(
    buildings_gdf, streets_gdf, source_gdf
):
    """Blocker 3, at unit level — runs without the optional dependency."""
    with pytest.raises(NetworkBackendError, match="lies exactly on the street network") as excinfo:
        TopothermBackend._to_topotherm_inputs(buildings_gdf, streets_gdf, source_gdf)
    assert excinfo.value.code == SOURCE_ON_STREET


def test_to_topotherm_inputs_reprojects_the_source(
    buildings_gdf, streets_gdf, source_off_street
):
    source_wgs84 = source_off_street.to_crs("EPSG:4326")
    _, _, srcs = TopothermBackend._to_topotherm_inputs(
        buildings_gdf, streets_gdf, source_wgs84
    )
    assert srcs.crs == buildings_gdf.crs
    assert srcs.geometry.iloc[0].distance(source_off_street.geometry.iloc[0]) < 1e-6


# ---------------------------------------------------------------------------
# _writeback_connect — economic mode deselecting buildings
# ---------------------------------------------------------------------------


def _sink_nodes_at(points):
    return pd.DataFrame(
        {
            "type_": ["sink"] * len(points),
            "x": [p[0] for p in points],
            "y": [p[1] for p in points],
        }
    )


def test_writeback_connect_clears_unconnected_buildings(buildings_gdf):
    """Only the buildings whose centroid is a sink node stay connected."""
    centroids = buildings_gdf.geometry.centroid
    kept = [(centroids.iloc[0].x, centroids.iloc[0].y),
            (centroids.iloc[2].x, centroids.iloc[2].y)]

    out = TopothermBackend._writeback_connect(
        buildings_gdf, edges_df=None, nodes_df=_sink_nodes_at(kept)
    )
    assert out[cols.CONNECT].tolist() == [1, 0, 1]
    # the input frame is not mutated
    assert buildings_gdf[cols.CONNECT].tolist() == [1, 1, 1]
    assert list(out.index) == list(buildings_gdf.index)


def test_writeback_connect_keeps_all_when_every_centroid_matches(buildings_gdf):
    centroids = buildings_gdf.geometry.centroid
    allpts = list(zip(centroids.x, centroids.y))
    out = TopothermBackend._writeback_connect(
        buildings_gdf, edges_df=None, nodes_df=_sink_nodes_at(allpts)
    )
    assert out[cols.CONNECT].tolist() == [1, 1, 1]


def test_writeback_connect_rejects_an_empty_sink_set(buildings_gdf):
    nodes_df = pd.DataFrame({"type_": ["source"], "x": [0.0], "y": [0.0]})
    with pytest.raises(NetworkBackendError, match="no building was connected") as excinfo:
        TopothermBackend._writeback_connect(
            buildings_gdf, edges_df=None, nodes_df=nodes_df
        )
    assert excinfo.value.code == EMPTY_NETWORK


# ---------------------------------------------------------------------------
# _merge_connect — the dispatcher writing a backend decision back
# ---------------------------------------------------------------------------


def _minimal_net(crs):
    from shapely.geometry import LineString

    return gpd.GeoDataFrame(
        {
            cols.TYPE: ["Straßenleitung"],
            cols.LENGTH: [10.0],
            cols.THERMAL_POWER: [10.0],
            cols.N_BUILDINGS: [1],
            cols.THERMAL_POWER_GLF: [10.0],
            cols.VOLUME_FLOW: [0.1],
            cols.NOMINAL_DIAMETER: ["PEX 20"],
            cols.VELOCITY: [0.5],
            cols.HEAT_LOSS: [100.0],
            cols.HEAT_LOSS_EXTRA_INSULATION: [80.0],
        },
        geometry=[LineString([(0, 0), (10, 0)])],
        crs=crs,
    )


class _DroppingBackend(NetworkBackend):
    """Stub expert-style backend: deselects the last building it is given."""

    name = "stub"

    def build(self, buildings, streets, source, config, adapter, civil_layers=None):
        out = buildings.copy()
        connect = np.ones(len(out), dtype=np.int64)
        connect[-1] = 0
        out[cols.CONNECT] = connect
        return _minimal_net(buildings.crs), out


@pytest.fixture
def dropping_backend(monkeypatch):
    monkeypatch.setattr(network_step, "get_backend", lambda mode: _DroppingBackend())


def _state_with(buildings, streets, parcels, source):
    return PipelineState(
        phase=Phase.STATUS,
        buildings_gdf=buildings,
        streets_gdf=streets,
        parcels_gdf=parcels,
        source_gdf=source,
    )


def test_merge_connect_does_not_reconnect_pre_excluded_buildings(
    buildings_gdf, streets_gdf, parcels_gdf, source_gdf, stub_adapter, dropping_backend
):
    """A building excluded before the step must stay excluded afterwards."""
    buildings = buildings_gdf.copy()
    buildings.loc[1, cols.CONNECT] = 0          # excluded up front
    state = _state_with(buildings, streets_gdf, parcels_gdf, source_gdf)

    out = network_step.run(state, FHeatConfig(), stub_adapter)

    # backend saw rows 0 and 2 and dropped the last of them
    assert out.buildings_gdf[cols.CONNECT].tolist() == [1, 0, 0]
    assert len(out.buildings_gdf) == 3           # no rows lost
    assert list(out.buildings_gdf.columns) == list(buildings_gdf.columns)


def test_merge_connect_accepts_an_int32_connect_column(
    buildings_gdf, streets_gdf, parcels_gdf, source_gdf, stub_adapter, dropping_backend
):
    """Regression: the NRW adapter yields int32; int64 into it warns/raises.

    pandas reports a dtype-incompatible setitem as a FutureWarning today and
    will raise later, so the merge must replace the column, not a slice.
    """
    buildings = buildings_gdf.copy()
    buildings[cols.CONNECT] = buildings[cols.CONNECT].astype("int32")
    state = _state_with(buildings, streets_gdf, parcels_gdf, source_gdf)

    with warnings.catch_warnings():
        warnings.simplefilter("error", FutureWarning)
        out = network_step.run(state, FHeatConfig(), stub_adapter)

    assert out.buildings_gdf[cols.CONNECT].tolist() == [1, 1, 0]


def test_merge_connect_tolerates_a_missing_connect_column(
    buildings_gdf, streets_gdf, parcels_gdf, source_gdf, stub_adapter, dropping_backend
):
    buildings = buildings_gdf.drop(columns=[cols.CONNECT])
    state = _state_with(buildings, streets_gdf, parcels_gdf, source_gdf)

    out = network_step.run(state, FHeatConfig(), stub_adapter)

    assert out.buildings_gdf is buildings
    assert cols.CONNECT not in out.buildings_gdf.columns


# ---------------------------------------------------------------------------
# Integration — needs topotherm and a solver
# ---------------------------------------------------------------------------


def test_settings_take_temperatures_from_fheat_config(tt):
    """FHeatConfig is the single source of truth for supply/return."""
    config = FHeatConfig(
        supply_temperature=95.0,
        return_temperature=55.0,
        network_mode=NetworkMode.EXPERT.value,
        topotherm=TopothermConfig(ambient_temperature=-14.0, max_pressure_loss=180.0),
    )
    settings = TopothermBackend._build_settings(tt, config)

    assert settings.temperatures.supply == 95.0
    assert settings.temperatures.return_ == 55.0
    assert settings.temperatures.ambient == -14.0
    assert settings.piping.max_pr_loss == 180.0


def test_unavailable_solver_names_the_fix(tt, expert_state, expert_adapter):
    config = FHeatConfig(
        network_mode=NetworkMode.EXPERT.value,
        topotherm=TopothermConfig(
            optimization_mode="forced", solver="no_such_solver_here"
        ),
    )
    with pytest.raises(NetworkBackendError, match="is not available") as excinfo:
        network_step.run(expert_state, config, expert_adapter)
    assert excinfo.value.code == SOLVER_UNAVAILABLE


def test_expert_mode_uses_the_shipped_catalogue_when_the_adapter_has_none(
    tt, expert_state, buildings_gdf, streets_gdf, parcels_gdf, source_off_street,
    temperature_series,
):
    """End-to-end with the real string-DN catalogue, as the examples run it."""
    adapter = StubAdapter(
        buildings_gdf, streets_gdf, parcels_gdf, source_off_street,
        pipe_info=None, temperature=temperature_series, holidays={},
    )
    state = network_step.run(expert_state, _forced_config(), adapter)

    NetSchema.validate(state.net_gdf)
    catalogue = set(load_pipe_info()["DN"])
    assert set(state.net_gdf[cols.NOMINAL_DIAMETER]) <= catalogue


def test_results_phase_accepts_the_expert_net(solved_expert_net, expert_adapter):
    """The RESULTS phase must consume the topotherm net without any change."""
    from fheat_core.schemas import LOAD_PROFILE_SCHEMA, RESULT_SUMMARY_SCHEMA
    from fheat_core.steps import results as results_step

    state = results_step.run(solved_expert_net, _forced_config(), expert_adapter)

    LOAD_PROFILE_SCHEMA.validate(state.load_profile_df)
    RESULT_SUMMARY_SCHEMA.validate(state.result_summary)
    assert state.phase == Phase.RESULTS
    assert len(state.load_profile_df) == 8760
    assert state.result_summary["total_buildings"] == 3
    assert state.result_summary["total_network_length_m"] > 0
    assert state.result_summary["total_loss_mwh_a"] > 0


def test_result_tables_from_the_expert_net(solved_expert_net, expert_adapter):
    """Pipe and building summaries work on the topotherm net as well."""
    from fheat_core.schemas import BuildingSummarySchema, PipeSummarySchema
    from fheat_core.steps import results as results_step

    state = results_step.run(solved_expert_net, _forced_config(), expert_adapter)
    s = state.result_summary
    pipes = state.pipe_summary_df

    PipeSummarySchema.validate(pipes)
    BuildingSummarySchema.validate(state.building_summary_df)
    # topotherm: exactly one house connection edge per connected building
    assert pipes[cols.N_HOUSE_CONNECTIONS].sum() == s["total_buildings"]
    assert s["total_house_connection_length_m"] + s["total_route_length_m"] == pytest.approx(
        s["total_network_length_m"], abs=0.11
    )
    assert pipes[cols.HEAT_LOSS_MWH].sum() == pytest.approx(s["total_loss_mwh_a"], abs=1e-3)
    assert state.building_summary_df[cols.N_BUILDINGS].sum() == s["total_buildings"]


def test_both_modes_produce_the_same_columns(
    buildings_gdf, streets_gdf, parcels_gdf, source_off_street, expert_adapter,
    solved_expert_net,
):
    """Comparability is the whole point of doing the sizing in fheat."""
    phase0_state = _state_with(
        buildings_gdf, streets_gdf, parcels_gdf, source_off_street
    )
    phase0 = network_step.run(phase0_state, FHeatConfig(), expert_adapter)

    assert set(phase0.net_gdf.columns) == set(solved_expert_net.net_gdf.columns)
    assert (
        set(cols.to_display(phase0.net_gdf).columns)
        == set(cols.to_display(solved_expert_net.net_gdf).columns)
    )


# ---------------------------------------------------------------------------
# Civil works factors — mapping without topotherm, MILP with it
# ---------------------------------------------------------------------------


def _civil_layer(factor, geometry, civil_class=None):
    return gpd.GeoDataFrame(
        {cols.CIVIL_COST_FACTOR: [factor], "civil_class": [civil_class]},
        geometry=[geometry], crs=CRS,
    )


def test_candidate_factors_fill_the_matrices():
    from shapely.geometry import LineString, box

    edges = gpd.GeoDataFrame(
        geometry=[LineString([(0, 0), (10, 0)]), LineString([(0, 50), (10, 50)])], crs=CRS
    )
    mat = {"l_i": np.array([10.0, 10.0])}
    layers = [_civil_layer(3.0, box(-5, -5, 15, 5)), None]
    config = FHeatConfig(civil_cost_share=0.5)

    civil = TopothermBackend._candidate_civil_factors(mat, edges, layers, CRS, config)

    assert civil[cols.CIVIL_COST_FACTOR].tolist() == pytest.approx([3.0, 1.0])
    assert mat["civil_f"].tolist() == pytest.approx([3.0, 1.0])
    assert mat["civil_m"].tolist() == pytest.approx([2.0, 1.0])     # 0.5 + 0.5·f


@pytest.mark.parametrize("layers", [None, [], [None, None], [gpd.GeoDataFrame(geometry=[], crs=CRS)]])
def test_without_layers_the_matrices_stay_untouched(layers):
    from shapely.geometry import LineString

    edges = gpd.GeoDataFrame(geometry=[LineString([(0, 0), (10, 0)])], crs=CRS)
    mat = {"l_i": np.array([10.0])}
    assert TopothermBackend._candidate_civil_factors(mat, edges, layers, CRS, FHeatConfig()) is None
    assert set(mat) == {"l_i"}


def test_candidate_factors_refuse_misaligned_edges(caplog):
    from shapely.geometry import LineString, box

    edges = gpd.GeoDataFrame(geometry=[LineString([(0, 0), (10, 0)])], crs=CRS)
    mat = {"l_i": np.array([12.0])}                     # not the edge's length
    layers = [_civil_layer(3.0, box(-5, -5, 15, 5))]
    with caplog.at_level("WARNING"):
        assert TopothermBackend._candidate_civil_factors(mat, edges, layers, CRS, FHeatConfig()) is None
    assert "civil_m" not in mat
    assert "do not match" in caplog.text


def _candidate_civil():
    return pd.DataFrame(
        {
            cols.CIVIL_COST_FACTOR: [1.1, 3.0, 1.2, 0.9],
            cols.ROAD_SURFACE: ["asphalt", None, "sett", None],
        }
    )


def test_result_civil_keeps_the_built_candidates_in_order():
    opt_mats = {"lambda_b_orig": np.array([1.0, 0.0, 1.0, 0.0])}
    mat = {"l_i": np.array([10.0, 0.0, 20.0, 0.0])}     # postprocessing zeroes unbuilt edges
    edges_df = pd.DataFrame({"length": [10.0, 20.0]})
    out = TopothermBackend._result_civil(_candidate_civil(), opt_mats, mat, edges_df)
    assert out[cols.CIVIL_COST_FACTOR].tolist() == [1.1, 1.2]
    assert out[cols.ROAD_SURFACE].tolist() == ["asphalt", "sett"]


def test_result_civil_gives_up_when_the_mapping_does_not_add_up(caplog):
    opt_mats = {"lambda_b_orig": np.array([1.0, 0.0, 1.0, 0.0])}
    mat = {"l_i": np.array([10.0, 0.0, 20.0, 0.0])}
    with caplog.at_level("WARNING"):
        assert TopothermBackend._result_civil(
            _candidate_civil(), opt_mats, mat, pd.DataFrame({"length": [10.0, 20.0, 5.0]})
        ) is None
        assert TopothermBackend._result_civil(
            _candidate_civil(), opt_mats, mat, pd.DataFrame({"length": [10.0, 25.0]})
        ) is None
    assert TopothermBackend._result_civil(None, opt_mats, mat, pd.DataFrame()) is None


def test_to_net_gdf_carries_the_civil_factors(fake_edges_df, fake_nodes_df, buildings_gdf, pipe_info_df):
    civil = pd.DataFrame(
        {
            cols.CIVIL_COST_FACTOR: [1.1, 1.2, 1.3, 1.4, 1.5],
            cols.ROAD_SURFACE: ["asphalt", "sett", None, None, "asphalt"],
        }
    )
    net = TopothermBackend._to_net_gdf(
        fake_edges_df, fake_nodes_df, buildings_gdf, pipe_info_df, FHeatConfig(), civil=civil
    )
    NetSchema.validate(net)
    assert net[cols.CIVIL_COST_FACTOR].tolist() == [1.1, 1.2, 1.3, 1.4, 1.5]
    surfaces = [None if pd.isna(v) else v for v in net[cols.ROAD_SURFACE]]  # pandas 3: NaN
    assert surfaces == ["asphalt", "sett", None, None, "asphalt"]


# Two equally long routes between the junctions (0, 0) and (100, 0): north via
# y = 20 and south via y = −20. Each is split in the middle so topotherm does
# not drop one of them as a duplicate edge. Source in the west, one building
# in the east.
def _two_route_inputs():
    from shapely.geometry import LineString, box

    streets = gpd.GeoDataFrame(
        {
            cols.ROUTABLE: [1] * 6,
            "geometry": [
                LineString([(-50, 0), (0, 0)]),
                LineString([(0, 0), (0, 20), (50, 20)]),
                LineString([(50, 20), (100, 20), (100, 0)]),
                LineString([(0, 0), (0, -20), (50, -20)]),
                LineString([(50, -20), (100, -20), (100, 0)]),
                LineString([(100, 0), (150, 0)]),
            ],
        },
        crs=CRS,
    )
    buildings = gpd.GeoDataFrame(
        {
            cols.BUILDING_ID: [0],
            cols.CONNECT: [1],
            cols.HEAT_DEMAND: [30000.0],
            cols.THERMAL_POWER: [20.0],
            cols.FULL_LOAD_HOURS: [1500.0],
            cols.LOAD_PROFILE: ["EFH"],
            "geometry": [box(120, 8, 130, 16)],
        },
        crs=CRS,
    )
    source = gpd.GeoDataFrame({"geometry": [Point(-25, 10)]}, crs=CRS)
    return buildings, streets, source


def _solve_two_routes(expensive_y):
    """Run the expert network step with factor 3 on the route at ``expensive_y``."""
    from shapely.geometry import box

    buildings, streets, source = _two_route_inputs()
    landuse = None
    if expensive_y is not None:
        landuse = _civil_layer(3.0, box(-5, expensive_y - 5, 105, expensive_y + 5), "Bahnverkehr")
    # the eastern stem is asphalt (factor 1.5) in the surface layer
    osm = _civil_layer(1.5, box(105, -2, 140, 2), "asphalt")
    adapter = StubAdapter(buildings, streets, buildings.iloc[0:0], source, landuse=landuse, osm_surface=osm)
    state = PipelineState(phase=Phase.STATUS, buildings_gdf=buildings, streets_gdf=streets, source_gdf=source)
    return network_step.run(state, _forced_config(), adapter).net_gdf


def _routes_built(net):
    """(north route built, south route built) — only they reach |y| = 20."""
    bounds = net.geometry.bounds
    return bool((bounds["maxy"] > 15).any()), bool((bounds["miny"] < -15).any())


def test_milp_avoids_the_expensive_route(tt):
    assert _routes_built(_solve_two_routes(expensive_y=-20)) == (True, False)
    assert _routes_built(_solve_two_routes(expensive_y=20)) == (False, True)


def test_milp_hands_its_factors_to_the_net(tt):
    net = _solve_two_routes(expensive_y=-20)
    stem = net[np.isclose(net[cols.CIVIL_COST_FACTOR], 1.5)]
    assert not stem.empty
    assert set(stem[cols.ROAD_SURFACE]) == {"asphalt"}
    assert net[cols.PIPE_COST].notna().all()
    # nothing on the expensive route was built
    assert not np.isclose(net[cols.CIVIL_COST_FACTOR], 3.0).any()


@pytest.mark.parametrize("layers", [[None, None], [gpd.GeoDataFrame(geometry=[], crs=CRS), None]])
def test_milp_without_layers_builds_the_same_net(tt, expert_state, expert_adapter, layers):
    backend = TopothermBackend()
    args = (
        expert_state.buildings_gdf, expert_state.streets_gdf, expert_state.source_gdf,
        _forced_config(), expert_adapter,
    )
    reference, _ = backend.build(*args)
    without, _ = backend.build(*args, civil_layers=layers)
    assert cols.CIVIL_COST_FACTOR not in without.columns
    pd.testing.assert_frame_equal(pd.DataFrame(without), pd.DataFrame(reference))
