"""Beispiel: Ergebnis Burgsteinfurt als XWärmeplan 0.9.6.

Ablauf:
    1. Analyse des Stadtteils (download, adjust, status) wie in burgsteinfurt.py
    2. Netzplanung im Planungsgebiet mit Wärmequelle (network, results)
    3. XWärmeplan schreiben: waermeplan.gml (normativ, gegen die XSD prüfbar) und
       waermeplan.json (JSON-FG, wie xplan-tools es schreibt), dazu der Prüfbericht
       waermeplan_pruefbericht.json

Ohne Beschlussdatum (Entwurf) stattdessen mode="fragment", wenn bekannt mit der
UUID des Wärmeplans der Gemeinde (plan_id=...): Dann entstehen nur Bereich und
Fachobjekte zum Einfügen in deren Plan.

Voraussetzungen:
    - Python 3.13, System-GDAL und pip install -e ".[nrw,xwp]"  (siehe README)
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

from fheat_core.config import FHeatConfig
from fheat_core.export.xwp import NetworkResult, XWPExportConfig, export_xwaermeplan
from fheat_core.orchestrator import FHeatOrchestrator
from fheat_core.state import Phase
from fheat_nrw.adapter.data_adapter import NRWDataAdapter

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

HERE = Path(__file__).parent
AREA_PATH = HERE / "planungsgebiet.gpkg"
OUTPUT_DIR = HERE / "output_burgsteinfurt_xwp"
SOURCE_LATLON = (52.1592, 7.3268)  # (lat, lon) WGS84 — Einspeisepunkt

adapter = NRWDataAdapter(city_name="Burgsteinfurt", heat_attribute="RW_WW")
config = FHeatConfig(supply_temperature=80.0, return_temperature=50.0, year=2022, output_dir=str(OUTPUT_DIR))
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

logging.info("=== 3. XWärmeplan ===")
xwp = XWPExportConfig(
    plan_name="Wärmeplan Burgsteinfurt (Beispiel)",
    municipality_name="Steinfurt",
    municipality_key=adapter.municipality_key,   # 05566084 → Regionalschlüssel 055660084084
    base_year=config.year,
    decision_date=datetime.date(2026, 6, 30),
)
report = export_xwaermeplan(
    orch.state, xwp,
    [OUTPUT_DIR / "waermeplan.gml", OUTPUT_DIR / "waermeplan.json"],
    networks=[NetworkResult(orch.state, name="Netz Zentrum")],
    boundary=adapter.provide_boundary(),
)
(OUTPUT_DIR / "waermeplan_pruefbericht.json").write_text(
    json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
)
for fmt, path in report.files.items():
    logging.info("%s → %s", fmt, path)
for name, count in sorted(report.counts.items()):
    logging.info("  %-36s %5d", name, count)
logging.info("ohne Befund: %s", "ja" if report.ok else f"nein, {len(report.issues)} Befunde")
for issue in report.issues:
    logging.info("  [%s] %s %s", issue.level, issue.feature or "", issue.message)
