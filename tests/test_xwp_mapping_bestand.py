"""Mapping inventory and potential onto XWaermeplan (phase 6)."""
from __future__ import annotations

import datetime

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString, Point, box

from fheat_core import columns as cols
from fheat_core.config import XwpConfig, XwpGemeinde, XwpPlanConfig
from fheat_core.xwp.mapping import build_inventory, units
from fheat_core.xwp.mapping.age_class import age_class, parse_year, subclass, to_upper, upper_class
from fheat_core.xwp.mapping.bestand import _prevailing
from fheat_core.xwp.mapping.blocks import Block, build_blocks, merge_small_blocks
from fheat_core.xwp.model import current as m
from tests.xwp_synth import small_town

CRS = "EPSG:25832"
X0, Y0 = 400_000.0, 5_760_000.0


# --------------------------------------------------------------------------
# units


def test_unit_conversions():
    assert units.mwh(22_230) == 22.23
    assert units.mwh_per_m(1_530) == 1.53  # kWh/(a·m) -> MWh/(m·a)
    assert units.hectares(226) == 0.0226
    assert units.mwh_per_ha(50_000, 5_000) == 100.0  # 50 MWh on 0.5 ha
    assert units.mwh_per_ha(1, 0) is None
    assert units.percent(1, 3) == 33.33 and units.percent(1, 0) == 0.0
    assert units.metres(141.999) == 142.0


# --------------------------------------------------------------------------
# age classes


@pytest.mark.parametrize("year, sub, upper", [
    (1900, "10001", "1000"), (1918, "10001", "1000"), (1919, "10002", "1000"), (1949, "10002", "1000"),
    (1950, "20001", "2000"), (1969, "20002", "2000"), (1985, "30002", "3000"), (1989, "30002", "3000"),
    (1990, "40001", "4000"), (2015, "40003", "4000"), (2016, "5000", "5000"), (2022, "5000", "5000"),
])
def test_age_class_bounds(year, sub, upper):
    assert subclass(year) == sub and upper_class(year) == upper and to_upper(sub) == upper


def test_parse_year():
    assert parse_year("1945") == 1945 and parse_year(1945.0) == 1945
    assert parse_year("1945, 1960") == 1945  # LANUV mode tie
    assert parse_year("0") is None and parse_year(None) is None and parse_year(float("nan")) is None


def test_age_class_sources():
    sources = ("construction_year", "age", "parcel_year")
    assert age_class({cols.CONSTRUCTION_YEAR: 1985, cols.AGE: "1945"}, sources) == "30002"  # true year: subclass
    assert age_class({cols.AGE: "1985", cols.PARCEL_YEAR: 1958}, sources) == "3000"  # LANUV: upper class only
    assert age_class({cols.PARCEL_YEAR: 1958}, sources) == "2000"
    assert age_class({cols.PARCEL_YEAR: 1958, cols.AGE: "1985"}, ("parcel_year", "age")) == "2000"
    assert age_class({}, sources) == "9999"


def test_prevailing_code():
    assert _prevailing(["10001", "10001", "2000"]) == "10001"
    assert _prevailing(["10001", "10003"]) == "1000"  # tie within residential
    assert _prevailing(["10001", "20001"]) == "9999"  # tie across categories
    assert _prevailing(["1000", "9999"]) == "9999"


# --------------------------------------------------------------------------
# building blocks


def _buildings(points, block_ids=None, demand=10_000.0):
    data = {cols.HEAT_DEMAND: [demand] * len(points)}
    if block_ids is not None:
        data[cols.BLOCK_ID] = block_ids
    return gpd.GeoDataFrame(data, geometry=[Point(x, y).buffer(3, cap_style=3) for x, y in points], crs=CRS)


def test_blocks_from_source_ids_and_parcels():
    parcels = gpd.GeoDataFrame(geometry=[box(0, 0, 50, 50), box(50, 0, 100, 50), box(0, 50, 50, 100)], crs=CRS)
    b = _buildings([(10, 10), (20, 20), (30, 30), (60, 10), (10, 60)], ["A", "A", "B", "B", "B"])
    blocks = {blk.key: blk for blk in build_blocks(b, parcels=parcels)}
    assert sorted(blocks) == ["A", "B"]
    assert sorted(blocks["A"].members) == [0, 1]
    # parcel 0 holds two buildings of A and one of B: it belongs to A
    assert blocks["A"].geometry.covers(box(0, 0, 50, 50))
    assert blocks["B"].geometry.covers(box(50, 0, 100, 50)) and blocks["B"].geometry.covers(box(0, 50, 50, 100))
    assert blocks["B"].geometry.covers(b.geometry.iloc[2])  # its building on A's parcel is still inside


