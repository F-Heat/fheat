"""Tests for fheat_core.steps (download, adjust, status, network, results).

Each step is invoked with a stub DataAdapter that returns the conftest
fixtures, so behaviour is exercised end-to-end without IO.
"""
from __future__ import annotations

from typing import Optional

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, Point, Polygon, box

from fheat_core import columns as cols
from fheat_core.config import FHeatConfig
from fheat_core.errors import NO_BUILDINGS, PipelineInputError
from fheat_core.schemas import SchemaError
from fheat_core.state import Phase, PipelineState
from fheat_core.steps import adjust, download, network, results, status

from tests.conftest import StubAdapter

CRS = "EPSG:25832"


@pytest.fixture
def cfg(tmp_path):
    return FHeatConfig(
        supply_temperature=80.0,
        return_temperature=50.0,
        wld_threshold=500.0,
        buffer_distance=15.0,
        year=2022,
        output_dir=str(tmp_path),
        output_format="gpkg",
    )


# ---------------------------------------------------------------------------
# download
# ---------------------------------------------------------------------------


class TestDownloadStep:
    def test_populates_state_and_advances_phase(self, stub_adapter, cfg):
        state = PipelineState()
        out = download.run(state, cfg, stub_adapter)
        assert out.buildings_gdf is not None
        assert out.streets_gdf is not None
        assert out.parcels_gdf is not None
        assert out.source_gdf is not None
        assert out.phase == Phase.DOWNLOADED


# ---------------------------------------------------------------------------
# adjust
# ---------------------------------------------------------------------------


class TestAdjustStep:
    def test_phase_advances(self, stub_adapter, cfg):
        state = PipelineState()
        download.run(state, cfg, stub_adapter)
        adjust.run(state, cfg, stub_adapter)
        assert state.phase == Phase.ADJUSTED

    def test_invalid_schema_raises(self, stub_adapter, cfg, buildings_gdf):
        state = PipelineState()
        download.run(state, cfg, stub_adapter)
        # break schema by removing a required column
        state.buildings_gdf = state.buildings_gdf.drop(columns=[cols.CONNECT])
        with pytest.raises(SchemaError):
            adjust.run(state, cfg, stub_adapter)

    def test_fixes_invalid_polygons(self, streets_gdf, parcels_gdf,
                                    source_gdf, pipe_info_df, temperature_series, cfg):
        """A self-intersecting polygon must be repaired by buffer(0)."""
        invalid = Polygon([(0, 0), (10, 10), (10, 0), (0, 10)])  # bowtie
        bad_buildings = gpd.GeoDataFrame(
            {
                cols.BUILDING_ID: [0],
                cols.CONNECT: [1],
                cols.HEAT_DEMAND: [1000.0],
                cols.THERMAL_POWER: [5.0],
                cols.FULL_LOAD_HOURS: [1500.0],
                cols.LOAD_PROFILE: ["EFH"],
                "geometry": [invalid],
            },
            crs=CRS, geometry="geometry",
        )
        adapter = StubAdapter(bad_buildings, streets_gdf, parcels_gdf, source_gdf,
                              pipe_info_df, temperature_series, {})
        state = PipelineState()
        download.run(state, cfg, adapter)
        assert not bad_buildings.geometry.iloc[0].is_valid
        adjust.run(state, cfg, adapter)
        assert state.buildings_gdf.geometry.iloc[0].is_valid

    @staticmethod
    def _adjusted(buildings_gdf, streets_gdf, parcels_gdf, source_gdf, basis):
        cfg = FHeatConfig(heat_demand_basis=basis)
        adapter = StubAdapter(buildings_gdf, streets_gdf, parcels_gdf, source_gdf)
        state = PipelineState()
        download.run(state, cfg, adapter)
        adjust.run(state, cfg, adapter)
        return state.buildings_gdf

    @staticmethod
    def _with_both_heat_demands(buildings_gdf):
        bld = buildings_gdf.copy()
        bld[cols.HEAT_DEMAND_DATASET] = [12000.0, 20000.0, 30000.0]
        bld[cols.HEAT_DEMAND_CALCULATED] = [15000.0, np.nan, 0.0]
        bld[cols.FULL_LOAD_HOURS] = [1500.0, 0.0, 2000.0]
        return bld

    def test_dataset_basis_sets_heat_demand_and_power(
        self, buildings_gdf, streets_gdf, parcels_gdf, source_gdf
    ):
        bld = self._with_both_heat_demands(buildings_gdf)
        out = self._adjusted(bld, streets_gdf, parcels_gdf, source_gdf, "dataset")
        assert out[cols.HEAT_DEMAND].tolist() == [12000.0, 20000.0, 30000.0]
        # power = heat demand / full load hours, 0 h counts as 1600 h
        assert out[cols.THERMAL_POWER].tolist() == pytest.approx([8.0, 12.5, 15.0])

    def test_calculated_basis_falls_back_to_dataset(
        self, buildings_gdf, streets_gdf, parcels_gdf, source_gdf
    ):
        bld = self._with_both_heat_demands(buildings_gdf)
        out = self._adjusted(bld, streets_gdf, parcels_gdf, source_gdf, "calculated")
        assert out[cols.HEAT_DEMAND].tolist() == [15000.0, 20000.0, 30000.0]
        assert out[cols.THERMAL_POWER].tolist() == pytest.approx([10.0, 12.5, 15.0])

    @pytest.mark.parametrize("basis", ["dataset", "calculated"])
    def test_heat_demand_unchanged_without_both_values(
        self, buildings_gdf, streets_gdf, parcels_gdf, source_gdf, basis
    ):
        out = self._adjusted(buildings_gdf, streets_gdf, parcels_gdf, source_gdf, basis)
        assert out[cols.HEAT_DEMAND].tolist() == buildings_gdf[cols.HEAT_DEMAND].tolist()
        assert out[cols.THERMAL_POWER].tolist() == buildings_gdf[cols.THERMAL_POWER].tolist()


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


