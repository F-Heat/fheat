"""Mapping networks, supply areas and suitability onto XWaermeplan (phase 7)."""
from __future__ import annotations

import datetime

import geopandas as gpd
import pytest
from shapely.geometry import LineString, box

from fheat_core import columns as cols
from fheat_core.config import XwpConfig, XwpGemeinde, XwpPlanConfig, XwpSuitabilityConfig
from fheat_core.state import PipelineState
from fheat_core.xwp.mapping import NetworkInput, build_plan
from fheat_core.xwp.mapping.planning import ROUTE_BUFFER_M, stage
from fheat_core.xwp.model import current as m
from tests.xwp_synth import X0, Y0, small_town

CRS = "EPSG:25832"


def _config(**kw):
    plan = XwpPlanConfig(name="Wärmeplan Test", gemeinde=XwpGemeinde("Teststadt", "051234567890"),
                         beschluss_datum=datetime.date(2026, 6, 30), zieljahr=2040)
    return XwpConfig(plan=plan, privacy_min_buildings=1, **kw)


def _network(buildings, with_area=True):
    """A network over the west block: 60 m route, 6 house connections."""
    route = [LineString([(X0 + 10, Y0 + 40), (X0 + 40, Y0 + 40)]), LineString([(X0 + 40, Y0 + 40), (X0 + 70, Y0 + 40)])]
    houses = [LineString([(X0 + 15 * i + 10, Y0 + 40), (X0 + 15 * i + 10, Y0 + 45)]) for i in range(6)]
    net = gpd.GeoDataFrame({
        cols.TYPE: ["Trasse", "Trasse"] + [cols.EDGE_TYPE_HOUSE_CONNECTION] * 6,
        cols.LENGTH: [30.0, 30.0] + [5.0] * 6,
    }, geometry=route + houses, crs=CRS)
    area = gpd.GeoDataFrame(geometry=[box(X0, Y0, X0 + 100, Y0 + 100)], crs=CRS) if with_area else None
    return PipelineState(buildings_gdf=buildings, net_gdf=net, planning_area_gdf=area,
                         result_summary={"total_route_length_m": 60.0, "total_buildings": 6})


@pytest.fixture
def town():
    return small_town()


def _plan(town, networks=(), **cfg):
    buildings, wld, streets, boundary = town
    return build_plan(buildings, wld, _config(**cfg), networks=networks, streets=streets,
                      boundary=boundary, data_year=2024)


def test_network_feature(town):
    state = _network(town[0])
    doc, notes = _plan(town, [NetworkInput(state, name="Netz West", betreiber="Stadtwerke", supply_temperature=75.0)])
    assert doc.errors() == []
    [net] = doc.of_type("WP_Waermenetz")
    assert (net.netzID, net.name, net.betreiber) == ("N01", "Netz West", "Stadtwerke")
    assert net.status is m.WP_Status.Potenziell and net.medium is m.WP_Transportmedium.Wasser
    assert (net.laenge, net.anzahlGebaeudeAnschluss, net.temperatur) == (60.0, 6, 75.0)
    assert net.position.equals(box(X0, Y0, X0 + 100, Y0 + 100))  # the planning area
    assert notes.networks == 1


def test_network_without_planning_area_is_a_route_buffer(town):
    doc, _ = _plan(town, [NetworkInput(_network(town[0], with_area=False))])
    [net] = doc.of_type("WP_Waermenetz")
    route = LineString([(X0 + 10, Y0 + 40), (X0 + 70, Y0 + 40)])
    assert net.position.symmetric_difference(route.buffer(ROUTE_BUFFER_M)).area < 1e-6  # house connections left out
    assert net.name == "Wärmenetz N01"


def test_status_is_checked():
    with pytest.raises(ValueError, match="WP_Status"):
        NetworkInput(PipelineState(), status="7")
    assert NetworkInput(PipelineState(), status="2000").status == "2000"


