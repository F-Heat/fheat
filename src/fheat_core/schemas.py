"""
Datenverträge zwischen Adaptern und Core.

Adapter-Implementierungen MÜSSEN GeoDataFrames liefern, die diese Schemas erfüllen.
Core erzeugt während der Pipeline weitere Frames, die ebenfalls gegen Schemas
validiert werden.

Spaltennamen sind kanonische, sprachneutrale Identifier (siehe
:mod:`fheat_core.columns`) — ohne Einheit im Namen; Einheiten sind Metadaten,
die deutsche Beschriftung ist Export-Sache. Sie werden NICHT über Config oder
Spaltenmappings ausserhalb des Adapters zur Laufzeit umkonfiguriert. Wer eigene
Daten verwenden will, baut einen Adapter, der seine Spalten auf diese Namen mappt.
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
            raise SchemaError(f"{self.name}: Frame ist None")
        if not isinstance(gdf, (gpd.GeoDataFrame, pd.DataFrame)):
            raise SchemaError(
                f"{self.name}: erwartet GeoDataFrame/DataFrame, "
                f"bekommen {type(gdf).__name__}"
            )
        if not self.allow_empty and gdf.empty:
            raise SchemaError(f"{self.name}: Frame ist leer")

        missing = set(self.required_columns) - set(gdf.columns)
        if missing:
            raise SchemaError(
                f"{self.name}: Pflichtspalten fehlen: {sorted(missing)}"
            )

        if self.geometry_type and isinstance(gdf, gpd.GeoDataFrame) and not gdf.empty:
            actual = set(gdf.geometry.geom_type.dropna().unique())
            allowed = {self.geometry_type, f"Multi{self.geometry_type}"}
            unexpected = actual - allowed
            if unexpected:
                raise SchemaError(
                    f"{self.name}: unerwartete Geometrietypen {sorted(unexpected)}, "
                    f"erlaubt: {sorted(allowed)}"
                )


# ============================================================
# Eingangsschemas — Adapter MUSS diese liefern
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
# Pipeline-Outputs — Core erzeugt diese
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
    name="EignungsPolygone",
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
# Lastprofil + ResultSummary
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
            raise SchemaError(f"{self.name}: DataFrame ist None")
        if not isinstance(df, pd.DataFrame):
            raise SchemaError(
                f"{self.name}: erwartet DataFrame, bekommen {type(df).__name__}"
            )
        if not isinstance(df.index, pd.DatetimeIndex):
            raise SchemaError(f"{self.name}: Index muss DatetimeIndex sein")
        if len(df) != self.required_length:
            raise SchemaError(
                f"{self.name}: erwartet {self.required_length} Zeitschritte, "
                f"bekommen {len(df)}"
            )
        missing = set(self.required_columns) - set(df.columns)
        if missing:
            raise SchemaError(f"{self.name}: Pflichtspalten fehlen: {sorted(missing)}")


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
            raise SchemaError(f"{self.name}: Dict ist None")
        if not isinstance(summary, dict):
            raise SchemaError(f"{self.name}: muss Dict sein")
        missing = set(self.required_keys) - set(summary.keys())
        if missing:
            raise SchemaError(f"{self.name}: Pflicht-Keys fehlen: {sorted(missing)}")


RESULT_SUMMARY_SCHEMA = ResultSummarySchema()
