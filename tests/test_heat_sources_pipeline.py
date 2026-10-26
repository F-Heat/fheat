"""Heat source layers in the core pipeline.

Covers:
- steps.download: layers and the study table on the state, empty → None,
  schema check
- algorithms.potentials.heat_source_summary: sums, the largest river
  project, NaN cells as 0, keys left out without a layer
- results summary keys, save_outputs layers (labels, never clipped) and
  the study table export
"""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Point, box

from fheat_core import columns as cols
from fheat_core.algorithms.potentials import heat_source_summary
from fheat_core.config import FHeatConfig
from fheat_core.export.tables import collect_tables
from fheat_core.orchestrator import FHeatOrchestrator
from fheat_core.schemas import SchemaError
from fheat_core.state import PipelineState
from fheat_core.steps import adjust, download, network, results, status

from tests.conftest import StubAdapter

CRS = "EPSG:25832"
CANDIDATE = {cols.SOURCE_CANDIDATE_LAT: [52.1, 52.2], cols.SOURCE_CANDIDATE_LON: [7.3, 7.4]}


@pytest.fixture
def cfg(tmp_path):
    return FHeatConfig(
        supply_temperature=80.0, return_temperature=50.0, wld_threshold=500.0,
        buffer_distance=15.0, year=2022, output_dir=str(tmp_path), output_format="gpkg",
    )


def _points(values: dict) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame({**values, cols.DISTANCE_TO_AREA: [0.0, 1500.0], **CANDIDATE},
                            geometry=[Point(500, 500), Point(2000, 500)], crs=CRS)


def _cells(ht, lt) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame({cols.HEAT_HT_MWH: ht, cols.HEAT_LT_MWH: lt, cols.DISTANCE_TO_AREA: [0.0, 900.0],
                             **CANDIDATE}, geometry=[box(0, 0, 1000, 1000), box(1000, 0, 2000, 1000)], crs=CRS)


def _layers() -> dict:
    return {
        "wastewater": _points({cols.SOURCE_NAME: ["Steinfurt", "Ochtrup"], cols.HEAT_EXTRACTION_MWH: [100.0, 50.0],
                               cols.HEAT_HT_MWH: [158.8, 79.4], cols.HEAT_LT_MWH: [138.5, 69.2]}),
        "industrial": _points({cols.HEAT_HT_MWH: [8247.0, 507.0], cols.HEAT_LT_MWH: [13977.0, 880.0]}),
        "incineration": _points({cols.EXCESS_HEAT_THEORETICAL_MWH: [1000.0, 0.0],
                                 cols.HEAT_HT_MWH: [660.0, 0.0], cols.HEAT_LT_MWH: [760.0, 0.0]}),
        "rivers": gpd.GeoDataFrame({cols.HEAT_PUMP_CAPACITY_MW: [30.0, 80.0], cols.HEAT_MWH: [60000.0, 240000.0],
                                    cols.DISTANCE_TO_AREA: [0.0, 4000.0]},
                                   geometry=[box(0, 0, 9, 9), box(10, 0, 19, 9)], crs=CRS),
        "hydrothermal": _cells([1500.0, np.nan], [3600.0, 3500.0]),
        "study_dh_areas": gpd.GeoDataFrame({cols.DH_AREA_ID: pd.array([298], dtype="Int64"),
                                            cols.DH_DEMAND_2050_MWH: [6791.0]},
                                           geometry=[box(0, 0, 300, 300)], crs=CRS),
        "study_potentials": pd.DataFrame({
            cols.STUDY_SOURCE: ["dh_demand", "wwtp"], cols.STUDY_SUPPLY_HT_MWH: [7878.0, 21083.0],
            cols.STUDY_UTILIZATION_HT_MWH: [np.nan, 7878.0], cols.STUDY_SUPPLY_LT_MWH: [7471.0, 25743.0],
            cols.STUDY_UTILIZATION_LT_MWH: [np.nan, 7471.0]}),
    }


