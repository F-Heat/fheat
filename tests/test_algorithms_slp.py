"""Tests for fheat_core.algorithms.slp.build_load_profile.

Covers:
- 8760-row DatetimeIndex output, schema-required columns present
- Building-type columns are added per unique Lastprofil
- Loss aggregation: net_gdf['Verlust [kWh/a]'].sum() / 8760 distributed
  uniformly across all hours (regression test for the .sum() vs .max() bug)
- Gesamtsumme = Summe aller Gebäudetypen + Verlust per row
- Empty/missing-loss columns fall back to zero
- ImportError surfaces clearly if demandlib is unavailable
"""
from __future__ import annotations

import datetime
import sys

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Polygon

from fheat_core import columns as cols
from fheat_core.algorithms import slp as slp_module
from fheat_core.algorithms.slp import build_load_profile


CRS = "EPSG:25832"


@pytest.fixture
def buildings_with_lastprofil():
    """Three buildings: 2× EFH, 1× MFH — covers the EFH/MFH branch."""
    polys = [
        Polygon([(0, 0), (10, 0), (10, 10), (0, 10)]),
        Polygon([(20, 0), (30, 0), (30, 10), (20, 10)]),
        Polygon([(40, 0), (50, 0), (50, 10), (40, 10)]),
    ]
    return gpd.GeoDataFrame(
        {
            cols.HEAT_DEMAND: [10000.0, 12000.0, 25000.0],
            cols.LOAD_PROFILE: ["EFH", "EFH", "MFH"],
            "geometry": polys,
        },
        crs=CRS, geometry="geometry",
    )


@pytest.fixture
def net_with_loss():
    """Loss values scaled large enough that per-hour value is well above
    the 3-decimal rounding applied by build_load_profile."""
    return pd.DataFrame(
        {
            # sum = 8 760 000 kWh = 8 760 MWh → per-hour = 1.0 MWh
            cols.HEAT_LOSS: [1_000_000.0, 2_000_000.0, 5_760_000.0],
            # sum = 4 380 000 kWh = 4 380 MWh → per-hour = 0.5 MWh
            cols.HEAT_LOSS_EXTRA_INSULATION: [500_000.0, 1_000_000.0, 2_880_000.0],
        }
    )


# ---------------------------------------------------------------------------
# Schema / structural tests
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestStructure:
    def test_returns_8760_hourly_dataframe(
        self, buildings_with_lastprofil, net_with_loss, temperature_series
    ):
        df = build_load_profile(
            buildings_gdf=buildings_with_lastprofil,
            net_gdf=net_with_loss,
            year=2022,
            temperature=temperature_series,
            holidays={},
            building_class=3,
            wind_class=1,
        )
        assert len(df) == 8760
        assert isinstance(df.index, pd.DatetimeIndex)
        assert df.index[0] == pd.Timestamp("2022-01-01 00:00")
        assert df.index[-1] == pd.Timestamp("2022-12-31 23:00")

    def test_required_columns_present(
        self, buildings_with_lastprofil, net_with_loss, temperature_series
    ):
        df = build_load_profile(
            buildings_gdf=buildings_with_lastprofil,
            net_gdf=net_with_loss,
            year=2022,
            temperature=temperature_series,
            holidays={},
            building_class=3,
            wind_class=1,
        )
        for col in (
            cols.BUILDING_DEMAND_SUM,
            cols.LOSS,
            cols.LOSS_EXTRA_INSULATION,
            cols.TOTAL,
            cols.TOTAL_EXTRA_INSULATION,
        ):
            assert col in df.columns

    def test_per_lastprofil_columns_added(
        self, buildings_with_lastprofil, net_with_loss, temperature_series
    ):
        df = build_load_profile(
            buildings_gdf=buildings_with_lastprofil,
            net_gdf=net_with_loss,
            year=2022,
            temperature=temperature_series,
            holidays={},
            building_class=3,
            wind_class=1,
        )
        assert "EFH" in df.columns
        assert "MFH" in df.columns


