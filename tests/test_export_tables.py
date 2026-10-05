"""Tests for fheat_core.export.tables and FHeatConfig.table_format.

Covers:
- table_format=None writes exactly the same files as before.
- "csv": one file per table, German or canonical headers.
- "xlsx": one workbook with one sheet per table; pipe and building sheets end
  with a bold total row, CSV files do not.
- Missing openpyxl raises an actionable ImportError.
- A state before RESULTS writes no tables.
- Invalid table_format is rejected.
"""
from __future__ import annotations

import builtins
import sys
from pathlib import Path

import pandas as pd
import pytest

from fheat_core import columns as cols
from fheat_core.config import FHeatConfig
from fheat_core.export.tables import XLSX_FILENAME, XLSX_KEY, with_total_row, write_tables
from fheat_core.orchestrator import FHeatOrchestrator
from fheat_core.state import Phase, PipelineState


def _result_state(buildings_gdf) -> PipelineState:
    idx = pd.date_range("2022-01-01 00:00", periods=3, freq="h")
    return PipelineState(
        phase=Phase.RESULTS,
        buildings_gdf=buildings_gdf,
        load_profile_df=pd.DataFrame({cols.BUILDING_DEMAND_SUM: [1.0, 2.0, 3.0], cols.LOSS: 0.1}, index=idx),
        pipe_summary_df=pd.DataFrame(
            {
                cols.NOMINAL_DIAMETER: ["PEX 20", "PEX 25"],
                cols.N_HOUSE_CONNECTIONS: [3, 0],
                cols.HOUSE_CONNECTION_LENGTH: [30.0, 0.0],
                cols.ROUTE_LENGTH: [0.0, 120.0],
                cols.HEAT_LOSS_MWH: [1.5, 4.0],
                cols.HEAT_LOSS_EXTRA_INSULATION_MWH: [1.2, 3.2],
            }
        ),
        building_summary_df=pd.DataFrame(
            [("EFH", 2, 40.0), ("MFH", 1, 35.0)],
            columns=[cols.LOAD_PROFILE, cols.N_BUILDINGS, cols.HEAT_DEMAND_MWH],
        ),
        result_summary={"total_buildings": 3, "total_route_length_m": 120.0},
    )


def _save(tmp_path, stub_adapter, state, **cfg_kwargs):
    cfg = FHeatConfig(output_dir=str(tmp_path), **cfg_kwargs)
    return FHeatOrchestrator(cfg, stub_adapter, state=state).save_outputs()


class TestTableFormatNone:
    def test_writes_only_geodata(self, tmp_path, stub_adapter, buildings_gdf):
        saved = _save(tmp_path, stub_adapter, _result_state(buildings_gdf))
        assert set(saved) == {"buildings"}
        assert sorted(p.name for p in tmp_path.iterdir()) == ["buildings.gpkg"]


