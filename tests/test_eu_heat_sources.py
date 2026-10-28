"""Tests for fheat_eu.heat_sources (Fordatis layers → canonical columns).

- wastewater: kW × 4421 h, heat after the heat pump per scenario, rows
  without power left out
- industry: 95 °C = HT, 55 °C = LT, GWh → MWh, Hotmaps names by id
- waste incineration: PJ → MWh, recovery 66 / 76 %, umlauts restored
- rivers: one typical project per zone, no source candidate
- geothermal: HT and LT raster joined per cell, 1 km squares, TWh → MWh
- study areas and table per municipality: sources without supply, biomass
  and petrothermal left out
"""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import MultiPoint, Point, box

from fheat_core import columns as cols
from fheat_eu import heat_sources as hs

CRS = "EPSG:25832"
GRID = "EPSG:3035"
AREA = box(400_000, 5_770_000, 401_000, 5_771_000)


def _points(values: dict, xy: list) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(values, geometry=[Point(x, y) for x, y in xy], crs=CRS)


class TestWastewater:
    def test_power_to_heat(self):
        raw = _points({"Power in k": [1000.0, -999.0, 0.0]},
                      [(400_500, 5_772_000), (400_500, 5_770_500), (400_600, 5_770_500)])
        out = hs.process_wastewater(raw, AREA)
        assert len(out) == 1
        row = out.iloc[0]
        assert row[cols.HEAT_EXTRACTION_KW] == pytest.approx(1000.0)
        assert row[cols.HEAT_EXTRACTION_MWH] == pytest.approx(4421.0)
        assert row[cols.HEAT_HT_MWH] == pytest.approx(4421.0 * 2.7 / 1.7)
        assert row[cols.HEAT_LT_MWH] == pytest.approx(4421.0 * 3.6 / 2.6)
        assert row[cols.DISTANCE_TO_AREA] == pytest.approx(1000.0)
        assert 52.0 < row[cols.SOURCE_CANDIDATE_LAT] < 52.2

    def test_missing_field(self):
        with pytest.raises(RuntimeError, match="Power in k"):
            hs.process_wastewater(_points({"power": [1.0]}, [(400_500, 5_770_500)]), AREA)


def test_industrial_with_names():
    raw = _points({"ID_Site": [173, 5060], "EH_55_GWh": [30.0, 0.9], "EH_95_GWh": [24.0, 0.5]},
                  [(420_000, 5_770_500), (401_500, 5_770_500)])
    names = pd.DataFrame({"SiteID": pd.array([173], dtype="Int64"), "CompanyName": ["Dyckerhoff GmbH"],
                          "SiteName": ["Werk Lengerich"], "City": ["Lengerich"], "Subsector": ["Cement"]})
    out = hs.process_industrial(raw, AREA, names)
    assert out[cols.SITE_ID].tolist() == [5060, 173]          # nearest first
    assert out[cols.HEAT_HT_MWH].tolist() == [500.0, 24000.0]
    assert out[cols.HEAT_LT_MWH].tolist() == [900.0, 30000.0]
    assert pd.isna(out[cols.SOURCE_NAME].iloc[0])
    assert out[cols.SOURCE_NAME].iloc[1] == "Werk Lengerich"
    assert out[cols.SUBSECTOR].iloc[1] == "Cement"


class TestWasteIncineration:
    def test_recovery_per_scenario(self):
        raw = _points({"City": ["Salzbergen"], "EH100PJ": [0.36]}, [(400_500, 5_790_000)])
        row = hs.process_waste_incineration(raw, AREA).iloc[0]
        assert row[cols.EXCESS_HEAT_THEORETICAL_MWH] == pytest.approx(100_000.0)
        assert row[cols.HEAT_HT_MWH] == pytest.approx(66_000.0)
        assert row[cols.HEAT_LT_MWH] == pytest.approx(76_000.0)

    @pytest.mark.parametrize("name, known, expected", [
        ("D�sseldorf", ["Düsseldorf", "Duisburg"], "Düsseldorf"),
        ("K�ln", ["Köln"], "Köln"),
        ("Link�ping", ["Köln"], "Link?ping"),
        ("Herten", [], "Herten"),
        (None, [], None),
    ])
    def test_repair_name(self, name, known, expected):
        assert hs.repair_name(name, known) == expected


def test_rivers_one_project_per_zone():
    raw = gpd.GeoDataFrame({"Capa in MW": [30, 150, 99]},
                           geometry=[box(402_000, 5_770_000, 403_000, 5_771_000), box(0, 0, 1, 1),
                                     box(0, 0, 2, 2)], crs=CRS)
    out = hs.process_rivers(raw, AREA)
    assert out[cols.HEAT_PUMP_CAPACITY_MW].tolist() == [30.0, 150.0]   # 99 MW is no class
    assert out[cols.RIVER_SIZE_CLASS].tolist() == ["small", "large"]
    assert out[cols.HEAT_MWH].tolist() == [60_000.0, 450_000.0]
    assert cols.SOURCE_CANDIDATE_LAT not in out.columns