class TestStatusStep:
    def test_phase_advances(self, stub_adapter, cfg):
        state = PipelineState()
        download.run(state, cfg, stub_adapter)
        adjust.run(state, cfg, stub_adapter)
        status.run(state, cfg, stub_adapter)
        assert state.phase == Phase.STATUS

    def test_wld_and_polygons_produced(self, stub_adapter, cfg):
        state = PipelineState()
        download.run(state, cfg, stub_adapter)
        adjust.run(state, cfg, stub_adapter)
        status.run(state, cfg, stub_adapter)
        assert state.wld_gdf is not None
        assert cols.HEAT_LINE_DENSITY in state.wld_gdf.columns
        assert cols.CONNECTED_IDS in state.wld_gdf.columns
        assert cols.LENGTH in state.wld_gdf.columns
        assert state.polygons_gdf is not None  # may be empty when no segment exceeds threshold

    def test_wld_value_equals_demand_over_length(self, stub_adapter, cfg):
        state = PipelineState()
        download.run(state, cfg, stub_adapter)
        adjust.run(state, cfg, stub_adapter)
        status.run(state, cfg, stub_adapter)
        wld = state.wld_gdf.iloc[0]
        # 3 buildings: 15000 + 25000 + 35000 = 75000 kWh on a 210 m street
        # → WLD ≈ 357.1 kWh/(a·m)
        expected = 75000 / wld[cols.LENGTH]
        assert wld[cols.HEAT_LINE_DENSITY] == pytest.approx(expected, rel=1e-6)

    @staticmethod
    def _separate_parcels():
        """Three parcels far apart, so every selected parcel stays its own block.

        Parcel A holds two buildings that stick out of it (overlap 0.4 and
        0.3), B one building completely (1.0) and C one building to 0.9.
        Sorting by overlap therefore reorders the parcel/building pairs.
        """
        parcels = gpd.GeoDataFrame(
            {"name": ["A", "B", "C"]},
            geometry=[box(0, 0, 20, 20), box(100, 0, 120, 20), box(200, 0, 220, 20)],
            crs=CRS,
        )
        buildings = gpd.GeoDataFrame(
            {
                cols.BUILDING_ID: [0, 1, 2, 3],
                cols.HEAT_DEMAND: [10000.0, 20000.0, 30000.0, 40000.0],
                cols.THERMAL_POWER: [5.0, 10.0, 15.0, 20.0],
            },
            geometry=[
                box(-6, 2, 4, 12),
                box(17, 5, 27, 15),
                box(105, 5, 115, 15),
                box(211, 5, 221, 15),
            ],
            crs=CRS,
        )
        streets = gpd.GeoDataFrame(
            geometry=[LineString([(-20, -10), (240, -10)])], crs=CRS
        )
        return parcels, buildings, streets

    @staticmethod
    def _blocks(parcels, buildings, streets):
        wld = status._compute_wld(buildings, streets)
        return status._compute_polygons(parcels, wld, buildings, 0.1, 0.5)

    def test_polygons_keep_every_parcel_with_connected_building(self):
        parcels, buildings, streets = self._separate_parcels()
        blocks = self._blocks(parcels, buildings, streets)
        assert len(blocks) == 3
        for parcel in parcels.geometry:
            assert blocks.geometry.contains(parcel).any()

    @pytest.mark.parametrize("seed", [0, 1, 2, 3, 4])
    def test_polygons_independent_of_row_order(self, seed):
        parcels, buildings, streets = self._separate_parcels()
        expected = self._blocks(parcels, buildings, streets)
        blocks = self._blocks(
            parcels.sample(frac=1, random_state=seed),
            buildings.sample(frac=1, random_state=seed + 10),
            streets,
        )
        assert len(blocks) == len(expected)
        assert blocks[cols.AREA].sum() == pytest.approx(expected[cols.AREA].sum())
        assert blocks[cols.HEAT_DEMAND].sum() == pytest.approx(expected[cols.HEAT_DEMAND].sum())

    def test_wld_counts_building_once_when_streets_are_equally_close(self):
        # Building 0 lies diagonally off a junction: both streets end there,
        # so they are exactly equally close to its centroid (5, 5).
        streets = gpd.GeoDataFrame(
            geometry=[LineString([(-50, 0), (0, 0)]), LineString([(0, 0), (0, -50)])],
            crs=CRS,
        )
        buildings = gpd.GeoDataFrame(
            {cols.BUILDING_ID: [0, 1], cols.HEAT_DEMAND: [10000.0, 5000.0]},
            geometry=[box(2, 2, 8, 8), box(-30, 5, -20, 15)],
            crs=CRS,
        )
        wld = status._compute_wld(buildings, streets)
        assert wld[cols.HEAT_DEMAND].sum() == pytest.approx(15000.0)
        connected = [i for ids in wld[cols.CONNECTED_IDS] for i in ids.split(",") if i]
        assert sorted(connected) == ["0", "1"]