class TestCsv:
    def test_one_file_per_table_with_german_headers(self, tmp_path, stub_adapter, buildings_gdf):
        saved = _save(tmp_path, stub_adapter, _result_state(buildings_gdf), table_format="csv")
        for name in ("ergebnisuebersicht", "rohrmengen", "gebaeude_lastprofil", "lastprofil"):
            assert Path(saved[name]).name == f"{name}.csv"

        pipes = pd.read_csv(saved["rohrmengen"])
        assert len(pipes) == 2  # plain data, no total row
        assert list(pipes.columns) == [
            "DN [mm]",
            "Anzahl Hausanschluesse",
            "Hausanschlusslaenge [m]",
            "Trassenlaenge [m]",
            "Verlust [MWh/a]",
            "Verlust bei extra Daemmung [MWh/a]",
        ]
        buildings = pd.read_csv(saved["gebaeude_lastprofil"])
        assert list(buildings.columns) == ["Lastprofil", "Anzahl Gebaeude", "Waermebedarf [MWh/a]"]

        summary = pd.read_csv(saved["ergebnisuebersicht"], encoding="utf-8")
        assert list(summary.columns) == ["Kennzahl", "Wert"]
        assert "Trassenlänge [m]" in set(summary["Kennzahl"])

        load = pd.read_csv(saved["lastprofil"])
        assert load.columns[0] == "Zeit"
        assert cols.LABELS_DE[cols.BUILDING_DEMAND_SUM] in load.columns

    def test_raw_keeps_canonical_headers(self, tmp_path, stub_adapter, buildings_gdf):
        saved = _save(
            tmp_path, stub_adapter, _result_state(buildings_gdf), table_format="csv", output_language="raw"
        )
        assert list(pd.read_csv(saved["rohrmengen"]).columns)[:2] == [
            cols.NOMINAL_DIAMETER,
            cols.N_HOUSE_CONNECTIONS,
        ]
        summary = pd.read_csv(saved["ergebnisuebersicht"])
        assert list(summary.columns) == ["key", "value"]
        assert "total_route_length_m" in set(summary["key"])
        assert pd.read_csv(saved["lastprofil"]).columns[0] == "time"

    def test_state_before_results_writes_no_tables(self, tmp_path, stub_adapter, buildings_gdf):
        state = PipelineState(phase=Phase.DOWNLOADED, buildings_gdf=buildings_gdf)
        saved = _save(tmp_path, stub_adapter, state, table_format="csv")
        assert set(saved) == {"buildings"}
        assert not list(tmp_path.glob("*.csv"))


class TestXlsx:
    def test_workbook_with_one_sheet_per_table(self, tmp_path, stub_adapter, buildings_gdf):
        openpyxl = pytest.importorskip("openpyxl")
        saved = _save(tmp_path, stub_adapter, _result_state(buildings_gdf), table_format="xlsx")
        path = Path(saved[XLSX_KEY])
        assert path.name == XLSX_FILENAME

        workbook = openpyxl.load_workbook(path)
        assert workbook.sheetnames == ["Übersicht", "Rohre", "Statistiken", "Lastprofil"]
        header = [cell.value for cell in workbook["Rohre"][1]]
        assert header[:2] == ["DN [mm]", "Anzahl Hausanschluesse"]

    def test_raw_keeps_canonical_headers(self, tmp_path, stub_adapter, buildings_gdf):
        openpyxl = pytest.importorskip("openpyxl")
        saved = _save(
            tmp_path, stub_adapter, _result_state(buildings_gdf), table_format="xlsx", output_language="raw"
        )
        workbook = openpyxl.load_workbook(saved[XLSX_KEY])
        # sheet names are file-level names and stay the same; only column labels follow output_language
        assert workbook.sheetnames == ["Übersicht", "Rohre", "Statistiken", "Lastprofil"]
        assert [c.value for c in workbook["Rohre"][1]][:2] == [cols.NOMINAL_DIAMETER, cols.N_HOUSE_CONNECTIONS]
        assert [c.value for c in workbook["Statistiken"][1]] == [
            cols.LOAD_PROFILE,
            cols.N_BUILDINGS,
            cols.HEAT_DEMAND_MWH,
        ]
        assert [c.value for c in workbook["Übersicht"][1]] == ["key", "value"]
        assert workbook["Lastprofil"]["A1"].value == "time"
        assert workbook["Rohre"].cell(workbook["Rohre"].max_row, 1).value == "total"

    def test_pipe_and_building_sheets_end_with_bold_total_row(self, tmp_path, stub_adapter, buildings_gdf):
        openpyxl = pytest.importorskip("openpyxl")
        state = _result_state(buildings_gdf)
        saved = _save(tmp_path, stub_adapter, state, table_format="xlsx")
        workbook = openpyxl.load_workbook(saved[XLSX_KEY])

        pipes = workbook["Rohre"]
        last = [cell.value for cell in pipes[pipes.max_row]]
        assert last[:2] == ["Gesamt", 3]
        assert last[2:] == pytest.approx([30.0, 120.0, 5.5, 4.4])
        assert all(cell.font.bold for cell in pipes[pipes.max_row])
        assert pipes.max_row == 1 + 2 + 1  # header + 2 DN rows + total

        buildings = workbook["Statistiken"]
        last = [cell.value for cell in buildings[buildings.max_row]]
        assert last[:2] == ["Gesamt", 3]
        assert last[2] == pytest.approx(75.0)

        # the other sheets get no total row, and the state tables stay untouched
        assert workbook["Übersicht"].cell(workbook["Übersicht"].max_row, 1).value != "Gesamt"
        assert workbook["Lastprofil"].max_row == 1 + 3
        assert len(state.pipe_summary_df) == 2
        assert len(state.building_summary_df) == 2

    def test_timezone_aware_index_is_written(self, tmp_path, buildings_gdf):
        pytest.importorskip("openpyxl")
        state = _result_state(buildings_gdf)
        state.load_profile_df.index = state.load_profile_df.index.tz_localize("Europe/Berlin")
        saved = write_tables(state, tmp_path, "xlsx", translate=True)
        loaded = pd.read_excel(saved[XLSX_KEY], sheet_name="Lastprofil")
        assert len(loaded) == 3

    def test_rerun_overwrites_workbook(self, tmp_path, buildings_gdf):
        pytest.importorskip("openpyxl")
        state = _result_state(buildings_gdf)
        first = write_tables(state, tmp_path, "xlsx", translate=True)
        second = write_tables(state, tmp_path, "xlsx", translate=True)
        assert first == second

    def test_missing_openpyxl_raises_install_hint(self, tmp_path, buildings_gdf, monkeypatch):
        real_import = builtins.__import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name.startswith("openpyxl"):
                raise ImportError("simulated missing openpyxl")
            return real_import(name, globals, locals, fromlist, level)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        for mod in list(sys.modules):
            if mod.startswith("openpyxl"):
                monkeypatch.delitem(sys.modules, mod, raising=False)

        with pytest.raises(ImportError, match=r"fheat\[excel\]"):
            write_tables(_result_state(buildings_gdf), tmp_path, "xlsx", translate=True)


