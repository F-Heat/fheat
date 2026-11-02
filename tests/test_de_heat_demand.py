"""Tests for fheat_de.heat_demand: the shipped tables and the heat demand from function and age class."""
from __future__ import annotations

import json

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from fheat_de import heat_demand as hd

CRS = "EPSG:25832"


@pytest.fixture(scope="module")
def functions():
    return hd.load_building_functions()


@pytest.fixture(scope="module")
def age_classes():
    return hd.load_age_classes()


def _buildings(**columns):
    n = len(next(iter(columns.values())))
    geoms = [box(20 * i, 0, 20 * i + 10, 10) for i in range(n)]
    return gpd.GeoDataFrame(columns, geometry=geoms, crs=CRS)


class TestTables:
    def test_functions_are_keyed_by_the_alkis_code(self, functions):
        assert {"Funktion", "Lastprofil", "Vlh", "WVBRpEBF"} <= set(functions.columns)
        assert functions["Funktion"].is_unique
        assert functions.set_index("Funktion").loc["1000", "Lastprofil"] == "EFH"

    def test_age_classes_have_the_specific_demand_of_both_house_types(self, age_classes):
        assert {"Baualtersklasse", "waerme_efh_kwh_m2a", "waerme_mfh_kwh_m2a"} <= set(age_classes.columns)
        assert set(hd.BAK_LABELS) <= set(age_classes["Baualtersklasse"])

    def test_an_own_table_replaces_the_shipped_one(self, tmp_path):
        path = tmp_path / "functions.json"
        path.write_text(json.dumps({"1000": {"Lastprofil": "MFH", "Vlh": 1800, "WVBRpEBF": 100.0}}), encoding="utf-8")
        table = hd.load_building_functions(path)
        assert table.to_dict("records") == [{"Funktion": "1000", "Lastprofil": "MFH", "Vlh": 1800, "WVBRpEBF": 100.0}]


class TestConstructionClass:
    def test_class_from_the_year_of_the_date(self):
        gdf = _buildings(validFrom=["1910-05-01", "1975-01-01", "2005-03-03", None])
        assert hd.add_construction_class(gdf)["BAK"].tolist() == ["B", "F", "J", "nan"]

    def test_without_dates_no_class(self):
        assert hd.add_construction_class(_buildings(NF=[100.0]))["BAK"].isna().all()


class TestHeatDemand:
    def test_houses_by_age_class_others_by_function(self, functions, age_classes):
        gdf = _buildings(
            citygml_fu=["31001_1010", "31001_1010", "31001_2071"],
            type=["EFH", "MFH", "NWG"],
            BAK=["F", "F", "F"],
            NF=[150.0, 600.0, 1000.0],
            heat=[1.0, 1.0, 1.0],
        )
        gdf = hd.add_full_load_hours_and_profile(gdf, functions)
        assert gdf["Lastprofil"].tolist()[:2] == ["EFH", "MFH"]   # a residential non-EFH gets the MFH profile
        out = hd.add_calculated_heat_demand(gdf, age_classes, functions, "heat")

        f = age_classes.set_index("Baualtersklasse").loc["F"]
        hotel = functions.set_index("Funktion").loc["2071", "WVBRpEBF"]
        assert out["Waermebedarf"].tolist() == pytest.approx(
            [150.0 * f["waerme_efh_kwh_m2a"], 600.0 * f["waerme_mfh_kwh_m2a"], 1000.0 * hotel]
        )
        assert out["heat"].tolist() == pytest.approx(out["Waermebedarf"].tolist())

    def test_without_floor_area_the_heat_demand_stays(self, functions, age_classes):
        gdf = hd.add_full_load_hours_and_profile(_buildings(citygml_fu=["31001_1010"], heat=[5000.0]), functions)
        out = hd.add_calculated_heat_demand(gdf, age_classes, functions, "heat")
        assert "Waermebedarf" not in out.columns and out["heat"].tolist() == [5000.0]

    def test_thermal_power_with_the_default_full_load_hours(self):
        out = hd.add_thermal_power(_buildings(heat=[16000.0, 16000.0], Vlh=[2000, 0]), "heat")
        assert out["power_th"].tolist() == [8.0, 16000.0 / hd.DEFAULT_FULL_LOAD_HOURS]
        assert hd.add_thermal_power(_buildings(heat=[3200.0]), "heat")["power_th"].tolist() == [2.0]


class TestFloorArea:
    def test_storeys_from_the_eaves_height(self):
        heights = pd.Series([2.0, 6.1, 7.6, None])
        out = hd.storeys_from_height(heights)
        assert out.iloc[:3].tolist() == [1.0, 2.0, 3.0] and pd.isna(out.iloc[3])
        assert hd.storeys_from_height(pd.Series([6.0]), storey_height=2.5).tolist() == [2.0]

    def test_net_floor_area_and_house_type(self):
        assert hd.net_floor_area(100.0, 2) == pytest.approx(140.0)
        assert hd.residential_type(pd.Series([150.0, 280.0, 281.0])).tolist() == ["EFH", "EFH", "MFH"]


def test_extract_year():
    assert hd.extract_year("2019-04-01") == 2019
    assert hd.extract_year(pd.Timestamp("1999-12-31")) == 1999
    assert pd.isna(hd.extract_year(None))
    assert pd.isna(hd.extract_year("unbekannt"))
