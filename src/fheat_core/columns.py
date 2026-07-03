"""Canonical column names — Single Source of Truth.

The pipeline works internally with language-neutral, stable snake_case identifiers
*without* units in the name. Units are metadata (:data:`UNITS`); German labels
are a pure display/export concern (:data:`LABELS_DE`).

Adapters map their source columns to these constants; the core exclusively reads
and writes these names. At the export boundary (``orchestrator.save_outputs``)
the canonical names are translated back to German labels via :func:`to_display`,
so output files remain unchanged for German users.
"""
from __future__ import annotations


# ============================================================
# Buildings — input columns (provided by the adapter)
# ============================================================

BUILDING_ID = "building_id"          # unique building index
CONNECT = "connect"                  # 1 = connect to network, 0 = exclude
HEAT_DEMAND = "heat_demand"          # annual heat demand [kWh/a]
THERMAL_POWER = "thermal_power"      # thermal power [kW]
FULL_LOAD_HOURS = "full_load_hours"  # full load hours [h]
LOAD_PROFILE = "load_profile"        # load profile code (EFH, MFH, …)

# optional
FUNCTION = "function"
BUILDING_TYPE = "building_type"
USAGE = "usage"
FLOOR_AREA = "floor_area"            # net floor area [m²]
AGE = "age"
CONSTRUCTION_CLASS = "construction_class"  # construction age class (BAK)


# ============================================================
# Streets — input columns
# ============================================================

ROUTABLE = "routable"                # 1 = usable as a route


# ============================================================
# WLD — pipeline output
# ============================================================

LENGTH = "length"                    # length [m]
HEAT_LINE_DENSITY = "heat_line_density"  # heat line density [kWh/(a·m)]
CONNECTED_IDS = "connected_ids"      # comma-separated building_id list


# ============================================================
# Suitability polygons — pipeline output
# ============================================================

AREA = "area"                        # area [m²]
N_CONNECTIONS = "n_connections"      # number of connections
HEAT_DEMAND_DENSITY = "heat_demand_density"   # heat demand per area [MWh/(ha·a)]
THERMAL_POWER_MEAN = "thermal_power_mean"     # mean thermal power [kW]


# ============================================================
# Network — pipeline output
# ============================================================

TYPE = "type"                        # pipe type
N_BUILDINGS = "n_buildings"          # number of buildings on the edge
THERMAL_POWER_GLF = "thermal_power_glf"  # power with simultaneity factor [kW]
VOLUME_FLOW = "volume_flow"          # volume flow [l/s]
NOMINAL_DIAMETER = "nominal_diameter"    # nominal diameter DN [mm]
VELOCITY = "velocity"                # flow velocity [m/s]
HEAT_LOSS = "heat_loss"              # heat loss [kWh/a]
HEAT_LOSS_EXTRA_INSULATION = "heat_loss_extra_insulation"  # heat loss with extra insulation [kWh/a]
GLF = "glf"                          # simultaneity factor


# ============================================================
# Internal geometry helper columns
# ============================================================

CONNECTION_POINT = "connection_point"  # connection point on the route
CENTROID = "centroid"
STREET_ID = "street_id"


# ============================================================
# Load profile — aggregate columns
# ============================================================

BUILDING_DEMAND_SUM = "building_demand_sum"      # sum of all building types
LOSS = "loss"                                    # loss
LOSS_EXTRA_INSULATION = "loss_extra_insulation"  # loss with extra insulation
TOTAL = "total"                                  # total
TOTAL_EXTRA_INSULATION = "total_extra_insulation"  # total (extra insulation)


# ============================================================
# Units (metadata)
# ============================================================

UNITS: dict[str, str] = {
    HEAT_DEMAND: "kWh/a",
    THERMAL_POWER: "kW",
    FULL_LOAD_HOURS: "h",
    FLOOR_AREA: "m²",
    LENGTH: "m",
    HEAT_LINE_DENSITY: "kWh/(a·m)",
    AREA: "m²",
    HEAT_DEMAND_DENSITY: "MWh/(ha·a)",
    THERMAL_POWER_MEAN: "kW",
    THERMAL_POWER_GLF: "kW",
    VOLUME_FLOW: "l/s",
    NOMINAL_DIAMETER: "mm",
    VELOCITY: "m/s",
    HEAT_LOSS: "kWh/a",
    HEAT_LOSS_EXTRA_INSULATION: "kWh/a",
}


# ============================================================
# German display labels (export boundary)
# ============================================================
# Values match the previously written column names exactly, so output
# files (GeoPackage/GeoJSON) remain unchanged for German users.

LABELS_DE: dict[str, str] = {
    # Buildings
    BUILDING_ID: "new_ID",
    CONNECT: "Anschluss",
    HEAT_DEMAND: "Waermebedarf [kWh/a]",
    THERMAL_POWER: "Leistung_th [kW]",
    FULL_LOAD_HOURS: "Vlh [h]",
    LOAD_PROFILE: "Lastprofil",
    FUNCTION: "Funktion",
    BUILDING_TYPE: "typ",
    USAGE: "Nutzung",
    FLOOR_AREA: "NF [m²]",
    AGE: "Alter",
    CONSTRUCTION_CLASS: "BAK",
    # Streets
    ROUTABLE: "Moegliche_Route",
    # WLD
    LENGTH: "Laenge [m]",
    HEAT_LINE_DENSITY: "WLD [kWh/a*m]",
    CONNECTED_IDS: "angeschlossen",
    # Suitability polygons
    AREA: "Flaeche [m²]",
    N_CONNECTIONS: "Anschluesse",
    HEAT_DEMAND_DENSITY: "Waermebedarf/Flaeche [MWh/ha*a]",
    THERMAL_POWER_MEAN: "Mittlere thermische Leistung [kW]",
    # Network
    TYPE: "Typ",
    N_BUILDINGS: "Anzahl Gebaeude",
    THERMAL_POWER_GLF: "Leistung_th_GLF [kW]",
    VOLUME_FLOW: "Volumenstrom [l/s]",
    NOMINAL_DIAMETER: "DN [mm]",
    VELOCITY: "Geschwindigkeit [m/s]",
    HEAT_LOSS: "Verlust [kWh/a]",
    HEAT_LOSS_EXTRA_INSULATION: "Verlust bei extra Daemmung [kWh/a]",
    GLF: "GLF",
    # Load profile
    BUILDING_DEMAND_SUM: "Summe aller Gebäudetypen",
    LOSS: "Verlust",
    LOSS_EXTRA_INSULATION: "Verlust bei extra Dämmung",
    TOTAL: "Gesamtsumme",
    TOTAL_EXTRA_INSULATION: "Gesamtsumme (extra Dämmung)",
}


def to_display(df, mapping: dict[str, str] = LABELS_DE):
    """Rename canonical columns to display labels (e.g. for export).

    Columns not in the mapping (geometry, adapter-specific extra columns)
    are left unchanged. Returns a new object.
    """
    rename = {c: mapping[c] for c in df.columns if c in mapping}
    return df.rename(columns=rename) if rename else df
