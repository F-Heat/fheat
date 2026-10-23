"""export_xwaermeplan on the stub pipeline: build, write, check, read back."""
from __future__ import annotations

import dataclasses
import datetime
from pathlib import Path

import pytest
from shapely.geometry import box

pytest.importorskip("xplan_tools")
pytestmark = pytest.mark.xwp

from fheat_core import columns as cols  # noqa: E402
from fheat_core.config import FHeatConfig  # noqa: E402
from fheat_core.export.xwp import NetworkResult, XWPExportConfig, export_xwaermeplan  # noqa: E402
from fheat_core.orchestrator import FHeatOrchestrator  # noqa: E402

XSD = Path(__file__).resolve().parent / "fixtures" / "xwp" / "xsd-0.9.6"
PLAN_ID = "6a2f41a3-c54c-4ce8-92d2-0324e1c32e22"
# the stub street runs beyond the parcels; the plan area covers it
AREA = box(-50, -50, 250, 100)
PRIVACY_NOTE = ("building blocks are single buildings: whether to publish them at this resolution is the "
                "municipality's decision (data protection)")


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
    report = export_xwaermeplan(state, config, tmp_path / "plan.gml", schema_dir=XSD, boundary=AREA)
    assert report.ok, report.issues
    assert report.schema_checked
    assert report.file == tmp_path / "plan.gml" and report.file.is_file()
    assert report.counts == {
        "WP_Plan": 1, "WP_Bereich": 1, "WP_Waermelinie": 1, "WP_Waermenetz": 1,
        "WP_WaermeversorgungsgebietZieljahr": len(state.polygons_gdf),
        "WP_GebaeudeBaublock": 3,  # one per heated building
    }
    assert report.notes == ["plan boundary: the boundary passed to the export", PRIVACY_NOTE]


def test_round_trip_keeps_ids_and_values(state, config, tmp_path):
    report = export_xwaermeplan(state, config, tmp_path / "plan.gml", boundary=AREA)
    gml = read(report.file)
    assert len(gml.features) == sum(report.counts.values())
    [netz] = [f for f in gml.get_features() if f.get_name() == "WP_Waermenetz"]
    assert netz.laenge.value == pytest.approx(state.result_summary["total_route_length_m"])
    assert netz.laenge.uom == "m"
    assert netz.anzahlGebaeudeAnschluss == state.result_summary["total_buildings"]
    assert netz.status == "3000"
    [plan] = [f for f in gml.get_features() if f.get_name() == "WP_Plan"]
    assert plan.planungsverantwortlicheStelle.regionalSchluessel12 == "055660084084"
    assert plan.beschlussDatum == datetime.date(2026, 6, 30)
    [bereich] = [f for f in gml.get_features() if f.get_name() == "WP_Bereich"]
    assert bereich.gehoertZuPlan == plan.id and plan.bereich == [bereich.id]
    assert all(f.gehoertZuBereich == bereich.id for f in gml.get_features() if hasattr(f, "gehoertZuBereich"))


def test_ids_are_stable_across_runs(state, config, tmp_path):
    first = export_xwaermeplan(state, config, tmp_path / "a.gml", boundary=AREA)
    second = export_xwaermeplan(state, config, tmp_path / "b.gml", boundary=AREA)
    assert set(read(first.file).features) == set(read(second.file).features)


def test_ids_depend_on_the_municipality(state, config, tmp_path):
    other = dataclasses.replace(config, municipality_key="05515000", municipality_name="Münster")
    a = read(export_xwaermeplan(state, config, tmp_path / "a.gml", boundary=AREA).file)
    b = read(export_xwaermeplan(state, other, tmp_path / "b.gml", boundary=AREA).file)
    assert not set(a.features) & set(b.features)


def test_schema_location_names_the_written_version(state, config, tmp_path):
    report = export_xwaermeplan(state, config, tmp_path / "plan.gml", boundary=AREA)
    assert "/xsd/0.9.6/waermeplan.xsd" in report.file.read_text(encoding="utf-8")


