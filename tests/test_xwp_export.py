"""XWaermeplan export through the orchestrator and the command line (phase 9)."""
from __future__ import annotations

import datetime
import json

import geopandas as gpd
import pytest
from shapely.geometry import LineString, box

from fheat_core import columns as cols
from fheat_core.adapters.base import DataAdapter
from fheat_core.config import FHeatConfig, XwpConfig, XwpGemeinde, XwpPlanConfig
from fheat_core.errors import PipelineInputError
from fheat_core.orchestrator import FHeatOrchestrator
from fheat_core.state import Phase, PipelineState
from tests.xwp_synth import X0, Y0, small_town

pytest.importorskip("lxml")
pytest.importorskip("pyogrio")
CRS = "EPSG:25832"


class TownAdapter(DataAdapter):
    def __init__(self, boundary):
        self.boundary = boundary

    def fetch_buildings(self):
        raise NotImplementedError

    def fetch_streets(self):
        raise NotImplementedError

    def fetch_parcels(self):
        raise NotImplementedError

    def provide_boundary(self):
        return gpd.GeoDataFrame(geometry=[self.boundary], crs=CRS)


def _xwp(beschluss=datetime.date(2026, 6, 30), **kw):
    plan = XwpPlanConfig(name="Wärmeplan Test", gemeinde=XwpGemeinde("Teststadt", "051234567890"),
                         beschluss_datum=beschluss)
    return XwpConfig(plan=plan, privacy_min_buildings=1, **kw)


def _network_state(buildings):
    net = gpd.GeoDataFrame({cols.TYPE: ["Trasse"], cols.LENGTH: [60.0]},
                           geometry=[LineString([(X0 + 10, Y0 + 40), (X0 + 70, Y0 + 40)])], crs=CRS)
    area = gpd.GeoDataFrame(geometry=[box(X0, Y0, X0 + 100, Y0 + 100)], crs=CRS)
    return PipelineState(buildings_gdf=buildings, net_gdf=net, planning_area_gdf=area)


@pytest.fixture
def orch(tmp_path):
    buildings, wld, streets, boundary = small_town()
    state = PipelineState(phase=Phase.STATUS, buildings_gdf=buildings, wld_gdf=wld, streets_gdf=streets)
    config = FHeatConfig(output_dir=str(tmp_path / "out"), year=2024, xwp=_xwp())
    return FHeatOrchestrator(config=config, adapter=TownAdapter(boundary), state=state)


def test_save_xwp_writes_all_formats_and_a_report(orch):
    from fheat_core.xwp.encode.gml import validate_gml

    files = orch.save_xwp(networks=[_network_state(orch.state.buildings_gdf)])
    assert set(files) == {"xwp_gml", "xwp_jsonfg", "xwp_gpkg", "xwp_report"}
    assert files["xwp_gml"].name == "xwaermeplan.gml" and validate_gml(files["xwp_gml"]) == []
    report = json.loads(files["xwp_report"].read_text(encoding="utf-8"))
    assert report["gueltig"] is True and report["befunde"] == []
    assert report["xwaermeplan_version"] == "0.9.6"
    cover = report["abdeckung"]
    assert cover["WP_Waermenetz"] == {"anzahl": 1, "herkunft": "automatisch", "fehlende_pflichtangaben": {}}
    assert cover["WP_WaermeversorgungsgebietZieljahr"]["herkunft"] == "Vorschlag"
    assert cover["WP_Massnahme"]["herkunft"] == "leer"
    assert len(cover) == 29


def test_report_lists_missing_mandatory_attributes(orch):
    orch.config.xwp = _xwp(beschluss=None, formats=("gml",))
    files = orch.save_xwp()
    assert set(files) == {"xwp_gml", "xwp_report"}
    report = json.loads(files["xwp_report"].read_text(encoding="utf-8"))
    assert report["gueltig"] is False
    assert report["abdeckung"]["WP_Plan"]["fehlende_pflichtangaben"] == {"beschlussDatum": 1}
    assert report["schema"]["xsd"]  # the XSD misses it as well


def test_default_network_is_the_state_itself(orch):
    orch.state.net_gdf = _network_state(orch.state.buildings_gdf).net_gdf
    report = json.loads(orch.save_xwp()["xwp_report"].read_text(encoding="utf-8"))
    assert report["abdeckung"]["WP_Waermenetz"]["anzahl"] == 1


def test_save_xwp_needs_config_and_analysis(orch, tmp_path):
    orch.config.xwp = None
    with pytest.raises(ValueError, match="FHeatConfig.xwp"):
        orch.save_xwp()
    orch.config.xwp = _xwp()
    orch.state.wld_gdf = None
    with pytest.raises(PipelineInputError, match="STATUS"):
        orch.save_xwp()


