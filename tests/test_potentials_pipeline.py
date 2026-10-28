"""Potential layers in the core pipeline.

Covers:
- algorithms.potentials.attach_potentials: block value by block_id or by
  location, shallow geothermal values, NaN + not_assessed outside, idempotent
- algorithms.potentials.potential_summary: each block once, max / sums
- steps.download: layers on the state, schema check, buildings unchanged
  without layers
- results summary keys and save_outputs layers (labels, clipping)
"""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

from fheat_core import columns as cols
from fheat_core.algorithms.potentials import attach_potentials, potential_summary
from fheat_core.config import FHeatConfig
from fheat_core.orchestrator import FHeatOrchestrator
from fheat_core.schemas import SchemaError
from fheat_core.state import Phase, PipelineState
from fheat_core.steps import adjust, download, network, results, status

from tests.conftest import StubAdapter

CRS = "EPSG:25832"


@pytest.fixture
def cfg(tmp_path):
    return FHeatConfig(
        supply_temperature=80.0, return_temperature=50.0, wld_threshold=500.0,
        buffer_distance=15.0, year=2022, output_dir=str(tmp_path), output_format="gpkg",
    )


def _blocks() -> gpd.GeoDataFrame:
    # block A covers buildings 0 and 1 (x 0..60), block B building 2 (x 100..110)
    return gpd.GeoDataFrame(
        {cols.BLOCK_ID: pd.array(["A", "B"], dtype="string"),
         cols.ONG_POTENTIAL_MWH: [100.0, 40.0], cols.ONG_POTENTIAL_2045_MWH: [90.0, 30.0],
         cols.MTG_POTENTIAL_MWH: [0.0, 5.0], cols.MTG_POTENTIAL_2045_MWH: [0.0, 4.0],
         cols.BLOCK_POTENTIAL_STATUS: [cols.STATUS_ASSESSED, cols.STATUS_ASSESSED]},
        geometry=[box(-5, -2, 65, 15), box(95, -2, 115, 15)], crs=CRS,
    )


def _shallow() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {cols.BOREHOLE_EXTRACTION_1800: [60.0], cols.BOREHOLE_EXTRACTION_2400: [50.0],
         cols.COLLECTOR_EXTRACTION_1800: [25.0], cols.COLLECTOR_EXTRACTION_2400: [20.0],
         cols.GEOTHERMAL_STATUS: [cols.STATUS_ASSESSED]},
        geometry=[box(-20, -20, 70, 20)], crs=CRS,
    )


def _deep() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {cols.DEEP_POTENTIAL_MWH: [7932.0, 19392.0], cols.DISTANCE_TO_AREA: [0.0, 4000.0],
         cols.SOURCE_CANDIDATE_LAT: [52.1, 52.2], cols.SOURCE_CANDIDATE_LON: [7.3, 7.4]},
        geometry=[box(-1000, -1000, 2000, 2000), box(6000, -1000, 9000, 2000)], crs=CRS,
    )


def _solar() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {cols.FLUR_ID: ["1", "2"], cols.SOLAR_USABLE_AREA: [1000.0, 3000.0],
         cols.SOLAR_FLAT_PLATE_MWH: [250.0, 750.0], cols.DISTANCE_TO_AREA: [500.0, 1500.0]},
        geometry=[box(600, 0, 700, 100), box(1600, 0, 1700, 100)], crs=CRS,
    )


