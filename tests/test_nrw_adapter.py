"""Tests for fheat_nrw.adapter.data_adapter and fheat_nrw.processing.

Covers:
- NRWDataAdapter constructor validation
- _filter_cities and _load_cities
- _build_source (WGS84 → target CRS)
- processing.process_streets (MultiLineString flattening, rounding,
  Moegliche_Route=1)
- processing.process_buildings (non-ALKIS branch — simpler, deterministic)
- processing._resolve_heat_col, _extract_year, _add_lanuv_age_and_type
- processing._rename_to_schema produces a BuildingsSchema-conformant frame
"""
from __future__ import annotations

import datetime

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, MultiLineString, Point, Polygon

from fheat_core import columns as cols
from fheat_core.schemas import BuildingsSchema, StreetsSchema
from fheat_nrw.adapter.data_adapter import NRWDataAdapter
from fheat_nrw.processing import (
    BAK_BINS,
    BAK_LABELS,
    _add_bak,
    _add_lanuv_age_and_type,
    _extract_year,
    _resolve_heat_col,
    _rename_to_schema,
    process_buildings,
    process_streets,
)


CRS = "EPSG:25832"


# ---------------------------------------------------------------------------
# NRWDataAdapter — constructor + non-network helpers
# ---------------------------------------------------------------------------


class TestNRWDataAdapterConstructor:
    def test_requires_municipality_or_city_name(self):
        with pytest.raises(ValueError, match="municipality_name.*city_name"):
            NRWDataAdapter(source_coordinates=(52.0, 7.0))

    def test_requires_source_coordinates(self):
        with pytest.raises(ValueError, match="source_coordinates"):
            NRWDataAdapter(source_coordinates=None, city_name="Münster")

    def test_construct_with_city_name(self):
        adapter = NRWDataAdapter(
            source_coordinates=(52.0, 7.0),
            city_name="Burgsteinfurt",
        )
        assert adapter._city_name == "Burgsteinfurt"
        assert adapter._municipality_name is None

    def test_construct_with_municipality_name(self):
        adapter = NRWDataAdapter(
            source_coordinates=(52.0, 7.0),
            municipality_name="Steinfurt",
        )
        assert adapter._municipality_name == "Steinfurt"

    def test_default_heat_attribute(self):
        adapter = NRWDataAdapter(
            source_coordinates=(52.0, 7.0),
            city_name="X",
        )
        assert adapter._heat_attribute == "RW_WW"

    def test_custom_heat_attribute(self):
        adapter = NRWDataAdapter(
            source_coordinates=(52.0, 7.0),
            city_name="X",
            heat_attribute="custom_heat",
        )
        assert adapter._heat_attribute == "custom_heat"


class TestFilterCities:
    def test_finds_city_by_name(self):
        df = pd.DataFrame({
            "name": ["Burgsteinfurt", "Borghorst"],
            "gemeinde": ["Steinfurt", "Steinfurt"],
            "schluessel": ["55190", "55001"],
            "gmdschl": ["05566036", "05566036"],
            "bbox": [(0, 0, 10, 10), (0, 0, 10, 10)],
        })
        result = NRWDataAdapter._filter_cities("Burgsteinfurt", df, "city")
        assert len(result) == 1
        assert result["schluessel"].iloc[0] == "55190"

    def test_finds_municipality(self):
        df = pd.DataFrame({
            "name": ["X", "Y"],
            "gemeinde": ["Steinfurt", "Steinfurt"],
            "schluessel": ["1", "2"],
            "gmdschl": ["05566036", "05566036"],
            "bbox": [(0, 0, 1, 1), (0, 0, 1, 1)],
        })
        result = NRWDataAdapter._filter_cities("Steinfurt", df, "municipality")
        assert len(result) == 2

    def test_unknown_name_raises(self):
        df = pd.DataFrame({
            "name": ["A"], "gemeinde": ["A"],
            "schluessel": ["1"], "gmdschl": ["1"], "bbox": [(0, 0, 1, 1)],
        })
        with pytest.raises(RuntimeError, match="Kein Eintrag"):
            NRWDataAdapter._filter_cities("Z", df, "city")