class HeatSourceStubAdapter(StubAdapter):
    def __init__(self, *args, layers=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._layers = layers or {}

    def fetch_wastewater(self):
        return self._layers.get("wastewater")

    def fetch_industrial_heat(self):
        return self._layers.get("industrial")

    def fetch_waste_incineration(self):
        return self._layers.get("incineration")

    def fetch_river_heat(self):
        return self._layers.get("rivers")

    def fetch_geothermal_hydrothermal(self):
        return self._layers.get("hydrothermal")

    def fetch_study_dh_areas(self):
        return self._layers.get("study_dh_areas")

    def fetch_study_potentials(self):
        return self._layers.get("study_potentials")


@pytest.fixture
def make_adapter(buildings_gdf, streets_gdf, parcels_gdf, source_gdf, temperature_series):
    def make(layers=None):
        return HeatSourceStubAdapter(
            buildings_gdf, streets_gdf, parcels_gdf, source_gdf,
            temperature=temperature_series, holidays={}, layers=layers,
        )
    return make


class TestDownloadStep:
    def test_layers_and_table_on_the_state(self, make_adapter, cfg):
        state = download.run(PipelineState(), cfg, make_adapter(_layers()))
        assert state.wastewater_gdf[cols.SOURCE_NAME].tolist() == ["Steinfurt", "Ochtrup"]
        assert state.hydrothermal_gdf is not None
        assert state.study_dh_areas_gdf[cols.DH_AREA_ID].tolist() == [298]
        assert state.study_potentials_df[cols.STUDY_SOURCE].tolist() == ["dh_demand", "wwtp"]

    def test_without_layers_nothing_is_set(self, make_adapter, cfg):
        state = download.run(PipelineState(), cfg, make_adapter())
        assert state.wastewater_gdf is None and state.study_potentials_df is None

    def test_an_empty_layer_is_none(self, make_adapter, cfg):
        state = download.run(PipelineState(), cfg, make_adapter({"rivers": _layers()["rivers"].iloc[0:0]}))
        assert state.river_heat_gdf is None

    def test_a_layer_against_the_schema_raises(self, make_adapter, cfg):
        broken = _layers()["industrial"].drop(columns=[cols.SOURCE_CANDIDATE_LAT])
        with pytest.raises(SchemaError, match="IndustrialHeat"):
            download.run(PipelineState(), cfg, make_adapter({"industrial": broken}))


class TestHeatSourceSummary:
    def test_sums_and_largest_project(self):
        layers = _layers()
        out = heat_source_summary(layers["wastewater"], layers["industrial"], layers["incineration"],
                                  layers["rivers"], layers["hydrothermal"])
        assert out == {
            cols.TOTAL_WASTEWATER_EXTRACTION: 150.0,
            cols.TOTAL_WASTEWATER_HEAT_HT: 238.2,
            cols.TOTAL_WASTEWATER_HEAT_LT: 207.7,
            cols.TOTAL_INDUSTRIAL_HEAT_HT: 8754.0,
            cols.TOTAL_INDUSTRIAL_HEAT_LT: 14857.0,
            cols.TOTAL_WASTE_INCINERATION_HT: 660.0,
            cols.TOTAL_WASTE_INCINERATION_LT: 760.0,
            cols.MAX_RIVER_HEAT: 240000.0,
            cols.TOTAL_HYDROTHERMAL_HT: 1500.0,       # the cell too cold for HT counts as 0
            cols.TOTAL_HYDROTHERMAL_LT: 7100.0,
        }

    def test_missing_layers_leave_the_keys_out(self):
        assert heat_source_summary() == {}
        assert set(heat_source_summary(rivers=_layers()["rivers"])) == {cols.MAX_RIVER_HEAT}

    def test_no_heat_leaves_the_keys_out(self):
        incineration = _layers()["incineration"].iloc[1:]   # the plant with 0 MWh/a
        assert heat_source_summary(incineration=incineration) == {}


class TestResultsAndExport:
    def test_summary_keys(self, make_adapter, cfg):
        adapter = make_adapter(_layers())
        state = PipelineState()
        for step in (download, adjust, status, network, results):
            step.run(state, cfg, adapter)
        summary = state.result_summary
        assert summary[cols.TOTAL_WASTEWATER_EXTRACTION] == 150.0
        assert summary[cols.MAX_RIVER_HEAT] == 240000.0
        assert set(summary) <= set(cols.SUMMARY_LABELS_DE)

    def test_layers_with_german_labels_never_clipped(self, make_adapter, tmp_path):
        cfg = FHeatConfig(output_dir=str(tmp_path), output_format="gpkg")
        adapter = make_adapter(_layers())
        state = download.run(PipelineState(), cfg, adapter)
        state.planning_area_gdf = gpd.GeoDataFrame(geometry=[box(-10, -10, 70, 20)], crs=CRS)
        saved = FHeatOrchestrator(cfg, adapter, state=state).save_outputs(clip_to_planning_area=True)
        for name in ("klaeranlagen", "industrie_abwaerme", "muellverbrennung", "fluesse_seen", "hydrothermie",
                     "waermenetzgebiete_studie"):
            assert name in saved
        plants = gpd.read_file(saved["klaeranlagen"])
        assert len(plants) == 2
        assert "Waerme HT-Szenario [MWh/a]" in plants.columns

    def test_study_table_export(self, make_adapter, cfg):
        state = download.run(PipelineState(), cfg, make_adapter(_layers()))
        table = collect_tables(state, translate=True)["studie_waermequellen"]
        assert table["Waermequelle"].tolist() == ["Wärmenetzbedarf 2050", "Kläranlagen"]
        assert "Nutzbar NT [MWh/a]" in table.columns
        raw = collect_tables(state, translate=False)["studie_waermequellen"]
        assert raw[cols.STUDY_SOURCE].tolist() == ["dh_demand", "wwtp"]
