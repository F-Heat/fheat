"""Tests for fheat_core.orchestrator.FHeatOrchestrator.

Covers:
- Constructor creates output_dir
- run_step rejects unknown phases (RESULTS has no associated step fn)
- run_step advances state phase
- run_all from INITIAL completes the full pipeline
- run_from skips earlier phases
- save_outputs writes files for every populated frame, with the right
  driver/extension, and supports re-runs (file overwrite).
"""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pytest

from fheat_core import columns as cols
from fheat_core.config import FHeatConfig
from fheat_core.orchestrator import FHeatOrchestrator, _FORMAT_MAP, _STEP_ORDER
from fheat_core.state import Phase, PipelineState


# ---------------------------------------------------------------------------
# Constructor / structural
# ---------------------------------------------------------------------------


class TestConstructor:
    def test_creates_output_dir(self, stub_adapter, tmp_path):
        out = tmp_path / "nested" / "out"
        cfg = FHeatConfig(output_dir=str(out))
        FHeatOrchestrator(cfg, stub_adapter)
        assert out.is_dir()

    def test_uses_provided_state(self, stub_adapter, tmp_path):
        cfg = FHeatConfig(output_dir=str(tmp_path))
        state = PipelineState(phase=Phase.STATUS)
        orch = FHeatOrchestrator(cfg, stub_adapter, state=state)
        assert orch.state is state

    def test_step_order_constant(self):
        # documented order
        assert _STEP_ORDER == [
            Phase.INITIAL,
            Phase.DOWNLOADED,
            Phase.ADJUSTED,
            Phase.STATUS,
            Phase.NETWORK,
            Phase.RESULTS,
        ]


# ---------------------------------------------------------------------------
# run_step
# ---------------------------------------------------------------------------


class TestRunStep:
    def test_run_step_initial_advances_phase(self, stub_adapter, tmp_path):
        cfg = FHeatConfig(output_dir=str(tmp_path))
        orch = FHeatOrchestrator(cfg, stub_adapter)
        orch.run_step(Phase.INITIAL)
        assert orch.state.phase == Phase.DOWNLOADED

    def test_run_step_results_phase_rejected(self, stub_adapter, tmp_path):
        """RESULTS has no associated step function — must raise."""
        cfg = FHeatConfig(output_dir=str(tmp_path))
        orch = FHeatOrchestrator(cfg, stub_adapter)
        with pytest.raises(ValueError, match="no associated step"):
            orch.run_step(Phase.RESULTS)


# ---------------------------------------------------------------------------
# run_all / run_from
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestRunAll:
    def test_run_all_completes_full_pipeline(self, stub_adapter, tmp_path):
        cfg = FHeatConfig(output_dir=str(tmp_path))
        orch = FHeatOrchestrator(cfg, stub_adapter)
        orch.run_all()

        s = orch.state
        assert s.phase == Phase.RESULTS
        assert s.buildings_gdf is not None
        assert s.streets_gdf is not None
        assert s.wld_gdf is not None
        assert s.net_gdf is not None
        assert s.load_profile_df is not None
        assert s.result_summary is not None


class TestRunFrom:
    """
    Note on the orchestrator API: _STEP_FN[phase] is "the step that runs WHILE
    in `phase`" — i.e. the function that advances FROM that phase. So
    run_from(ADJUSTED) executes status.run first (because _STEP_FN[ADJUSTED] =
    status.run) and skips download.run + adjust.run.
    """

    def test_run_from_adjusted_skips_download_and_adjust(
        self, buildings_gdf, streets_gdf, parcels_gdf, source_gdf,
        pipe_info_df, temperature_series, tmp_path,
    ):
        from tests.conftest import StubAdapter

        # counting adapter that records every call to fetch_*
        class CountingAdapter(StubAdapter):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.calls = {"buildings": 0, "streets": 0, "parcels": 0, "source": 0}

            def fetch_buildings(self):
                self.calls["buildings"] += 1
                return super().fetch_buildings()

            def fetch_streets(self):
                self.calls["streets"] += 1
                return super().fetch_streets()

            def fetch_parcels(self):
                self.calls["parcels"] += 1
                return super().fetch_parcels()

            def fetch_source(self):
                self.calls["source"] += 1
                return super().fetch_source()

        adapter = CountingAdapter(
            buildings_gdf, streets_gdf, parcels_gdf, source_gdf,
            pipe_info_df, temperature_series, {},
        )
        cfg = FHeatConfig(output_dir=str(tmp_path))
        state = PipelineState(
            phase=Phase.ADJUSTED,
            buildings_gdf=buildings_gdf,
            streets_gdf=streets_gdf,
            parcels_gdf=parcels_gdf,
            source_gdf=source_gdf,
        )
        orch = FHeatOrchestrator(cfg, adapter, state=state)
        orch.run_from(Phase.ADJUSTED)

        # status.run ran → wld populated
        assert orch.state.wld_gdf is not None
        # full pipeline completed
        assert orch.state.phase == Phase.RESULTS
        # download.run was NOT executed (no fetch_* calls)
        assert all(c == 0 for c in adapter.calls.values())

    def test_run_from_status_runs_only_network_and_results(
        self, stub_adapter, tmp_path,
        buildings_gdf, streets_gdf, parcels_gdf, source_gdf,
    ):
        """run_from(STATUS) skips status.run — wld_gdf must be pre-populated."""
        cfg = FHeatConfig(output_dir=str(tmp_path))
        state = PipelineState(
            phase=Phase.STATUS,
            buildings_gdf=buildings_gdf,
            streets_gdf=streets_gdf,
            parcels_gdf=parcels_gdf,
            source_gdf=source_gdf,
        )
        orch = FHeatOrchestrator(cfg, stub_adapter, state=state)
        orch.run_from(Phase.STATUS)
        assert orch.state.phase == Phase.RESULTS
        assert orch.state.net_gdf is not None
        # wld was never produced because status.run was skipped
        assert orch.state.wld_gdf is None


