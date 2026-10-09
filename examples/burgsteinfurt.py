"""Beispiel: Wärmenetzanalyse Burgsteinfurt (NRW).

Stufe A – Potenzialanalyse (ganzer Stadtteil, ohne Wärmequelle):
    1. Strassen, Flurstuecke, Gebaeude des ganzen Stadtteils herunterladen (NRW Open Geodata)
    2. Strassen und Gebaeude bereinigen (adjust)
    3. Wärmeliniendichte und Eignungspolygone berechnen (status)  →  wld.gpkg, eignungspolygone.gpkg
Stufe B – Netzplanung (Planungsgebiet + Wärmequelle):
    4. Planungsgebiet und Wärmequelle setzen
    5. Netzberechnung (network)  →  Netz.gpkg
    6. Lastprofil, Ergebniszusammenfassung, Rohrkosten, Rohrmengen je DN, Gebäude je Lastprofil (results)
    7. Ausgaben im Planungsgebiet speichern (GeoPackages + fheat-ergebnisse.xlsx bzw. CSV + Lastprofil-Grafiken)

Jeder Schritt läuft hier einzeln (run_step); orch.run_analysis() bzw.
orch.run_planning() führen eine Stufe in einem Aufruf aus.

Voraussetzungen:
    - planungsgebiet.gpkg im selben Verzeichnis wie dieses Skript (oder Pfad anpassen)
    - .venv mit installierten Paketen: pip install -e ".[nrw]"  (im Repo-Root)
    - Internetverbindung (NRW WFS / ZIP-Download; ALKIS-Nutzung und OSM-Straßenbeläge
      für die Tiefbaukosten — fehlen sie, rechnet das Netz mit Tiefbaufaktor 1,0)

Rohdatenspalten (NRW) → kanonisches Schema (siehe fheat_core.columns):
    - Wärmebedarf:      RW_WW  (oder RW_WW [kWh/a])  → wird zu  heat_demand
    - Therm. Leistung:  Leistung_th                   → wird zu  thermal_power

Intern arbeitet die Pipeline mit sprachneutralen Spaltennamen; save_outputs()
übersetzt sie beim Export auf deutsche Labels (output_language="de").
"""
from __future__ import annotations

import importlib.util
import logging
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Point

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
# Die Wärmequelle wird erst für die Netzplanung gebraucht (Schritt 4).
adapter = NRWDataAdapter(
    city_name="Burgsteinfurt",               # Stadtteil/Gemarkung (gemeinde = "Steinfurt")
    heat_attribute="RW_WW",                  # NRW-Rohdatenspalte; [kWh/a]-Suffix wird autom. erkannt
)
SOURCE_LATLON = (52.1592, 7.3268)            # (lat, lon) WGS84 — Einspeisepunkt

config = FHeatConfig(
    supply_temperature=80.0,
    return_temperature=50.0,
    wld_threshold=500.0,     # WLD-Schwellenwert [kWh/(a·m)]
    buffer_distance=50.0,    # Puffer für Eignungspolygone [m]
    year=2022,
    civil_cost_share=0.6,    # Anteil der Rohrkosten, der auf den Tiefbau entfällt
    output_dir=str(OUTPUT_DIR),
    output_format="gpkg",
    # Ergebnistabellen als Excel (benötigt pip install -e ".[excel]"), sonst CSV
    table_format="xlsx" if importlib.util.find_spec("openpyxl") else "csv",
    # Lastprofil-Grafiken als PNG (benötigt pip install -e ".[plots]")
    plot_format="png" if importlib.util.find_spec("matplotlib") else None,
)

# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
orch = FHeatOrchestrator(config=config, adapter=adapter)

# ---------------------------------------------------------------------------
# Schritt 1: Download — ganzer Stadtteil (Strassen, Flurstuecke, Gebaeude)
# ---------------------------------------------------------------------------
logging.info("=== Schritt 1: Download ===")
orch.run_step(Phase.INITIAL)

