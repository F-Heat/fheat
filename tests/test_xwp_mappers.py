"""Mappers of the XWaermeplan export on hand-built frames; no xplan-tools needed."""
from __future__ import annotations

import ast
import dataclasses
import datetime
from collections import defaultdict
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box

from fheat_core import columns as cols
from fheat_core.export.xwp import NetworkResult, XWPExportConfig, mapping
from fheat_core.export.xwp.mappers import (
    building_type_code,
    construction_period_code,
    geometry_key,
    map_baubloecke,
    map_plan,
    map_versorgungsgebiete,
    map_waermelinien,
    map_waermenetze,
    suitability_stage,
)
from fheat_core.state import PipelineState

CRS = "EPSG:25832"
PLAN_ID = "6a2f41a3-c54c-4ce8-92d2-0324e1c32e22"


@pytest.fixture
def config():
    return XWPExportConfig(
        plan_name="Wärmeplan Steinfurt", municipality_name="Steinfurt", municipality_key="05566084",
        base_year=2022, decision_date=datetime.date(2026, 6, 30),
    )


def by_key(records):
    return {r["key"]: r for r in records}


class TestWaermelinien:
    @pytest.fixture
    def wld(self):
        return gpd.GeoDataFrame({
            cols.LENGTH: [100.0, 50.0, 0.0],
            cols.HEAT_DEMAND: [120_000.0, 0.0, 5_000.0],
            cols.HEAT_LINE_DENSITY: [1200.0, 0.0, float("nan")],
            cols.CONNECTED_IDS: ["1,2", "", "3"],
        }, geometry=[LineString([(0, 0), (100, 0)]), LineString([(0, 10), (50, 10)]), LineString([(5, 5), (5, 5)])],
            crs=CRS)

    def test_units_kwh_to_mwh(self, wld):
        [record] = map_waermelinien(wld)
        props = record["properties"]
        assert props["waermeMenge"] == {"value": 120.0, "uom": "MWh/a"}
        assert props["waermelinienDichte"] == {"value": 1.2, "uom": "MWh/(m*a)"}
        assert props["laenge"] == {"value": 100.0, "uom": "m"}
        assert record["featuretype"] == "WP_Waermelinie"
        assert record["geometry"].geom_type == "MultiLineString"

    def test_segments_without_demand_or_length_are_left_out(self, wld):
        assert len(map_waermelinien(wld)) == 1

    def test_demand_from_density_without_demand_column(self, wld):
        [record] = map_waermelinien(wld.drop(columns=cols.HEAT_DEMAND))
        assert record["properties"]["waermeMenge"]["value"] == 120.0

    def test_cut_to_the_boundary_keeps_the_density(self, wld):
        [record] = map_waermelinien(wld, box(-10, -10, 60, 10))
        props = record["properties"]
        assert props["laenge"] == {"value": 60.0, "uom": "m"}
        assert props["waermelinienDichte"] == {"value": 1.2, "uom": "MWh/(m*a)"}
        assert props["waermeMenge"] == {"value": 72.0, "uom": "MWh/a"}
        assert record["geometry"].length == pytest.approx(60.0)

    def test_inside_the_boundary_unchanged(self, wld):
        assert map_waermelinien(wld, box(-10, -10, 200, 20)) == map_waermelinien(wld)

    @pytest.mark.parametrize("boundary", [box(200, 200, 300, 300), box(99.6, -10, 200, 10)])
    def test_outside_or_shorter_than_half_a_metre_is_left_out(self, wld, boundary):
        assert map_waermelinien(wld, boundary) == []

    def test_empty(self):
        assert map_waermelinien(None) == []