def test_fragment_refers_to_the_municipality_plan(state, tmp_path):
    config = XWPExportConfig(mode="fragment", plan_id=PLAN_ID, municipality_key="05566084")
    report = export_xwaermeplan(state, config, tmp_path / "fragment.gml", schema_dir=XSD, boundary=AREA)
    assert report.ok, report.issues
    assert "WP_Plan" not in report.counts
    text = report.file.read_text(encoding="utf-8")
    assert f'gehoertZuPlan xlink:href="#GML_{PLAN_ID}"' in text
    assert report.notes == ["plan boundary: the boundary passed to the export", PRIVACY_NOTE,
                            "WP_Bereich.nummer 0 has to be unique within the municipality's plan"]


def test_fragment_without_plan_id_refers_to_a_derived_id(state, tmp_path):
    from fheat_core.export.xwp.builder import plan_id

    config = XWPExportConfig(mode="fragment", municipality_key="05566084")
    report = export_xwaermeplan(state, config, tmp_path / "fragment.gml", schema_dir=XSD, boundary=AREA)
    assert report.ok, report.issues
    derived = plan_id(config)
    assert derived == plan_id(XWPExportConfig(mode="fragment", regional_key="055660084084"))  # one per municipality
    assert f'gehoertZuPlan xlink:href="#GML_{derived}"' in report.file.read_text(encoding="utf-8")
    assert any(str(derived) in note and "replace it" in note for note in report.notes)


def test_fragment_round_trip(state, tmp_path):
    """xplan-tools rejects a fragment as a collection (open mandatory reference), so every feature is read alone."""
    from fheat_core.export.xwp.writer import read_features

    config = XWPExportConfig(mode="fragment", plan_id=PLAN_ID, municipality_key="05566084")
    report = export_xwaermeplan(state, config, tmp_path / "fragment.gml", boundary=AREA)
    features = read_features(report.file)
    assert sorted(f.get_name() for f in features.values()) == sorted(
        name for name, n in report.counts.items() for _ in range(n))
    [bereich] = [f for f in features.values() if f.get_name() == "WP_Bereich"]
    assert str(bereich.gehoertZuPlan) == PLAN_ID
    assert all(f.gehoertZuBereich == bereich.id for f in features.values() if hasattr(f, "gehoertZuBereich"))
    [netz] = [f for f in features.values() if f.get_name() == "WP_Waermenetz"]
    assert netz.laenge.value == pytest.approx(state.result_summary["total_route_length_m"])


def test_reference_errors_in_a_fragment_are_found(state):
    import uuid

    from fheat_core.export.xwp.builder import build_collection
    from fheat_core.export.xwp.mappers import map_plan, map_waermenetze

    config = XWPExportConfig(mode="fragment", municipality_key="05566084")
    [netz] = map_waermenetze([NetworkResult(state)], config, state.wld_gdf.crs)
    netz["properties"]["refMassnahme"] = uuid.uuid4()  # a measure that is not in the file
    collection, issues = build_collection([*map_plan(config, AREA), netz], config, state.wld_gdf.crs.to_epsg())
    assert collection is None
    assert [i.level for i in issues] == ["structure"] and "refMassnahme" in issues[0].message


def test_energy_carrier_and_interim_year(state, config, tmp_path):
    config = dataclasses.replace(config, source_energy_carrier="72002", supply_year="2030")
    report = export_xwaermeplan(state, config, tmp_path / "plan.gml", schema_dir=XSD, boundary=AREA)
    assert report.ok, report.issues
    collection = read(report.file)
    [netz] = [f for f in collection.get_features() if f.get_name() == "WP_Waermenetz"]
    summary = state.result_summary
    assert netz.eeNachEnergietraeger.energietraeger == "72002"
    assert netz.eeNachEnergietraeger.endenergie.value == pytest.approx(
        summary["total_heat_demand_mwh_a"] + summary["total_loss_mwh_a"])
    areas = [f for f in collection.get_features() if f.get_name() == "WP_WaermeversorgungsgebietStuetzjahr"]
    assert areas and all(a.stuetzjahr == "1000" for a in areas)


def test_several_networks(state, config, tmp_path):
    nets = [NetworkResult(state, name="Netz A"), NetworkResult(state, name="Netz B")]
    report = export_xwaermeplan(state, config, tmp_path / "plan.gml", networks=nets, boundary=AREA)
    assert report.ok, report.issues
    collection = read(report.file)
    names = sorted((f.name, f.status) for f in collection.get_features() if f.get_name() == "WP_Waermenetz")
    assert names == [("Netz A", "3000"), ("Netz B", "3000")]
    assert {f.versorgungsart for f in collection.get_features() if hasattr(f, "versorgungsart")} == {"40001"}


