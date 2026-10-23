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
CONSTRUCTION_YEAR = "construction_year"    # year of construction, where the source knows it
BLOCK_ID = "block_id"                      # building block of the source (NRW: LANUV Block_ID)
# Both heat demand values, so FHeatConfig.heat_demand_basis can choose which
# one becomes HEAT_DEMAND (see steps/adjust.py).
HEAT_DEMAND_DATASET = "heat_demand_dataset"        # as delivered by the data source [kWh/a]
HEAT_DEMAND_CALCULATED = "heat_demand_calculated"  # floor area × specific demand of the age class [kWh/a]


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
# Civil works (written by the NETWORK step, see fheat_core/network/costs.py)
CIVIL_COST_FACTOR = "civil_cost_factor"  # civil works factor of the route (1.0 = neutral)
ROAD_SURFACE = "road_surface"        # dominant road surface / class along the edge
PIPE_COST = "pipe_cost"              # pipe investment of the edge [€]
CIVIL_COST = "civil_cost"            # civil works part of pipe_cost [€]
# Written by the NETWORK step (fheat_core/algorithms/under_buildings.py)
LENGTH_UNDER_BUILDINGS = "length_under_buildings"  # house connection under other buildings [m], 0 = none

# Value of TYPE for a building's house connection. Every other edge type
# (street pipe, source connection) counts as route in the pipe summary.
EDGE_TYPE_HOUSE_CONNECTION = "Hausanschluss"


# ============================================================
# Result tables — pipe summary per DN, buildings per load profile
# ============================================================

N_HOUSE_CONNECTIONS = "n_house_connections"          # number of house connections
HOUSE_CONNECTION_LENGTH = "house_connection_length"  # house connection length [m]
ROUTE_LENGTH = "route_length"                        # route (trunk) length [m]
HEAT_LOSS_MWH = "heat_loss_mwh"                      # heat loss [MWh/a]
HEAT_LOSS_EXTRA_INSULATION_MWH = "heat_loss_extra_insulation_mwh"  # heat loss with extra insulation [MWh/a]
HEAT_DEMAND_MWH = "heat_demand_mwh"                  # heat demand [MWh/a]


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
# Result summary — keys of PipelineState.result_summary
# (the simultaneity factor of the network is the key GLF)
# ============================================================

TOTAL_HEAT_DEMAND = "total_heat_demand_mwh_a"                      # heat demand of the connected buildings [MWh/a]
TOTAL_BUILDINGS = "total_buildings"                                # connected buildings
TOTAL_POWER_GLF = "total_power_glf_kw"                             # thermal power with simultaneity factor [kW]
TOTAL_NETWORK_LENGTH = "total_network_length_m"                    # all edges [m]
TOTAL_HOUSE_CONNECTION_LENGTH = "total_house_connection_length_m"  # house connections [m]
TOTAL_ROUTE_LENGTH = "total_route_length_m"                        # route without house connections [m]
TOTAL_LOSS = "total_loss_mwh_a"                                    # heat loss of the network [MWh/a]
TOTAL_LOSS_EXTRA_INSULATION = "total_loss_extra_insulation_mwh_a"  # heat loss with extra insulation [MWh/a]
SUPPLY_TEMPERATURE = "supply_temperature_c"                        # supply temperature [°C]
RETURN_TEMPERATURE = "return_temperature_c"                        # return temperature [°C]
CIVIL_COST_SHARE = "civil_cost_share"                              # civil works share of the pipe costs (config)
TOTAL_PIPE_COST = "total_pipe_cost_eur"                            # pipe investment [€]
TOTAL_CIVIL_COST = "total_civil_cost_eur"                          # civil works part of the pipe investment [€]
MEAN_CIVIL_COST_FACTOR = "mean_civil_cost_factor"                  # civil works factor, weighted by length


# ============================================================
# Units (metadata)
# ============================================================

