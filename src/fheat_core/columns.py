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
ADDRESS = "address"                  # address text of the building (NRW: ALKIS lagebeztxt)
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
# Expansion potential of an edge for an average building power, computed on
# request and never stored (fheat_core/algorithms/expansion.py)
EXPANDABLE_POWER = "expandable_power"        # building power connectable at the edge before a DN on its way to the source grows [kW]
POTENTIAL_BUILDINGS = "potential_buildings"  # buildings of the average power that fit into it

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
SOURCE_CANDIDATE_LAT = "source_candidate_lat"  # point inside the cell or field, WGS84 latitude (for source_coordinates)
SOURCE_CANDIDATE_LON = "source_candidate_lon"  # dto. WGS84 longitude

# Ground-mounted solar thermal per cadastral district (NRW: LANUK heat study)
FLUR_ID = "flur_id"                                  # id of the cadastral district (Flur)
SOLAR_USABLE_AREA = "solar_usable_area"              # usable area without a 3 m margin [m²]
SOLAR_FLAT_PLATE_MWH = "solar_flat_plate_mwh"        # flat plate collectors, 60 °C [MWh/a]
SOLAR_VACUUM_TUBE_MWH = "solar_vacuum_tube_mwh"      # vacuum tube collectors, 90 °C [MWh/a]
SOLAR_TROUGH_NS_MWH = "solar_trough_ns_mwh"          # parabolic trough north-south, 150 °C [MWh/a]
SOLAR_TROUGH_EW_MWH = "solar_trough_ew_mwh"          # parabolic trough east-west, 150 °C [MWh/a]
SOLAR_FLAT_PLATE_SPECIFIC = "solar_flat_plate_specific"    # yield per usable area [kWh/(m²·a)]
SOLAR_VACUUM_TUBE_SPECIFIC = "solar_vacuum_tube_specific"  # [kWh/(m²·a)]
SOLAR_TROUGH_NS_SPECIFIC = "solar_trough_ns_specific"      # [kWh/(m²·a)]
SOLAR_TROUGH_EW_SPECIFIC = "solar_trough_ew_specific"      # [kWh/(m²·a)]
DISTANCE_TO_DEMAND = "distance_to_demand"            # to the nearest building with heat demand [m]


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
# present only when the adapter provides the potential layer (algorithms/potentials.py)
TOTAL_ONG_POTENTIAL = "ong_potential_mwh_a"                        # shallow geothermal of the blocks of the connected buildings [MWh/a]
TOTAL_MTG_POTENTIAL = "mtg_potential_mwh_a"                        # medium-deep geothermal (probes) of these blocks [MWh/a]
MAX_DEEP_POTENTIAL = "deep_potential_max_mwh_a"                    # largest doublet cell around the area (P50) [MWh/a]
TOTAL_SOLAR_THERMAL_FLAT_PLATE = "solar_thermal_flat_plate_mwh_a"  # ground-mounted solar thermal around the area, flat plate [MWh/a]
TOTAL_SOLAR_THERMAL_AREA = "solar_thermal_area_m2"                 # its usable area [m²]
# outdoor temperatures of the load profile (steps/results.py); the station
# keys and WEATHER_YEAR only for a DWD year, the reason only after a fallback
TEMPERATURE_SOURCE = "temperature_source"                          # "dwd" | "example" | "adapter"
WEATHER_STATION_ID = "weather_station_id"                          # DWD station id
WEATHER_STATION_NAME = "weather_station_name"                      # DWD station name
WEATHER_STATION_DISTANCE = "weather_station_distance_km"           # station to the centre of the area [km]
WEATHER_YEAR = "weather_year"                                      # measured year
MEAN_OUTDOOR_TEMPERATURE = "mean_outdoor_temperature_c"            # annual mean [°C]
MIN_OUTDOOR_TEMPERATURE = "min_outdoor_temperature_c"              # lowest hourly value [°C]
HEATING_DEGREE_DAYS = "heating_degree_days_kd"                     # G20/15 after VDI 3807 [K·d]
TEMPERATURE_FALLBACK_REASON = "temperature_fallback_reason"        # why the example year was used instead


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
    EXPANDABLE_POWER: "kW",
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
    SOLAR_USABLE_AREA: "m²",
    SOLAR_FLAT_PLATE_MWH: "MWh/a",
    SOLAR_VACUUM_TUBE_MWH: "MWh/a",
    SOLAR_TROUGH_NS_MWH: "MWh/a",
    SOLAR_TROUGH_EW_MWH: "MWh/a",
    SOLAR_FLAT_PLATE_SPECIFIC: "kWh/(m²·a)",
    SOLAR_VACUUM_TUBE_SPECIFIC: "kWh/(m²·a)",
    SOLAR_TROUGH_NS_SPECIFIC: "kWh/(m²·a)",
    SOLAR_TROUGH_EW_SPECIFIC: "kWh/(m²·a)",
    DISTANCE_TO_DEMAND: "m",
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
    ADDRESS: "Adresse",
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
    FLUR_ID: "Flur_ID",
    SOLAR_USABLE_AREA: "Nutzflaeche [m²]",
    SOLAR_FLAT_PLATE_MWH: "Flachkollektor [MWh/a]",
    SOLAR_VACUUM_TUBE_MWH: "Vakuumroehre [MWh/a]",
    SOLAR_TROUGH_NS_MWH: "Parabolrinne N-S [MWh/a]",
    SOLAR_TROUGH_EW_MWH: "Parabolrinne O-W [MWh/a]",
    SOLAR_FLAT_PLATE_SPECIFIC: "Flachkollektor [kWh/m²*a]",
    SOLAR_VACUUM_TUBE_SPECIFIC: "Vakuumroehre [kWh/m²*a]",
    SOLAR_TROUGH_NS_SPECIFIC: "Parabolrinne N-S [kWh/m²*a]",
    SOLAR_TROUGH_EW_SPECIFIC: "Parabolrinne O-W [kWh/m²*a]",
    DISTANCE_TO_DEMAND: "Abstand Waermebedarf [m]",
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
    TOTAL_ONG_POTENTIAL: "Potenzial oberflächennahe Geothermie der Baublöcke [MWh/a]",
    TOTAL_MTG_POTENTIAL: "Potenzial mitteltiefe Geothermie (Sonden) der Baublöcke [MWh/a]",
    MAX_DEEP_POTENTIAL: "Größtes Potenzial einer Dublette im Umkreis (P50) [MWh/a]",
    TOTAL_SOLAR_THERMAL_FLAT_PLATE: "Freiflächen-Solarthermie im Umkreis, Flachkollektor [MWh/a]",
    TOTAL_SOLAR_THERMAL_AREA: "Nutzfläche Freiflächen-Solarthermie im Umkreis [m²]",
    TEMPERATURE_SOURCE: "Temperaturjahr",
    WEATHER_STATION_ID: "DWD-Stationskennung",
    WEATHER_STATION_NAME: "DWD-Station",
    WEATHER_STATION_DISTANCE: "Entfernung DWD-Station [km]",
    WEATHER_YEAR: "Wetterjahr",
    MEAN_OUTDOOR_TEMPERATURE: "Mittlere Außentemperatur [°C]",
    MIN_OUTDOOR_TEMPERATURE: "Niedrigste Außentemperatur [°C]",
    HEATING_DEGREE_DAYS: "Gradtagzahl G20/15 [Kd]",
    TEMPERATURE_FALLBACK_REASON: "Hinweis Temperaturjahr",
}


def to_display(df, mapping: dict[str, str] = LABELS_DE):
    """Rename canonical columns to display labels (e.g. for export).

    Columns not in the mapping (geometry, adapter-specific extra columns)
    are left unchanged. Returns a new object.
    """
    rename = {c: mapping[c] for c in df.columns if c in mapping}
    return df.rename(columns=rename) if rename else df