class TestWithTotalRow:
    def test_sums_numeric_columns_and_labels_first_column(self):
        frame = pd.DataFrame({"DN": [20, 25], "n": [1, 2], "len": [1.5, 2.5], "note": ["a", "b"]})
        result = with_total_row(frame, "Gesamt")
        assert len(result) == 3
        assert result.iloc[-1]["DN"] == "Gesamt"
        assert result.iloc[-1]["n"] == 3
        assert result.iloc[-1]["len"] == pytest.approx(4.0)
        assert pd.isna(result.iloc[-1]["note"])
        assert len(frame) == 2  # input not modified

    def test_missing_load_profile_row_is_included(self):
        frame = pd.DataFrame(
            [("EFH", 2, 40.0), (pd.NA, 1, 5.0)],
            columns=[cols.LOAD_PROFILE, cols.N_BUILDINGS, cols.HEAT_DEMAND_MWH],
        )
        total = with_total_row(frame, "Gesamt").iloc[-1]
        assert total[cols.N_BUILDINGS] == 3
        assert total[cols.HEAT_DEMAND_MWH] == pytest.approx(45.0)


class TestConfig:
    def test_default_is_none(self, tmp_path):
        assert FHeatConfig(output_dir=str(tmp_path)).table_format is None

    @pytest.mark.parametrize("value", ["csv", "xlsx"])
    def test_allowed_values(self, tmp_path, value):
        assert FHeatConfig(output_dir=str(tmp_path), table_format=value).table_format == value

    def test_invalid_value_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="table_format"):
            FHeatConfig(output_dir=str(tmp_path), table_format="ods")