# ---------------------------------------------------------------------------
# Loss aggregation — regression test for .sum() vs .max() bug
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestLossAggregation:
    def test_loss_uses_sum_not_max(
        self, buildings_with_lastprofil, net_with_loss, temperature_series
    ):
        """Network loss is evenly distributed across 8760 h.

        Per-hour = sum(Verlust) / 1000 / 8760  →  fixture chosen so result = 1.0
        Regression for the .max() vs .sum() bug — using .max() would yield a
        value ≈ 0.658 instead of 1.0, comfortably outside our tolerance.
        """
        df = build_load_profile(
            buildings_gdf=buildings_with_lastprofil,
            net_gdf=net_with_loss,
            year=2022,
            temperature=temperature_series,
            holidays={},
            building_class=3,
            wind_class=1,
        )
        total_kwh = net_with_loss[cols.HEAT_LOSS].sum()
        expected = (total_kwh / 1000) / 8760
        # Verlust must be constant (same value every hour) — with rounding to
        # 3 decimals there can be at most one distinct value.
        assert df[cols.LOSS].nunique() == 1
        assert df[cols.LOSS].iloc[0] == pytest.approx(expected, abs=0.001)

    def test_loss_extra_aggregation(
        self, buildings_with_lastprofil, net_with_loss, temperature_series
    ):
        df = build_load_profile(
            buildings_gdf=buildings_with_lastprofil,
            net_gdf=net_with_loss,
            year=2022,
            temperature=temperature_series,
            holidays={},
            building_class=3,
            wind_class=1,
        )
        total_extra_kwh = net_with_loss[cols.HEAT_LOSS_EXTRA_INSULATION].sum()
        expected_extra = (total_extra_kwh / 1000) / 8760
        assert df[cols.LOSS_EXTRA_INSULATION].nunique() == 1
        assert df[cols.LOSS_EXTRA_INSULATION].iloc[0] == pytest.approx(
            expected_extra, abs=0.001
        )
        # extra insulation must be ≤ standard loss
        assert (df[cols.LOSS_EXTRA_INSULATION] <= df[cols.LOSS] + 1e-9).all()

    def test_missing_loss_column_falls_back_to_zero(
        self, buildings_with_lastprofil, temperature_series
    ):
        net_empty = pd.DataFrame({"Other": [1.0, 2.0]})
        df = build_load_profile(
            buildings_gdf=buildings_with_lastprofil,
            net_gdf=net_empty,
            year=2022,
            temperature=temperature_series,
            holidays={},
            building_class=3,
            wind_class=1,
        )
        assert (df[cols.LOSS] == 0.0).all()
        assert (df[cols.LOSS_EXTRA_INSULATION] == 0.0).all()