def network_state(summary=None):
    net = gpd.GeoDataFrame({
        cols.TYPE: ["Rohr", "Rohr", cols.EDGE_TYPE_HOUSE_CONNECTION],
        cols.LENGTH: [100.0, 50.0, 20.0],
    }, geometry=[LineString([(0, 0), (100, 0)]), LineString([(100, 0), (150, 0)]),
                 LineString([(50, 0), (50, 20)])], crs=CRS)
    return PipelineState(
        net_gdf=net,
        result_summary=summary or {
            "total_route_length_m": 150.0, "total_buildings": 7, "supply_temperature_c": 80.0,
            "total_heat_demand_mwh_a": 900.0, "total_loss_mwh_a": 100.0,
        },
    )


class TestWaermenetz:
    def test_attributes_from_the_summary(self, config):
        [record] = map_waermenetze([NetworkResult(network_state(), name="Netz Zentrum")], config, CRS)
        props = record["properties"]
        assert props["laenge"] == {"value": 150.0, "uom": "m"}
        assert props["anzahlGebaeudeAnschluss"] == 7
        assert props["temperatur"] == {"value": 80.0, "uom": "°C"}
        assert (props["status"], props["medium"]) == ("3000", "1000")
        assert props["name"] == props["netzID"] == "Netz Zentrum"
        assert "eeNachEnergietraeger" not in props and "betreiber" not in props

    def test_area_is_a_buffer_around_every_edge(self, config):
        config = dataclasses.replace(config, network_buffer=10.0)
        [record] = map_waermenetze([NetworkResult(network_state())], config, CRS)
        geom = record["geometry"]
        assert geom.geom_type == "MultiPolygon"
        assert geom.covers(Point(75, 9)) and geom.covers(Point(50, 29))  # the house connection too
        assert not geom.covers(Point(75, 11))
        # route 150 m x 20 m with round ends, plus the house connection above it
        assert geom.area == pytest.approx(150 * 20 + 3.1416 * 100 + 10 * 20 + 3.1416 * 100 / 2, rel=0.01)

    def test_buffer_defaults_to_the_calculation(self, config):
        from fheat_core.config import FHeatConfig

        [record] = map_waermenetze([NetworkResult(network_state())], config, CRS)
        assert record["geometry"].covers(Point(75, FHeatConfig().buffer_distance - 0.1))

    def test_energy_carrier_gets_demand_plus_losses(self, config):
        config = dataclasses.replace(config, source_energy_carrier="72002")
        [record] = map_waermenetze([NetworkResult(network_state())], config, CRS)
        assert record["properties"]["eeNachEnergietraeger"] == {
            "energietraeger": "72002", "endenergie": {"value": 1000.0, "uom": "MWh/a"},
        }

    def test_key_per_network_and_status_from_the_config(self, config):
        config = dataclasses.replace(config, network_status="2000")
        records = map_waermenetze([NetworkResult(network_state(), key="A"), NetworkResult(network_state())],
                                  config, CRS)
        assert [(r["key"], r["properties"]["status"]) for r in records] == [("A", "2000"), ("N02", "2000")]

    def test_network_without_result_raises(self, config):
        with pytest.raises(ValueError, match="no result"):
            map_waermenetze([NetworkResult(PipelineState(net_gdf=network_state().net_gdf))], config, CRS)

    def test_frames_in_another_crs_are_reprojected(self, config):
        state = network_state()
        state.net_gdf = state.net_gdf.set_crs(CRS).to_crs("EPSG:3857")
        [record] = map_waermenetze([NetworkResult(state)], dataclasses.replace(config, network_buffer=10.0), CRS)
        assert record["geometry"].bounds[0] == pytest.approx(-10, abs=0.01)


