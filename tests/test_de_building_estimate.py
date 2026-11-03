"""Tests for fheat_de.building_estimate (a building added by hand).

- a house: floor area from footprint and storeys, the EFH demand of the
  newest age class, power from the full load hours of the function
- above the largest EFH floor area it is an MFH, unless it is given as EFH;
  other functions use their own specific demand and load profile
- given values replace the estimate, and what follows uses them; a given
  heat demand has no calculated one
- the result is a valid building for the pipeline, also under both heat
  demand bases
- unknown or unusable input is an error
"""
from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import box

from fheat_core import columns as cols
from fheat_core.schemas import BuildingsSchema
from fheat_core.steps.adjust import _apply_heat_demand_basis
from fheat_de import building_estimate as est


def test_a_house_from_footprint_and_storeys():
    house = est.estimate_building(100.0)
    age = est.age_classes()["L"]
    assert est.newest_age_class() == "L"
    assert house[cols.FUNCTION] == "1010"
    assert house[cols.USAGE] == "Wohnhaus"
    assert house[cols.STOREYS] == 2
    assert house[cols.FLOOR_AREA] == pytest.approx(140.0)
    assert house[cols.CONSTRUCTION_CLASS] == "L"
    assert house[cols.BUILDING_TYPE] == house[cols.LOAD_PROFILE] == "EFH"
    assert house[cols.HEAT_DEMAND] == house[cols.HEAT_DEMAND_CALCULATED] == pytest.approx(140.0 * age["waerme_efh_kwh_m2a"])
    assert house[cols.FULL_LOAD_HOURS] == 1600
    assert house[cols.THERMAL_POWER] == pytest.approx(house[cols.HEAT_DEMAND] / 1600)


def test_a_large_house_is_an_mfh():
    block = est.estimate_building(200.0, function="31001_1010", storeys=4, age_class="e")
    assert block[cols.FUNCTION] == "31001_1010"
    assert block[cols.CONSTRUCTION_CLASS] == "E"
    assert block[cols.BUILDING_TYPE] == block[cols.LOAD_PROFILE] == "MFH"
    assert block[cols.HEAT_DEMAND] == pytest.approx(560.0 * est.age_classes()["E"]["waerme_mfh_kwh_m2a"])


def test_a_house_given_as_efh_or_mfh():
    small = est.estimate_building(50.0, building_type="mfh")
    assert small[cols.BUILDING_TYPE] == small[cols.LOAD_PROFILE] == "MFH"
    assert small[cols.HEAT_DEMAND] == pytest.approx(70.0 * est.age_classes()["L"]["waerme_mfh_kwh_m2a"])
    large = est.estimate_building(200.0, storeys=4, building_type="EFH")
    assert large[cols.BUILDING_TYPE] == large[cols.LOAD_PROFILE] == "EFH"
    assert est.house_functions() == {"1000", "1010"}


def test_other_functions_use_their_own_demand_and_profile():
    office = est.estimate_building(300.0, function="2020", storeys=3, building_type="EFH")  # no house: ignored
    info = est.building_functions()["2020"]
    assert office[cols.BUILDING_TYPE] == est.NON_RESIDENTIAL
    assert office[cols.LOAD_PROFILE] == info["Lastprofil"]
    assert office[cols.FULL_LOAD_HOURS] == info["Vlh"]
    assert office[cols.HEAT_DEMAND] == pytest.approx(630.0 * info["WVBRpEBF"])


def test_given_values_replace_the_estimate():
    house = est.estimate_building(100.0, floor_area=200.0, load_profile="MFH", full_load_hours=2000)
    assert house[cols.FLOOR_AREA] == 200.0
    assert house[cols.BUILDING_TYPE] == "MFH"
    assert house[cols.HEAT_DEMAND] == pytest.approx(200.0 * est.age_classes()["L"]["waerme_mfh_kwh_m2a"])
    assert house[cols.THERMAL_POWER] == pytest.approx(house[cols.HEAT_DEMAND] / 2000)


def test_a_given_heat_demand_has_no_calculated_one():
    house = est.estimate_building(100.0, heat_demand=32000.0)
    assert house[cols.HEAT_DEMAND] == 32000.0
    assert cols.HEAT_DEMAND_CALCULATED not in house
    assert house[cols.THERMAL_POWER] == pytest.approx(20.0)


@pytest.mark.parametrize("basis", ["calculated", "dataset"])
def test_the_estimate_is_a_building_for_the_pipeline(basis):
    rows = [
        {cols.BUILDING_ID: 0, cols.CONNECT: 1, **est.estimate_building(100.0)},
        {cols.BUILDING_ID: 1, cols.CONNECT: 1, **est.estimate_building(100.0, heat_demand=5000.0)},
    ]
    buildings = gpd.GeoDataFrame(rows, geometry=[box(0, 0, 10, 10), box(20, 0, 30, 10)], crs="EPSG:25832")
    BuildingsSchema.validate(buildings)
    adjusted = _apply_heat_demand_basis(buildings, basis)
    assert adjusted[cols.HEAT_DEMAND].tolist() == pytest.approx([rows[0][cols.HEAT_DEMAND], 5000.0])


@pytest.mark.parametrize(
    "kwargs",
    [
        {"function": "9999"},
        {"function": "Wohnhaus"},
        {"function": "1311"},  # no load profile
        {"age_class": "Z"},
        {"building_type": "NWG"},
        {"storeys": 0},
        {"floor_area": -1.0},
        {"load_profile": "XYZ"},
        {"full_load_hours": 0},
        {"heat_demand": -1.0},
    ],
)
def test_unusable_input_is_an_error(kwargs):
    with pytest.raises(ValueError):
        est.estimate_building(100.0, **kwargs)


def test_a_footprint_is_needed():
    with pytest.raises(ValueError):
        est.estimate_building(0.0)
