"""Golden file test: the Burgsteinfurt example as XWaermeplan, offline.

Runs the real pipeline on ``tests/fixtures/xwp/burgsteinfurt_auszug.gpkg``
(LANUV buildings and streets, ALKIS parcels around the example planning
area): NRW building processing, analysis, Dijkstra network from the example
heat source, then the export. The key figures are compared with
``golden_burgsteinfurt.json`` so a change of the mapping shows up in review.
After an intended change regenerate the file with

    FHEAT_UPDATE_GOLDEN=1 python -m pytest -m xwp tests/test_xwp_golden.py

and check the diff.
"""
from __future__ import annotations

import datetime
import json
import os
from collections import defaultdict
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import Point

pytest.importorskip("xplan_tools")
pytestmark = pytest.mark.xwp

from fheat_core.export.xwp import NetworkResult, XWPExportConfig, export_xwaermeplan  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "xwp"
EXCERPT = FIXTURES / "burgsteinfurt_auszug.gpkg"
GOLDEN = FIXTURES / "golden_burgsteinfurt.json"
XSD = FIXTURES / "xsd-0.9.6"
SOURCE_LONLAT = (7.3268, 52.1592)  # heat source of examples/burgsteinfurt.py


def burgsteinfurt_state(tmp_path):
    from fheat_core.adapters.base import DataAdapter
    from fheat_core.config import FHeatConfig
    from fheat_core.orchestrator import FHeatOrchestrator
    from fheat_core.state import Phase
    from fheat_nrw.adapter.data_adapter import NRWDataAdapter
    from fheat_nrw.processing import process_buildings, process_streets

    raw = gpd.read_file(EXCERPT, layer="gebaeude")
    parcels = gpd.read_file(EXCERPT, layer="flurstuecke")
    streets = gpd.read_file(EXCERPT, layer="strassen").explode(index_parts=False).reset_index(drop=True)
    streets = process_streets(streets)
    functions, age_classes = NRWDataAdapter(city_name="Burgsteinfurt")._load_building_info()
    buildings = process_buildings(raw, parcels, functions, age_classes, "RW_WW")

    class Offline(DataAdapter):
        def fetch_buildings(self):
            return buildings

        def fetch_streets(self):
            return streets

        def fetch_parcels(self):
            return parcels

    orch = FHeatOrchestrator(config=FHeatConfig(output_dir=str(tmp_path), year=2022), adapter=Offline())
    orch.run_until(Phase.STATUS)
    crs = orch.state.buildings_gdf.crs
    orch.state.planning_area_gdf = gpd.read_file(EXCERPT, layer="planungsgebiet").to_crs(crs)
    orch.state.source_gdf = gpd.GeoDataFrame(geometry=[Point(*SOURCE_LONLAT)], crs="EPSG:4326").to_crs(crs)
    orch.run_until(Phase.RESULTS)
    return orch.state


@pytest.fixture(scope="module")
def export(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("burgsteinfurt")
    state = burgsteinfurt_state(tmp)
    config = XWPExportConfig(
        plan_name="Wärmeplan Burgsteinfurt (Test)", municipality_name="Steinfurt",
        municipality_key="05566084", base_year=2022, decision_date=datetime.date(2026, 6, 30),
    )
    report = export_xwaermeplan(state, config, [tmp / "plan.gml", tmp / "plan.json"],
                                networks=[NetworkResult(state, name="Netz Zentrum")], schema_dir=XSD)
    return state, report


def key_figures(report) -> dict:
    """What a change of the mapping should make visible: counts, sums and findings."""
    from xplan_tools.interface import Datasource

    collection = Datasource(str(report.files["gml"])).repo().get_all()
    sums = defaultdict(float)
    for feature in collection.get_features():
        for prop in ("waermeMenge", "laenge"):
            value = getattr(feature, prop, None)
            if value is not None:
                sums[f"{feature.get_name()}.{prop}"] += value.value
    [netz] = [f for f in collection.get_features() if f.get_name() == "WP_Waermenetz"]
    suitability = defaultdict(int)
    for feature in collection.get_features():
        if feature.get_name() == "WP_WaermeversorgungsgebietZieljahr" and feature.eignungWaermenetz is not None:
            suitability[str(feature.eignungWaermenetz)] += 1
    return {
        "counts": dict(sorted(report.counts.items())),
        "sums": {k: round(v, 1) for k, v in sorted(sums.items())},
        "network": {"anzahlGebaeudeAnschluss": netz.anzahlGebaeudeAnschluss, "temperatur": netz.temperatur.value},
        "eignungWaermenetz": dict(sorted(suitability.items())),
        "issues": sorted(f"{i.level}: {i.feature or ''} {i.message}".strip() for i in report.issues),
    }


def test_key_figures_match_the_golden_file(export):
    _, report = export
    figures = json.loads(json.dumps(key_figures(report), ensure_ascii=False))
    if os.environ.get("FHEAT_UPDATE_GOLDEN"):
        GOLDEN.write_text(json.dumps(figures, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    assert figures == json.loads(GOLDEN.read_text(encoding="utf-8"))


def test_example_is_schema_valid(export):
    _, report = export
    assert report.schema_checked
    assert [i for i in report.issues if i.level != "consistency"] == []


def test_example_agrees_with_the_pipeline(export):
    state, report = export
    figures = key_figures(report)
    summary = state.result_summary
    assert figures["sums"]["WP_Waermenetz.laenge"] == round(summary["total_route_length_m"], 1)
    assert figures["network"]["anzahlGebaeudeAnschluss"] == summary["total_buildings"]
    assert figures["sums"]["WP_WaermeversorgungsgebietZieljahr.waermeMenge"] == pytest.approx(
        state.polygons_gdf["heat_demand"].sum() / 1000, abs=0.1)