class TestVersorgungsgebiete:
    @pytest.fixture
    def polygons(self):
        return gpd.GeoDataFrame({
            cols.HEAT_DEMAND: [500_000.0, 40_000.0],
            cols.HEAT_DEMAND_DENSITY: [500.0, 40.0],
        }, geometry=[box(0, 0, 100, 100), box(200, 0, 300, 100)], crs=CRS)

    def test_pruefgebiet_needs_no_suitability_statement(self, config, polygons):
        first, _ = map_versorgungsgebiete(polygons, dataclasses.replace(config, suitability_thresholds=(415, 175, 70)))
        assert first["featuretype"] == "WP_WaermeversorgungsgebietZieljahr"
        assert first["properties"] == {
            "versorgungsart": "40001", "waermeMenge": {"value": 500.0, "uom": "MWh/a"},
            "eignungDezentraleVersorgung": "5000", "eignungWaermenetz": "5000", "eignungWasserstoffnetz": "5000",
        }

    def test_simplified_procedure_needs_no_suitability_statement(self, config, polygons):
        first, _ = map_versorgungsgebiete(polygons, dataclasses.replace(config, supply_type="1000", procedure="3000"))
        assert {first["properties"][k] for k in ("eignungDezentraleVersorgung", "eignungWaermenetz",
                                                 "eignungWasserstoffnetz")} == {"5000"}

    def test_suitability_proposed_with_thresholds(self, config, polygons):
        config = dataclasses.replace(config, supply_type="1000", suitability_thresholds=(415, 175, 70))
        first, second = map_versorgungsgebiete(polygons, config)
        assert (first["properties"]["eignungWaermenetz"], second["properties"]["eignungWaermenetz"]) == ("1000", "4000")
        assert "eignungDezentraleVersorgung" not in first["properties"]

    def test_no_suitability_without_thresholds(self, config, polygons):
        first, _ = map_versorgungsgebiete(polygons, dataclasses.replace(config, supply_type="1000"))
        assert not any(k.startswith("eignung") for k in first["properties"])

    def test_one_supply_type_for_every_area(self, config, polygons):
        config = dataclasses.replace(config, supply_type="1000")
        assert {r["properties"]["versorgungsart"] for r in map_versorgungsgebiete(polygons, config)} == {"1000"}

    def test_interim_year(self, config, polygons):
        first, _ = map_versorgungsgebiete(polygons, dataclasses.replace(config, supply_year="2035"))
        assert first["featuretype"] == "WP_WaermeversorgungsgebietStuetzjahr"
        assert first["properties"]["stuetzjahr"] == "2000"
        assert "eignungWaermenetz" not in first["properties"]

    @pytest.mark.parametrize("density, stage", [
        (415.0, "1000"), (414.9, "2000"), (175.0, "2000"), (100.0, "3000"), (70.0, "3000"), (69.9, "4000"),
        (None, None), (float("nan"), None),
    ])
    def test_suitability_stage(self, density, stage):
        assert suitability_stage(density, (415.0, 175.0, 70.0)) == stage

    def test_no_stage_without_thresholds(self):
        assert suitability_stage(500.0, None) is None


