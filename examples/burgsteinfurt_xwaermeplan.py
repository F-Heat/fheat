"""Beispiel: Wärmeplan Burgsteinfurt im Standard XWärmeplan 0.9.6.

Ablauf:
    1. Analyse des Stadtteils (download, adjust, status) wie in burgsteinfurt.py
    2. Netzplanung im Planungsgebiet mit Wärmequelle (network, results)
    3. Ergänzungsvorlage schreiben: xwp_ergaenzung.gpkg (QGIS) und .xlsx (Excel)
       → dort trägt der Planer ein, was F|Heat nicht kennt (Maßnahmen, Energiebilanz,
         Energieträger der Wärmequelle, Entscheidung über die Versorgungsgebiete …)
    4. XWärmeplan schreiben: xwaermeplan.gml / .json / .gpkg und den Prüfbericht
       xwaermeplan_pruefbericht.json (gültig?, fehlende Pflichtangaben, Herkunft je Objektart)

Beim ersten Lauf ist die Ergänzung noch leer; der Prüfbericht zeigt dann, was fehlt.
Nach dem Ausfüllen das Skript erneut starten: Schritt 4 liest die Ergänzung ein.

Voraussetzungen:
    - pip install -e ".[nrw,xwp,excel]"  (im Repo-Root)
    - Internetverbindung (NRW WFS / ZIP-Download)

Die Plan-Metadaten unten sind Beispielwerte, keine Angaben der Stadt Steinfurt.
"""
from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Point

from fheat_core.config import FHeatConfig, XwpConfig, XwpExterneReferenz, XwpGemeinde, XwpPlanConfig
from fheat_core.orchestrator import FHeatOrchestrator
from fheat_core.state import Phase
from fheat_nrw.adapter.data_adapter import NRWDataAdapter

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

HERE = Path(__file__).parent
AREA_PATH = HERE / "planungsgebiet.gpkg"
OUTPUT_DIR = HERE / "output_burgsteinfurt_xwaermeplan"
SOURCE_LATLON = (52.1592, 7.3268)  # (lat, lon) WGS84 — Einspeisepunkt

adapter = NRWDataAdapter(city_name="Burgsteinfurt", heat_attribute="RW_WW")

xwp = XwpConfig(
    plan=XwpPlanConfig(
        name="Wärmeplan Burgsteinfurt (Beispiel)",
        gemeinde=XwpGemeinde("Steinfurt", regional_schluessel12="055660032032"),
        aufstellungsbeschluss_datum=datetime.date(2025, 3, 1),
        beschluss_datum=datetime.date(2026, 6, 30),
        zieljahr=2045,
        technische_planerstellung=["FH Münster, F|Heat"],
        externe_referenzen=[XwpExterneReferenz("F|Heat", "https://www.fh-muenster.de/de/iep/fheat/index", art="3200")],
    ),
    privacy_min_buildings=5,   # Baublöcke mit weniger Gebäuden werden zusammengelegt
    energy_raster=True,        # zusätzlich 100-m-Raster (INSPIRE)
    large_consumer_mwh=500.0,  # Gebäude ab 500 MWh/a als Großverbraucher-Platzhalter in der Vorlage
)

config = FHeatConfig(supply_temperature=80.0, return_temperature=50.0, year=2022,
                     output_dir=str(OUTPUT_DIR), xwp=xwp)
orch = FHeatOrchestrator(config=config, adapter=adapter)

logging.info("=== 1. Analyse ===")
orch.run_until(Phase.STATUS)

logging.info("=== 2. Netzplanung ===")
crs = orch.state.buildings_gdf.crs
orch.state.planning_area_gdf = gpd.read_file(AREA_PATH).to_crs(crs)
orch.state.source_gdf = gpd.GeoDataFrame(
    geometry=[Point(SOURCE_LATLON[1], SOURCE_LATLON[0])], crs="EPSG:4326"
).to_crs(crs)
orch.run_until(Phase.RESULTS)

template = OUTPUT_DIR / "xwp_ergaenzung.gpkg"
if not template.exists():
    logging.info("=== 3. Ergänzungsvorlage ===")
    for key, path in orch.save_xwp_template().items():
        logging.info("%s → %s", key, path)
    supplement = None
else:
    logging.info("=== 3. Ergänzung gefunden, wird eingelesen ===")
    supplement = [p for p in (template, OUTPUT_DIR / "xwp_ergaenzung.xlsx") if p.exists()]

logging.info("=== 4. XWärmeplan ===")
files = orch.save_xwp(supplement=supplement)
for key, path in files.items():
    logging.info("%s → %s", key, path)

report = json.loads(files["xwp_report"].read_text(encoding="utf-8"))
logging.info("gültig: %s, %d Befunde", "ja" if report["gueltig"] else "nein", len(report["befunde"]))
for name, cover in report["abdeckung"].items():
    if cover["anzahl"]:
        logging.info("  %-36s %5d  %s", name, cover["anzahl"], cover["herkunft"])
for note in report["hinweise"]:
    logging.info("Hinweis: %s", note)