def test_blocks_get_connections_and_network_id(town):
    doc, _ = _plan(town, [NetworkInput(_network(town[0]))])
    by_count = {b.anzahlAnschluesseWaermenetz: b for b in doc.of_type("WP_EnergieBaublock")}
    assert by_count[6].refWaermeNetzID == "N01"
    assert None in by_count and by_count[None].refWaermeNetzID is None  # the east block


def test_target_year_infrastructure(town):
    doc, _ = _plan(town, [NetworkInput(_network(town[0]))])
    target = next(i for i in doc.of_type("WP_WaermeinfrastrukturAggregiert")
                  if i.betrachtungszeitpunkt.art is m.WP_ZeitpunktArt.Zieljahr)
    assert target.betrachtungszeitpunkt.jahr == "2040"
    assert (target.waermenetzePlanung.anzahlNetze, target.waermenetzePlanung.trassenlaenge) == (1, 60.0)
    assert target.gebaeudeAnschlussWaermenetzPlanung.anzahl == 6
    assert target.gebaeudeAnschlussWaermenetzPlanung.anteil == pytest.approx(85.71)  # 6 of 7 heated


@pytest.mark.parametrize("value, expected", [
    (500.0, "1000"), (415.0, "1000"), (200.0, "2000"), (100.0, "3000"), (69.9, "4000"), (None, "4000"),
])
def test_stage(value, expected):
    assert stage(value, (415.0, 175.0, 70.0)) == expected


def test_supply_area_proposal(town):
    doc, notes = _plan(town, [NetworkInput(_network(town[0]))])
    areas = doc.of_type("WP_WaermeversorgungsgebietZieljahr")
    assert len(areas) == 2 and notes.proposed_supply_areas == 2
    west = next(a for a in areas if a.position.centroid.x < X0 + 100)
    east = next(a for a in areas if a.position.centroid.x > X0 + 100)
    assert west.versorgungsart is m.WP_WaermeversorgungsgebietTyp.Waermenetzgebiet
    assert east.versorgungsart is m.WP_WaermeversorgungsgebietTyp.GebietDezentrWaerVersorgung
    # west: 120 MWh/ha -> heat density stage 3000; WLD 0.6 MWh/(m·a) -> 3000 with the default bounds
    assert west.eignungWaermenetz.code == "3000" and west.waermeMenge == 120.0
    assert any("Vorschläge" in msg for msg in notes.messages)


def test_worse_stage_wins_and_unsuitable_blocks_get_a_check(town):
    suitability = XwpSuitabilityConfig(heat_line_density=(5.0, 4.0, 3.0), heat_density=(50.0, 20.0, 10.0))
    doc, notes = _plan(town, (), suitability=suitability)
    areas = doc.of_type("WP_WaermeversorgungsgebietZieljahr")
    assert {a.eignungWaermenetz.code for a in areas} == {"4000"}  # density says 1000, WLD says 4000
    assert all(a.versorgungsart.code == "3000" for a in areas)  # no network
    checks = doc.of_type("WP_Eignungspruefung")
    assert len(checks) == 2 and all(c.istUngeeignetWaermenetz for c in checks)
    assert notes.proposed_suitability_checks == 2


def test_network_without_result_is_skipped(town):
    doc, notes = _plan(town, [NetworkInput(PipelineState(buildings_gdf=town[0]), name="leer")])
    assert doc.of_type("WP_Waermenetz") == [] and notes.networks_skipped == ["leer: kein Netzergebnis"]
    assert not [i for i in doc.of_type("WP_WaermeinfrastrukturAggregiert")
                if i.betrachtungszeitpunkt.art is m.WP_ZeitpunktArt.Zieljahr]


def test_plan_writes_valid_gml_and_jsonfg(town):
    pytest.importorskip("lxml")
    pytest.importorskip("jsonschema")
    from fheat_core.xwp.encode.gml import to_gml, validate_gml
    from fheat_core.xwp.encode.jsonfg import to_jsonfg, validate_jsonfg

    doc, _ = _plan(town, [NetworkInput(_network(town[0]), supply_temperature=80.0)], energy_raster=True)
    assert validate_gml(to_gml(doc)) == []
    assert validate_jsonfg(to_jsonfg(doc)) == []