# ---------------------------------------------------------------------------
# network
# ---------------------------------------------------------------------------


class TestNetworkStep:
    def test_phase_advances_and_net_schema(self, stub_adapter, cfg):
        state = PipelineState()
        download.run(state, cfg, stub_adapter)
        adjust.run(state, cfg, stub_adapter)
        status.run(state, cfg, stub_adapter)
        network.run(state, cfg, stub_adapter)
        assert state.phase == Phase.NETWORK
        for col in (
            cols.TYPE, cols.LENGTH, cols.THERMAL_POWER, cols.N_BUILDINGS,
            cols.THERMAL_POWER_GLF, cols.VOLUME_FLOW, cols.NOMINAL_DIAMETER,
            cols.VELOCITY, cols.HEAT_LOSS,
            cols.HEAT_LOSS_EXTRA_INSULATION,
        ):
            assert col in state.net_gdf.columns

    def test_only_anschluss_buildings_included(self, buildings_gdf, streets_gdf,
                                               parcels_gdf, source_gdf,
                                               pipe_info_df, temperature_series, cfg):
        """Setting connect=0 on a building excludes it from the network."""
        bld = buildings_gdf.copy()
        bld.loc[0, cols.CONNECT] = 0
        adapter = StubAdapter(bld, streets_gdf, parcels_gdf, source_gdf,
                              pipe_info_df, temperature_series, {})
        state = PipelineState()
        download.run(state, cfg, adapter)
        adjust.run(state, cfg, adapter)
        status.run(state, cfg, adapter)
        network.run(state, cfg, adapter)
        # only 2 buildings remain → max n_buildings on a shared segment ≤ 2
        assert state.net_gdf[cols.N_BUILDINGS].max() <= 2

    def test_no_building_to_connect_raises_with_code(self, buildings_gdf, streets_gdf,
                                                     parcels_gdf, source_gdf,
                                                     pipe_info_df, temperature_series, cfg):
        bld = buildings_gdf.copy()
        bld[cols.CONNECT] = 0
        adapter = StubAdapter(bld, streets_gdf, parcels_gdf, source_gdf,
                              pipe_info_df, temperature_series, {})
        state = PipelineState()
        download.run(state, cfg, adapter)
        adjust.run(state, cfg, adapter)
        status.run(state, cfg, adapter)
        with pytest.raises(PipelineInputError, match="No building to connect") as excinfo:
            network.run(state, cfg, adapter)
        assert excinfo.value.code == NO_BUILDINGS

    def test_only_moegliche_route_used(self, buildings_gdf, streets_gdf,
                                       parcels_gdf, source_gdf, pipe_info_df,
                                       temperature_series, cfg):
        """Streets with routable=0 must be excluded from the graph."""
        # add a second street that's marked unusable; topology forces routing
        # along the usable one
        usable = streets_gdf.copy()
        unusable = gpd.GeoDataFrame(
            {cols.ROUTABLE: [0],
             "geometry": [LineString([(-10, 100), (200, 100)])]},
            crs=CRS, geometry="geometry",
        )
        merged = pd.concat([usable, unusable], ignore_index=True)
        merged = gpd.GeoDataFrame(merged, geometry="geometry", crs=CRS)
        adapter = StubAdapter(buildings_gdf, merged, parcels_gdf, source_gdf,
                              pipe_info_df, temperature_series, {})
        state = PipelineState()
        download.run(state, cfg, adapter)
        adjust.run(state, cfg, adapter)
        status.run(state, cfg, adapter)
        network.run(state, cfg, adapter)
        # no edge geometry should pass through y=100 (the unusable street)
        assert (state.net_gdf.geometry.bounds["maxy"] < 100).all()