# ---------------------------------------------------------------------------
# Schritt 2: Adjust — Strassen und Gebaeude bereinigen
# ---------------------------------------------------------------------------
logging.info("=== Schritt 2: Adjust ===")
orch.run_step(Phase.DOWNLOADED)

# ---------------------------------------------------------------------------
# Schritt 3: Status — Wärmeliniendichte und Eignungspolygone
# ---------------------------------------------------------------------------
logging.info("=== Schritt 3: WLD & Eignung (Status) ===")
orch.run_step(Phase.ADJUSTED)

logging.info(
    "WLD: %d Straßensegmente analysiert, %d Eignungspolygone",
    len(orch.state.wld_gdf) if orch.state.wld_gdf is not None else 0,
    len(orch.state.polygons_gdf) if orch.state.polygons_gdf is not None else 0,
)
orch.save_outputs(layers=["wld", "eignungspolygone"])

# ---------------------------------------------------------------------------
# Schritt 4: Planungsgebiet und Wärmequelle setzen
#   Nur Gebäude im Planungsgebiet (und mit connect == 1) werden angeschlossen.
#   WLD und Eignungspolygone gelten weiter für den ganzen Stadtteil. Statt
#   planungsgebiet.gpkg kann z. B. auch ein Eignungspolygon verwendet werden:
#     orch.state.planning_area_gdf = orch.state.polygons_gdf.iloc[[0]]
# ---------------------------------------------------------------------------
logging.info("=== Schritt 4: Planungsgebiet und Wärmequelle ===")
crs = orch.state.buildings_gdf.crs
orch.state.planning_area_gdf = gpd.read_file(AREA_PATH).to_crs(crs)
orch.state.source_gdf = gpd.GeoDataFrame(
    geometry=[Point(SOURCE_LATLON[1], SOURCE_LATLON[0])], crs="EPSG:4326"
).to_crs(crs)

# ---------------------------------------------------------------------------
# Schritt 5: Netzberechnung
#   buildings_gdf.connect == 1 und streets_gdf.routable == 1 werden
#   durch den Adapter bereits gesetzt. Für manuelle Selektion können diese
#   Felder vor diesem Schritt überschrieben werden. Die Route zur Quelle nutzt
#   alle Straßen, auch außerhalb des Planungsgebiets.
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
    print(f"    davon Trasse:             {summary['total_route_length_m']:.0f} m")
    print(f"    davon Hausanschlüsse:     {summary['total_house_connection_length_m']:.0f} m")
    print(f"  Netzwärmeverlust:           {summary['total_loss_mwh_a']:.1f} MWh/a")
    print(f"    bei extra Dämmung:        {summary['total_loss_extra_insulation_mwh_a']:.1f} MWh/a")
    print(f"  Vorlauftemperatur:          {summary['supply_temperature_c']} °C")
    print(f"  Rücklauftemperatur:         {summary['return_temperature_c']} °C")
    if "total_pipe_cost_eur" in summary:
        print(f"  Investition Rohrleitungen:  {summary['total_pipe_cost_eur']:,.0f} €")
        print(f"    davon Tiefbau:            {summary['total_civil_cost_eur']:,.0f} €"
              f" (Tiefbauanteil {summary['civil_cost_share']:.0%})")
        print(f"  Mittlerer Tiefbaufaktor:    {summary['mean_civil_cost_factor']:.2f}")

    print("\n--- Rohrmengen je DN ---")
    print(cols.to_display(orch.state.pipe_summary_df).to_string(index=False))
    print("\n--- Gebäude je Lastprofil ---")
    print(cols.to_display(orch.state.building_summary_df).to_string(index=False))

# ---------------------------------------------------------------------------
# Schritt 7: Ausgaben im Planungsgebiet speichern (Netz und Quelle vollständig)
# ---------------------------------------------------------------------------
logging.info("=== Schritt 7: Speichern ===")
saved = orch.save_outputs(clip_to_planning_area=True)
for layer, path in saved.items():
    print(f"  {layer:20s} → {path}")
