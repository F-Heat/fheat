"""Tests for fheat_core.export.plots and FHeatConfig.plot_format.

Covers:
- chart_series: time order vs. sorted descending, loss moves with its hour.
- render_charts: four figures from a load profile, none before RESULTS.
- write_charts / save_outputs: png and svg files with the plugin's names;
  plot_format=None writes nothing.
- xlsx: charts embedded in the Lastprofil sheet only when charts are drawn.
- Missing matplotlib raises an actionable ImportError.
- Invalid plot_format is rejected.
"""
from __future__ import annotations

import builtins
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from fheat_core import columns as cols
from fheat_core.config import FHeatConfig
from fheat_core.export.plots import CHARTS, chart_series, render_charts, write_charts
from fheat_core.export.tables import XLSX_KEY
from fheat_core.orchestrator import FHeatOrchestrator
from fheat_core.state import Phase, PipelineState

CHART_NAMES = ["Lastprofil", "Lastprofil_geordnet", "Lastprofil_extra_Daemmung", "Lastprofil_extra_Daemmung_geordnet"]


def _load_profile(hours: int = 48) -> pd.DataFrame:
    idx = pd.date_range("2022-01-01 00:00", periods=hours, freq="h")
    demand = 1.0 + np.sin(np.arange(hours) / 4.0) ** 2
    return pd.DataFrame(
        {
            cols.BUILDING_DEMAND_SUM: demand,
            cols.LOSS: 0.1,
            cols.LOSS_EXTRA_INSULATION: 0.08,
            cols.TOTAL: demand + 0.1,
            cols.TOTAL_EXTRA_INSULATION: demand + 0.08,
        },
        index=idx,
    )


def _state(buildings_gdf) -> PipelineState:
    return PipelineState(phase=Phase.RESULTS, buildings_gdf=buildings_gdf, load_profile_df=_load_profile())


def _spec(name):
    return next(spec for spec in CHARTS if spec.name == name)


class TestChartSeries:
    def test_time_order_is_kept(self):
        lp = _load_profile()
        total, loss = chart_series(lp, _spec("Lastprofil"))
        np.testing.assert_allclose(total, lp[cols.TOTAL].to_numpy())
        np.testing.assert_allclose(loss, lp[cols.LOSS].to_numpy())

    def test_ordered_chart_is_sorted_descending(self):
        lp = _load_profile()
        total, _ = chart_series(lp, _spec("Lastprofil_geordnet"))
        assert (np.diff(total) <= 0).all()
        assert total[0] == pytest.approx(lp[cols.TOTAL].max())

    def test_loss_moves_with_its_hour(self):
        lp = _load_profile()
        lp[cols.LOSS] = np.arange(len(lp), dtype=float)  # unique loss per hour
        total, loss = chart_series(lp, _spec("Lastprofil_geordnet"))
        hour_of_peak = int(lp[cols.TOTAL].to_numpy().argmax())
        assert loss[0] == hour_of_peak

    def test_extra_insulation_charts_use_extra_insulation_columns(self):
        lp = _load_profile()
        _, loss = chart_series(lp, _spec("Lastprofil_extra_Daemmung"))
        np.testing.assert_allclose(loss, lp[cols.LOSS_EXTRA_INSULATION].to_numpy())


class TestRenderAndWrite:
    def test_four_charts_with_plugin_names(self, buildings_gdf):
        pytest.importorskip("matplotlib")
        figures = render_charts(_state(buildings_gdf))
        assert list(figures) == CHART_NAMES

    def test_no_charts_before_results(self, buildings_gdf):
        assert render_charts(PipelineState(phase=Phase.DOWNLOADED, buildings_gdf=buildings_gdf)) == {}

    @pytest.mark.parametrize("fmt, magic", [("png", b"\x89PNG"), ("svg", b"<?xml")])
    def test_writes_files(self, tmp_path, buildings_gdf, fmt, magic):
        pytest.importorskip("matplotlib")
        saved = write_charts(render_charts(_state(buildings_gdf)), tmp_path, fmt)
        assert sorted(Path(p).name for p in saved.values()) == sorted(f"{n}.{fmt}" for n in CHART_NAMES)
        for path in saved.values():
            assert Path(path).read_bytes().startswith(magic)

    def test_save_outputs_writes_charts(self, tmp_path, stub_adapter, buildings_gdf):
        pytest.importorskip("matplotlib")
        cfg = FHeatConfig(output_dir=str(tmp_path), plot_format="png")
        saved = FHeatOrchestrator(cfg, stub_adapter, state=_state(buildings_gdf)).save_outputs()
        assert Path(saved["grafik_lastprofil"]).name == "Lastprofil.png"
        assert len([key for key in saved if key.startswith("grafik_")]) == 4

    def test_plot_format_none_writes_no_charts(self, tmp_path, stub_adapter, buildings_gdf):
        cfg = FHeatConfig(output_dir=str(tmp_path))
        saved = FHeatOrchestrator(cfg, stub_adapter, state=_state(buildings_gdf)).save_outputs()
        assert not [key for key in saved if key.startswith("grafik_")]
        assert not list(tmp_path.glob("*.png"))


class TestExcelEmbedding:
    def test_charts_embedded_in_load_profile_sheet(self, tmp_path, stub_adapter, buildings_gdf):
        pytest.importorskip("matplotlib")
        openpyxl = pytest.importorskip("openpyxl")
        cfg = FHeatConfig(output_dir=str(tmp_path), table_format="xlsx", plot_format="png")
        saved = FHeatOrchestrator(cfg, stub_adapter, state=_state(buildings_gdf)).save_outputs()

        sheet = openpyxl.load_workbook(saved[XLSX_KEY])["Lastprofil"]
        assert len(sheet._images) == 4
        # one empty column after the data (Zeit + 5 columns), then a chart every 22 rows
        anchors = [(img.anchor._from.col, img.anchor._from.row) for img in sheet._images]
        assert anchors == [(7, 0), (7, 22), (7, 44), (7, 66)]

    def test_no_charts_in_workbook_without_plot_format(self, tmp_path, stub_adapter, buildings_gdf):
        openpyxl = pytest.importorskip("openpyxl")
        cfg = FHeatConfig(output_dir=str(tmp_path), table_format="xlsx")
        saved = FHeatOrchestrator(cfg, stub_adapter, state=_state(buildings_gdf)).save_outputs()
        assert openpyxl.load_workbook(saved[XLSX_KEY])["Lastprofil"]._images == []


class TestMissingMatplotlib:
    def test_raises_install_hint(self, buildings_gdf, monkeypatch):
        real_import = builtins.__import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name.startswith("matplotlib"):
                raise ImportError("simulated missing matplotlib")
            return real_import(name, globals, locals, fromlist, level)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        for mod in list(sys.modules):
            if mod.startswith("matplotlib"):
                monkeypatch.delitem(sys.modules, mod, raising=False)

        with pytest.raises(ImportError, match=r"fheat\[plots\]"):
            render_charts(_state(buildings_gdf))


class TestConfig:
    def test_default_is_none(self, tmp_path):
        assert FHeatConfig(output_dir=str(tmp_path)).plot_format is None

    @pytest.mark.parametrize("value", ["png", "svg"])
    def test_allowed_values(self, tmp_path, value):
        assert FHeatConfig(output_dir=str(tmp_path), plot_format=value).plot_format == value

    def test_invalid_value_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="plot_format"):
            FHeatConfig(output_dir=str(tmp_path), plot_format="pdf")
