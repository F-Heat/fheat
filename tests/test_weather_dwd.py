"""Tests for fheat_core.weather.dwd.load_dwd_temperature.

wetterdienst is replaced by a fake request (station list + values as pandas
frames), so the tests need neither the package nor the network. One test
against the real DWD server carries the marker ``network`` and only runs
with ``pytest -m network``.
"""
from __future__ import annotations

import sys
from datetime import date

import numpy as np
import pandas as pd
import pytest

from fheat_core.weather import TemperatureYear, WeatherDataError, dwd, heating_degree_days, load_dwd_temperature

LAT, LON = 52.15, 7.34  # Burgsteinfurt


class _Frame:
    def __init__(self, df):
        self.df = df


class _Values:
    def __init__(self, df):
        self._df = df

    def all(self):
        return _Frame(self._df)


class _Stations:
    def __init__(self, df):
        self._df = df

    def values(self):
        return _Values(self._df)


class FakeRequest:
    """Answers like a DwdObservationRequest of wetterdienst, from pandas frames."""

    def __init__(self, stations: pd.DataFrame, values: dict[str, pd.DataFrame]):
        self.stations = stations
        self.values = values
        self.station_calls = 0
        self.value_calls: list[str] = []

    def filter_by_distance(self, latlon, distance):
        self.station_calls += 1
        return _Frame(self.stations[self.stations["distance"] <= distance])

    def filter_by_station_id(self, station_id):
        (sid,) = station_id
        self.value_calls.append(sid)
        return _Stations(self.values[sid])


def _stations(*rows):
    """rows: (station_id, name, distance_km[, start, end])."""
    records = []
    for row in rows:
        sid, name, distance, *period = row
        start, end = period or ("1990-01-01", "2026-10-26")
        records.append({
            "station_id": sid, "name": name, "distance": distance,
            "start_timestamp": pd.Timestamp(start, tz="UTC"), "end_timestamp": pd.Timestamp(end, tz="UTC"),
        })
    return pd.DataFrame(records)


def _utc_values(year, value=lambda hours: np.arange(len(hours), dtype=float), drop=None):
    """Hourly UTC values from 31 Dec of the year before to 1 Jan after, ``drop`` = UTC hours left out."""
    hours = pd.date_range(f"{year - 1}-12-31", f"{year + 1}-01-01 23:00", freq="h", tz="UTC")
    df = pd.DataFrame({"timestamp": hours, "value": value(hours)})
    if drop is not None:
        df = df[~df["timestamp"].isin(drop)]
    return df.reset_index(drop=True)


@pytest.fixture
def fake(monkeypatch):
    """Install a FakeRequest; returns a setter for its stations and values."""
    holder = {}

    def install(stations, values):
        holder["request"] = FakeRequest(stations, values)
        return holder["request"]

    monkeypatch.setattr(dwd, "_request", lambda year, wd_cache: holder["request"])
    return install


class TestTimeAxis:
    def test_utc_is_shifted_to_cet_and_cut_to_the_year(self, fake, tmp_path):
        fake(_stations(("01766", "Münster/Osnabrück", 24.4)), {"01766": _utc_values(2023)})
        result = load_dwd_temperature(LAT, LON, 2023, cache_dir=tmp_path)
        assert isinstance(result, TemperatureYear)
        assert len(result.series) == 8760
        assert result.series.index[0] == pd.Timestamp("2023-01-01 00:00")
        assert result.series.index[-1] == pd.Timestamp("2023-12-31 23:00")
        # 01-01 00:00 CET is 31-12 23:00 UTC, the 23rd value of the fake
        assert result.series.iloc[0] == 23.0
        assert result.source == "dwd"
        assert result.station_id == "01766"
        assert result.station_name == "Münster/Osnabrück"
        assert result.distance_km == 24.4
        assert result.coverage == 1.0

    def test_leap_year_has_8784_hours(self, fake, tmp_path):
        fake(_stations(("01766", "Münster/Osnabrück", 24.4)), {"01766": _utc_values(2024)})
        result = load_dwd_temperature(LAT, LON, 2024, cache_dir=tmp_path)
        assert len(result.series) == 8784
        assert pd.Timestamp("2024-02-29 12:00") in result.series.index