# ---------------------------------------------------------------------------
# results
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestResultsStep:
    def test_phase_and_outputs(self, stub_adapter, cfg):
        state = PipelineState()
        download.run(state, cfg, stub_adapter)
        adjust.run(state, cfg, stub_adapter)
        status.run(state, cfg, stub_adapter)
        network.run(state, cfg, stub_adapter)
        results.run(state, cfg, stub_adapter)

        assert state.phase == Phase.RESULTS
        assert state.load_profile_df is not None
        assert len(state.load_profile_df) == 8760
        assert isinstance(state.result_summary, dict)

    def test_result_summary_keys_and_values(self, stub_adapter, cfg):
        state = PipelineState()
        download.run(state, cfg, stub_adapter)
        adjust.run(state, cfg, stub_adapter)
        status.run(state, cfg, stub_adapter)
        network.run(state, cfg, stub_adapter)
        results.run(state, cfg, stub_adapter)

        s = state.result_summary
        assert s["total_buildings"] == 3
        # 15000 + 25000 + 35000 = 75000 kWh = 75 MWh
        assert s["total_heat_demand_mwh_a"] == pytest.approx(75.0, rel=1e-6)
        assert s["supply_temperature_c"] == cfg.supply_temperature
        assert s["return_temperature_c"] == cfg.return_temperature
        assert s["total_network_length_m"] > 0
        assert 0 < s["glf"] <= 1.001  # n=3 → GLF < 1 by formula
        assert s["total_loss_mwh_a"] >= 0

    def test_result_tables_match_summary(self, stub_adapter, cfg, pipe_info_df):
        state = PipelineState()
        download.run(state, cfg, stub_adapter)
        adjust.run(state, cfg, stub_adapter)
        status.run(state, cfg, stub_adapter)
        network.run(state, cfg, stub_adapter)
        results.run(state, cfg, stub_adapter)

        s = state.result_summary
        assert s["total_house_connection_length_m"] > 0
        assert s["total_route_length_m"] > 0
        assert s["total_house_connection_length_m"] + s["total_route_length_m"] == pytest.approx(
            s["total_network_length_m"], abs=0.11
        )
        assert 0 <= s["total_loss_extra_insulation_mwh_a"] <= s["total_loss_mwh_a"]

        pipes = state.pipe_summary_df
        # every catalogue DN is listed, in catalogue order (the stub adapter's catalogue)
        assert list(pipes[cols.NOMINAL_DIAMETER])[: len(pipe_info_df)] == list(pipe_info_df["DN"])
        assert pipes[cols.HEAT_LOSS_MWH].sum() == pytest.approx(s["total_loss_mwh_a"], abs=1e-3)
        assert pipes[cols.HEAT_LOSS_EXTRA_INSULATION_MWH].sum() == pytest.approx(
            s["total_loss_extra_insulation_mwh_a"], abs=1e-3
        )
        assert pipes[cols.HOUSE_CONNECTION_LENGTH].sum() == pytest.approx(
            s["total_house_connection_length_m"], abs=0.06
        )
        assert pipes[cols.N_HOUSE_CONNECTIONS].sum() == 3  # one per connected building

        buildings = state.building_summary_df
        assert list(buildings[cols.LOAD_PROFILE]) == ["EFH", "MFH", "GHA", "GMK", "GKO"]
        assert buildings[cols.N_BUILDINGS].sum() == s["total_buildings"]
        assert buildings[cols.HEAT_DEMAND_MWH].sum() == pytest.approx(s["total_heat_demand_mwh_a"])

    def test_unreachable_building_has_no_house_connection(
        self, buildings_gdf, streets_gdf, parcels_gdf, source_gdf,
        pipe_info_df, temperature_series, cfg,
    ):
        """phase0 skips a building the router cannot reach. It stays connected,
        so it counts in the building summary but has no house connection edge."""
        isolated_street = gpd.GeoDataFrame(
            {cols.ROUTABLE: [1], "geometry": [LineString([(0, 300), (60, 300)])]},
            crs=CRS, geometry="geometry",
        )
        streets = gpd.GeoDataFrame(
            pd.concat([streets_gdf, isolated_street], ignore_index=True),
            geometry="geometry", crs=CRS,
        )
        remote = gpd.GeoDataFrame(
            {
                cols.BUILDING_ID: [3],
                cols.CONNECT: [1],
                cols.HEAT_DEMAND: [5000.0],
                cols.THERMAL_POWER: [5.0],
                cols.FULL_LOAD_HOURS: [1500.0],
                cols.LOAD_PROFILE: ["GKO"],
                "geometry": [Polygon([(20, 305), (30, 305), (30, 315), (20, 315)])],
            },
            crs=CRS, geometry="geometry",
        )
        buildings = gpd.GeoDataFrame(
            pd.concat([buildings_gdf, remote], ignore_index=True),
            geometry="geometry", crs=CRS,
        )
        adapter = StubAdapter(buildings, streets, parcels_gdf, source_gdf,
                              pipe_info_df, temperature_series, {})
        state = PipelineState()
        download.run(state, cfg, adapter)
        adjust.run(state, cfg, adapter)
        status.run(state, cfg, adapter)
        network.run(state, cfg, adapter)
        results.run(state, cfg, adapter)

        s = state.result_summary
        assert s["total_buildings"] == 4
        assert state.pipe_summary_df[cols.N_HOUSE_CONNECTIONS].sum() == 3
        summary = state.building_summary_df.set_index(cols.LOAD_PROFILE)
        assert summary.loc["GKO", cols.N_BUILDINGS] == 1
        assert summary[cols.N_BUILDINGS].sum() == 4
        assert s["total_house_connection_length_m"] + s["total_route_length_m"] == pytest.approx(
            s["total_network_length_m"], abs=0.11
        )