UNITS: dict[str, str] = {
    HEAT_DEMAND: "kWh/a",
    HEAT_DEMAND_DATASET: "kWh/a",
    HEAT_DEMAND_CALCULATED: "kWh/a",
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
    HOUSE_CONNECTION_LENGTH: "m",
    LENGTH_UNDER_BUILDINGS: "m",
    ROUTE_LENGTH: "m",
    HEAT_LOSS_MWH: "MWh/a",
    HEAT_LOSS_EXTRA_INSULATION_MWH: "MWh/a",
    HEAT_DEMAND_MWH: "MWh/a",
    PIPE_COST: "€",
    CIVIL_COST: "€",
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
    CONSTRUCTION_YEAR: "Baujahr",
    BLOCK_ID: "Block_ID",
    # same names as the attributes of the former QGIS plugin
    HEAT_DEMAND_DATASET: "RW_WW [kWh/a]",
    HEAT_DEMAND_CALCULATED: "WB [kWh/a]",
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
    CIVIL_COST_FACTOR: "Tiefbau_Faktor",
    ROAD_SURFACE: "Belag",
    LENGTH_UNDER_BUILDINGS: "Unter Gebaeuden [m]",
    PIPE_COST: "Rohrkosten [€]",
    CIVIL_COST: "Tiefbaukosten [€]",
    # Load profile
    BUILDING_DEMAND_SUM: "Summe aller Gebäudetypen",
    LOSS: "Verlust",
    LOSS_EXTRA_INSULATION: "Verlust bei extra Dämmung",
    TOTAL: "Gesamtsumme",
    TOTAL_EXTRA_INSULATION: "Gesamtsumme (extra Dämmung)",
    # Result tables (same labels as the former QGIS plugin)
    N_HOUSE_CONNECTIONS: "Anzahl Hausanschluesse",
    HOUSE_CONNECTION_LENGTH: "Hausanschlusslaenge [m]",
    ROUTE_LENGTH: "Trassenlaenge [m]",
    HEAT_LOSS_MWH: "Verlust [MWh/a]",
    HEAT_LOSS_EXTRA_INSULATION_MWH: "Verlust bei extra Daemmung [MWh/a]",
    HEAT_DEMAND_MWH: "Waermebedarf [MWh/a]",
}


# German labels for the keys of ``PipelineState.result_summary`` (table export).
SUMMARY_LABELS_DE: dict[str, str] = {
    TOTAL_HEAT_DEMAND: "Gesamtwärmebedarf [MWh/a]",
    TOTAL_BUILDINGS: "Angeschlossene Gebäude",
    TOTAL_POWER_GLF: "Thermische Leistung (GLF) [kW]",
    GLF: "Gleichzeitigkeitsfaktor",
    TOTAL_NETWORK_LENGTH: "Netzlänge [m]",
    TOTAL_HOUSE_CONNECTION_LENGTH: "Hausanschlusslänge [m]",
    TOTAL_ROUTE_LENGTH: "Trassenlänge [m]",
    TOTAL_LOSS: "Netzwärmeverlust [MWh/a]",
    TOTAL_LOSS_EXTRA_INSULATION: "Netzwärmeverlust bei extra Dämmung [MWh/a]",
    SUPPLY_TEMPERATURE: "Vorlauftemperatur [°C]",
    RETURN_TEMPERATURE: "Rücklauftemperatur [°C]",
    CIVIL_COST_SHARE: "Tiefbauanteil der Rohrkosten",
    TOTAL_PIPE_COST: "Investition Rohrleitungen [€]",
    TOTAL_CIVIL_COST: "davon Tiefbau [€]",
    MEAN_CIVIL_COST_FACTOR: "Mittlerer Tiefbaufaktor",
}


def to_display(df, mapping: dict[str, str] = LABELS_DE):
    """Rename canonical columns to display labels (e.g. for export).

    Columns not in the mapping (geometry, adapter-specific extra columns)
    are left unchanged. Returns a new object.
    """
    rename = {c: mapping[c] for c in df.columns if c in mapping}
    return df.rename(columns=rename) if rename else df
