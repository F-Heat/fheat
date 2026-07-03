"""Tests for fheat_core.schemas.

Covers:
- FrameSchema.validate rejects None, wrong type, empty (when not allowed),
  missing required columns, and unexpected geometry types.
- All concrete schemas accept their respective fixtures.
- LoadProfileSchema enforces DatetimeIndex, length 8760, required columns.
- ResultSummarySchema enforces dict type and required keys.
"""
from __future__ import annotations

import datetime

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString, Point, Polygon

from fheat_core import columns as cols
from fheat_core.schemas import (
    BuildingsSchema,
    FrameSchema,
    LOAD_PROFILE_SCHEMA,
    NetSchema,
    ParcelsSchema,
    PolygonsSchema,
    RESULT_SUMMARY_SCHEMA,
    SchemaError,
    SourceSchema,
    StreetsSchema,
    WLDSchema,
)


# ---------------------------------------------------------------------------
# FrameSchema — generic behaviour
# ---------------------------------------------------------------------------


class TestFrameSchemaGeneric:
    def test_none_raises(self):
        schema = FrameSchema(name="X", required_columns={"a": "int"})
        with pytest.raises(SchemaError, match="None"):
            schema.validate(None)

    def test_wrong_type_raises(self):
        schema = FrameSchema(name="X", required_columns={"a": "int"})
        with pytest.raises(SchemaError, match="GeoDataFrame/DataFrame"):
            schema.validate([1, 2, 3])

    def test_empty_not_allowed_raises(self):
        schema = FrameSchema(name="X", required_columns={"geometry": "Polygon"})
        empty = gpd.GeoDataFrame({"geometry": []}, geometry="geometry", crs="EPSG:25832")
        with pytest.raises(SchemaError, match="leer"):
            schema.validate(empty)

    def test_empty_allowed_passes(self):
        schema = FrameSchema(
            name="X",
            required_columns={"geometry": "Polygon"},
            allow_empty=True,
        )
        empty = gpd.GeoDataFrame({"geometry": []}, geometry="geometry", crs="EPSG:25832")
        schema.validate(empty)  # must not raise

    def test_missing_columns_raise_with_names(self):
        schema = FrameSchema(name="X", required_columns={"a": "int", "b": "float"})
        df = pd.DataFrame({"a": [1]})
        with pytest.raises(SchemaError, match=r"\['b'\]"):
            schema.validate(df)

    def test_unexpected_geometry_type_raises(self):
        schema = FrameSchema(
            name="X",
            required_columns={"geometry": "Polygon"},
            geometry_type="Polygon",
        )
        gdf = gpd.GeoDataFrame(
            {"geometry": [Point(0, 0)]},
            geometry="geometry",
            crs="EPSG:25832",
        )
        with pytest.raises(SchemaError, match="Geometrietypen"):
            schema.validate(gdf)

    def test_multi_variant_accepted(self):
        """Polygon schema must accept MultiPolygon."""
        from shapely.geometry import MultiPolygon

        schema = FrameSchema(
            name="X",
            required_columns={"geometry": "Polygon"},
            geometry_type="Polygon",
        )
        poly = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
        gdf = gpd.GeoDataFrame(
            {"geometry": [MultiPolygon([poly])]},
            geometry="geometry",
            crs="EPSG:25832",
        )
        schema.validate(gdf)  # must not raise

    def test_plain_dataframe_passes_when_no_geometry_check(self):
        schema = FrameSchema(name="X", required_columns={"a": "int"})
        df = pd.DataFrame({"a": [1, 2, 3]})
        schema.validate(df)


# ---------------------------------------------------------------------------
# Concrete input schemas
# ---------------------------------------------------------------------------


class TestInputSchemas:
    def test_buildings_fixture_valid(self, buildings_gdf):
        BuildingsSchema.validate(buildings_gdf)

    def test_buildings_missing_required_column(self, buildings_gdf):
        bad = buildings_gdf.drop(columns=[cols.CONNECT])
        with pytest.raises(SchemaError, match=cols.CONNECT):
            BuildingsSchema.validate(bad)

    def test_streets_fixture_valid(self, streets_gdf):
        StreetsSchema.validate(streets_gdf)

    def test_streets_wrong_geometry(self, streets_gdf):
        bad = streets_gdf.copy()
        bad["geometry"] = [Point(0, 0)]
        with pytest.raises(SchemaError, match="Geometrietypen"):
            StreetsSchema.validate(bad)

    def test_parcels_fixture_valid(self, parcels_gdf):
        ParcelsSchema.validate(parcels_gdf)

    def test_parcels_empty_allowed(self, crs):
        empty = gpd.GeoDataFrame({"geometry": []}, geometry="geometry", crs=crs)
        ParcelsSchema.validate(empty)  # allow_empty=True

    def test_source_fixture_valid(self, source_gdf):
        SourceSchema.validate(source_gdf)

    def test_source_must_be_point(self, crs):
        bad = gpd.GeoDataFrame(
            {"geometry": [LineString([(0, 0), (1, 1)])]},
            geometry="geometry",
            crs=crs,
        )
        with pytest.raises(SchemaError, match="Geometrietypen"):
            SourceSchema.validate(bad)


# ---------------------------------------------------------------------------
# Pipeline-output schemas
# ---------------------------------------------------------------------------