class TestBuildSource:
    def test_reprojects_wgs84_to_target_crs(self):
        adapter = NRWDataAdapter(
            source_coordinates=(52.1592, 7.3268),  # Burgsteinfurt
            city_name="X",
        )
        gdf = adapter._build_source(target_crs=CRS)
        assert isinstance(gdf, gpd.GeoDataFrame)
        assert gdf.crs.to_string() == CRS
        # Burgsteinfurt is well within sensible UTM 32N bounds
        x, y = gdf.geometry.iloc[0].x, gdf.geometry.iloc[0].y
        assert 100_000 < x < 1_000_000
        assert 5_000_000 < y < 7_000_000

    def test_no_reprojection_when_target_none(self):
        adapter = NRWDataAdapter(source_coordinates=(52.0, 7.0), city_name="X")
        gdf = adapter._build_source(target_crs=None)
        assert gdf.crs.to_string() == "EPSG:4326"


# ---------------------------------------------------------------------------
# processing.process_streets
# ---------------------------------------------------------------------------


class TestProcessStreets:
    def test_adds_moegliche_route(self):
        gdf = gpd.GeoDataFrame(
            {"geometry": [LineString([(0, 0), (1, 0)])]},
            crs=CRS, geometry="geometry",
        )
        out = process_streets(gdf)
        assert (out[cols.ROUTABLE] == 1).all()
        StreetsSchema.validate(out)

    def test_flattens_multilinestring(self):
        ml = MultiLineString([
            LineString([(0, 0), (1, 0)]),
            LineString([(1, 0), (2, 0)]),
        ])
        gdf = gpd.GeoDataFrame({"geometry": [ml]}, crs=CRS, geometry="geometry")
        out = process_streets(gdf)
        assert all(g.geom_type == "LineString" for g in out.geometry)

    def test_rounds_coordinates_to_3_decimals(self):
        gdf = gpd.GeoDataFrame(
            {"geometry": [LineString([(0.1234567, 0.7654321), (1.1111111, 2.2222222)])]},
            crs=CRS, geometry="geometry",
        )
        out = process_streets(gdf)
        coords = list(out.geometry.iloc[0].coords)
        assert coords == [(0.123, 0.765), (1.111, 2.222)]


# ---------------------------------------------------------------------------
# processing internals
# ---------------------------------------------------------------------------


class TestResolveHeatCol:
    def test_direct_match(self):
        gdf = pd.DataFrame({"RW_WW": [100.0]})
        assert _resolve_heat_col(gdf, "RW_WW") == "RW_WW"

    def test_kwh_a_suffix_fallback(self):
        gdf = pd.DataFrame({"RW_WW [kWh/a]": [100.0]})
        assert _resolve_heat_col(gdf, "RW_WW") == "RW_WW [kWh/a]"

    def test_missing_raises_keyerror(self):
        gdf = pd.DataFrame({"OTHER": [100.0]})
        with pytest.raises(KeyError, match="RW_WW"):
            _resolve_heat_col(gdf, "RW_WW")


class TestExtractYear:
    def test_date_object(self):
        assert _extract_year(datetime.date(1995, 3, 15)) == 1995

    def test_datetime_object(self):
        assert _extract_year(datetime.datetime(1980, 6, 1, 12, 0)) == 1980

    def test_iso_string(self):
        assert _extract_year("1972-04-01") == 1972

    def test_nan(self):
        assert pd.isna(_extract_year(np.nan))

    def test_invalid_string_returns_nan(self):
        assert pd.isna(_extract_year("not-a-date"))


