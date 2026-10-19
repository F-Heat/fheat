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
PARCEL_YEAR = "parcel_year"                # NRW: year of the parcel's validFrom (BAK input; a proxy, not the construction year)
BLOCK_ID = "block_id"                      # building block of the source (NRW: LANUV Block_ID), for XWaermeplan
XWP_BUILDING_TYPE = "xwp_building_type"    # code of WP_GebaeudeTyp (XWaermeplan), see fheat_core/xwp/mapping/building_type.py
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
# Potential layers (optional, see DataAdapter.fetch_geothermal_*)
# ============================================================

# Shallow geothermal parameters (NRW: GD NRW IS GT 50, scale 1:50,000)
GROUND_CONDUCTIVITY_40 = "ground_conductivity_40"    # thermal conductivity, probe 40 m [W/(m·K)]
GROUND_CONDUCTIVITY_60 = "ground_conductivity_60"    # dto. 60 m [W/(m·K)]
GROUND_CONDUCTIVITY_80 = "ground_conductivity_80"    # dto. 80 m [W/(m·K)]
GROUND_CONDUCTIVITY_100 = "ground_conductivity_100"  # dto. 100 m [W/(m·K)]
COLLECTOR_EXTRACTION_1800 = "collector_extraction_1800"  # ground collector, 1800 h/a [W/m²]
COLLECTOR_EXTRACTION_2400 = "collector_extraction_2400"  # dto. 2400 h/a [W/m²]
# Screening value from the conductivity (VDI 4640-2:2001), NOT for design
BOREHOLE_EXTRACTION_1800 = "borehole_extraction_1800"    # borehole heat exchanger, 1800 h/a [W/m]
BOREHOLE_EXTRACTION_2400 = "borehole_extraction_2400"    # dto. 2400 h/a [W/m]
GEOTHERMAL_STATUS = "geothermal_status"  # assessed / partly_assessed / not_assessed

# Shallow and medium-deep geothermal potential per building block (NRW: LANUK
# heat study). A value of the whole block, never split onto its buildings.
ONG_POTENTIAL_MWH = "ong_potential_mwh"            # shallow geothermal yield today [MWh/a]
ONG_POTENTIAL_2045_MWH = "ong_potential_2045_mwh"  # dto. 2045 [MWh/a]
MTG_POTENTIAL_MWH = "mtg_potential_mwh"            # medium-deep borehole heat exchangers today [MWh/a]
MTG_POTENTIAL_2045_MWH = "mtg_potential_2045_mwh"  # dto. 2045 [MWh/a]
BLOCK_HEATING_LOAD = "block_heating_load"          # heating load of the block's buildings [kW]
BLOCK_HEATING_LOAD_2045 = "block_heating_load_2045"  # dto. 2045 [kW]
BLOCK_POTENTIAL_STATUS = "block_potential_status"  # assessed / not_assessed

#: values of GEOTHERMAL_STATUS / BLOCK_POTENTIAL_STATUS
STATUS_ASSESSED = "assessed"
STATUS_PARTLY_ASSESSED = "partly_assessed"
STATUS_NOT_ASSESSED = "not_assessed"

