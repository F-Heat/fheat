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

import calendar
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
        cols.ADDRESS: "str",
        cols.FLOOR_AREA: "float",
        cols.AGE: "str",
        cols.CONSTRUCTION_CLASS: "str",
        cols.CONSTRUCTION_YEAR: "int",
        cols.BLOCK_ID: "str",
        cols.HEAT_DEMAND_DATASET: "float",
        cols.HEAT_DEMAND_CALCULATED: "float",
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
    optional_columns={
        cols.HEAT_DEMAND: "float",  # written by the status step; the density is demand / length
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
    optional_columns={
        cols.GLF: "float",
        cols.CIVIL_COST_FACTOR: "float",
        cols.ROAD_SURFACE: "str",
        cols.PIPE_COST: "float",
        cols.CIVIL_COST: "float",
        cols.LENGTH_UNDER_BUILDINGS: "float",
    },
    geometry_type="LineString",
    allow_empty=True,
)


# ============================================================
# Result tables — created by the RESULTS step
# ============================================================

PipeSummarySchema = FrameSchema(
    name="PipeSummary",
    required_columns={
        cols.NOMINAL_DIAMETER: "str",
        cols.N_HOUSE_CONNECTIONS: "int",
        cols.HOUSE_CONNECTION_LENGTH: "float",
        cols.ROUTE_LENGTH: "float",
        cols.HEAT_LOSS_MWH: "float",
        cols.HEAT_LOSS_EXTRA_INSULATION_MWH: "float",
    },
    optional_columns={
        cols.PIPE_COST: "float",  # only when the net carries pipe costs
    },
    allow_empty=True,
)

BuildingSummarySchema = FrameSchema(
    name="BuildingSummary",
    required_columns={
        cols.LOAD_PROFILE: "str",
        cols.N_BUILDINGS: "int",
        cols.HEAT_DEMAND_MWH: "float",
    },
    allow_empty=True,
)


# ============================================================
# Load profile + ResultSummary
# ============================================================

@dataclass(frozen=True)
class LoadProfileSchema:
    name: str = "LoadProfile"
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
        # one calendar year: 8760 h, 8784 h in a leap year
        required_length = 8784 if len(df) and calendar.isleap(df.index[0].year) else 8760
        if len(df) != required_length:
            raise SchemaError(
                f"{self.name}: expected {required_length} time steps, "
                f"got {len(df)}"
            )
        missing = set(self.required_columns) - set(df.columns)
        if missing:
            raise SchemaError(f"{self.name}: required columns missing: {sorted(missing)}")


LOAD_PROFILE_SCHEMA = LoadProfileSchema()


# ============================================================
# Potential layers — optional, adapter provides them or None
# ============================================================

GeothermalShallowSchema = FrameSchema(
    name="GeothermalShallow",
    required_columns={
        cols.GEOTHERMAL_STATUS: "str",
        "geometry": "Polygon",
    },
    optional_columns={
        cols.GROUND_CONDUCTIVITY_40: "float",
        cols.GROUND_CONDUCTIVITY_60: "float",
        cols.GROUND_CONDUCTIVITY_80: "float",
        cols.GROUND_CONDUCTIVITY_100: "float",
        cols.COLLECTOR_EXTRACTION_1800: "float",
        cols.COLLECTOR_EXTRACTION_2400: "float",
        cols.BOREHOLE_EXTRACTION_1800: "float",
        cols.BOREHOLE_EXTRACTION_2400: "float",
    },
    geometry_type="Polygon",
)

GeothermalBlocksSchema = FrameSchema(
    name="GeothermalBlocks",
    required_columns={
        cols.BLOCK_ID: "str",
        cols.ONG_POTENTIAL_MWH: "float",
        cols.MTG_POTENTIAL_MWH: "float",
        cols.BLOCK_POTENTIAL_STATUS: "str",
        "geometry": "Polygon",
    },
    optional_columns={
        cols.ONG_POTENTIAL_2045_MWH: "float",
        cols.MTG_POTENTIAL_2045_MWH: "float",
        cols.BLOCK_HEATING_LOAD: "float",
        cols.BLOCK_HEATING_LOAD_2045: "float",
    },
    geometry_type="Polygon",
)

GeothermalDeepSchema = FrameSchema(
    name="GeothermalDeep",
    required_columns={
        cols.DEEP_POTENTIAL_MWH: "float",
        cols.DISTANCE_TO_AREA: "float",
        cols.SOURCE_CANDIDATE_LAT: "float",
        cols.SOURCE_CANDIDATE_LON: "float",
        "geometry": "Polygon",
    },
    geometry_type="Polygon",
)

SolarThermalSchema = FrameSchema(
    name="SolarThermal",
    required_columns={
        cols.SOLAR_USABLE_AREA: "float",
        cols.SOLAR_FLAT_PLATE_MWH: "float",
        cols.DISTANCE_TO_AREA: "float",
        "geometry": "Polygon",
    },
    optional_columns={
        cols.FLUR_ID: "str",
        cols.SOLAR_VACUUM_TUBE_MWH: "float",
        cols.SOLAR_TROUGH_NS_MWH: "float",
        cols.SOLAR_TROUGH_EW_MWH: "float",
        cols.DISTANCE_TO_DEMAND: "float",
    },
    geometry_type="Polygon",
)


@dataclass(frozen=True)
class ResultSummarySchema:
    name: str = "ResultSummary"
    required_keys: tuple = (
        cols.TOTAL_HEAT_DEMAND,
        cols.TOTAL_BUILDINGS,
        cols.TOTAL_POWER_GLF,
        cols.GLF,
        cols.TOTAL_NETWORK_LENGTH,
        cols.TOTAL_LOSS,
        cols.SUPPLY_TEMPERATURE,
        cols.RETURN_TEMPERATURE,
        cols.TOTAL_HOUSE_CONNECTION_LENGTH,
        cols.TOTAL_ROUTE_LENGTH,
        cols.TOTAL_LOSS_EXTRA_INSULATION,
    )
    # Present only when the net carries civil cost factors / pipe costs
    # (left out rather than set to 0, see steps/results.py).
    optional_keys: tuple = (
        cols.CIVIL_COST_SHARE,
        cols.TOTAL_PIPE_COST,
        cols.TOTAL_CIVIL_COST,
        cols.MEAN_CIVIL_COST_FACTOR,
        # Present only when the adapter provides the potential layer
        cols.TOTAL_ONG_POTENTIAL,
        cols.TOTAL_MTG_POTENTIAL,
        cols.MAX_DEEP_POTENTIAL,
        cols.TOTAL_SOLAR_THERMAL_FLAT_PLATE,
        cols.TOTAL_SOLAR_THERMAL_AREA,
        # Outdoor temperatures of the load profile: the source and the
        # temperature figures always, the station only for a DWD year
        cols.TEMPERATURE_SOURCE,
        cols.WEATHER_STATION_ID,
        cols.WEATHER_STATION_NAME,
        cols.WEATHER_STATION_DISTANCE,
        cols.WEATHER_YEAR,
        cols.MEAN_OUTDOOR_TEMPERATURE,
        cols.MIN_OUTDOOR_TEMPERATURE,
        cols.HEATING_DEGREE_DAYS,
        cols.TEMPERATURE_FALLBACK_REASON,
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
