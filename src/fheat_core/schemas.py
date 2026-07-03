"""
Data contracts between adapters and the core.

Adapter implementations MUST provide GeoDataFrames that satisfy these schemas.
The core creates additional frames during the pipeline that are also validated
against schemas.

Column names are canonical, language-neutral snake_case identifiers (see
:mod:`fheat_core.columns`) — without units in the name; units are metadata,
and German labels are handled at the export boundary. They are NOT reconfigured
at runtime via Config or column mappings outside the adapter. Users who want to
use their own data build an adapter that maps their columns to these names.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import geopandas as gpd
import pandas as pd

from fheat_core import columns as cols


class SchemaError(Exception):
    pass


@dataclass(frozen=True)
class FrameSchema:
    name: str
    required_columns: dict = field(default_factory=dict)
    optional_columns: dict = field(default_factory=dict)
    geometry_type: Optional[str] = None
    allow_empty: bool = False

    def validate(self, gdf) -> None:
        if gdf is None:
            raise SchemaError(f"{self.name}: Frame is None")
        if not isinstance(gdf, (gpd.GeoDataFrame, pd.DataFrame)):
            raise SchemaError(
                f"{self.name}: expected GeoDataFrame/DataFrame, "
                f"got {type(gdf).__name__}"
            )
        if not self.allow_empty and gdf.empty:
            raise SchemaError(f"{self.name}: Frame is empty")

        missing = set(self.required_columns) - set(gdf.columns)
        if missing:
            raise SchemaError(
                f"{self.name}: required columns missing: {sorted(missing)}"
            )

        if self.geometry_type and isinstance(gdf, gpd.GeoDataFrame) and not gdf.empty:
            actual = set(gdf.geometry.geom_type.dropna().unique())
            allowed = {self.geometry_type, f"Multi{self.geometry_type}"}
            unexpected = actual - allowed
            if unexpected:
                raise SchemaError(
                    f"{self.name}: unexpected geometry types {sorted(unexpected)}, "
                    f"allowed: {sorted(allowed)}"
                )


# ============================================================
# Input schemas — adapter MUST provide these
# ============================================================

BuildingsSchema = FrameSchema(
    name="Buildings",
    required_columns={
        cols.BUILDING_ID: "int",
        cols.CONNECT: "int",
        cols.HEAT_DEMAND: "float",
        cols.THERMAL_POWER: "float",
        cols.FULL_LOAD_HOURS: "float",
        cols.LOAD_PROFILE: "str",
        "geometry": "Polygon",
    },
    optional_columns={
        cols.FUNCTION: "str",
        cols.BUILDING_TYPE: "str",
        cols.USAGE: "str",
        cols.FLOOR_AREA: "float",
        cols.AGE: "str",
        cols.CONSTRUCTION_CLASS: "str",
    },
    geometry_type="Polygon",
)

StreetsSchema = FrameSchema(
    name="Streets",
    required_columns={
        "geometry": "LineString",
    },
    optional_columns={
        cols.ROUTABLE: "int",
    },
    geometry_type="LineString",
)

ParcelsSchema = FrameSchema(
    name="Parcels",
    required_columns={
        "geometry": "Polygon",
    },
    geometry_type="Polygon",
    allow_empty=True,
)

SourceSchema = FrameSchema(
    name="Source",
    required_columns={
        "geometry": "Point",
    },
    geometry_type="Point",
)


# ============================================================
# Pipeline outputs — created by the core
# ============================================================

WLDSchema = FrameSchema(
    name="WLD",
    required_columns={
        "geometry": "LineString",
        cols.LENGTH: "float",
        cols.HEAT_LINE_DENSITY: "float",
        cols.CONNECTED_IDS: "str",
    },
    geometry_type="LineString",
    allow_empty=True,
)

PolygonsSchema = FrameSchema(
    name="SuitabilityPolygons",
    required_columns={
        "geometry": "Polygon",
    },
    optional_columns={
        cols.AREA: "float",
        cols.N_CONNECTIONS: "int",
        cols.HEAT_DEMAND: "float",
        cols.THERMAL_POWER: "float",
        cols.HEAT_DEMAND_DENSITY: "float",
        cols.THERMAL_POWER_MEAN: "float",
    },
    geometry_type="Polygon",
    allow_empty=True,
)

NetSchema = FrameSchema(
    name="Net",
    required_columns={
        "geometry": "LineString",
        cols.TYPE: "str",
        cols.LENGTH: "float",
        cols.THERMAL_POWER: "float",
        cols.N_BUILDINGS: "int",
        cols.THERMAL_POWER_GLF: "float",
        cols.VOLUME_FLOW: "float",
        cols.NOMINAL_DIAMETER: "float",
        cols.VELOCITY: "float",
        cols.HEAT_LOSS: "float",
        cols.HEAT_LOSS_EXTRA_INSULATION: "float",
    },
    geometry_type="LineString",
    allow_empty=True,
)


# ============================================================
# Load profile + ResultSummary
# ============================================================

@dataclass(frozen=True)
class LoadProfileSchema:
    name: str = "LoadProfile"
    required_length: int = 8760
    required_columns: tuple = (
        cols.BUILDING_DEMAND_SUM,
        cols.LOSS,
        cols.LOSS_EXTRA_INSULATION,
        cols.TOTAL,
        cols.TOTAL_EXTRA_INSULATION,
    )

    def validate(self, df) -> None:
        if df is None:
            raise SchemaError(f"{self.name}: DataFrame is None")
        if not isinstance(df, pd.DataFrame):
            raise SchemaError(
                f"{self.name}: expected DataFrame, got {type(df).__name__}"
            )
        if not isinstance(df.index, pd.DatetimeIndex):
            raise SchemaError(f"{self.name}: index must be a DatetimeIndex")
        if len(df) != self.required_length:
            raise SchemaError(
                f"{self.name}: expected {self.required_length} time steps, "
                f"got {len(df)}"
            )
        missing = set(self.required_columns) - set(df.columns)
        if missing:
            raise SchemaError(f"{self.name}: required columns missing: {sorted(missing)}")


LOAD_PROFILE_SCHEMA = LoadProfileSchema()


@dataclass(frozen=True)
class ResultSummarySchema:
    name: str = "ResultSummary"
    required_keys: tuple = (
        "total_heat_demand_mwh_a",
        "total_buildings",
        "total_power_glf_kw",
        "glf",
        "total_network_length_m",
        "total_loss_mwh_a",
        "supply_temperature_c",
        "return_temperature_c",
    )

    def validate(self, summary) -> None:
        if summary is None:
            raise SchemaError(f"{self.name}: dict is None")
        if not isinstance(summary, dict):
            raise SchemaError(f"{self.name}: must be a dict")
        missing = set(self.required_keys) - set(summary.keys())
        if missing:
            raise SchemaError(f"{self.name}: required keys missing: {sorted(missing)}")


RESULT_SUMMARY_SCHEMA = ResultSummarySchema()