def test_blocks_from_streets():
    streets = gpd.GeoDataFrame(geometry=[
        LineString([(0, 0), (200, 0)]), LineString([(0, 100), (200, 100)]), LineString([(0, 200), (200, 200)]),
        LineString([(0, 0), (0, 200)]), LineString([(100, 0), (100, 200)]), LineString([(200, 0), (200, 200)]),
    ], crs=CRS)
    b = _buildings([(50, 50), (60, 60), (150, 50), (150, 150), (300, 300)])
    blocks = build_blocks(b, streets=streets)
    by_member = {tuple(sorted(blk.members)): blk for blk in blocks}
    assert set(by_member) == {(0, 1), (2,), (3,), (4,)}
    assert by_member[(0, 1)].geometry.area == pytest.approx(100 * 100)
    assert by_member[(4,)].geometry.contains(b.geometry.iloc[4])  # outside every face: own block
    assert all(blk.key.startswith("S") for blk in blocks)


def test_mixed_sources_do_not_overlap():
    streets = gpd.GeoDataFrame(geometry=[LineString([(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)])], crs=CRS)
    parcels = gpd.GeoDataFrame(geometry=[box(0, 0, 50, 100)], crs=CRS)
    b = _buildings([(20, 50), (80, 50)], ["A", None])
    blocks = {blk.key: blk for blk in build_blocks(b, parcels=parcels, streets=streets)}
    assert set(blocks) == {"A", "S00001"}
    assert blocks["A"].geometry.intersection(blocks["S00001"].geometry).area == pytest.approx(0)


def test_small_blocks_merge_into_the_nearest():
    blocks = [
        Block("big", box(0, 0, 10, 10), list(range(6))),
        Block("near", box(12, 0, 20, 10), [6, 7]),
        Block("far", box(100, 0, 110, 10), [8]),
    ]
    merged, dropped = merge_small_blocks(blocks, 5)
    assert dropped == []
    # "far" (1 building) goes to its nearest block "near" first, then "near" (3) into "big"
    assert [(b.key, b.n) for b in merged] == [("big", 9)]
    assert merged[0].geometry.area == pytest.approx(100 + 80 + 100)


def test_ties_prefer_the_longest_shared_border():
    blocks = [
        Block("a", box(0, 0, 10, 10), list(range(5))),
        Block("b", box(10, 0, 14, 2), list(range(5, 10))),   # shares 4 m with "small"
        Block("small", box(10, 2, 20, 10), [10]),            # shares 8 m with "a"
    ]
    merged, _ = merge_small_blocks(blocks, 5)
    assert sorted((b.key, b.n) for b in merged) == [("a", 6), ("b", 5)]


def test_a_lonely_small_block_is_dropped():
    merged, dropped = merge_small_blocks([Block("x", box(0, 0, 1, 1), [0, 1])], 5)
    assert merged == [] and [b.key for b in dropped] == ["x"]


# --------------------------------------------------------------------------
# build_inventory


def _config(**kw):
    plan = XwpPlanConfig(
        name="Wärmeplan Test", gemeinde=XwpGemeinde("Teststadt", "051234567890"),
        beschluss_datum=datetime.date(2026, 6, 30), extra={"nummer": "WP-1"},
    )
    return XwpConfig(plan=plan, **kw)


@pytest.fixture
def area():
    return small_town()


def test_inventory_is_valid_and_complete(area):
    buildings, wld, streets, boundary = area
    doc, notes = build_inventory(buildings, wld, _config(privacy_min_buildings=1), streets=streets,
                                 boundary=boundary, data_year=2024)
    assert doc.errors() == []
    kinds = sorted(type(f).__name__ for f in doc.features)
    assert kinds.count("WP_Waermelinie") == 2 and notes.lines_without_demand == 3
    assert kinds.count("WP_GebaeudeBaublock") == kinds.count("WP_EnergieBaublock") == 2
    plan = doc.of_type("WP_Plan")[0]
    assert plan.basisJahrDatenerfassung == "2024" and plan.zieljahr == "2045" and plan.nummer == "WP-1"
    assert len(plan.bereich) == 1 and len(plan.infrastruktur) == 1


def test_heat_lines_in_xwp_units(area):
    buildings, wld, streets, boundary = area
    doc, _ = build_inventory(buildings, wld, _config(), streets=streets, boundary=boundary, data_year=2024)
    line = next(f for f in doc.of_type("WP_Waermelinie") if f.laenge == 200.0)
    assert line.waermeMenge == 120.0 and line.waermelinienDichte == 0.6


