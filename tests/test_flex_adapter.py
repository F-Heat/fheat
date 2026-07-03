"""Tests for fheat_flex.adapter.data_adapter.FlexDataAdapter.

Covers:
- column_map renaming
- Waermebedarf > 0 filter and missing-column error path
- default_vlh / default_lastprofil fall-backs and column repair
- Leistung_th computed when missing, preserved when present
- new_ID and Anschluss defaults
- Source resolution: tuple, GeoDataFrame, file path
- All four fetch_* methods produce schema-conformant frames
"""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString, Point, Polygon

from fheat_core import columns as cols
from fheat_core.schemas import (
    BuildingsSchema,
    ParcelsSchema,
    SourceSchema,
    StreetsSchema,
)
from fheat_flex.adapter.data_adapter import FlexDataAdapter


CRS = "EPSG:25832"


# ---------------------------------------------------------------------------
# Test data factories
# ---------------------------------------------------------------------------


def _write_buildings(tmp_path: Path, **overrides) -> Path:
    """Write a 3-building GPKG with optional column overrides."""
    base = {
        "wbedarf": [10000.0, 20000.0, 30000.0],
        "geometry": [
            Polygon([(0, 0), (10, 0), (10, 10), (0, 10)]),
            Polygon([(20, 0), (30, 0), (30, 10), (20, 10)]),
            Polygon([(40, 0), (50, 0), (50, 10), (40, 10)]),
        ],
    }
    base.update(overrides)
    gdf = gpd.GeoDataFrame(base, crs=CRS, geometry="geometry")
    path = tmp_path / "buildings.gpkg"
    gdf.to_file(str(path), driver="GPKG")
    return path


def _write_streets(tmp_path: Path) -> Path:
    gdf = gpd.GeoDataFrame(
        {"geometry": [LineString([(-10, -5), (200, -5)])]},
        crs=CRS, geometry="geometry",
    )
    path = tmp_path / "streets.gpkg"
    gdf.to_file(str(path), driver="GPKG")
    return path


def _write_parcels(tmp_path: Path) -> Path:
    gdf = gpd.GeoDataFrame(
        {"geometry": [Polygon([(-5, -5), (55, -5), (55, 15), (-5, 15)])]},
        crs=CRS, geometry="geometry",
    )
    path = tmp_path / "parcels.gpkg"
    gdf.to_file(str(path), driver="GPKG")
    return path


@pytest.fixture
def files_set(tmp_path):
    return {
        "buildings": _write_buildings(tmp_path),
        "streets": _write_streets(tmp_path),
        "parcels": _write_parcels(tmp_path),
    }


# ---------------------------------------------------------------------------
# fetch_buildings — column_map and defaults
# ---------------------------------------------------------------------------