# Hydrothermal doublet per grid cell (NRW: LANUK heat study, 3 × 3 km raster).
# A rough estimate: whether a well finds water is unknown. MT = medium-deep
# reservoir (400-1,500 m), T = deep reservoir (1,500-5,000 m); P10/P50/P90 =
# reached with 10/50/90 % probability.
DOUBLET_MT_P10_MW = "doublet_mt_p10_mw"      # thermal power [MW]
DOUBLET_MT_P50_MW = "doublet_mt_p50_mw"      # [MW]
DOUBLET_MT_P90_MW = "doublet_mt_p90_mw"      # [MW]
DOUBLET_T_P10_MW = "doublet_t_p10_mw"        # [MW]
DOUBLET_T_P50_MW = "doublet_t_p50_mw"        # [MW]
DOUBLET_T_P90_MW = "doublet_t_p90_mw"        # [MW]
DOUBLET_MT_P10_MWH = "doublet_mt_p10_mwh"    # heat yield at the full load hours [MWh/a]
DOUBLET_MT_P50_MWH = "doublet_mt_p50_mwh"    # [MWh/a]
DOUBLET_MT_P90_MWH = "doublet_mt_p90_mwh"    # [MWh/a]
DOUBLET_T_P10_MWH = "doublet_t_p10_mwh"      # [MWh/a]
DOUBLET_T_P50_MWH = "doublet_t_p50_mwh"      # [MWh/a]
DOUBLET_T_P90_MWH = "doublet_t_p90_mwh"      # [MWh/a]
DOUBLET_FULL_LOAD_HOURS = "doublet_full_load_hours"  # [h/a]
DEEP_POTENTIAL_MWH = "deep_potential_mwh"    # better reservoir of the cell, P50 [MWh/a] (upper bound)
CELL_SHARE = "cell_share"                    # share of the cell inside NRW [%]
DEEP_NOTE_DEPTH = "deep_note_depth"          # source note on potential below 5,000 m
DEEP_NOTE_SURVEY = "deep_note_survey"        # source note on ongoing surveys
DISTANCE_TO_AREA = "distance_to_area"        # distance to the loaded area [m], 0 = inside
SOURCE_CANDIDATE_LAT = "source_candidate_lat"  # cell centre, WGS84 latitude (for source_coordinates)
SOURCE_CANDIDATE_LON = "source_candidate_lon"  # cell centre, WGS84 longitude


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
    GROUND_CONDUCTIVITY_40: "W/(m·K)",
    GROUND_CONDUCTIVITY_60: "W/(m·K)",
    GROUND_CONDUCTIVITY_80: "W/(m·K)",
    GROUND_CONDUCTIVITY_100: "W/(m·K)",
    COLLECTOR_EXTRACTION_1800: "W/m²",
    COLLECTOR_EXTRACTION_2400: "W/m²",
    BOREHOLE_EXTRACTION_1800: "W/m",
    BOREHOLE_EXTRACTION_2400: "W/m",
    ONG_POTENTIAL_MWH: "MWh/a",
    ONG_POTENTIAL_2045_MWH: "MWh/a",
    MTG_POTENTIAL_MWH: "MWh/a",
    MTG_POTENTIAL_2045_MWH: "MWh/a",
    BLOCK_HEATING_LOAD: "kW",
    BLOCK_HEATING_LOAD_2045: "kW",
    DOUBLET_MT_P10_MW: "MW",
    DOUBLET_MT_P50_MW: "MW",
    DOUBLET_MT_P90_MW: "MW",
    DOUBLET_T_P10_MW: "MW",
    DOUBLET_T_P50_MW: "MW",
    DOUBLET_T_P90_MW: "MW",
    DOUBLET_MT_P10_MWH: "MWh/a",
    DOUBLET_MT_P50_MWH: "MWh/a",
    DOUBLET_MT_P90_MWH: "MWh/a",
    DOUBLET_T_P10_MWH: "MWh/a",
    DOUBLET_T_P50_MWH: "MWh/a",
    DOUBLET_T_P90_MWH: "MWh/a",
    DOUBLET_FULL_LOAD_HOURS: "h/a",
    DEEP_POTENTIAL_MWH: "MWh/a",
    CELL_SHARE: "%",
    DISTANCE_TO_AREA: "m",
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
    PARCEL_YEAR: "Jahr_Flurstueck",
    XWP_BUILDING_TYPE: "Gebaeudetyp_XWP",
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
    # Potential layers
    GROUND_CONDUCTIVITY_40: "Waermeleitfaehigkeit 40m [W/m*K]",
    GROUND_CONDUCTIVITY_60: "Waermeleitfaehigkeit 60m [W/m*K]",
    GROUND_CONDUCTIVITY_80: "Waermeleitfaehigkeit 80m [W/m*K]",
    GROUND_CONDUCTIVITY_100: "Waermeleitfaehigkeit 100m [W/m*K]",
    COLLECTOR_EXTRACTION_1800: "Entzug Kollektor 1800h [W/m²]",
    COLLECTOR_EXTRACTION_2400: "Entzug Kollektor 2400h [W/m²]",
    BOREHOLE_EXTRACTION_1800: "Richtwert Entzug Sonde 1800h [W/m]",
    BOREHOLE_EXTRACTION_2400: "Richtwert Entzug Sonde 2400h [W/m]",
    GEOTHERMAL_STATUS: "Bewertung Geothermie",
    ONG_POTENTIAL_MWH: "Potenzial ONG Baublock [MWh/a]",
    ONG_POTENTIAL_2045_MWH: "Potenzial ONG Baublock 2045 [MWh/a]",
    MTG_POTENTIAL_MWH: "Potenzial MTG Baublock [MWh/a]",
    MTG_POTENTIAL_2045_MWH: "Potenzial MTG Baublock 2045 [MWh/a]",
    BLOCK_HEATING_LOAD: "Heizlast Baublock [kW]",
    BLOCK_HEATING_LOAD_2045: "Heizlast Baublock 2045 [kW]",
    BLOCK_POTENTIAL_STATUS: "Bewertung Baublock",
    DOUBLET_MT_P10_MW: "MTG Dublette P10 [MW]",
    DOUBLET_MT_P50_MW: "MTG Dublette P50 [MW]",
    DOUBLET_MT_P90_MW: "MTG Dublette P90 [MW]",
    DOUBLET_T_P10_MW: "TG Dublette P10 [MW]",
    DOUBLET_T_P50_MW: "TG Dublette P50 [MW]",
    DOUBLET_T_P90_MW: "TG Dublette P90 [MW]",
    DOUBLET_MT_P10_MWH: "MTG Dublette P10 [MWh/a]",
    DOUBLET_MT_P50_MWH: "MTG Dublette P50 [MWh/a]",
    DOUBLET_MT_P90_MWH: "MTG Dublette P90 [MWh/a]",
    DOUBLET_T_P10_MWH: "TG Dublette P10 [MWh/a]",
    DOUBLET_T_P50_MWH: "TG Dublette P50 [MWh/a]",
    DOUBLET_T_P90_MWH: "TG Dublette P90 [MWh/a]",
    DOUBLET_FULL_LOAD_HOURS: "Vlh Dublette [h/a]",
    DEEP_POTENTIAL_MWH: "Potenzial Dublette P50 [MWh/a]",
    CELL_SHARE: "Anteil in NRW [%]",
    DEEP_NOTE_DEPTH: "Hinweis Tiefe",
    DEEP_NOTE_SURVEY: "Hinweis Bearbeitung",
    DISTANCE_TO_AREA: "Abstand Gebiet [m]",
    SOURCE_CANDIDATE_LAT: "Quelle Breite",
    SOURCE_CANDIDATE_LON: "Quelle Laenge",
}


