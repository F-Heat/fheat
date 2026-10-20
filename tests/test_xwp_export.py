"""export_xwaermeplan on the stub pipeline: build, write, check, read back."""
from __future__ import annotations

import dataclasses
import datetime
import json
from pathlib import Path

import pytest
from shapely.geometry import box

pytest.importorskip("xplan_tools")
pytestmark = pytest.mark.xwp

from fheat_core.config import FHeatConfig  # noqa: E402
from fheat_core.export.xwp import NetworkResult, SupplyDecision, XWPExportConfig, export_xwaermeplan  # noqa: E402
from fheat_core.orchestrator import FHeatOrchestrator  # noqa: E402

XSD = Path(__file__).resolve().parent / "fixtures" / "xwp" / "xsd-0.9.6"
PLAN_ID = "6a2f41a3-c54c-4ce8-92d2-0324e1c32e22"
# the stub street runs beyond the parcels; the plan area covers it
AREA = box(-50, -50, 250, 100)


@pytest.fixture
def state(stub_adapter, tmp_path):
    """The stub pipeline until RESULTS, with a WLD threshold low enough for suitability polygons."""
    orch = FHeatOrchestrator(config=FHeatConfig(output_dir=str(tmp_path / "out"), wld_threshold=100.0),
                             adapter=stub_adapter)
    orch.run_all()
    assert not orch.state.polygons_gdf.empty
    return orch.state


@pytest.fixture
def config():
    return XWPExportConfig(
        plan_name="Wärmeplan Test", municipality_name="Steinfurt", municipality_key="05566084",
        base_year=2022, decision_date=datetime.date(2026, 6, 30),
    )


def read(path):
    from xplan_tools.interface import Datasource

    return Datasource(str(path)).repo().get_all()


def test_plan_is_written_and_schema_valid(state, config, tmp_path):
    report = export_xwaermeplan(state, config, [tmp_path / "plan.gml", tmp_path / "plan.json"],
                                schema_dir=XSD, boundary=AREA)
    assert report.ok, report.issues
    assert report.schema_checked
    assert set(report.files) == {"gml", "jsonfg"} and all(p.is_file() for p in report.files.values())
    assert report.counts == {
        "WP_Plan": 1, "WP_Bereich": 1, "WP_Waermelinie": 1, "WP_Waermenetz": 1,
        "WP_WaermeversorgungsgebietZieljahr": len(state.polygons_gdf),
    }


def test_round_trip_keeps_ids_and_values(state, config, tmp_path):
    report = export_xwaermeplan(state, config, [tmp_path / "plan.gml", tmp_path / "plan.json"], boundary=AREA)
    gml, jsonfg = read(report.files["gml"]), read(report.files["jsonfg"])
    assert set(gml.features) == set(jsonfg.features)
    [netz] = [f for f in gml.get_features() if f.get_name() == "WP_Waermenetz"]
    assert netz.laenge.value == pytest.approx(state.result_summary["total_route_length_m"])
    assert netz.laenge.uom == "m"
    assert netz.anzahlGebaeudeAnschluss == state.result_summary["total_buildings"]
    assert netz.status == "3000"
    [plan] = [f for f in gml.get_features() if f.get_name() == "WP_Plan"]
    assert plan.planungsverantwortlicheStelle.regionalSchluessel12 == "055660084084"
    assert plan.beschlussDatum == datetime.date(2026, 6, 30)
    [bereich] = [f for f in jsonfg.get_features() if f.get_name() == "WP_Bereich"]
    assert bereich.gehoertZuPlan == plan.id and plan.bereich == [bereich.id]
    assert all(f.gehoertZuBereich == bereich.id for f in gml.get_features() if hasattr(f, "gehoertZuBereich"))


def test_ids_are_stable_across_runs(state, config, tmp_path):
    first = export_xwaermeplan(state, config, tmp_path / "a.gml", boundary=AREA)
    second = export_xwaermeplan(state, config, tmp_path / "b.gml", boundary=AREA)
    assert set(read(first.files["gml"]).features) == set(read(second.files["gml"]).features)


def test_ids_depend_on_the_municipality(state, config, tmp_path):
    other = dataclasses.replace(config, municipality_key="05515000", municipality_name="Münster")
    a = read(export_xwaermeplan(state, config, tmp_path / "a.gml", boundary=AREA).files["gml"])
    b = read(export_xwaermeplan(state, other, tmp_path / "b.gml", boundary=AREA).files["gml"])
    assert not set(a.features) & set(b.features)


def test_schema_links_name_the_written_version(state, config, tmp_path):
    report = export_xwaermeplan(state, config, [tmp_path / "plan.gml", tmp_path / "plan.json"], boundary=AREA)
    assert "/xsd/0.9.6/waermeplan.xsd" in report.files["gml"].read_text(encoding="utf-8")
    links = json.loads(report.files["jsonfg"].read_text(encoding="utf-8"))["links"]
    assert [link["href"] for link in links if link["rel"] == "describedby"] == [
        "https://gitlab.opencode.de/xleitstelle/xwaermeplan/spezifikation/-/raw/main/json/0.9.6/featurecollection.json"
    ]