class TestAddLanuvAgeAndType:
    def test_splits_gebaeudety(self):
        gdf = gpd.GeoDataFrame(
            {
                "GEBAEUDETY": ["EFH_J", "MFH_H", "NWG_C"],
                "geometry": [Point(0, 0), Point(1, 0), Point(2, 0)],
            },
            crs=CRS, geometry="geometry",
        )
        out = _add_lanuv_age_and_type(gdf)
        assert list(out["type"]) == ["EFH", "MFH", "NWG"]
        assert list(out["age_LANUV"]) == ["J", "H", "C"]

    def test_nwg_overrides_type(self):
        gdf = gpd.GeoDataFrame(
            {
                "GEBAEUDETY": ["EFH_J", "EFH_J"],
                "WG_NWG": ["WG", "NWG"],
                "geometry": [Point(0, 0), Point(1, 0)],
            },
            crs=CRS, geometry="geometry",
        )
        out = _add_lanuv_age_and_type(gdf)
        assert out["type"].tolist() == ["EFH", "NWG"]

    def test_missing_gebaeudety_creates_na_columns(self):
        gdf = gpd.GeoDataFrame(
            {"geometry": [Point(0, 0)]}, crs=CRS, geometry="geometry",
        )
        out = _add_lanuv_age_and_type(gdf)
        assert pd.isna(out["type"].iloc[0])
        assert pd.isna(out["age_LANUV"].iloc[0])


class TestAddBak:
    def test_bak_classification(self):
        gdf = pd.DataFrame({
            "validFrom": [
                datetime.date(1900, 1, 1),
                datetime.date(1955, 6, 1),
                datetime.date(2010, 1, 1),
            ],
        })
        out = _add_bak(gdf)
        # 1900 → 'B' (≤1918), 1955 → 'D' (1948-1957 right=True so 1957→D),
        # 2010 → 'J' (≤9999, last bin)
        assert out["BAK"].tolist() == ["B", "D", "J"]

    def test_bins_and_labels_are_consistent(self):
        # one fewer bin edge than labels because pd.cut uses N bins from N+1 edges
        assert len(BAK_BINS) == len(BAK_LABELS) + 1


# ---------------------------------------------------------------------------
# process_buildings — non-ALKIS branch (simpler path)
# ---------------------------------------------------------------------------


class TestProcessBuildingsNonAlkis:
    def _bld(self):
        return gpd.GeoDataFrame(
            {
                "RW_WW": [10000.0, 20000.0, 0.0],  # 3rd is filtered out
                "geometry": [
                    Polygon([(0, 0), (10, 0), (10, 10), (0, 10)]),
                    Polygon([(20, 0), (30, 0), (30, 10), (20, 10)]),
                    Polygon([(40, 0), (50, 0), (50, 10), (40, 10)]),
                ],
            },
            crs=CRS, geometry="geometry",
        )

    def _empty_parcels(self):
        return gpd.GeoDataFrame({"geometry": []}, crs=CRS, geometry="geometry")

    def test_filters_zero_heat_buildings(self):
        out = process_buildings(
            raw=self._bld(),
            parcels=self._empty_parcels(),
            building_info_db=pd.DataFrame(),
            wg_demand_data=pd.DataFrame(),
            heat_attribute="RW_WW",
        )
        assert len(out) == 2

    def test_output_satisfies_buildings_schema(self):
        out = process_buildings(
            raw=self._bld(),
            parcels=self._empty_parcels(),
            building_info_db=pd.DataFrame(),
            wg_demand_data=pd.DataFrame(),
            heat_attribute="RW_WW",
        )
        BuildingsSchema.validate(out)

    def test_anschluss_set_to_one(self):
        out = process_buildings(
            raw=self._bld(),
            parcels=self._empty_parcels(),
            building_info_db=pd.DataFrame(),
            wg_demand_data=pd.DataFrame(),
            heat_attribute="RW_WW",
        )
        assert (out[cols.CONNECT] == 1).all()

    def test_default_vlh_1600(self):
        out = process_buildings(
            raw=self._bld(),
            parcels=self._empty_parcels(),
            building_info_db=pd.DataFrame(),
            wg_demand_data=pd.DataFrame(),
            heat_attribute="RW_WW",
        )
        assert (out[cols.FULL_LOAD_HOURS] == 1600).all()

    def test_power_equals_heat_over_vlh(self):
        out = process_buildings(
            raw=self._bld(),
            parcels=self._empty_parcels(),
            building_info_db=pd.DataFrame(),
            wg_demand_data=pd.DataFrame(),
            heat_attribute="RW_WW",
        )
        # 10000 / 1600 = 6.25, 20000 / 1600 = 12.5
        expected = (out[cols.HEAT_DEMAND] / 1600).tolist()
        assert out[cols.THERMAL_POWER].tolist() == pytest.approx(expected)

    def test_all_zero_heat_raises(self):
        bld = gpd.GeoDataFrame(
            {
                "RW_WW": [0.0, 0.0],
                "geometry": [Point(0, 0).buffer(1), Point(1, 0).buffer(1)],
            },
            crs=CRS, geometry="geometry",
        )
        with pytest.raises(ValueError, match="Waermebedarf"):
            process_buildings(
                raw=bld,
                parcels=self._empty_parcels(),
                building_info_db=pd.DataFrame(),
                wg_demand_data=pd.DataFrame(),
                heat_attribute="RW_WW",
            )

    def test_resolves_kwh_a_suffix_attribute(self):
        bld = gpd.GeoDataFrame(
            {
                "RW_WW [kWh/a]": [5000.0],
                "geometry": [Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])],
            },
            crs=CRS, geometry="geometry",
        )
        out = process_buildings(
            raw=bld,
            parcels=self._empty_parcels(),
            building_info_db=pd.DataFrame(),
            wg_demand_data=pd.DataFrame(),
            heat_attribute="RW_WW",
        )
        assert out[cols.HEAT_DEMAND].iloc[0] == 5000.0