def test_template_and_supplement_round(orch):
    import pyogrio

    networks = [_network_state(orch.state.buildings_gdf)]
    paths = orch.save_xwp_template(networks=networks)
    assert paths["xwp_template_gpkg"].name == "xwp_ergaenzung.gpkg"
    assert len(pyogrio.list_layers(paths["xwp_template_gpkg"])) == 92
    files = orch.save_xwp(networks=networks, supplement=[paths["xwp_template_gpkg"]] + (
        [paths["xwp_template_xlsx"]] if "xwp_template_xlsx" in paths else []))
    report = json.loads(files["xwp_report"].read_text(encoding="utf-8"))
    assert report["gueltig"] is True
    assert report["ergaenzung"]["ueberschrieben"] == 0 and report["ergaenzung"]["befunde"] == []


# --------------------------------------------------------------------------
# configuration from JSON


def test_xwp_config_from_dict():
    config = XwpConfig.from_dict({
        "plan": {"name": "P", "gemeinde": {"name": "G", "regional_schluessel12": "051234567890"},
                 "beschluss_datum": "2026-06-30", "beteiligte_gemeinden": [{"name": "H"}],
                 "externe_referenzen": [{"name": "Plan", "url": "https://example.org", "art": "1000"}]},
        "formats": ["gml", "gpkg"], "suitability": {"heat_density": [400, 170, 60]},
    })
    assert config.plan.beschluss_datum == datetime.date(2026, 6, 30)
    assert config.plan.beteiligte_gemeinden[0].name == "H" and config.formats == ("gml", "gpkg")
    assert config.suitability.heat_density == (400, 170, 60)
    with pytest.raises(ValueError, match="unknown keys"):
        XwpConfig.from_dict({"plan": {"name": "P", "gemeinde": {"name": "G"}}, "format": ["gml"]})


def test_from_display_inverts_to_display():
    buildings = small_town()[0]
    shown = cols.to_display(buildings)
    assert "Waermebedarf [kWh/a]" in shown.columns
    assert list(cols.from_display(shown).columns) == list(buildings.columns)


# --------------------------------------------------------------------------
# command line


def test_cli_build_and_validate(tmp_path, capsys):
    from fheat_core.xwp.__main__ import main

    buildings, wld, streets, boundary = small_town()
    paths = {}
    for name, frame in (("buildings", buildings), ("wld", wld), ("streets", streets)):
        paths[name] = tmp_path / f"{name}.gpkg"
        cols.to_display(frame).to_file(paths[name], driver="GPKG")  # as save_outputs writes them
    gpd.GeoDataFrame(geometry=[boundary], crs=CRS).to_file(tmp_path / "gebiet.gpkg", driver="GPKG")
    (tmp_path / "plan.json").write_text(json.dumps({
        "plan": {"name": "Wärmeplan CLI", "gemeinde": {"name": "Teststadt"}, "beschluss_datum": "2026-06-30"},
        "privacy_min_buildings": 1,
    }), encoding="utf-8")
    out = tmp_path / "out"
    code = main(["build", "--plan", str(tmp_path / "plan.json"), "--buildings", str(paths["buildings"]),
                 "--wld", str(paths["wld"]), "--streets", str(paths["streets"]),
                 "--boundary", str(tmp_path / "gebiet.gpkg"), "--year", "2024", "--out", str(out)])
    assert code == 0 and "gültig: ja" in capsys.readouterr().out
    assert main(["validate", str(out / "xwaermeplan.gml")]) == 0
    assert main(["validate", str(out / "xwaermeplan.gpkg")]) == 0
    broken = tmp_path / "kaputt.gml"
    broken.write_text((out / "xwaermeplan.gml").read_text(encoding="utf-8").replace("<zieljahr>2045</zieljahr>", ""),
                      encoding="utf-8")
    assert main(["validate", str(broken)]) == 1
    assert "zieljahr" in capsys.readouterr().out


def test_jsonfg_validation_still_sees_geometry_errors(orch):
    pytest.importorskip("jsonschema")
    from fheat_core.xwp.encode.jsonfg import to_jsonfg, validate_jsonfg
    from fheat_core.xwp.mapping import build_plan

    s = orch.state
    doc, _ = build_plan(s.buildings_gdf, s.wld_gdf, _xwp(), streets=s.streets_gdf, data_year=2024)
    data = to_jsonfg(doc)
    line = next(f for f in data["features"] if f["featureType"] == "WP_Waermelinie")
    line["place"]["coordinates"][0][-1] = [float("nan"), 1.0]
    block = next(f for f in data["features"] if f["featureType"] == "WP_EnergieBaublock")
    block["geometry"] = {"type": "MultiLineString", "coordinates": [[[7.0, 52.0], [7.1, 52.1]]]}
    messages = validate_jsonfg(data)
    assert any("ungültige Position" in msg for msg in messages)
    assert any("WP_EnergieBaublock" in msg and "geometry" in msg for msg in messages)
