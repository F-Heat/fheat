"""Tests for the outdoor temperatures of the RESULTS step.

Order of the sources: the adapter's series, the DWD year
(``temperature_source="dwd"``), the example year. The DWD loader is
replaced, so no network is needed.
"""
from __future__ import annotations

import logging

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from fheat_core import columns as cols
from fheat_core.config import FHeatConfig
from fheat_core.state import PipelineState
from fheat_core.steps import adjust, download, network, results, status
from fheat_core.weather import TemperatureYear, WeatherDataError

from tests.conftest import StubAdapter

CRS = "EPSG:25832"


def _cfg(tmp_path, **kwargs):
    return FHeatConfig(buffer_distance=15.0, year=2022, output_dir=str(tmp_path), **kwargs)


def _network_state(adapter, cfg) -> PipelineState:
    state = PipelineState()
    for step in (download, adjust, status, network):
        step.run(state, cfg, adapter)
    return state


def _dwd_year(year=2022, value=4.0):
    hours = pd.date_range(f"{year}-01-01", f"{year}-12-31 23:00", freq="h")
    return TemperatureYear(
        series=pd.Series(value, index=hours), source="dwd",
        station_id="01766", station_name="Münster/Osnabrück", distance_km=24.4, coverage=0.99,
    )


@pytest.fixture
def adapter_without_temperature(buildings_gdf, streets_gdf, parcels_gdf, source_gdf, pipe_info_df):
    return StubAdapter(buildings_gdf, streets_gdf, parcels_gdf, source_gdf, pipe_info=pipe_info_df, holidays={})


@pytest.fixture
def dwd_calls(monkeypatch):
    """Replace the DWD loader; set ``dwd_calls.answer`` to a TemperatureYear or an exception."""

    class Calls(list):
        answer = _dwd_year()

    calls = Calls()

    def fake(lat, lon, year):
        calls.append((lat, lon, year))
        if isinstance(calls.answer, Exception):
            raise calls.answer
        return calls.answer

    monkeypatch.setattr(results, "load_dwd_temperature", fake)
    return calls


class TestOrder:
    def test_adapter_series_wins(self, stub_adapter, dwd_calls, tmp_path):
        cfg = _cfg(tmp_path, temperature_source="dwd")
        state = results.run(_network_state(stub_adapter, cfg), cfg, stub_adapter)
        assert dwd_calls == []
        assert state.result_summary[cols.TEMPERATURE_SOURCE] == "adapter"
        assert cols.WEATHER_STATION_ID not in state.result_summary
        assert state.temperature_info["source"] == "adapter"

    def test_dwd_year_with_station_keys(self, adapter_without_temperature, dwd_calls, tmp_path):
        cfg = _cfg(tmp_path, temperature_source="dwd")
        state = results.run(_network_state(adapter_without_temperature, cfg), cfg, adapter_without_temperature)
        assert len(dwd_calls) == 1
        assert dwd_calls[0][2] == 2022
        s = state.result_summary
        assert s[cols.TEMPERATURE_SOURCE] == "dwd"
        assert s[cols.WEATHER_STATION_ID] == "01766"
        assert s[cols.WEATHER_STATION_NAME] == "Münster/Osnabrück"
        assert s[cols.WEATHER_STATION_DISTANCE] == 24.4
        assert s[cols.WEATHER_YEAR] == 2022
        assert s[cols.MEAN_OUTDOOR_TEMPERATURE] == 4.0
        assert s[cols.MIN_OUTDOOR_TEMPERATURE] == 4.0
        assert s[cols.HEATING_DEGREE_DAYS] == 365 * 16
        assert cols.TEMPERATURE_FALLBACK_REASON not in s
        assert state.temperature_info == {
            "source": "dwd", "station_id": "01766", "station_name": "Münster/Osnabrück",
            "distance_km": 24.4, "coverage": 0.99, "year": 2022, "fallback_reason": None,
        }

    def test_example_year_by_default(self, adapter_without_temperature, dwd_calls, tmp_path):
        cfg = _cfg(tmp_path)
        state = results.run(_network_state(adapter_without_temperature, cfg), cfg, adapter_without_temperature)
        assert dwd_calls == []
        s = state.result_summary
        assert s[cols.TEMPERATURE_SOURCE] == "example"
        assert cols.WEATHER_YEAR not in s
        assert cols.TEMPERATURE_FALLBACK_REASON not in s
        assert -30 < s[cols.MIN_OUTDOOR_TEMPERATURE] < s[cols.MEAN_OUTDOOR_TEMPERATURE] < 20


class TestFallback:
    def test_failed_dwd_request_falls_back_with_a_warning(
        self, adapter_without_temperature, dwd_calls, tmp_path, caplog
    ):
        dwd_calls.answer = WeatherDataError("DWD server down")
        cfg = _cfg(tmp_path, temperature_source="dwd")
        with caplog.at_level(logging.WARNING, logger="fheat_core.steps.results"):
            state = results.run(_network_state(adapter_without_temperature, cfg), cfg, adapter_without_temperature)
        assert "DWD server down" in caplog.text
        s = state.result_summary
        assert s[cols.TEMPERATURE_SOURCE] == "example"
        assert s[cols.TEMPERATURE_FALLBACK_REASON] == "DWD server down"
        assert cols.WEATHER_STATION_ID not in s
        assert state.temperature_info["fallback_reason"] == "DWD server down"

    def test_missing_package_falls_back_too(self, adapter_without_temperature, dwd_calls, tmp_path):
        dwd_calls.answer = ImportError('pip install "fheat[dwd]"')
        cfg = _cfg(tmp_path, temperature_source="dwd")
        state = results.run(_network_state(adapter_without_temperature, cfg), cfg, adapter_without_temperature)
        assert "fheat[dwd]" in state.result_summary[cols.TEMPERATURE_FALLBACK_REASON]

    def test_without_fallback_the_error_stops_the_step(self, adapter_without_temperature, dwd_calls, tmp_path):
        dwd_calls.answer = WeatherDataError("DWD server down")
        cfg = _cfg(tmp_path, temperature_source="dwd", temperature_fallback=False)
        state = _network_state(adapter_without_temperature, cfg)
        with pytest.raises(WeatherDataError):
            results.run(state, cfg, adapter_without_temperature)


class TestPlace:
    # Burgsteinfurt in UTM 32N
    X, Y = 386_150.0, 5_778_800.0

    def _frame(self, x, y):
        return gpd.GeoDataFrame(geometry=[box(x - 500, y - 500, x + 500, y + 500)], crs=CRS)

    def test_centre_of_the_planning_area(self):
        lat, lon = results._area_centre(self._frame(self.X, self.Y), self._frame(0, 0))
        assert lat == pytest.approx(52.15, abs=0.01)
        assert lon == pytest.approx(7.34, abs=0.01)

    def test_buildings_without_planning_area(self):
        lat, lon = results._area_centre(None, self._frame(self.X, self.Y))
        assert lat == pytest.approx(52.15, abs=0.01)

    def test_unknown_place_raises(self):
        buildings = gpd.GeoDataFrame(geometry=[box(0, 0, 1, 1)])
        with pytest.raises(WeatherDataError, match="place"):
            results._area_centre(None, buildings)


def test_config_rejects_unknown_source(tmp_path):
    with pytest.raises(ValueError, match="temperature_source"):
        _cfg(tmp_path, temperature_source="try")