# ---------------------------------------------------------------------------
# Aggregation formulas
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestAggregationFormulas:
    def test_gesamtsumme_equals_sum_plus_verlust(
        self, buildings_with_lastprofil, net_with_loss, temperature_series
    ):
        df = build_load_profile(
            buildings_gdf=buildings_with_lastprofil,
            net_gdf=net_with_loss,
            year=2022,
            temperature=temperature_series,
            holidays={},
            building_class=3,
            wind_class=1,
        )
        # rounding to 3 decimals → tolerate small absolute error
        diff = (df[cols.TOTAL] - (df[cols.BUILDING_DEMAND_SUM] + df[cols.LOSS])).abs()
        assert diff.max() <= 0.002

    def test_gesamtsumme_extra_equals_sum_plus_verlust_extra(
        self, buildings_with_lastprofil, net_with_loss, temperature_series
    ):
        df = build_load_profile(
            buildings_gdf=buildings_with_lastprofil,
            net_gdf=net_with_loss,
            year=2022,
            temperature=temperature_series,
            holidays={},
            building_class=3,
            wind_class=1,
        )
        diff = (
            df[cols.TOTAL_EXTRA_INSULATION]
            - (df[cols.BUILDING_DEMAND_SUM] + df[cols.LOSS_EXTRA_INSULATION])
        ).abs()
        assert diff.max() <= 0.002

    def test_summe_equals_lastprofil_columns_total(
        self, buildings_with_lastprofil, net_with_loss, temperature_series
    ):
        df = build_load_profile(
            buildings_gdf=buildings_with_lastprofil,
            net_gdf=net_with_loss,
            year=2022,
            temperature=temperature_series,
            holidays={},
            building_class=3,
            wind_class=1,
        )
        # cols.BUILDING_DEMAND_SUM is computed via demand.sum(axis=1) BEFORE
        # the loss/total columns are added — so it should equal EFH + MFH.
        recomputed = df["EFH"] + df["MFH"]
        diff = (df[cols.BUILDING_DEMAND_SUM] - recomputed).abs()
        assert diff.max() <= 0.002

    def test_annual_demand_matches_input(
        self, buildings_with_lastprofil, net_with_loss, temperature_series
    ):
        """Annual demand of EFH column ≈ annual_heat_demand passed to demandlib."""
        df = build_load_profile(
            buildings_gdf=buildings_with_lastprofil,
            net_gdf=net_with_loss,
            year=2022,
            temperature=temperature_series,
            holidays={},
            building_class=3,
            wind_class=1,
        )
        # input EFH demand = 10000 + 12000 = 22000 kWh = 22 MWh
        # demandlib returns hourly profile in the same unit as annual_heat_demand
        # (MWh, since slp.py passes annual_mwh / 1000) → annual sum = 22 MWh.
        efh_total_mwh = df["EFH"].sum()
        assert efh_total_mwh == pytest.approx(22.0, rel=0.1)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestEdgeCases:
    def test_no_lastprofil_column(self, net_with_loss, temperature_series):
        bld = gpd.GeoDataFrame(
            {
                cols.HEAT_DEMAND: [1000.0],
                "geometry": [Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])],
            },
            crs=CRS, geometry="geometry",
        )
        df = build_load_profile(
            buildings_gdf=bld,
            net_gdf=net_with_loss,
            year=2022,
            temperature=temperature_series,
            holidays={},
            building_class=3,
            wind_class=1,
        )
        # no per-Lastprofil column → Summe aller Gebäudetypen is zero
        assert (df[cols.BUILDING_DEMAND_SUM] == 0).all()
        # but losses are still applied
        assert df[cols.LOSS].iloc[0] > 0

    def test_all_lastprofil_nan(self, net_with_loss, temperature_series):
        bld = gpd.GeoDataFrame(
            {
                cols.HEAT_DEMAND: [1000.0, 2000.0],
                cols.LOAD_PROFILE: [np.nan, np.nan],
                "geometry": [
                    Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
                    Polygon([(2, 0), (3, 0), (3, 1), (2, 1)]),
                ],
            },
            crs=CRS, geometry="geometry",
        )
        df = build_load_profile(
            buildings_gdf=bld,
            net_gdf=net_with_loss,
            year=2022,
            temperature=temperature_series,
            holidays={},
            building_class=3,
            wind_class=1,
        )
        assert (df[cols.BUILDING_DEMAND_SUM] == 0).all()


# ---------------------------------------------------------------------------
# Import error path
# ---------------------------------------------------------------------------


class TestImportErrorPath:
    def test_missing_demandlib_raises_import_error(
        self, monkeypatch, buildings_with_lastprofil, net_with_loss, temperature_series
    ):
        """Simulate demandlib not installed → clear ImportError surfaced."""
        import builtins

        real_import = builtins.__import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name.startswith("demandlib"):
                raise ImportError("simulated missing dependency")
            return real_import(name, globals, locals, fromlist, level)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        # make sure cached imports do not satisfy the lookup
        monkeypatch.delitem(sys.modules, "demandlib", raising=False)
        monkeypatch.delitem(sys.modules, "demandlib.bdew", raising=False)

        with pytest.raises(ImportError, match="demandlib"):
            build_load_profile(
                buildings_gdf=buildings_with_lastprofil,
                net_gdf=net_with_loss,
                year=2022,
                temperature=temperature_series,
                holidays={},
                building_class=3,
                wind_class=1,
            )
