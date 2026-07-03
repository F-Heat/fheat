"""Beispiel: Wärmenetzanalyse Burgsteinfurt (NRW).

Schritte:
    1. Strassen, Flurstuecke, Gebaeude herunterladen (NRW Open Geodata)
    2. Strassen und Gebaeude bereinigen (adjust)
    3. Planungsgebiet zuschneiden
    4. Wärmedichte-Blöcke berechnen (status)
    5. Netzberechnung (network)  →  Netz.gpkg
    6. Lastprofil + Ergebniszusammenfassung (results)
    7. Alle Ausgaben speichern

Voraussetzungen:
    - planungsgebiet.gpkg im selben Verzeichnis wie dieses Skript (oder Pfad anpassen)
    - .venv mit installierten Paketen: pip install -e ".[nrw]"  (im Repo-Root)
    - Internetverbindung (NRW WFS / ZIP-Download)

Rohdatenspalten (NRW) → kanonisches Schema (siehe fheat_core.columns):
    - Wärmebedarf:      RW_WW  (oder RW_WW [kWh/a])  → wird zu  heat_demand
    - Therm. Leistung:  Leistung_th                   → wird zu  thermal_power

Intern arbeitet die Pipeline mit sprachneutralen Spaltennamen; save_outputs()
übersetzt sie beim Export auf deutsche Labels (output_language="de").
"""
from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd

from fheat_core import columns as cols
from fheat_core.config import FHeatConfig
from fheat_core.orchestrator import FHeatOrchestrator
from fheat_core.state import Phase
from fheat_nrw.adapter.data_adapter import NRWDataAdapter

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

# ---------------------------------------------------------------------------
# Pfade
# ---------------------------------------------------------------------------
HERE = Path(__file__).parent
AREA_PATH = HERE / "planungsgebiet.gpkg"
OUTPUT_DIR = HERE / "output_burgsteinfurt"

# ---------------------------------------------------------------------------
# Adapter + Config
# ---------------------------------------------------------------------------
adapter = NRWDataAdapter(
    city_name="Burgsteinfurt",               # Stadtteil/Gemarkung (gemeinde = "Steinfurt")
    source_coordinates=(52.1592, 7.3268),   # (lat, lon) WGS84 — Einspeisepunkt
    heat_attribute="RW_WW",                  # NRW-Rohdatenspalte; [kWh/a]-Suffix wird autom. erkannt
)

config = FHeatConfig(
    supply_temperature=80.0,
    return_temperature=50.0,
    wld_threshold=500.0,     # WLD-Schwellenwert [kWh/(a·m)]
    buffer_distance=50.0,    # Puffer für Eignungspolygone [m]
    year=2022,
    output_dir=str(OUTPUT_DIR),
    output_format="gpkg",
)

# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
orch = FHeatOrchestrator(config=config, adapter=adapter)

# ---------------------------------------------------------------------------
# Schritt 1: Download — Strassen, Flurstuecke, Gebaeude
# ---------------------------------------------------------------------------
logging.info("=== Schritt 1: Download ===")
orch.run_step(Phase.INITIAL)

# ---------------------------------------------------------------------------
# Schritt 2: Planungsgebiet-Clip
#   Gebaeude und Strassen auf das Planungsgebiet zuschneiden.
#   Dieser manuelle Schritt kommt NACH dem Download (vollständige NRW-Daten)
#   und VOR adjust (Clip auf schema-konformen, noch unbereinigten Daten).
# ---------------------------------------------------------------------------
logging.info("=== Schritt 2: Planungsgebiet-Clip ===")

area = gpd.read_file(AREA_PATH).to_crs(orch.state.buildings_gdf.crs)
area_geom = area.geometry.union_all()   # shapely ≥ 2.0; für ältere: unary_union(area.geometry)

orch.state.buildings_gdf = (
    orch.state.buildings_gdf[orch.state.buildings_gdf.geometry.intersects(area_geom)]
    .reset_index(drop=True)
)
orch.state.streets_gdf = (
    orch.state.streets_gdf[orch.state.streets_gdf.geometry.intersects(area_geom)]
    .reset_index(drop=True)
)

logging.info(
    "Nach Clip: %d Gebäude, %d Straßensegmente",
    len(orch.state.buildings_gdf),
    len(orch.state.streets_gdf),
)

# ---------------------------------------------------------------------------
# Schritt 3: Adjust — Strassen und Gebaeude bereinigen
# ---------------------------------------------------------------------------
logging.info("=== Schritt 3: Adjust ===")
orch.run_step(Phase.DOWNLOADED)

# ---------------------------------------------------------------------------
# Schritt 4: Status — Wärmedichte-Blöcke berechnen
# ---------------------------------------------------------------------------
logging.info("=== Schritt 4: Wärmedichte-Blöcke (Status) ===")
orch.run_step(Phase.ADJUSTED)

logging.info(
    "Wärmedichte-Blöcke: %d Straßensegmente analysiert, %d Eignungspolygone",
    len(orch.state.wld_gdf) if orch.state.wld_gdf is not None else 0,
    len(orch.state.polygons_gdf) if orch.state.polygons_gdf is not None else 0,
)

# ---------------------------------------------------------------------------
# Optional: Nur bis hierher ausführen (z. B. für manuelle Netzplanung)
#
#   orch.save_outputs()
#   raise SystemExit
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Schritt 5: Netzberechnung
#   buildings_gdf.connect == 1 und streets_gdf.routable == 1 werden
#   durch den Adapter bereits gesetzt. Für manuelle Selektion können diese
#   Felder vor diesem Schritt überschrieben werden.
# ---------------------------------------------------------------------------
logging.info("=== Schritt 5: Netzberechnung ===")
orch.run_step(Phase.STATUS)

# Netz sofort als eigene Datei speichern
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
netz_path = OUTPUT_DIR / "Netz.gpkg"
netz_path.unlink(missing_ok=True)
cols.to_display(orch.state.net_gdf).to_file(netz_path, driver="GPKG")
logging.info("Netz gespeichert → %s", netz_path)

# ---------------------------------------------------------------------------
# Schritt 6: Lastprofil + Ergebniszusammenfassung
# ---------------------------------------------------------------------------
logging.info("=== Schritt 6: Ergebnisse ===")
orch.run_step(Phase.NETWORK)

summary = orch.state.result_summary
if summary:
    print("\n--- Ergebniszusammenfassung ---")
    print(f"  Gesamtwärmebedarf:          {summary['total_heat_demand_mwh_a']:.1f} MWh/a")
    print(f"  Angeschlossene Gebäude:     {summary['total_buildings']}")
    print(f"  Therm. Leistung (GLF):      {summary['total_power_glf_kw']:.1f} kW")
    print(f"  GLF:                        {summary['glf']:.3f}")
    print(f"  Netzlänge:                  {summary['total_network_length_m']:.0f} m")
    print(f"  Netzwärmeverlust:           {summary['total_loss_mwh_a']:.1f} MWh/a")
    print(f"  Vorlauftemperatur:          {summary['supply_temperature_c']} °C")
    print(f"  Rücklauftemperatur:         {summary['return_temperature_c']} °C")

# ---------------------------------------------------------------------------
# Schritt 7: Alle Ausgaben speichern
# ---------------------------------------------------------------------------
logging.info("=== Schritt 7: Speichern ===")
saved = orch.save_outputs()
for layer, path in saved.items():
    print(f"  {layer:20s} → {path}")