class TestGaps:
    def test_short_gap_is_interpolated_linearly(self, fake, tmp_path):
        gap = pd.date_range("2023-03-01 10:00", periods=3, freq="h", tz="UTC")
        fake(_stations(("A", "A", 5.0)), {"A": _utc_values(2023, drop=gap)})
        series = load_dwd_temperature(LAT, LON, 2023, cache_dir=tmp_path).series
        # the fake counts up by one per hour, so linear filling restores it
        cet = gap.tz_convert(None) + pd.Timedelta(hours=1)
        before = series[cet[0] - pd.Timedelta(hours=1)]
        assert list(series[cet]) == [before + 1, before + 2, before + 3]

    def test_long_gap_is_filled_from_the_next_station(self, fake, tmp_path):
        gap = pd.date_range("2023-03-01 10:00", periods=12, freq="h", tz="UTC")
        request = fake(
            _stations(("A", "A", 5.0), ("B", "B", 12.0)),
            {
                "A": _utc_values(2023, drop=gap),
                "B": _utc_values(2023, value=lambda hours: np.full(len(hours), -3.0)),
            },
        )
        result = load_dwd_temperature(LAT, LON, 2023, cache_dir=tmp_path)
        cet = gap.tz_convert(None) + pd.Timedelta(hours=1)
        assert (result.series[cet] == -3.0).all()
        assert result.station_id == "A"
        assert result.coverage == pytest.approx(1 - 12 / 8760, abs=1e-4)
        assert request.value_calls == ["A", "B"]

    def test_low_coverage_takes_the_next_station(self, fake, tmp_path):
        half = pd.date_range("2023-01-01", "2023-07-01", freq="h", tz="UTC")
        fake(
            _stations(("A", "A", 5.0), ("B", "B", 12.0)),
            {"A": _utc_values(2023, drop=half), "B": _utc_values(2023)},
        )
        result = load_dwd_temperature(LAT, LON, 2023, cache_dir=tmp_path)
        assert result.station_id == "B"
        assert result.distance_km == 12.0

    def test_station_outside_the_year_is_not_asked(self, fake, tmp_path):
        request = fake(
            _stations(("OLD", "closed", 3.0, "1990-01-01", "2017-12-20"), ("B", "B", 12.0)),
            {"B": _utc_values(2023)},
        )
        assert load_dwd_temperature(LAT, LON, 2023, cache_dir=tmp_path).station_id == "B"
        assert request.value_calls == ["B"]

    def test_unfillable_gap_raises(self, fake, tmp_path):
        gap = pd.date_range("2023-03-01 10:00", periods=12, freq="h", tz="UTC")
        fake(_stations(("A", "A", 5.0)), {"A": _utc_values(2023, drop=gap)})
        with pytest.raises(WeatherDataError, match="12 hours"):
            load_dwd_temperature(LAT, LON, 2023, cache_dir=tmp_path)

    def test_no_station_in_range_raises(self, fake, tmp_path):
        fake(_stations(("FAR", "far", 80.0)), {})
        with pytest.raises(WeatherDataError, match="No DWD station"):
            load_dwd_temperature(LAT, LON, 2023, cache_dir=tmp_path)

    def test_request_error_becomes_weather_data_error(self, monkeypatch, tmp_path):
        class Broken:
            def filter_by_distance(self, latlon, distance):
                raise OSError("connection refused")

        monkeypatch.setattr(dwd, "_request", lambda year, wd_cache: Broken())
        with pytest.raises(WeatherDataError, match="connection refused"):
            load_dwd_temperature(LAT, LON, 2023, cache_dir=tmp_path)


class TestCache:
    def test_second_call_does_not_ask_wetterdienst(self, fake, tmp_path, monkeypatch):
        fake(_stations(("01766", "Münster/Osnabrück", 24.4)), {"01766": _utc_values(2023)})
        first = load_dwd_temperature(LAT, LON, 2023, cache_dir=tmp_path)
        assert (tmp_path / "dwd" / "tt_01766_2023.csv").exists()
        assert (tmp_path / "dwd" / "tt_01766_2023.json").exists()

        def no_request(year, wd_cache):
            raise AssertionError("wetterdienst asked again")

        monkeypatch.setattr(dwd, "_request", no_request)
        second = load_dwd_temperature(LAT + 0.001, LON, 2023, cache_dir=tmp_path)
        pd.testing.assert_series_equal(first.series, second.series, check_freq=False)
        assert second.station_name == "Münster/Osnabrück"
        assert second.distance_km == 24.4

    def test_other_place_reuses_the_station_year(self, fake, tmp_path):
        fake(_stations(("01766", "Münster/Osnabrück", 24.4)), {"01766": _utc_values(2023)})
        load_dwd_temperature(LAT, LON, 2023, cache_dir=tmp_path)
        request = fake(_stations(("01766", "Münster/Osnabrück", 9.0)), {"01766": _utc_values(2023)})
        result = load_dwd_temperature(52.0, 7.6, 2023, cache_dir=tmp_path)
        assert request.station_calls == 1
        assert request.value_calls == []
        assert result.distance_km == 9.0


class TestRefusals:
    def test_current_year_raises(self, tmp_path):
        with pytest.raises(WeatherDataError, match="not finished"):
            load_dwd_temperature(LAT, LON, date.today().year, cache_dir=tmp_path)

    def test_missing_package_names_the_extra(self, monkeypatch, tmp_path):
        monkeypatch.setitem(sys.modules, "wetterdienst", None)
        with pytest.raises(ImportError, match=r"fheat\[dwd\]"):
            load_dwd_temperature(LAT, LON, 2023, cache_dir=tmp_path)


class TestHeatingDegreeDays:
    def test_only_days_below_the_heating_limit_count(self):
        # 10 days at 5 °C (15 K each) and 10 days at 18 °C (above 15 °C)
        series = pd.Series([5.0] * 240 + [18.0] * 240)
        assert heating_degree_days(series) == pytest.approx(150.0)


@pytest.mark.network
def test_real_dwd_year(tmp_path):
    pytest.importorskip("wetterdienst")
    result = load_dwd_temperature(LAT, LON, 2023, cache_dir=tmp_path)
    assert result.distance_km < 30
    assert len(result.series) == 8760
    assert 9.0 < result.series.mean() < 13.0
