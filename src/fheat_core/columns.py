"""Kanonische Spaltennamen — Single Source of Truth.

Die Pipeline arbeitet intern mit sprachneutralen, stabilen snake_case-Identifiern
*ohne* Einheit im Namen. Einheiten sind Metadaten (:data:`UNITS`), die deutsche
Beschriftung ist eine reine Anzeige-/Export-Angelegenheit (:data:`LABELS_DE`).

Adapter mappen ihre Quellspalten auf diese Konstanten; der Core liest und schreibt
ausschließlich diese Namen. Am Export-Boundary (``orchestrator.save_outputs``)
werden die kanonischen Namen über :func:`to_display` wieder auf deutsche Labels
übersetzt, damit Ausgabedateien für deutsche Nutzer unverändert bleiben.
"""
from __future__ import annotations


# ============================================================
# Gebäude — Eingangsspalten (Adapter liefert diese)
# ============================================================

BUILDING_ID = "building_id"          # eindeutiger Gebäudeindex
CONNECT = "connect"                  # 1 = an Netz anschließen, 0 = ausschließen
HEAT_DEMAND = "heat_demand"          # Jahreswärmebedarf [kWh/a]
THERMAL_POWER = "thermal_power"      # thermische Leistung [kW]
FULL_LOAD_HOURS = "full_load_hours"  # Volllaststunden [h]
LOAD_PROFILE = "load_profile"        # Lastprofil-Code (EFH, MFH, …)

# optional
FUNCTION = "function"
BUILDING_TYPE = "building_type"
USAGE = "usage"
FLOOR_AREA = "floor_area"            # Nettofläche [m²]
AGE = "age"
CONSTRUCTION_CLASS = "construction_class"  # Baualtersklasse (BAK)


# ============================================================
# Straßen — Eingangsspalten
# ============================================================

ROUTABLE = "routable"                # 1 = als Trasse nutzbar


# ============================================================
# WLD — Pipeline-Output
# ============================================================

LENGTH = "length"                    # Länge [m]
HEAT_LINE_DENSITY = "heat_line_density"  # Wärmeliniendichte [kWh/(a·m)]
CONNECTED_IDS = "connected_ids"      # kommaseparierte building_id-Liste


# ============================================================
# Eignungspolygone — Pipeline-Output
# ============================================================

AREA = "area"                        # Fläche [m²]
N_CONNECTIONS = "n_connections"      # Anzahl Anschlüsse
HEAT_DEMAND_DENSITY = "heat_demand_density"   # Wärmebedarf/Fläche [MWh/(ha·a)]
THERMAL_POWER_MEAN = "thermal_power_mean"     # mittlere thermische Leistung [kW]


# ============================================================
# Netz — Pipeline-Output
# ============================================================

TYPE = "type"                        # Leitungstyp
N_BUILDINGS = "n_buildings"          # Anzahl Gebäude auf der Kante
THERMAL_POWER_GLF = "thermal_power_glf"  # Leistung mit Gleichzeitigkeitsfaktor [kW]
VOLUME_FLOW = "volume_flow"          # Volumenstrom [l/s]
NOMINAL_DIAMETER = "nominal_diameter"    # Nenndurchmesser DN [mm]
VELOCITY = "velocity"                # Strömungsgeschwindigkeit [m/s]
HEAT_LOSS = "heat_loss"              # Wärmeverlust [kWh/a]
HEAT_LOSS_EXTRA_INSULATION = "heat_loss_extra_insulation"  # Verlust bei extra Dämmung [kWh/a]
GLF = "glf"                          # Gleichzeitigkeitsfaktor


# ============================================================
# Geometrie-interne Hilfsspalten
# ============================================================

CONNECTION_POINT = "connection_point"  # Anschlusspunkt auf der Trasse
CENTROID = "centroid"
STREET_ID = "street_id"


# ============================================================
# Lastprofil — Aggregatspalten
# ============================================================

BUILDING_DEMAND_SUM = "building_demand_sum"      # Summe aller Gebäudetypen
LOSS = "loss"                                    # Verlust
LOSS_EXTRA_INSULATION = "loss_extra_insulation"  # Verlust bei extra Dämmung
TOTAL = "total"                                  # Gesamtsumme
TOTAL_EXTRA_INSULATION = "total_extra_insulation"  # Gesamtsumme (extra Dämmung)


# ============================================================
# Einheiten (Metadaten)
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
# Deutsche Anzeige-Labels (Export-Boundary)
# ============================================================
# Werte entsprechen exakt den bisher geschriebenen Spaltennamen, damit sich
# Ausgabedateien (GeoPackage/GeoJSON) für deutsche Nutzer nicht ändern.

LABELS_DE: dict[str, str] = {
    # Gebäude
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
    # Straßen
    ROUTABLE: "Moegliche_Route",
    # WLD
    LENGTH: "Laenge [m]",
    HEAT_LINE_DENSITY: "WLD [kWh/a*m]",
    CONNECTED_IDS: "angeschlossen",
    # Eignungspolygone
    AREA: "Flaeche [m²]",
    N_CONNECTIONS: "Anschluesse",
    HEAT_DEMAND_DENSITY: "Waermebedarf/Flaeche [MWh/ha*a]",
    THERMAL_POWER_MEAN: "Mittlere thermische Leistung [kW]",
    # Netz
    TYPE: "Typ",
    N_BUILDINGS: "Anzahl Gebaeude",
    THERMAL_POWER_GLF: "Leistung_th_GLF [kW]",
    VOLUME_FLOW: "Volumenstrom [l/s]",
    NOMINAL_DIAMETER: "DN [mm]",
    VELOCITY: "Geschwindigkeit [m/s]",
    HEAT_LOSS: "Verlust [kWh/a]",
    HEAT_LOSS_EXTRA_INSULATION: "Verlust bei extra Daemmung [kWh/a]",
    GLF: "GLF",
    # Lastprofil
    BUILDING_DEMAND_SUM: "Summe aller Gebäudetypen",
    LOSS: "Verlust",
    LOSS_EXTRA_INSULATION: "Verlust bei extra Dämmung",
    TOTAL: "Gesamtsumme",
    TOTAL_EXTRA_INSULATION: "Gesamtsumme (extra Dämmung)",
}


def to_display(df, mapping: dict[str, str] = LABELS_DE):
    """Benennt kanonische Spalten in Anzeige-Labels um (z. B. für den Export).

    Spalten, die nicht im Mapping stehen (Geometrie, adapter-spezifische
    Zusatzspalten), bleiben unverändert. Gibt ein neues Objekt zurück.
    """
    rename = {c: mapping[c] for c in df.columns if c in mapping}
    return df.rename(columns=rename) if rename else df