class TestBaubloecke:
    BOUNDARY = box(-100, -100, 200, 100)

    @pytest.fixture
    def buildings(self):
        """Two heated houses, an unheated shed and a heated hall."""
        return gpd.GeoDataFrame({
            cols.HEAT_DEMAND: [10_000.0, 20_000.0, 0.0, 50_000.0],
            cols.FUNCTION: ["31001_1010", "31001_1010", "31001_2463", "31001_2143"],
            cols.BUILDING_TYPE: ["EFH", "EFH", "NWG", "NWG"],
            cols.AGE: ["1945", "1960", "1960", "2022"],
            cols.FLOOR_AREA: [100.0, 150.0, 20.0, 400.0],
        }, geometry=[box(1, 1, 9, 9), box(11, 1, 19, 9), box(1, 12, 4, 15), box(50, 0, 70, 20)], crs=CRS)

    def test_every_heated_building_is_a_block_with_its_footprint(self, buildings):
        house, _, hall = map_baubloecke(buildings, self.BOUNDARY)
        assert house["featuretype"] == "WP_GebaeudeBaublock"
        assert house["geometry"].equals(MultiPolygon([box(1, 1, 9, 9)]))
        assert house["key"] == geometry_key(MultiPolygon([box(1, 1, 9, 9)]))
        assert house["properties"] == {
            "baublockId": house["key"], "gebaeudetyp": "1000", "ueberwiegendBaujahr": "1000",
            "nutzflaeche": {"value": 0.01, "uom": "ha"},
        }
        assert (hall["properties"]["gebaeudetyp"], hall["properties"]["ueberwiegendBaujahr"]) == ("20009", "5000")

    def test_a_footprint_is_cut_to_the_boundary_and_buildings_outside_are_left_out(self, buildings):
        [house] = map_baubloecke(buildings, box(-100, -100, 7, 100))
        assert house["geometry"].equals(MultiPolygon([box(1, 1, 7, 9)]))
        assert house["properties"]["nutzflaeche"]["value"] == 0.01  # the building's, not cut

    @pytest.mark.parametrize("missing", [float("nan"), pd.NA])
    def test_no_floor_area_without_one(self, buildings, missing):
        buildings[cols.FLOOR_AREA] = buildings[cols.FLOOR_AREA].astype("Float64")
        buildings.loc[0, cols.FLOOR_AREA] = missing
        house, *_ = map_baubloecke(buildings, self.BOUNDARY)
        assert "nutzflaeche" not in house["properties"]

    def test_no_buildings(self):
        assert map_baubloecke(None, self.BOUNDARY) == []

    @pytest.mark.parametrize("function, building_type, code", [
        ("31001_1010", "MFH", "1000"),    # the function first
        ("1123", "EFH", "20002"),         # Wohn- und Geschäftsgebäude
        ("9998", "EFH", "9999"),          # nach Quellenlage nicht zu spezifizieren
        ("31001_3021", "NWG", "20006"),
        ("31001_2463", None, "2000"),
        (None, "GMFH", "1000"),           # LANUV: a residential type, the subtype counts no dwellings
        ("Wohnhaus", "NWG", "2000"),      # not an ALKIS code
        (float("nan"), float("nan"), "9999"),
        (None, "HH", "9999"),
    ])
    def test_building_type(self, function, building_type, code):
        assert building_type_code({cols.FUNCTION: function, cols.BUILDING_TYPE: building_type}) == code

    @pytest.mark.parametrize("year, age, code", [
        (1975, "1945", "3000"),    # the construction year first
        (1949, None, "1000"),
        (2016, None, "5000"),
        (None, "1995", "4000"),    # 1986-1995: six years in 1990-2015
        (None, "1945, 1900", "1000"),
        (None, "1945, 2022", "9999"),
        (None, "1955", "9999"),    # no LANUV class
        (None, None, "9999"),
    ])
    def test_construction_period(self, year, age, code):
        assert construction_period_code({cols.CONSTRUCTION_YEAR: year, cols.AGE: age}) == code


class TestPlan:
    def test_plan_and_area(self, config):
        plan, bereich = map_plan(config, box(0, 0, 10, 10))
        assert plan["featuretype"] == "WP_Plan" and plan["geometry_property"] == "raeumlicherGeltungsbereich"
        assert plan["properties"] == {
            "name": "Wärmeplan Steinfurt",
            "planungsverantwortlicheStelle": {"name": "Steinfurt", "regionalSchluessel12": "055660084084"},
            "verfahrensart": "1000", "gesetzlicheGrundlage": "1000", "zieljahr": "2045",
            "basisJahrDatenerfassung": "2022", "beschlussDatum": datetime.date(2026, 6, 30),
        }
        assert bereich["featuretype"] == "WP_Bereich" and bereich["properties"] == {"nummer": 0, "name": "F|Heat"}

    def test_fragment_has_no_plan(self):
        config = XWPExportConfig(mode="fragment", plan_id=PLAN_ID, municipality_key="05566084")
        [bereich] = map_plan(config, box(0, 0, 10, 10))
        assert bereich["featuretype"] == "WP_Bereich"
        assert bereich["key"] == f"{PLAN_ID}/0/{geometry_key(MultiPolygon([box(0, 0, 10, 10)]))}"

    def test_area_key_depends_on_the_boundary(self):
        config = XWPExportConfig(mode="fragment", municipality_key="05566084")
        [first], [second] = map_plan(config, box(0, 0, 10, 10)), map_plan(config, box(0, 0, 20, 10))
        assert first["key"].startswith("/0/") and first["key"] != second["key"]