# ---------------------------------------------------------------------------
# civil works factors and pipe costs
# ---------------------------------------------------------------------------


class CivilStubAdapter(StubAdapter):
    """StubAdapter that counts how often the civil works layers are asked for."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.civil_calls = 0

    def fetch_landuse(self):
        self.civil_calls += 1
        return super().fetch_landuse()


def _civil_layers():
    # land use: a road area left of x = 50 (factor 1.4); OSM: the whole street
    # band (y = -5) is asphalt (factor 1.15)
    landuse = gpd.GeoDataFrame(
        {cols.CIVIL_COST_FACTOR: [1.4], "civil_class": ["Straßenverkehr"]},
        geometry=[box(-20, -20, 50, 20)], crs=CRS,
    )
    osm = gpd.GeoDataFrame(
        {cols.CIVIL_COST_FACTOR: [1.15], "civil_class": ["asphalt"]},
        geometry=[box(-20, -8, 220, -2)], crs=CRS,
    )
    return landuse, osm


def _expected_pipe_cost(net, share):
    """Σ l·c·m with c from the shipped catalogue and m from the net's factor."""
    from fheat_core.algorithms.civil_cost import cost_multiplier
    from fheat_core.resources import load_pipe_info

    catalogue = load_pipe_info().set_index("DN")
    house = net[cols.TYPE] == cols.EDGE_TYPE_HOUSE_CONNECTION
    c = np.where(
        house,
        net[cols.NOMINAL_DIAMETER].map(catalogue["cost_h-connect"]),
        net[cols.NOMINAL_DIAMETER].map(catalogue["cost_main"]),
    )
    f = net[cols.CIVIL_COST_FACTOR].to_numpy()
    return float((net[cols.LENGTH] * c * cost_multiplier(f, share)).sum())


