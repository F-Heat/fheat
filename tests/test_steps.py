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
from shapely.geometry import LineString, Point, Polygon

from fheat_core import columns as cols
from fheat_core.config import FHeatConfig
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