class TestFetchBuildings:
    def test_column_map_renames_heat_demand(self, files_set):
        adapter = FlexDataAdapter(
            buildings_path=files_set["buildings"],
            streets_path=files_set["streets"],
            parcels_path=files_set["parcels"],
            source=(52.0, 7.0),
            column_map={"wbedarf": cols.HEAT_DEMAND},
        )
        bld = adapter.fetch_buildings()
        BuildingsSchema.validate(bld)
        assert bld[cols.HEAT_DEMAND].tolist() == [10000.0, 20000.0, 30000.0]

    def test_missing_heat_demand_raises(self, files_set):
        """Without column_map, the user column 'wbedarf' isn't recognised."""
        adapter = FlexDataAdapter(
            buildings_path=files_set["buildings"],
            streets_path=files_set["streets"],
            parcels_path=files_set["parcels"],
            source=(52.0, 7.0),
        )
        with pytest.raises(ValueError, match="heat_demand"):
            adapter.fetch_buildings()

    def test_filters_zero_heat_buildings(self, tmp_path):
        bld_path = _write_buildings(tmp_path, wbedarf=[0.0, 5000.0, 0.0])
        adapter = FlexDataAdapter(
            buildings_path=bld_path,
            streets_path=_write_streets(tmp_path),
            parcels_path=_write_parcels(tmp_path),
            source=(52.0, 7.0),
            column_map={"wbedarf": cols.HEAT_DEMAND},
        )
        bld = adapter.fetch_buildings()
        assert len(bld) == 1
        assert bld[cols.HEAT_DEMAND].iloc[0] == 5000.0

    def test_all_zero_heat_raises(self, tmp_path):
        bld_path = _write_buildings(tmp_path, wbedarf=[0.0, 0.0, 0.0])
        adapter = FlexDataAdapter(
            buildings_path=bld_path,
            streets_path=_write_streets(tmp_path),
            parcels_path=_write_parcels(tmp_path),
            source=(52.0, 7.0),
            column_map={"wbedarf": cols.HEAT_DEMAND},
        )
        with pytest.raises(ValueError, match="heat_demand > 0"):
            adapter.fetch_buildings()

    def test_default_vlh_applied_when_missing(self, files_set):
        adapter = FlexDataAdapter(
            buildings_path=files_set["buildings"],
            streets_path=files_set["streets"],
            parcels_path=files_set["parcels"],
            source=(52.0, 7.0),
            column_map={"wbedarf": cols.HEAT_DEMAND},
            default_vlh=2000.0,
        )
        bld = adapter.fetch_buildings()
        assert (bld[cols.FULL_LOAD_HOURS] == 2000.0).all()

    def test_zero_or_negative_vlh_replaced_with_default(self, tmp_path):
        bld_path = _write_buildings(
            tmp_path,
            wbedarf=[10000.0, 20000.0, 30000.0],
            vlh=[0.0, -100.0, 1500.0],
        )
        adapter = FlexDataAdapter(
            buildings_path=bld_path,
            streets_path=_write_streets(tmp_path),
            parcels_path=_write_parcels(tmp_path),
            source=(52.0, 7.0),
            column_map={"wbedarf": cols.HEAT_DEMAND, "vlh": cols.FULL_LOAD_HOURS},
            default_vlh=1700.0,
        )
        bld = adapter.fetch_buildings()
        # rows 0 and 1 had ≤ 0 VLh → replaced with default; row 2 keeps 1500
        assert bld[cols.FULL_LOAD_HOURS].tolist() == [1700.0, 1700.0, 1500.0]

    def test_leistung_th_computed_from_heat_over_vlh(self, files_set):
        adapter = FlexDataAdapter(
            buildings_path=files_set["buildings"],
            streets_path=files_set["streets"],
            parcels_path=files_set["parcels"],
            source=(52.0, 7.0),
            column_map={"wbedarf": cols.HEAT_DEMAND},
        )
        bld = adapter.fetch_buildings()
        expected = (bld[cols.HEAT_DEMAND] / 1600.0).tolist()
        assert bld[cols.THERMAL_POWER].tolist() == pytest.approx(expected)

    def test_leistung_th_preserved_when_supplied(self, tmp_path):
        bld_path = _write_buildings(
            tmp_path,
            wbedarf=[10000.0, 20000.0, 30000.0],
            power=[42.0, 84.0, 126.0],
        )
        adapter = FlexDataAdapter(
            buildings_path=bld_path,
            streets_path=_write_streets(tmp_path),
            parcels_path=_write_parcels(tmp_path),
            source=(52.0, 7.0),
            column_map={"wbedarf": cols.HEAT_DEMAND, "power": cols.THERMAL_POWER},
        )
        bld = adapter.fetch_buildings()
        assert bld[cols.THERMAL_POWER].tolist() == [42.0, 84.0, 126.0]

    def test_default_lastprofil_applied(self, files_set):
        adapter = FlexDataAdapter(
            buildings_path=files_set["buildings"],
            streets_path=files_set["streets"],
            parcels_path=files_set["parcels"],
            source=(52.0, 7.0),
            column_map={"wbedarf": cols.HEAT_DEMAND},
            default_lastprofil="EFH",
        )
        bld = adapter.fetch_buildings()
        assert (bld[cols.LOAD_PROFILE] == "EFH").all()

    def test_lastprofil_nan_filled_with_default(self, tmp_path):
        bld_path = _write_buildings(
            tmp_path,
            wbedarf=[10000.0, 20000.0, 30000.0],
            lp=["EFH", None, "MFH"],
        )
        adapter = FlexDataAdapter(
            buildings_path=bld_path,
            streets_path=_write_streets(tmp_path),
            parcels_path=_write_parcels(tmp_path),
            source=(52.0, 7.0),
            column_map={"wbedarf": cols.HEAT_DEMAND, "lp": cols.LOAD_PROFILE},
            default_lastprofil="GMK",
        )
        bld = adapter.fetch_buildings()
        assert bld[cols.LOAD_PROFILE].tolist() == ["EFH", "GMK", "MFH"]

    def test_anschluss_default_one(self, files_set):
        adapter = FlexDataAdapter(
            buildings_path=files_set["buildings"],
            streets_path=files_set["streets"],
            parcels_path=files_set["parcels"],
            source=(52.0, 7.0),
            column_map={"wbedarf": cols.HEAT_DEMAND},
        )
        bld = adapter.fetch_buildings()
        assert (bld[cols.CONNECT] == 1).all()

    def test_new_id_assigned_when_missing(self, files_set):
        adapter = FlexDataAdapter(
            buildings_path=files_set["buildings"],
            streets_path=files_set["streets"],
            parcels_path=files_set["parcels"],
            source=(52.0, 7.0),
            column_map={"wbedarf": cols.HEAT_DEMAND},
        )
        bld = adapter.fetch_buildings()
        assert bld[cols.BUILDING_ID].tolist() == [0, 1, 2]