class TestAttachPotentials:
    def test_block_value_by_id_and_location(self, buildings_gdf):
        buildings = buildings_gdf.copy()
        # building 1 has a wrong id → found by id ("B"); building 2 has none → by location
        buildings[cols.BLOCK_ID] = pd.array(["A", "B", None], dtype="string")
        out = attach_potentials(buildings, _blocks())
        assert out[cols.ONG_POTENTIAL_MWH].tolist() == [100.0, 40.0, 40.0]
        assert out[cols.MTG_POTENTIAL_2045_MWH].tolist() == [0.0, 4.0, 4.0]

    def test_outside_every_block_is_nan_and_not_assessed(self, buildings_gdf):
        blocks = _blocks().iloc[[0]]
        out = attach_potentials(buildings_gdf, blocks)
        assert np.isnan(out[cols.ONG_POTENTIAL_MWH].iloc[2])
        assert out[cols.BLOCK_POTENTIAL_STATUS].tolist() == [
            cols.STATUS_ASSESSED, cols.STATUS_ASSESSED, cols.STATUS_NOT_ASSESSED]

    def test_shallow_values(self, buildings_gdf):
        out = attach_potentials(buildings_gdf, shallow=_shallow())
        assert out[cols.BOREHOLE_EXTRACTION_1800].tolist()[:2] == [60.0, 60.0]
        assert np.isnan(out[cols.BOREHOLE_EXTRACTION_1800].iloc[2])
        assert out[cols.GEOTHERMAL_STATUS].iloc[2] == cols.STATUS_NOT_ASSESSED
        assert cols.ONG_POTENTIAL_MWH not in out.columns

    def test_again_gives_the_same(self, buildings_gdf):
        once = attach_potentials(buildings_gdf, _blocks(), _shallow())
        twice = attach_potentials(once, _blocks(), _shallow())
        pd.testing.assert_frame_equal(once, twice)

    def test_without_layers_unchanged(self, buildings_gdf):
        pd.testing.assert_frame_equal(attach_potentials(buildings_gdf), buildings_gdf)


class TestPotentialSummary:
    def test_each_block_counts_once(self, buildings_gdf):
        out = potential_summary(buildings_gdf, _blocks(), _deep(), _solar())
        assert out == {
            "ong_potential_mwh_a": 140.0, "mtg_potential_mwh_a": 5.0,
            "deep_potential_max_mwh_a": 19392.0,
            "solar_thermal_flat_plate_mwh_a": 1000.0, "solar_thermal_area_m2": 4000.0,
        }

    def test_only_the_blocks_of_the_buildings(self, buildings_gdf):
        out = potential_summary(buildings_gdf.iloc[:2], _blocks())
        assert out == {"ong_potential_mwh_a": 100.0}   # no MTG potential in these blocks: left out

    def test_missing_layers_leave_the_keys_out(self, buildings_gdf):
        assert potential_summary(buildings_gdf) == {}