class TestTable:
    """``mapping.CLASSES`` is exactly what the export writes; test_xwp_evidence checks it against the XSD."""

    def test_table_equals_the_records(self, config):
        wld = gpd.GeoDataFrame({cols.LENGTH: [100.0], cols.HEAT_DEMAND: [120_000.0], cols.HEAT_LINE_DENSITY: [1200.0]},
                               geometry=[LineString([(0, 0), (100, 0)])], crs=CRS)
        polygons = gpd.GeoDataFrame({cols.HEAT_DEMAND: [500_000.0], cols.HEAT_DEMAND_DENSITY: [500.0]},
                                    geometry=[box(0, 0, 100, 100)], crs=CRS)
        buildings = gpd.GeoDataFrame({cols.HEAT_DEMAND: [10_000.0], cols.FLOOR_AREA: [100.0]},
                                     geometry=[box(1, 1, 9, 9)], crs=CRS)
        records = [
            *map_plan(config, box(0, 0, 10, 10)),
            *map_waermelinien(wld),
            *map_waermenetze([NetworkResult(network_state(), name="Netz", operator="Stadtwerke")],
                             dataclasses.replace(config, source_energy_carrier="72002"), CRS),
            *map_versorgungsgebiete(polygons, dataclasses.replace(config, suitability_thresholds=(415, 175, 70))),
            *map_versorgungsgebiete(polygons, dataclasses.replace(config, supply_year="2035")),
            *map_baubloecke(buildings, box(0, 0, 100, 100)),
        ]
        written = defaultdict(set)
        for record in records:
            featuretype = record["featuretype"]
            written[featuretype] |= set(record["properties"]) | {record["geometry_property"]}
            for prop, value in record["properties"].items():
                attribute = mapping.CLASSES[featuretype][prop]
                if attribute.source == "nested":
                    written[attribute.name] |= set(value)
        # the references are added by the builder
        expected = {c: {n for n, a in table.items() if a.source != "reference"} for c, table in mapping.CLASSES.items()}
        assert dict(written) == expected

    def test_exporter_reads_columns_only_through_constants(self):
        """No column or summary key of F|Heat as text in a subscript, ``.get()`` or ``getattr()`` of the export."""
        names = {v for k, v in vars(cols).items() if k.isupper() and isinstance(v, str)}
        found = []
        for path in sorted(Path(mapping.__file__).parent.glob("*.py")):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Subscript):
                    keys = [node.slice]
                elif isinstance(node, ast.Call) and (
                    (isinstance(node.func, ast.Attribute) and node.func.attr == "get")
                    or (isinstance(node.func, ast.Name) and node.func.id == "getattr")
                ):
                    keys = node.args[1:2] if isinstance(node.func, ast.Name) else node.args[:1]
                else:
                    continue
                found += [f"{path.name}:{node.lineno} {k.value!r}" for k in keys
                          if isinstance(k, ast.Constant) and k.value in names]
        assert found == []


class TestGeometryKey:
    def test_stable_under_vertex_order_and_noise(self):
        a = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        b = Polygon([(10, 10.01), (0, 10), (0, 0), (10, 0)])
        assert geometry_key(a) == geometry_key(b)

    def test_differs_for_other_geometries(self):
        assert geometry_key(box(0, 0, 10, 10)) != geometry_key(box(0, 0, 10, 11))