def test_block_figures(area):
    buildings, wld, streets, boundary = area
    doc, _ = build_inventory(buildings, wld, _config(privacy_min_buildings=1), streets=streets,
                             boundary=boundary, data_year=2024)
    west_g = next(f for f in doc.of_type("WP_GebaeudeBaublock") if f.position.centroid.x < X0 + 100)
    assert west_g.gebaeudetyp is m.WP_GebaeudeTyp.Einfamlienhaus
    assert west_g.ueberwiegendBaujahr.code == "20002"  # 4 × 1965 in 1960-1969
    shares = {a.baualtersklasse.code: a.anteil for a in west_g.verteilungBaujahr}
    assert shares == {"20002": 66.67, "30002": 16.67, "9999": 16.67}
    assert west_g.nutzflaeche == 0.09  # 6 × 150 m²
    west_e = next(f for f in doc.of_type("WP_EnergieBaublock") if f.baublockId == west_g.baublockId)
    assert west_e.waermeMenge == 120.0 and west_e.waermeDichte == 120.0  # 120 MWh on 1 ha
    # the unheated building is not counted
    east_e = next(f for f in doc.of_type("WP_EnergieBaublock") if f.baublockId != west_g.baublockId)
    assert east_e.waermeMenge == 100.0


def test_privacy_threshold_merges_blocks(area):
    buildings, wld, streets, boundary = area
    doc, notes = build_inventory(buildings, wld, _config(privacy_min_buildings=5), streets=streets,
                                 boundary=boundary, data_year=2024)
    [block] = doc.of_type("WP_EnergieBaublock")
    assert block.waermeMenge == 220.0 and notes.blocks_dropped == 0
    doc, notes = build_inventory(buildings, wld, _config(privacy_min_buildings=10), streets=streets,
                                 boundary=boundary, data_year=2024)
    assert doc.of_type("WP_EnergieBaublock") == [] and notes.buildings_in_dropped_blocks == 7
    assert notes.messages


def test_energy_raster(area):
    buildings, wld, streets, boundary = area
    doc, notes = build_inventory(buildings, wld, _config(privacy_min_buildings=1, energy_raster=True),
                                 streets=streets, boundary=boundary, data_year=2024)
    cells = doc.of_type("WP_EnergieRaster")
    assert cells and all(c.rasterID.startswith("CRS3035RES100mN") for c in cells)
    assert sum(c.waermeMenge for c in cells) == pytest.approx(220.0)
    assert all(c.position.area == pytest.approx(10_000, rel=0.01) for c in cells)
    assert doc.errors() == []


def test_infrastructure_counts(area):
    buildings, wld, streets, boundary = area
    doc, _ = build_inventory(buildings, wld, _config(), streets=streets, boundary=boundary, data_year=2024)
    [infra] = doc.of_type("WP_WaermeinfrastrukturAggregiert")
    assert infra.betrachtungszeitpunkt.art is m.WP_ZeitpunktArt.Basisjahr and infra.betrachtungszeitpunkt.jahr == "2024"
    count = infra.anzahlGebaeude
    assert (count.gebaeude, count.beheizteWohngebaeude, count.beheizteNichtwohngebaeude) == (8, 6, 1)


def test_ids_are_stable(area):
    buildings, wld, streets, boundary = area
    a, _ = build_inventory(buildings, wld, _config(), streets=streets, boundary=boundary, data_year=2024)
    b, _ = build_inventory(buildings, wld, _config(), streets=streets, boundary=boundary, data_year=2024)
    assert [f.id for f in a.features] == [f.id for f in b.features] and a.id == b.id


def test_without_boundary_and_base_year(area):
    buildings, wld, streets, _ = area
    doc, notes = build_inventory(buildings, None, _config(), streets=streets)
    plan = doc.of_type("WP_Plan")[0]
    assert plan.raeumlicherGeltungsbereich.contains(buildings.geometry.iloc[0])
    assert any(i.path.endswith("basisJahrDatenerfassung") for i in doc.errors())
    assert not doc.of_type("WP_WaermeinfrastrukturAggregiert") and notes.messages


def test_inventory_writes_valid_gml_and_jsonfg(area):
    pytest.importorskip("lxml")
    pytest.importorskip("jsonschema")
    from fheat_core.xwp.encode.gml import to_gml, validate_gml
    from fheat_core.xwp.encode.jsonfg import to_jsonfg, validate_jsonfg

    buildings, wld, streets, boundary = area
    doc, _ = build_inventory(buildings, wld, _config(privacy_min_buildings=1, energy_raster=True),
                             streets=streets, boundary=boundary, data_year=2024)
    assert validate_gml(to_gml(doc)) == []
    assert validate_jsonfg(to_jsonfg(doc)) == []