class TestOutputSchemas:
    def test_wld_empty_allowed_when_columns_present(self, crs):
        """allow_empty skips the empty-rejection but still requires columns."""
        empty = gpd.GeoDataFrame(
            {
                cols.LENGTH: pd.Series([], dtype=float),
                cols.HEAT_LINE_DENSITY: pd.Series([], dtype=float),
                cols.CONNECTED_IDS: pd.Series([], dtype=str),
                "geometry": [],
            },
            geometry="geometry",
            crs=crs,
        )
        WLDSchema.validate(empty)

    def test_wld_with_data_valid(self, crs):
        gdf = gpd.GeoDataFrame(
            {
                cols.LENGTH: [10.0],
                cols.HEAT_LINE_DENSITY: [1500.0],
                cols.CONNECTED_IDS: ["1,2"],
                "geometry": [LineString([(0, 0), (10, 0)])],
            },
            geometry="geometry",
            crs=crs,
        )
        WLDSchema.validate(gdf)

    def test_polygons_empty_allowed(self, crs):
        empty = gpd.GeoDataFrame({"geometry": []}, geometry="geometry", crs=crs)
        PolygonsSchema.validate(empty)

    def test_net_empty_allowed_when_columns_present(self, crs):
        """allow_empty skips the empty-rejection but still requires columns."""
        empty = gpd.GeoDataFrame(
            {col: pd.Series([], dtype=float) for col in [
                cols.LENGTH, cols.THERMAL_POWER, cols.N_BUILDINGS,
                cols.THERMAL_POWER_GLF, cols.VOLUME_FLOW, cols.NOMINAL_DIAMETER,
                cols.VELOCITY, cols.HEAT_LOSS,
                cols.HEAT_LOSS_EXTRA_INSULATION,
            ]} | {cols.TYPE: pd.Series([], dtype=str), "geometry": []},
            geometry="geometry",
            crs=crs,
        )
        NetSchema.validate(empty)

    def test_net_missing_column_rejected(self, crs):
        gdf = gpd.GeoDataFrame(
            {
                cols.TYPE: ["Straßenleitung"],
                cols.LENGTH: [10.0],
                "geometry": [LineString([(0, 0), (10, 0)])],
            },
            geometry="geometry",
            crs=crs,
        )
        with pytest.raises(SchemaError, match="Pflichtspalten fehlen"):
            NetSchema.validate(gdf)


# ---------------------------------------------------------------------------
# LoadProfileSchema
# ---------------------------------------------------------------------------


def _valid_load_profile() -> pd.DataFrame:
    idx = pd.date_range(
        start=datetime.datetime(2022, 1, 1, 0),
        end=datetime.datetime(2022, 12, 31, 23),
        freq="h",
    )
    return pd.DataFrame(
        {
            cols.BUILDING_DEMAND_SUM: 0.0,
            cols.LOSS: 0.0,
            cols.LOSS_EXTRA_INSULATION: 0.0,
            cols.TOTAL: 0.0,
            cols.TOTAL_EXTRA_INSULATION: 0.0,
        },
        index=idx,
    )


class TestLoadProfileSchema:
    def test_valid_load_profile(self):
        LOAD_PROFILE_SCHEMA.validate(_valid_load_profile())

    def test_none_raises(self):
        with pytest.raises(SchemaError, match="None"):
            LOAD_PROFILE_SCHEMA.validate(None)

    def test_non_dataframe_raises(self):
        with pytest.raises(SchemaError, match="DataFrame"):
            LOAD_PROFILE_SCHEMA.validate({"a": 1})

    def test_non_datetime_index_raises(self):
        df = _valid_load_profile().reset_index(drop=True)
        with pytest.raises(SchemaError, match="DatetimeIndex"):
            LOAD_PROFILE_SCHEMA.validate(df)

    def test_wrong_length_raises(self):
        df = _valid_load_profile().iloc[:100]
        with pytest.raises(SchemaError, match="Zeitschritte"):
            LOAD_PROFILE_SCHEMA.validate(df)

    def test_missing_column_raises(self):
        df = _valid_load_profile().drop(columns=[cols.LOSS])
        with pytest.raises(SchemaError, match=cols.LOSS):
            LOAD_PROFILE_SCHEMA.validate(df)


# ---------------------------------------------------------------------------
# ResultSummarySchema
# ---------------------------------------------------------------------------


def _valid_summary() -> dict:
    return {
        "total_heat_demand_mwh_a": 100.0,
        "total_buildings": 10,
        "total_power_glf_kw": 50.0,
        "glf": 0.7,
        "total_network_length_m": 1234.5,
        "total_loss_mwh_a": 5.0,
        "supply_temperature_c": 80.0,
        "return_temperature_c": 50.0,
    }


class TestResultSummarySchema:
    def test_valid_summary(self):
        RESULT_SUMMARY_SCHEMA.validate(_valid_summary())

    def test_none_raises(self):
        with pytest.raises(SchemaError, match="None"):
            RESULT_SUMMARY_SCHEMA.validate(None)

    def test_non_dict_raises(self):
        with pytest.raises(SchemaError, match="Dict"):
            RESULT_SUMMARY_SCHEMA.validate(["not", "a", "dict"])

    def test_missing_key_raises(self):
        bad = _valid_summary()
        del bad["glf"]
        with pytest.raises(SchemaError, match="glf"):
            RESULT_SUMMARY_SCHEMA.validate(bad)

    def test_extra_keys_allowed(self):
        bad = _valid_summary()
        bad["custom_metric"] = 42
        RESULT_SUMMARY_SCHEMA.validate(bad)  # extra keys must not raise
