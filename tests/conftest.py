"""Shared pytest fixtures for the FHeat test suite.

Provides minimal synthetic GeoDataFrames that satisfy the fheat_core schemas
without requiring network access or heavy real-world datasets.
"""
from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString, Point, Polygon

from fheat_core import columns as cols


CRS = "EPSG:25832"


@pytest.fixture
def crs():
    return CRS


@pytest.fixture
def buildings_gdf():
    """Three buildings on a 100 m grid, all schema-compliant."""
    polys = [
        Polygon([(0, 0), (10, 0), (10, 10), (0, 10)]),
        Polygon([(50, 0), (60, 0), (60, 10), (50, 10)]),
        Polygon([(100, 0), (110, 0), (110, 10), (100, 10)]),
    ]
    return gpd.GeoDataFrame(
        {
            cols.BUILDING_ID: [0, 1, 2],
            cols.CONNECT: [1, 1, 1],
            cols.HEAT_DEMAND: [15000.0, 25000.0, 35000.0],
            cols.THERMAL_POWER: [10.0, 15.0, 20.0],
            cols.FULL_LOAD_HOURS: [1500.0, 1666.0, 1750.0],
            cols.LOAD_PROFILE: ["EFH", "EFH", "MFH"],
            "geometry": polys,
        },
        crs=CRS,
        geometry="geometry",
    )


@pytest.fixture
def streets_gdf():
    """Single straight street running across the buildings."""
    line = LineString([(-10, -5), (200, -5)])
    return gpd.GeoDataFrame(
        {cols.ROUTABLE: [1], "geometry": [line]},
        crs=CRS,
        geometry="geometry",
    )


@pytest.fixture
def parcels_gdf():
    """Two parcels covering the buildings."""
    polys = [
        Polygon([(-5, -5), (65, -5), (65, 15), (-5, 15)]),
        Polygon([(95, -5), (115, -5), (115, 15), (95, 15)]),
    ]
    return gpd.GeoDataFrame(
        {"geometry": polys},
        crs=CRS,
        geometry="geometry",
    )


@pytest.fixture
def source_gdf():
    """Single heat source point near the start of the street."""
    return gpd.GeoDataFrame(
        {"geometry": [Point(-10, -5)]},
        crs=CRS,
        geometry="geometry",
    )


@pytest.fixture
def pipe_info_df():
    """Minimal pipe catalogue covering reasonable volume flows."""
    return pd.DataFrame(
        {
            "DN": [20, 25, 32, 40, 50, 65, 80],
            "di": [22.0, 28.0, 37.2, 43.1, 54.5, 70.3, 82.5],
            "U-Value": [0.20, 0.21, 0.23, 0.25, 0.27, 0.30, 0.33],
            "U-Value_extra_insulation": [0.13, 0.14, 0.15, 0.16, 0.17, 0.19, 0.21],
            "max_volumeFlow": [0.10, 0.20, 0.40, 0.70, 1.20, 2.00, 3.20],
        }
    )


@pytest.fixture
def temperature_series():
    """8760 hourly outdoor temperatures for one non-leap year."""
    idx = pd.date_range("2022-01-01 00:00", "2022-12-31 23:00", freq="h")
    # gentle seasonal sine: -5 °C in Jan, +20 °C in Jul
    import numpy as np

    hours = np.arange(len(idx))
    temps = 7.5 + 12.5 * np.sin(2 * np.pi * (hours - 24 * 31 * 5) / (24 * 365))
    return pd.Series(temps, index=idx, name="TT_TU")


@pytest.fixture
def empty_gdf():
    return gpd.GeoDataFrame({"geometry": []}, geometry="geometry", crs=CRS)


# ---------------------------------------------------------------------------
# Stub adapter (shared between test_steps.py and test_orchestrator.py)
# ---------------------------------------------------------------------------

from typing import Optional

from fheat_core.adapters.base import DataAdapter


class StubAdapter(DataAdapter):
    """Return-pre-built-frames adapter for deterministic step tests."""

    def __init__(
        self,
        buildings,
        streets,
        parcels,
        source,
        pipe_info: Optional[pd.DataFrame] = None,
        temperature: Optional[pd.Series] = None,
        holidays: Optional[dict] = None,
    ):
        self._buildings = buildings
        self._streets = streets
        self._parcels = parcels
        self._source = source
        self._pipe_info = pipe_info
        self._temperature = temperature
        self._holidays = holidays

    def fetch_buildings(self):
        return self._buildings

    def fetch_streets(self):
        return self._streets

    def fetch_parcels(self):
        return self._parcels

    def fetch_source(self):
        return self._source

    def provide_pipe_info(self):
        return self._pipe_info

    def provide_temperature(self):
        return self._temperature

    def provide_holidays(self):
        return self._holidays


@pytest.fixture
def stub_adapter(buildings_gdf, streets_gdf, parcels_gdf, source_gdf,
                 pipe_info_df, temperature_series):
    return StubAdapter(
        buildings_gdf, streets_gdf, parcels_gdf, source_gdf,
        pipe_info=pipe_info_df, temperature=temperature_series, holidays={},
    )
