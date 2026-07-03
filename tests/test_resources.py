"""Tests for fheat_core.resources.

Covers the bundled-data loaders:
- load_pipe_info: returns the pipe catalogue used by network sizing
- load_default_temperature: 8760-hour outdoor temperature series
- load_default_holidays: dict[date → name]; falls back to {} if workalendar
  is missing.
"""
from __future__ import annotations

import datetime
import sys

import pandas as pd
import pytest

from fheat_core.resources import (
    load_default_holidays,
    load_default_temperature,
    load_pipe_info,
)


# ---------------------------------------------------------------------------
# load_pipe_info
# ---------------------------------------------------------------------------


class TestLoadPipeInfo:
    def test_returns_dataframe(self):
        df = load_pipe_info()
        assert isinstance(df, pd.DataFrame)
        assert not df.empty

    def test_required_columns(self):
        df = load_pipe_info()
        for col in ("DN", "di", "U-Value", "U-Value_extra_insulation", "max_volumeFlow"):
            assert col in df.columns, col

    def test_max_volumeflow_monotonically_increasing(self):
        """The pipe-sizing algorithm relies on max_volumeFlow being sorted."""
        df = load_pipe_info()
        assert df["max_volumeFlow"].is_monotonic_increasing

    def test_extra_insulation_lower_u_value(self):
        df = load_pipe_info()
        assert (df["U-Value_extra_insulation"] <= df["U-Value"]).all()

    def test_di_increases_with_volumeflow(self):
        """Inner diameter must grow as the flow tier grows."""
        df = load_pipe_info().sort_values("max_volumeFlow").reset_index(drop=True)
        assert df["di"].is_monotonic_increasing

    def test_compatible_with_calculate_diameter_velocity_loss(self):
        """Smoke test: real pipe_info works with the network algorithm."""
        from fheat_core.algorithms.network import calculate_diameter_velocity_loss

        df = load_pipe_info()
        dn, vel, loss, loss_extra = calculate_diameter_velocity_loss(
            volumeflow=0.5, htemp=80, ltemp=50, length=10.0,
            pipe_info=df, edge_type="Hausanschluss",
        )
        # DN may be a string label (e.g. "PEX 25") in the bundled catalogue
        assert dn is not None
        assert vel > 0
        assert loss > 0
        assert 0 <= loss_extra <= loss


# ---------------------------------------------------------------------------
# load_default_temperature
# ---------------------------------------------------------------------------


class TestLoadDefaultTemperature:
    def test_returns_series(self):
        s = load_default_temperature()
        assert isinstance(s, pd.Series)

    def test_length_8760(self):
        """One non-leap year of hourly samples."""
        s = load_default_temperature()
        assert len(s) == 8760

    def test_temperatures_in_plausible_range(self):
        """German reference year: outdoor temperatures roughly within [-30, +45] °C."""
        s = load_default_temperature()
        assert s.min() >= -30
        assert s.max() <= 45

    def test_no_nans(self):
        s = load_default_temperature()
        assert s.notna().all()


# ---------------------------------------------------------------------------
# load_default_holidays
# ---------------------------------------------------------------------------


class TestLoadDefaultHolidays:
    def test_returns_dict(self):
        h = load_default_holidays(2022)
        assert isinstance(h, dict)

    def test_keys_are_dates(self):
        h = load_default_holidays(2022)
        if h:  # only check if workalendar is available
            for k in h:
                assert isinstance(k, datetime.date)

    def test_neujahr_present_for_2022(self):
        h = load_default_holidays(2022)
        if h:
            assert datetime.date(2022, 1, 1) in h

    def test_year_filter(self):
        h = load_default_holidays(2022)
        if h:
            for d in h:
                assert d.year == 2022

    def test_missing_workalendar_returns_empty_dict(self, monkeypatch):
        """ImportError fallback path."""
        import builtins

        real_import = builtins.__import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if "workalendar" in name:
                raise ImportError("simulated missing workalendar")
            return real_import(name, globals, locals, fromlist, level)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        for mod in list(sys.modules):
            if mod.startswith("workalendar"):
                monkeypatch.delitem(sys.modules, mod, raising=False)

        h = load_default_holidays(2022)
        assert h == {}