class PotentialStubAdapter(StubAdapter):
    def __init__(self, *args, potentials=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._potentials = potentials or {}

    def fetch_geothermal_shallow(self):
        return self._potentials.get("shallow")

    def fetch_geothermal_blocks(self):
        return self._potentials.get("blocks")

    def fetch_geothermal_deep(self):
        return self._potentials.get("deep")

    def fetch_solar_thermal(self):
        return self._potentials.get("solar")


def _all_layers() -> dict:
    return {"shallow": _shallow(), "blocks": _blocks(), "deep": _deep(), "solar": _solar()}


@pytest.fixture
def make_adapter(buildings_gdf, streets_gdf, parcels_gdf, source_gdf, temperature_series):
    def make(potentials=None):
        return PotentialStubAdapter(
            buildings_gdf, streets_gdf, parcels_gdf, source_gdf,
            temperature=temperature_series, holidays={}, potentials=potentials,
        )
    return make


class TestDownloadStep:
    def test_layers_on_the_state_and_the_buildings(self, make_adapter, cfg):
        state = download.run(PipelineState(), cfg, make_adapter(_all_layers()))
        assert state.geothermal_blocks_gdf is not None and state.solar_thermal_gdf is not None
        assert state.geothermal_deep_gdf[cols.DEEP_POTENTIAL_MWH].max() == 19392.0
        assert state.buildings_gdf[cols.ONG_POTENTIAL_MWH].tolist() == [100.0, 100.0, 40.0]
        assert cols.BOREHOLE_EXTRACTION_1800 in state.buildings_gdf.columns

    def test_without_layers_the_buildings_stay_as_they_were(self, make_adapter, cfg, buildings_gdf):
        state = download.run(PipelineState(), cfg, make_adapter())
        assert state.geothermal_shallow_gdf is None and state.solar_thermal_gdf is None
        assert list(state.buildings_gdf.columns) == list(buildings_gdf.columns)

    def test_an_empty_layer_is_none(self, make_adapter, cfg):
        state = download.run(PipelineState(), cfg, make_adapter({"deep": _deep().iloc[0:0]}))
        assert state.geothermal_deep_gdf is None

    def test_a_layer_against_the_schema_raises(self, make_adapter, cfg):
        broken = _blocks().drop(columns=[cols.ONG_POTENTIAL_MWH])
        with pytest.raises(SchemaError, match="GeothermalBlocks"):
            download.run(PipelineState(), cfg, make_adapter({"blocks": broken}))


class TestResultsAndExport:
    @staticmethod
    def _run(adapter, cfg):
        state = PipelineState()
        for step in (download, adjust, status, network, results):
            step.run(state, cfg, adapter)
        return state

    def test_summary_keys(self, make_adapter, cfg):
        state = self._run(make_adapter(_all_layers()), cfg)
        summary = state.result_summary
        assert summary["ong_potential_mwh_a"] == 140.0
        assert summary["deep_potential_max_mwh_a"] == 19392.0
        assert summary["solar_thermal_flat_plate_mwh_a"] == 1000.0
        assert set(summary) <= set(cols.SUMMARY_LABELS_DE)

    def test_no_layers_no_keys(self, make_adapter, cfg):
        summary = self._run(make_adapter(), cfg).result_summary
        assert not {k for k in summary if "potential" in k or "solar" in k}

    def test_save_outputs_writes_the_layers_with_german_labels(self, make_adapter, tmp_path):
        cfg = FHeatConfig(output_dir=str(tmp_path), output_format="gpkg")
        adapter = make_adapter(_all_layers())
        state = download.run(PipelineState(), cfg, adapter)
        state.phase = Phase.DOWNLOADED
        saved = FHeatOrchestrator(cfg, adapter, state=state).save_outputs()
        for name in ("geothermie_kennwerte", "geothermie_baubloecke", "geothermie_tief",
                     "solarthermie_freiflaechen"):
            assert name in saved
        blocks = gpd.read_file(saved["geothermie_baubloecke"])
        assert "Potenzial ONG Baublock [MWh/a]" in blocks.columns
        buildings = gpd.read_file(saved["buildings"])
        assert "Richtwert Entzug Sonde 1800h [W/m]" in buildings.columns

    def test_clipping_keeps_the_layers_around_the_area(self, make_adapter, tmp_path):
        cfg = FHeatConfig(output_dir=str(tmp_path), output_format="gpkg")
        adapter = make_adapter(_all_layers())
        state = download.run(PipelineState(), cfg, adapter)
        state.planning_area_gdf = gpd.GeoDataFrame(geometry=[box(-10, -10, 70, 20)], crs=CRS)
        saved = FHeatOrchestrator(cfg, adapter, state=state).save_outputs(clip_to_planning_area=True)
        assert len(gpd.read_file(saved["solarthermie_freiflaechen"])) == 2
        assert len(gpd.read_file(saved["geothermie_tief"])) == 2
        assert len(gpd.read_file(saved["geothermie_baubloecke"])) == 1

    def test_a_large_block_touching_the_area_is_left_out(self, make_adapter, tmp_path):
        cfg = FHeatConfig(output_dir=str(tmp_path), output_format="gpkg")
        layers = _all_layers()
        outer = gpd.GeoDataFrame(
            {cols.BLOCK_ID: pd.array(["X"], dtype="string"), cols.ONG_POTENTIAL_MWH: [1e5],
             cols.MTG_POTENTIAL_MWH: [0.0], cols.BLOCK_POTENTIAL_STATUS: [cols.STATUS_ASSESSED]},
            geometry=[box(-5000, 20, 5000, 5000)], crs=CRS,
        )
        layers["blocks"] = pd.concat([layers["blocks"], outer], ignore_index=True)
        adapter = make_adapter(layers)
        state = download.run(PipelineState(), cfg, adapter)
        state.planning_area_gdf = gpd.GeoDataFrame(geometry=[box(-10, -10, 70, 25)], crs=CRS)
        saved = FHeatOrchestrator(cfg, adapter, state=state).save_outputs(clip_to_planning_area=True)
        assert gpd.read_file(saved["geothermie_baubloecke"])[cols.LABELS_DE[cols.BLOCK_ID]].tolist() == ["A"]
