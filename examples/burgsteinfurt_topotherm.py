"""Beispiel: Wärmenetzanalyse Burgsteinfurt (NRW) im **Experten-Modus**.

Identisch zu ``burgsteinfurt.py`` — nur die Netztopologie kommt nicht aus dem
kürzesten Weg (Dijkstra), sondern aus der Single-Time-Step-Optimierung von
topotherm. Abweichend ist ausschließlich die Config.

Arbeitsteilung:
    topotherm bestimmt NUR die Topologie — welche Trassenabschnitte gebaut
    werden und (im Modus "economic") welche Gebäude sich rentieren.
    Gleichzeitigkeitsfaktor (GLF), Volumenstrom, DN, Geschwindigkeit und
    Wärmeverluste rechnet F|Heat anschließend mit denselben Funktionen wie in
    Phase 0 — beide Modi bleiben dadurch direkt vergleichbar.

Voraussetzungen (zusätzlich zu burgsteinfurt.py):
    - Python 3.12 — genau diese Version: 3.10/3.11 scheitern am PEP-701-
      f-String von topotherm 0.6.0, ab 3.13.1 greift dessen eigene Schranke
      requires-python "<=3.13".
    - pip install -e ".[nrw,topotherm]" --group topotherm-git
      (topotherm liegt nicht auf PyPI, daher die Dependency-Group)
    - im Modus "economic" können Randlagen abgeworfen werden; das ist das
      erwartete Verhalten, kein Fehler. Wer alle Gebäude anschließen will,
      nutzt optimization_mode="forced".
"""
from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd

from fheat_core import columns as cols
from fheat_core.config import FHeatConfig, NetworkMode, TopothermConfig
from fheat_core.orchestrator import FHeatOrchestrator
from fheat_core.state import Phase
from fheat_nrw.adapter.data_adapter import NRWDataAdapter

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

# ---------------------------------------------------------------------------
# Pfade
# ---------------------------------------------------------------------------
HERE = Path(__file__).parent
AREA_PATH = HERE / "planungsgebiet.gpkg"
OUTPUT_DIR = HERE / "output_burgsteinfurt_topotherm"

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

    # --- Experten-Modus: Netztopologie via topotherm STS ---------------
    network_mode=NetworkMode.EXPERT.value,
    topotherm=TopothermConfig(
        optimization_mode="economic",  # "economic" (Default) | "forced"
        solver="highs",                # pip install highspy
        heat_price=150e-3,             # €/kWh Erlös
        source_price=50e-3,            # €/kWh variable Erzeugungskosten
        pipes_lifetime=40.0,           # Jahre
        ambient_temperature=-12.0,     # °C Auslegungsaußentemperatur
    ),
)

# ---------------------------------------------------------------------------
# Orchestrator — ab hier identisch zu burgsteinfurt.py.
# Der Orchestrator merkt vom Moduswechsel nichts; die NETWORK-Phase wählt das
# Backend selbst anhand von config.network_mode.
# ---------------------------------------------------------------------------
orch = FHeatOrchestrator(config=config, adapter=adapter)

# ---------------------------------------------------------------------------
# Schritt 1: Download — Strassen, Flurstuecke, Gebaeude
# ---------------------------------------------------------------------------
logging.info("=== Schritt 1: Download ===")
orch.run_step(Phase.INITIAL)

# ---------------------------------------------------------------------------
# Schritt 2: Planungsgebiet-Clip
# ---------------------------------------------------------------------------
logging.info("=== Schritt 2: Planungsgebiet-Clip ===")

area = gpd.read_file(AREA_PATH).to_crs(orch.state.buildings_gdf.crs)
area_geom = area.geometry.union_all()

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

# ---------------------------------------------------------------------------
# Schritt 5: Netzberechnung — hier läuft die topotherm-Optimierung
#   Hinweis: Ein MILP skaliert anders als Dijkstra. Läuft der Solver zu lange,
#   ist TopothermConfig.time_limit (Default 10 000 s) die Stellschraube.
# ---------------------------------------------------------------------------
logging.info("=== Schritt 5: Netzberechnung (topotherm) ===")
orch.run_step(Phase.STATUS)

n_connected = int(orch.state.buildings_gdf[cols.CONNECT].sum())
logging.info(
    "Netz: %d Kanten, %d angeschlossene Gebäude",
    len(orch.state.net_gdf),
    n_connected,
)

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
    print("\n--- Ergebniszusammenfassung (Experten-Modus) ---")
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