class TestCivilCosts:
    @staticmethod
    def _run(adapter, cfg, until="results"):
        state = PipelineState()
        for step in (download, adjust, status, network, results):
            step.run(state, cfg, adapter)
            if step.__name__.endswith(until):
                break
        return state

    @staticmethod
    def _adapter(buildings_gdf, streets_gdf, parcels_gdf, source_gdf, temperature_series, layers=(None, None)):
        landuse, osm = layers
        # pipe_info=None → the shipped catalogue with its cost columns
        return CivilStubAdapter(
            buildings_gdf, streets_gdf, parcels_gdf, source_gdf,
            temperature=temperature_series, holidays={},
            landuse=landuse, osm_surface=osm,
        )

    def test_download_step_keeps_the_layers(self, buildings_gdf, streets_gdf, parcels_gdf,
                                            source_gdf, temperature_series, cfg):
        landuse, osm = _civil_layers()
        adapter = self._adapter(buildings_gdf, streets_gdf, parcels_gdf, source_gdf,
                                temperature_series, (landuse, osm))
        state = download.run(PipelineState(), cfg, adapter)
        assert state.landuse_gdf is landuse
        assert state.osm_surface_gdf is osm

    def test_net_gets_factors_surface_and_costs(self, buildings_gdf, streets_gdf, parcels_gdf,
                                                source_gdf, temperature_series, cfg):
        adapter = self._adapter(buildings_gdf, streets_gdf, parcels_gdf, source_gdf,
                                temperature_series, _civil_layers())
        state = self._run(adapter, cfg)
        net = state.net_gdf

        assert {cols.CIVIL_COST_FACTOR, cols.ROAD_SURFACE, cols.PIPE_COST, cols.CIVIL_COST} <= set(net.columns)
        assert (net[cols.CIVIL_COST_FACTOR] != 1.0).any()
        street = net[cols.TYPE] == "Straßenleitung"
        assert (net.loc[street, cols.ROAD_SURFACE] == "asphalt").all()
        # street west of x = 50: land use × surface
        west = street & (net.geometry.bounds["maxx"] <= 45)
        assert west.any()
        assert net.loc[west, cols.CIVIL_COST_FACTOR].tolist() == pytest.approx([1.4 * 1.15] * int(west.sum()))
        assert net[cols.PIPE_COST].notna().all()

        s = state.result_summary
        assert s["civil_cost_share"] == cfg.civil_cost_share
        assert s["total_pipe_cost_eur"] == pytest.approx(_expected_pipe_cost(net, cfg.civil_cost_share), abs=0.01)
        assert s["total_pipe_cost_eur"] == pytest.approx(net[cols.PIPE_COST].sum(), abs=0.01)
        assert s["total_civil_cost_eur"] == pytest.approx(net[cols.CIVIL_COST].sum(), abs=0.01)
        assert s["total_civil_cost_eur"] < s["total_pipe_cost_eur"]
        assert s["mean_civil_cost_factor"] > 1.0
        assert state.pipe_summary_df[cols.PIPE_COST].sum() == pytest.approx(s["total_pipe_cost_eur"], abs=0.01)

    def test_without_layers_the_factor_is_one(self, buildings_gdf, streets_gdf, parcels_gdf,
                                              source_gdf, temperature_series, cfg):
        adapter = self._adapter(buildings_gdf, streets_gdf, parcels_gdf, source_gdf, temperature_series)
        state = self._run(adapter, cfg)
        net = state.net_gdf
        assert (net[cols.CIVIL_COST_FACTOR] == 1.0).all()
        assert net[cols.ROAD_SURFACE].isna().all()
        # m = 1 → pipe_cost = l·c
        assert state.result_summary["total_pipe_cost_eur"] == pytest.approx(_expected_pipe_cost(net, 1.0), abs=0.01)
        assert state.result_summary["mean_civil_cost_factor"] == 1.0

    def test_zero_share_ignores_the_surfaces(self, buildings_gdf, streets_gdf, parcels_gdf,
                                             source_gdf, temperature_series, cfg):
        with_layers = self._adapter(buildings_gdf, streets_gdf, parcels_gdf, source_gdf,
                                    temperature_series, _civil_layers())
        without = self._adapter(buildings_gdf, streets_gdf, parcels_gdf, source_gdf, temperature_series)
        cfg.civil_cost_share = 0.0
        a = self._run(with_layers, cfg).result_summary
        b = self._run(without, cfg).result_summary
        assert a["total_pipe_cost_eur"] == pytest.approx(b["total_pipe_cost_eur"])
        assert a["total_civil_cost_eur"] == 0.0

    def test_resumed_state_asks_the_adapter_for_the_layers(self, buildings_gdf, streets_gdf, parcels_gdf,
                                                           source_gdf, temperature_series, cfg):
        """fheat-web resumes from STATUS without layers: same factors as a full run."""
        layers = _civil_layers()
        full = self._run(
            self._adapter(buildings_gdf, streets_gdf, parcels_gdf, source_gdf, temperature_series, layers),
            cfg, until="network",
        )
        analysed = self._run(
            self._adapter(buildings_gdf, streets_gdf, parcels_gdf, source_gdf, temperature_series),
            cfg, until="status",
        )
        resumed = PipelineState(
            phase=Phase.STATUS,
            buildings_gdf=analysed.buildings_gdf,
            streets_gdf=analysed.streets_gdf,
            source_gdf=analysed.source_gdf,
        )
        adapter = self._adapter(buildings_gdf, streets_gdf, parcels_gdf, source_gdf, temperature_series, layers)
        network.run(resumed, cfg, adapter)

        assert adapter.civil_calls == 1
        assert resumed.landuse_gdf is layers[0]
        pd.testing.assert_series_equal(
            resumed.net_gdf[cols.CIVIL_COST_FACTOR], full.net_gdf[cols.CIVIL_COST_FACTOR]
        )
        pd.testing.assert_series_equal(resumed.net_gdf[cols.PIPE_COST], full.net_gdf[cols.PIPE_COST])

    def test_catalogue_without_costs_leaves_the_totals_out(self, stub_adapter, cfg, caplog):
        # the conftest catalogue has no cost columns
        with caplog.at_level("WARNING"):
            state = self._run(stub_adapter, cfg)
        assert state.net_gdf[cols.PIPE_COST].isna().all()
        assert "total_pipe_cost_eur" not in state.result_summary
        assert "total_civil_cost_eur" not in state.result_summary
        assert cols.PIPE_COST not in state.pipe_summary_df.columns
        assert any("no cost columns" in r.getMessage() for r in caplog.records)