# German labels for the keys of ``PipelineState.result_summary`` (table export).
SUMMARY_LABELS_DE: dict[str, str] = {
    "total_heat_demand_mwh_a": "Gesamtwärmebedarf [MWh/a]",
    "total_buildings": "Angeschlossene Gebäude",
    "total_power_glf_kw": "Thermische Leistung (GLF) [kW]",
    "glf": "Gleichzeitigkeitsfaktor",
    "total_network_length_m": "Netzlänge [m]",
    "total_house_connection_length_m": "Hausanschlusslänge [m]",
    "total_route_length_m": "Trassenlänge [m]",
    "total_loss_mwh_a": "Netzwärmeverlust [MWh/a]",
    "total_loss_extra_insulation_mwh_a": "Netzwärmeverlust bei extra Dämmung [MWh/a]",
    "supply_temperature_c": "Vorlauftemperatur [°C]",
    "return_temperature_c": "Rücklauftemperatur [°C]",
    "civil_cost_share": "Tiefbauanteil der Rohrkosten",
    "total_pipe_cost_eur": "Investition Rohrleitungen [€]",
    "total_civil_cost_eur": "davon Tiefbau [€]",
    "mean_civil_cost_factor": "Mittlerer Tiefbaufaktor",
}


def to_display(df, mapping: dict[str, str] = LABELS_DE):
    """Rename canonical columns to display labels (e.g. for export).

    Columns not in the mapping (geometry, adapter-specific extra columns)
    are left unchanged. Returns a new object.
    """
    rename = {c: mapping[c] for c in df.columns if c in mapping}
    return df.rename(columns=rename) if rename else df


def from_display(df, mapping: dict[str, str] = LABELS_DE):
    """Inverse of :func:`to_display`: German display labels back to canonical names.

    For files written by ``save_outputs`` with ``output_language="de"``.
    Columns that are no label stay unchanged. Returns a new object.
    """
    inverse = {label: name for name, label in mapping.items()}
    rename = {c: inverse[c] for c in df.columns if c in inverse}
    return df.rename(columns=rename) if rename else df