def test_fragment_refers_to_the_municipality_plan(state, tmp_path):
    config = XWPExportConfig(mode="fragment", plan_id=PLAN_ID, municipality_key="05566084")
    report = export_xwaermeplan(state, config, tmp_path / "fragment.gml", schema_dir=XSD, boundary=AREA)
    assert report.ok, report.issues
    assert "WP_Plan" not in report.counts
    text = report.files["gml"].read_text(encoding="utf-8")
    assert f'gehoertZuPlan xlink:href="#GML_{PLAN_ID}"' in text


def test_energy_carrier_and_interim_year(state, config, tmp_path):
    config = dataclasses.replace(config, source_energy_carrier="72002", supply_year="2030")
    report = export_xwaermeplan(state, config, tmp_path / "plan.gml", schema_dir=XSD, boundary=AREA)
    assert report.ok, report.issues
    collection = read(report.files["gml"])
    [netz] = [f for f in collection.get_features() if f.get_name() == "WP_Waermenetz"]
    summary = state.result_summary
    assert netz.eeNachEnergietraeger.energietraeger == "72002"
    assert netz.eeNachEnergietraeger.endenergie.value == pytest.approx(
        summary["total_heat_demand_mwh_a"] + summary["total_loss_mwh_a"])
    areas = [f for f in collection.get_features() if f.get_name() == "WP_WaermeversorgungsgebietStuetzjahr"]
    assert areas and all(a.stuetzjahr == "1000" for a in areas)


def test_planner_decision_and_several_networks(state, config, tmp_path):
    decisions = [SupplyDecision(box(-1000, -1000, 1000, 1000), supply_type="1000")]
    nets = [NetworkResult(state, name="Netz A"), NetworkResult(state, name="Netz B", status="2000")]
    report = export_xwaermeplan(state, config, tmp_path / "plan.gml", networks=nets, supply_decisions=decisions,
                                boundary=AREA)
    assert report.ok, report.issues
    collection = read(report.files["gml"])
    names = sorted((f.name, f.status) for f in collection.get_features() if f.get_name() == "WP_Waermenetz")
    assert names == [("Netz A", "3000"), ("Netz B", "2000")]
    assert {f.versorgungsart for f in collection.get_features() if hasattr(f, "versorgungsart")} == {"1000"}


def test_analysis_only_has_no_network(state, config, tmp_path):
    report = export_xwaermeplan(state, config, tmp_path / "plan.gml", networks=[], boundary=AREA)
    assert report.ok, report.issues
    assert "WP_Waermenetz" not in report.counts


def test_consistency_findings_are_reported(state, config, tmp_path):
    report = export_xwaermeplan(state, config, tmp_path / "plan.gml", boundary=box(-5, -5, 20, 15))
    assert report.files and not report.ok
    assert {i.level for i in report.issues} == {"consistency"}
    assert any("beyond the plan boundary" in i.message for i in report.issues)


def test_structure_findings_stop_the_export(state, config, tmp_path):
    config.procedure = "9999"  # past the config check: a code the schema does not know
    report = export_xwaermeplan(state, config, tmp_path / "plan.gml", boundary=AREA)
    assert not report.files and not (tmp_path / "plan.gml").exists()
    assert [(i.level, i.feature.split()[0]) for i in report.issues] == [("structure", "WP_Plan")]
    assert "verfahrensart" in report.issues[0].message


def test_areas_are_cut_to_the_parcels_by_default(state, config, tmp_path):
    from shapely import wkt

    report = export_xwaermeplan(state, config, tmp_path / "plan.gml")
    parcels = state.parcels_gdf.union_all().buffer(0.01)
    areas = [wkt.loads(f.position.wkt) for f in read(report.files["gml"]).get_features()
             if f.get_name() in ("WP_Waermenetz", "WP_WaermeversorgungsgebietZieljahr")]
    assert areas and all(parcels.covers(a) for a in areas)
    # the stub street runs beyond the parcels: reported, not cut
    assert [i.feature.split()[0] for i in report.issues] == ["WP_Waermelinie"]


def test_schema_check_finds_invalid_gml(state, config, tmp_path):
    from fheat_core.export.xwp.writer import validate_gml

    path = export_xwaermeplan(state, config, tmp_path / "plan.gml", boundary=AREA).files["gml"]
    assert validate_gml(path, XSD) == []
    path.write_text(path.read_text(encoding="utf-8").replace("<verfahrensart>1000<", "<verfahrensart>1234<"),
                    encoding="utf-8")
    findings = validate_gml(path, XSD)
    assert findings and "verfahrensart" in findings[0]


def test_geographic_crs_is_rejected(state, config, tmp_path):
    geographic = dataclasses.replace(state, wld_gdf=state.wld_gdf.to_crs("EPSG:4326"))
    with pytest.raises(ValueError, match="projected CRS"):
        export_xwaermeplan(geographic, config, tmp_path / "plan.gml", boundary=AREA)


def test_unknown_suffix_is_rejected(state, config, tmp_path):
    with pytest.raises(ValueError, match="suffix"):
        export_xwaermeplan(state, config, tmp_path / "plan.gpkg", boundary=AREA)