def test_geothermal_cells_join_both_scenarios():
    # cell A in both rasters, cell B only in the LT one (MultiPoint like hydrothermal)
    ht = gpd.GeoDataFrame({"TWh": [0.0002]}, geometry=[MultiPoint([(4_115_000.4, 3_252_000.2)])], crs=GRID)
    lt = gpd.GeoDataFrame({"TWh": [0.0005, 0.0004]},
                          geometry=[Point(4_115_000.4, 3_252_000.2), Point(4_116_000.5, 3_252_000.2)], crs=GRID)
    area = gpd.GeoSeries([Point(4_115_000, 3_252_000).buffer(10)], crs=GRID).to_crs(CRS).iloc[0]
    out = hs.process_geothermal_cells(ht, lt, "TWh", area, CRS)
    assert out.crs == CRS and len(out) == 2
    assert out[cols.HEAT_HT_MWH].iloc[0] == pytest.approx(200.0)
    assert out[cols.HEAT_LT_MWH].tolist() == pytest.approx([500.0, 400.0])
    assert np.isnan(out[cols.HEAT_HT_MWH].iloc[1])
    assert out.geometry.area.iloc[0] == pytest.approx(1e6, rel=0.01)
    assert out[cols.DISTANCE_TO_AREA].iloc[0] == 0.0


def test_study_dh_areas_of_a_municipality():
    mapping = pd.DataFrame({"fid": [1, 2, 3], "Label": [298, 305, 298],
                            "country": ["DE"] * 3, "LAU_ID": ["DE_05566084", "DE_05566012", "DE_05566084"]})
    labels = hs.study_dh_labels(mapping, "DE_05566084")
    assert labels == [298]
    raw = gpd.GeoDataFrame({"Label": [298, 305], "country": ["DE", "DE"], "Dem_GWh": [6.79, 31.6]},
                           geometry=[box(0, 0, 1, 1), box(2, 2, 3, 3)], crs=CRS)
    out = hs.process_study_dh_areas(raw, labels)
    assert out[cols.DH_AREA_ID].tolist() == [298]
    assert out[cols.DH_DEMAND_2050_MWH].iloc[0] == pytest.approx(6790.0)


def _matching() -> pd.DataFrame:
    sources = list(hs._STUDY_HEADERS)
    head = ["GISCO_ID", "Country", "Unit", "DH_demand", *sources, *sources,
            "DH_demand", *sources, *sources]
    # rivers and lakes (4th source): no supply in either scenario, only an LT supply for sludge (8th)
    supply_ht, supply_lt = [1, 2, 3, 0, 5, 6, 7, 0], [21, 22, 23, 0, 25, 26, 27, 28]
    values = ["DE_05566084", "DE", "GWh", 7.88, *supply_ht, *range(11, 19), 7.47, *supply_lt, *range(31, 39)]
    return pd.DataFrame([[None] * len(head), head, values])


class TestStudyTable:
    def test_rows_per_source(self):
        table = hs.study_table(_matching(), "DE_05566084")
        assert table[cols.STUDY_SOURCE].tolist() == ["dh_demand", "hydrothermal", "industrial_eh", "wte", "wwtp",
                                                     "sludge"]
        demand = table.iloc[0]
        assert demand[cols.STUDY_SUPPLY_HT_MWH] == pytest.approx(7880.0)
        assert demand[cols.STUDY_SUPPLY_LT_MWH] == pytest.approx(7470.0)
        assert np.isnan(demand[cols.STUDY_UTILIZATION_HT_MWH])
        wwtp = table[table[cols.STUDY_SOURCE] == "wwtp"].iloc[0]
        assert (wwtp[cols.STUDY_SUPPLY_HT_MWH], wwtp[cols.STUDY_UTILIZATION_HT_MWH],
                wwtp[cols.STUDY_SUPPLY_LT_MWH], wwtp[cols.STUDY_UTILIZATION_LT_MWH]) == (7000.0, 17000.0, 27000.0, 37000.0)

    def test_municipality_without_study_area(self):
        assert hs.study_table(_matching(), "DE_05566999") is None

    def test_changed_layout(self):
        matching = _matching()
        matching.iloc[1, 5] = "Geothermal"
        with pytest.raises(RuntimeError, match="nicht wie erwartet"):
            hs.study_table(matching, "DE_05566084")


def test_delivered_heat():
    assert hs.delivered_heat(100.0, 3.0) == pytest.approx(150.0)