# ---------------------------------------------------------------------------
# fetch_streets / fetch_parcels
# ---------------------------------------------------------------------------


class TestFetchStreetsAndParcels:
    def test_streets_get_moegliche_route_default(self, files_set):
        adapter = FlexDataAdapter(
            buildings_path=files_set["buildings"],
            streets_path=files_set["streets"],
            parcels_path=files_set["parcels"],
            source=(52.0, 7.0),
            column_map={"wbedarf": cols.HEAT_DEMAND},
        )
        streets = adapter.fetch_streets()
        StreetsSchema.validate(streets)
        assert (streets[cols.ROUTABLE] == 1).all()

    def test_parcels_loaded_and_valid(self, files_set):
        adapter = FlexDataAdapter(
            buildings_path=files_set["buildings"],
            streets_path=files_set["streets"],
            parcels_path=files_set["parcels"],
            source=(52.0, 7.0),
            column_map={"wbedarf": cols.HEAT_DEMAND},
        )
        parcels = adapter.fetch_parcels()
        ParcelsSchema.validate(parcels)
        assert parcels.geometry.iloc[0].is_valid


# ---------------------------------------------------------------------------
# fetch_source — three input flavours
# ---------------------------------------------------------------------------


class TestFetchSource:
    def test_source_from_tuple_reprojects_to_buildings_crs(self, files_set):
        adapter = FlexDataAdapter(
            buildings_path=files_set["buildings"],
            streets_path=files_set["streets"],
            parcels_path=files_set["parcels"],
            source=(52.1592, 7.3268),
            column_map={"wbedarf": cols.HEAT_DEMAND},
        )
        src = adapter.fetch_source()
        SourceSchema.validate(src)
        assert src.crs.to_string() == CRS

    def test_source_from_geodataframe(self, files_set):
        src_gdf = gpd.GeoDataFrame(
            {"geometry": [Point(0, 0)]}, crs=CRS, geometry="geometry",
        )
        adapter = FlexDataAdapter(
            buildings_path=files_set["buildings"],
            streets_path=files_set["streets"],
            parcels_path=files_set["parcels"],
            source=src_gdf,
            column_map={"wbedarf": cols.HEAT_DEMAND},
        )
        src = adapter.fetch_source()
        SourceSchema.validate(src)
        assert src.geometry.iloc[0].x == 0.0

    def test_source_from_file_path(self, tmp_path, files_set):
        src_path = tmp_path / "src.gpkg"
        gpd.GeoDataFrame(
            {"geometry": [Point(100, 200)]}, crs=CRS, geometry="geometry",
        ).to_file(str(src_path), driver="GPKG")
        adapter = FlexDataAdapter(
            buildings_path=files_set["buildings"],
            streets_path=files_set["streets"],
            parcels_path=files_set["parcels"],
            source=str(src_path),
            column_map={"wbedarf": cols.HEAT_DEMAND},
        )
        src = adapter.fetch_source()
        SourceSchema.validate(src)
        assert src.geometry.iloc[0].x == 100.0
        assert src.geometry.iloc[0].y == 200.0

    def test_source_invalid_type_raises(self, files_set):
        adapter = FlexDataAdapter(
            buildings_path=files_set["buildings"],
            streets_path=files_set["streets"],
            parcels_path=files_set["parcels"],
            source=12345,  # invalid type
            column_map={"wbedarf": cols.HEAT_DEMAND},
        )
        with pytest.raises(ValueError, match="muss tuple"):
            adapter.fetch_source()


# ---------------------------------------------------------------------------
# Caching — repeated fetch returns same instance
# ---------------------------------------------------------------------------


class TestCaching:
    def test_buildings_cached(self, files_set):
        adapter = FlexDataAdapter(
            buildings_path=files_set["buildings"],
            streets_path=files_set["streets"],
            parcels_path=files_set["parcels"],
            source=(52.0, 7.0),
            column_map={"wbedarf": cols.HEAT_DEMAND},
        )
        b1 = adapter.fetch_buildings()
        b2 = adapter.fetch_buildings()
        assert b1 is b2  # cached, no re-read

    def test_streets_cached(self, files_set):
        adapter = FlexDataAdapter(
            buildings_path=files_set["buildings"],
            streets_path=files_set["streets"],
            parcels_path=files_set["parcels"],
            source=(52.0, 7.0),
            column_map={"wbedarf": cols.HEAT_DEMAND},
        )
        assert adapter.fetch_streets() is adapter.fetch_streets()