# ---------------------------------------------------------------------------
# save_outputs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fmt", ["gpkg", "geojson"])
class TestSaveOutputs:
    def test_writes_all_populated_frames(
        self, stub_adapter, tmp_path, fmt,
        buildings_gdf, streets_gdf, parcels_gdf, source_gdf,
    ):
        cfg = FHeatConfig(output_dir=str(tmp_path), output_format=fmt)
        state = PipelineState(
            phase=Phase.DOWNLOADED,
            buildings_gdf=buildings_gdf,
            streets_gdf=streets_gdf,
            parcels_gdf=parcels_gdf,
            source_gdf=source_gdf,
        )
        orch = FHeatOrchestrator(cfg, stub_adapter, state=state)
        saved = orch.save_outputs()

        ext = _FORMAT_MAP[fmt][1]
        for layer in ("buildings", "streets", "parcels", "source"):
            assert layer in saved
            p = Path(saved[layer])
            assert p.exists()
            assert p.suffix == ext

    def test_skips_empty_and_none_frames(
        self, stub_adapter, tmp_path, fmt, buildings_gdf,
    ):
        """save_outputs only writes non-None, non-empty frames."""
        cfg = FHeatConfig(output_dir=str(tmp_path), output_format=fmt)
        state = PipelineState(phase=Phase.DOWNLOADED, buildings_gdf=buildings_gdf)
        # streets/parcels/source remain None
        orch = FHeatOrchestrator(cfg, stub_adapter, state=state)
        saved = orch.save_outputs()
        assert "buildings" in saved
        assert "streets" not in saved
        assert "parcels" not in saved
        assert "source" not in saved

    def test_rerun_overwrites_existing_file(
        self, stub_adapter, tmp_path, fmt, buildings_gdf,
    ):
        cfg = FHeatConfig(output_dir=str(tmp_path), output_format=fmt)
        state = PipelineState(phase=Phase.DOWNLOADED, buildings_gdf=buildings_gdf)
        orch = FHeatOrchestrator(cfg, stub_adapter, state=state)
        first = orch.save_outputs()
        # write again — must not raise even if file exists
        second = orch.save_outputs()
        assert first == second
        # round-trip readable
        loaded = gpd.read_file(second["buildings"])
        assert len(loaded) == len(buildings_gdf)


# ---------------------------------------------------------------------------
# output_language — canonical internal names vs German export labels
# ---------------------------------------------------------------------------


class TestOutputLanguage:
    def test_de_writes_german_labels(self, stub_adapter, tmp_path, buildings_gdf):
        """Default output_language='de' translates canonical columns back to
        the German display labels, so on-disk files stay unchanged."""
        cfg = FHeatConfig(output_dir=str(tmp_path), output_format="gpkg",
                          output_language="de")
        state = PipelineState(phase=Phase.DOWNLOADED, buildings_gdf=buildings_gdf)
        orch = FHeatOrchestrator(cfg, stub_adapter, state=state)
        saved = orch.save_outputs()

        loaded = gpd.read_file(saved["buildings"])
        assert cols.LABELS_DE[cols.HEAT_DEMAND] in loaded.columns  # "Waermebedarf [kWh/a]"
        assert cols.LABELS_DE[cols.THERMAL_POWER] in loaded.columns  # "Leistung_th [kW]"
        # canonical names must NOT leak into the German export
        assert cols.HEAT_DEMAND not in loaded.columns

    def test_raw_keeps_canonical_names(self, stub_adapter, tmp_path, buildings_gdf):
        cfg = FHeatConfig(output_dir=str(tmp_path), output_format="gpkg",
                          output_language="raw")
        state = PipelineState(phase=Phase.DOWNLOADED, buildings_gdf=buildings_gdf)
        orch = FHeatOrchestrator(cfg, stub_adapter, state=state)
        saved = orch.save_outputs()

        loaded = gpd.read_file(saved["buildings"])
        assert cols.HEAT_DEMAND in loaded.columns
        assert cols.THERMAL_POWER in loaded.columns
        assert cols.LABELS_DE[cols.HEAT_DEMAND] not in loaded.columns

    def test_invalid_language_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="output_language"):
            FHeatConfig(output_dir=str(tmp_path), output_language="fr")