class TestRenameToSchema:
    def test_minimal_input_produces_required_columns(self):
        gdf = gpd.GeoDataFrame(
            {
                "RW_WW": [12000.0],
                "Vlh": [1500.0],
                "power_th": [8.0],
                "Lastprofil": ["EFH"],
                "Anschluss": [1],
                "new_ID": [0],
                "geometry": [Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])],
            },
            crs=CRS, geometry="geometry",
        )
        out = _rename_to_schema(gdf, "RW_WW")
        BuildingsSchema.validate(out)
        assert out[cols.HEAT_DEMAND].iloc[0] == 12000.0
        assert out[cols.THERMAL_POWER].iloc[0] == 8.0
        assert out[cols.FULL_LOAD_HOURS].iloc[0] == 1500.0


class TestBundledReferenceData:
    """Guards the real shipped data files (JSON/CSV) and their loaders — the file
    load path was previously untested, so a header/field-name drift would have
    silently fallen back to defaults instead of failing."""

    def _adapter(self):
        return NRWDataAdapter(source_coordinates=(52.0, 7.0), city_name="X")

    def test_building_info_json_loads_with_contract_columns(self):
        db, wg = self._adapter()._load_building_info()
        # function lookup: the 4 columns processing.py merges/reads
        assert {"Funktion", "Lastprofil", "Vlh", "WVBRpEBF"} <= set(db.columns)
        assert (db["Funktion"] == "1010").any()
        # age-class lookup: normalized ASCII headers, exactly 12 classes
        assert {
            "Baualtersklasse",
            "waerme_mfh_kwh_m2a",
            "waerme_efh_kwh_m2a",
        } <= set(wg.columns)
        assert len(wg) == 12

    def test_cities_csv_loads_with_required_columns(self):
        cities = self._adapter()._load_cities()
        assert set(("name", "gemeinde", "schluessel", "gmdschl", "bbox")) <= set(cities.columns)
        assert not cities.empty
        # bbox parsed from its CSV string into a 4-tuple/list of floats
        bbox = cities["bbox"].iloc[0]
        assert len(bbox) == 4

    def test_custom_heat_demand_actually_fires(self):
        """End-to-end guard: with real reference data the age-class merge produces
        a specific heat demand (not the silent `return gdf` fallback)."""
        from fheat_nrw.processing import _add_custom_heat_demand

        db, wg = self._adapter()._load_building_info()
        gdf = gpd.GeoDataFrame(
            {
                "RW_WW": [0.0],
                "NF": [100.0],
                "Lastprofil": ["EFH"],
                "BAK": ["A"],
                "citygml_fu": ["31001010"],  # last four → 1010
                "geometry": [Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])],
            },
            crs=CRS, geometry="geometry",
        )
        out = _add_custom_heat_demand(gdf, wg, db, "RW_WW")
        # BAK "A", EFH → waerme_efh_kwh_m2a (188.2) × NF (100) = 18820
        assert out["RW_WW"].iloc[0] == pytest.approx(18820.0)