def test_analysis_only_has_no_network(state, config, tmp_path):
    report = export_xwaermeplan(state, config, tmp_path / "plan.gml", networks=[], boundary=AREA)
    assert report.ok, report.issues
    assert "WP_Waermenetz" not in report.counts


def test_features_outside_the_boundary_are_left_out(state, config, tmp_path):
    # a plan boundary beside the analysis: the supply area and the network lie outside it
    report = export_xwaermeplan(state, config, tmp_path / "plan.gml", boundary=box(170, -50, 250, 100))
    assert report.ok, report.issues
    assert "WP_Waermenetz" not in report.counts and "WP_WaermeversorgungsgebietZieljahr" not in report.counts
    assert ("outside the plan boundary, left out: 1 WP_Waermenetz, 1 WP_WaermeversorgungsgebietZieljahr"
            in report.notes)
    assert "WP_GebaeudeBaublock" not in report.counts
    assert "heated buildings outside the plan boundary, in no building block: 3" in report.notes


def no_file_in(directory: Path) -> bool:
    """No export file in ``directory``, not even a partial one (the state fixture writes into ``out/``)."""
    return not any(p.suffix == ".gml" for p in directory.iterdir())


def test_structure_findings_stop_the_export(state, config, tmp_path):
    config.procedure = "9999"  # past the config check: a code the schema does not know
    report = export_xwaermeplan(state, config, tmp_path / "plan.gml", boundary=AREA)
    assert report.file is None and no_file_in(tmp_path)
    assert [(i.level, i.feature.split()[0]) for i in report.issues] == [("structure", "WP_Plan")]
    assert "verfahrensart" in report.issues[0].message


def test_consistency_findings_stop_the_export(state, config, tmp_path, monkeypatch):
    from fheat_core.export.xwp import export as export_module

    def wrong_heat(wld_gdf, boundary=None):  # a mapper that loses the unit conversion
        records = map_waermelinien(wld_gdf, boundary)
        for r in records:
            r["properties"]["waermeMenge"]["value"] *= 1000
        return records

    from fheat_core.export.xwp.mappers import map_waermelinien
    monkeypatch.setattr(export_module, "map_waermelinien", wrong_heat)
    report = export_xwaermeplan(state, config, tmp_path / "plan.gml", boundary=AREA)
    assert report.file is None and no_file_in(tmp_path)
    assert [i.level for i in report.issues] == ["consistency"] and "heat lines" in report.issues[0].message


def test_building_block_findings_stop_the_export(state, config, tmp_path, monkeypatch):
    from fheat_core.export.xwp import export as export_module
    from fheat_core.export.xwp.mappers import map_baubloecke

    # a mapper that loses the last block
    monkeypatch.setattr(export_module, "map_baubloecke", lambda *args: map_baubloecke(*args)[:-1])
    report = export_xwaermeplan(state, config, tmp_path / "plan.gml", boundary=AREA)
    assert report.file is None and no_file_in(tmp_path)
    assert [i.level for i in report.issues] == ["consistency"]
    assert report.issues[0].message == ("1 heated buildings inside the plan boundary do not lie in exactly one "
                                        "WP_GebaeudeBaublock")


def test_floor_area_findings_stop_the_export(state, config, tmp_path, monkeypatch):
    from fheat_core.export.xwp import export as export_module
    from fheat_core.export.xwp.mappers import map_baubloecke

    state.buildings_gdf[cols.FLOOR_AREA] = 120.0
    assert export_xwaermeplan(state, config, tmp_path / "plan.gml", boundary=AREA).ok

    def wrong_area(*args):  # a mapper that loses the unit conversion
        records = map_baubloecke(*args)
        for r in records:
            r["properties"]["nutzflaeche"]["value"] *= 10_000
        return records

    monkeypatch.setattr(export_module, "map_baubloecke", wrong_area)
    report = export_xwaermeplan(state, config, tmp_path / "other.gml", boundary=AREA)
    assert report.file is None and not (tmp_path / "other.gml").exists()
    assert [i.level for i in report.issues] == ["consistency"]
    assert report.issues[0].message.startswith("nutzflaeche of the building blocks 360.000000 ha != floor area")


@pytest.mark.parametrize("change, missing", [
    ({"supply_type": "1000"}, "eignungDezentraleVersorgung, eignungWaermenetz, eignungWasserstoffnetz"),
    ({"supply_type": "1000", "suitability_thresholds": (415, 175, 70)}, "eignungDezentraleVersorgung"),
    ({"network_status": "1000"}, "temperatur"),
])
def test_conformity_findings_stop_the_export(state, config, tmp_path, change, missing):
    state.result_summary = {k: v for k, v in state.result_summary.items() if k != "supply_temperature_c"}
    report = export_xwaermeplan(state, dataclasses.replace(config, **change), tmp_path / "plan.gml", boundary=AREA)
    assert report.file is None and no_file_in(tmp_path)
    assert {i.level for i in report.issues} == {"conformity"}
    assert report.issues[0].message.startswith(missing)


def test_conformity_allows_the_small_heat_planning_without_suitability(state, config, tmp_path):
    config = dataclasses.replace(config, supply_type="1000", procedure="2000")
    report = export_xwaermeplan(state, config, tmp_path / "plan.gml", boundary=AREA)
    assert report.ok, report.issues


def test_schema_findings_stop_the_export(state, config, tmp_path, monkeypatch):
    from fheat_core.export.xwp import writer

    monkeypatch.setattr(writer, "validate_gml", lambda path, schema_dir: ["line 1: not valid"])
    report = export_xwaermeplan(state, config, tmp_path / "plan.gml", schema_dir=XSD, boundary=AREA)
    assert report.file is None and no_file_in(tmp_path)
    assert [i.level for i in report.issues] == ["schema"]


def test_without_schema_dir_the_notes_say_so(state, config, tmp_path):
    report = export_xwaermeplan(state, config, tmp_path / "plan.gml", boundary=AREA)
    assert report.ok and not report.schema_checked
    assert report.notes[-1] == "GML not checked against the XSD (no schema_dir given)"


def test_features_are_cut_to_the_parcels_by_default(state, config, tmp_path):
    from shapely import wkt

    report = export_xwaermeplan(state, config, tmp_path / "plan.gml")
    assert report.ok, report.issues
    parcels = state.parcels_gdf.union_all().buffer(0.01)
    features = list(read(report.file).get_features())
    areas = [wkt.loads(f.position.wkt) for f in features
             if f.get_name() in ("WP_Waermenetz", "WP_WaermeversorgungsgebietZieljahr")]
    assert areas and all(parcels.covers(a) for a in areas)
    # the stub street runs beyond the parcels: cut, its heat demand outside is named in the notes
    [line] = [f for f in features if f.get_name() == "WP_Waermelinie"]
    assert parcels.covers(wkt.loads(line.position.wkt))
    assert line.laenge.value == pytest.approx(90.0)
    assert line.waermeMenge.value == pytest.approx(line.waermelinienDichte.value * 90.0)
    assert report.notes[0] == "plan boundary: the union of the parcels (no boundary passed)"
    assert report.notes[1].startswith("heat lines cut at the plan boundary: 1;")


def test_schema_check_finds_invalid_gml(state, config, tmp_path):
    from fheat_core.export.xwp.writer import validate_gml

    path = export_xwaermeplan(state, config, tmp_path / "plan.gml", boundary=AREA).file
    assert validate_gml(path, XSD) == []
    path.write_text(path.read_text(encoding="utf-8").replace("<verfahrensart>1000<", "<verfahrensart>1234<"),
                    encoding="utf-8")
    findings = validate_gml(path, XSD)
    assert findings and "verfahrensart" in findings[0]


def test_schema_dir_may_be_relative(state, config, tmp_path, monkeypatch):
    monkeypatch.chdir(XSD.parent)
    report = export_xwaermeplan(state, config, tmp_path / "plan.gml", schema_dir=XSD.name, boundary=AREA)
    assert report.ok and report.schema_checked, report.issues


def test_geographic_crs_is_rejected(state, config, tmp_path):
    geographic = dataclasses.replace(state, wld_gdf=state.wld_gdf.to_crs("EPSG:4326"))
    with pytest.raises(ValueError, match="projected CRS"):
        export_xwaermeplan(geographic, config, tmp_path / "plan.gml", boundary=AREA)


@pytest.mark.parametrize("name", ["plan.json", "plan.gpkg"])
def test_only_gml_is_written(state, config, tmp_path, name):
    with pytest.raises(ValueError, match="GML only"):
        export_xwaermeplan(state, config, tmp_path / name, boundary=AREA)
