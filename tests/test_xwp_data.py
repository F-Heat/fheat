"""Data basis for XWaermeplan (phase 5): building type, construction year, plan configuration."""
from __future__ import annotations

import datetime
import json
from importlib.resources import files

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString, box

from fheat_core import columns as cols
from fheat_core.config import (
    XwpConfig,
    XwpExterneReferenz,
    XwpGemeinde,
    XwpPlanConfig,
    XwpSuitabilityConfig,
)
from fheat_core.schemas import BuildingsSchema
from fheat_core.xwp.mapping.building_type import assign_building_types, building_type_code, function_table
from fheat_core.xwp.model import current as m

CRS = "EPSG:25832"


# --------------------------------------------------------------------------
# building type table


def test_every_alkis_function_has_a_building_type():
    functions = json.loads(files("fheat_nrw.data").joinpath("building_functions.json").read_text(encoding="utf-8"))
    table = function_table()
    assert set(functions) == set(table)
    codes = {e.code for e in m.WP_GebaeudeTyp}
    assert set(table.values()) <= codes
    # residential sub-types come from the source's building type, never from the function table
    assert not {"10001", "10002", "10003", "10004"} & set(table.values())


@pytest.mark.parametrize("function, expected", [
    ("31001_1010", "1000"),   # Wohnhaus
    ("31001_1022", "1000"),   # Seniorenheim: residential after GEG § 3
    ("31001_1123", "9999"),   # Wohn- und Geschäftsgebäude: not clear
    ("31001_2020", "20001"),  # Bürogebäude
    ("31001_2054", "20002"),  # Laden
    ("31001_2071", "20003"),  # Hotel
    ("31001_3051", "20004"),  # Krankenhaus
    ("31001_3021", "20006"),  # Schule
    ("31001_3221", "20008"),  # Hallenbad
    ("31001_2143", "20009"),  # Lagerhalle
    ("31001_2111", "20010"),  # Fabrik
    ("31001_2724", "2000"),   # Stall
])
def test_function_table_examples(function, expected):
    assert building_type_code(function=function) == expected


def test_order_of_evidence():
    # the source's residential type wins over the function
    assert building_type_code("31001_1010", "EFH", "EFH") == "10001"
    assert building_type_code("31001_1010", "gmfh", "MFH") == "10004"
    assert building_type_code("31001_1010", "RH", None) == "10002"
    # NWG (or another non-residential type) defers to the function
    assert building_type_code("31001_2020", "NWG", "GMK") == "20001"
    # without function: load profile, but only the upper category
    assert building_type_code(None, None, "EFH") == "1000"
    assert building_type_code(None, None, "GHA") == "2000"
    assert building_type_code(pd.NA, float("nan"), None) == "9999"
    assert building_type_code("31001_0001", None, None) == "9999"  # unknown function


def test_assign_building_types_without_optional_columns():
    df = pd.DataFrame({cols.LOAD_PROFILE: ["EFH", "GKO", None]})
    assert assign_building_types(df).tolist() == ["1000", "2000", "9999"]


# --------------------------------------------------------------------------
# NRW and flex adapters


def _nrw_buildings(valid_from="1958-03-01"):
    from fheat_nrw.adapter.data_adapter import NRWDataAdapter
    from fheat_nrw.processing import process_buildings

    db, wg = NRWDataAdapter(source_coordinates=(52.0, 7.0), city_name="X")._load_building_info()
    raw = gpd.GeoDataFrame(
        {
            "citygml_fu": ["31001_1010", "31001_2020"],
            "GEBAEUDETY": ["EFH_1945", "0"],
            "WG_NWG": ["WG", "NWG"],
            "Flurstueck": ["1", "2"],
            "Fortschrei": ["1", "1"],
            "NF": [100.0, 400.0],
            "RW_WW": [10000.0, 30000.0],
        },
        geometry=[box(0, 0, 10, 10), box(20, 0, 40, 20)],
        crs=CRS,
    )
    parcels = gpd.GeoDataFrame(
        {"nationalCadastralReference": ["1", "2"], "validFrom": [valid_from, "2011-05-02"]},
        geometry=[box(-5, -5, 15, 15), box(18, -2, 42, 22)],
        crs=CRS,
    )
    return process_buildings(raw, parcels, db, wg, "RW_WW")


def test_nrw_keeps_parcel_year_and_derives_building_type():
    out = _nrw_buildings()
    BuildingsSchema.validate(out)
    assert out[cols.PARCEL_YEAR].tolist() == [1958, 2011]
    assert out[cols.CONSTRUCTION_CLASS].tolist() == ["E", "J"]  # BAK unchanged
    assert out[cols.AGE].tolist()[0] == "1945"  # LANUV age stays as it was
    assert out[cols.XWP_BUILDING_TYPE].tolist() == ["10001", "20001"]
    assert cols.CONSTRUCTION_YEAR not in out.columns  # NRW does not know the true year


def test_nrw_new_columns_have_german_labels():
    shown = cols.to_display(_nrw_buildings())
    assert {"Jahr_Flurstueck", "Gebaeudetyp_XWP"} <= set(shown.columns)


def test_flex_maps_the_construction_year(tmp_path):
    from fheat_flex.adapter.data_adapter import FlexDataAdapter

    buildings = gpd.GeoDataFrame(
        {"wbedarf": [10000.0, 20000.0], "bj": ["1975", None], "geometry": [box(0, 0, 10, 10), box(20, 0, 30, 10)]},
        crs=CRS,
    )
    path = tmp_path / "b.gpkg"
    buildings.to_file(path, driver="GPKG")
    streets = gpd.GeoDataFrame(geometry=[LineString([(0, -5), (40, -5)])], crs=CRS)
    streets.to_file(tmp_path / "s.gpkg", driver="GPKG")
    adapter = FlexDataAdapter(
        buildings_path=path, streets_path=tmp_path / "s.gpkg", parcels_path=path,
        column_map={"wbedarf": cols.HEAT_DEMAND, "bj": cols.CONSTRUCTION_YEAR},
    )
    out = adapter.fetch_buildings()
    assert str(out[cols.CONSTRUCTION_YEAR].dtype) == "Int64"
    assert out[cols.CONSTRUCTION_YEAR].iloc[0] == 1975 and pd.isna(out[cols.CONSTRUCTION_YEAR].iloc[1])


# --------------------------------------------------------------------------
# configuration


def _plan(**kw):
    return XwpPlanConfig(name="Wärmeplan Steinfurt", gemeinde=XwpGemeinde("Steinfurt", "055660032032"), **kw)


def test_plan_config_defaults():
    c = XwpConfig(plan=_plan(beschluss_datum=datetime.date(2026, 6, 30)))
    assert c.plan.verfahrensart == "1000" and c.plan.zieljahr == 2045
    assert c.formats == ("gml", "jsonfg", "gpkg")
    assert c.privacy_min_buildings == 5
    assert c.suitability.heat_density == (415.0, 175.0, 70.0)


@pytest.mark.parametrize("kwargs, message", [
    (dict(verfahrensart="5000"), "WP_VerfahrenArt"),
    (dict(gesetzliche_grundlage="x"), "WP_GesetzlicheGrundlage"),
    (dict(zieljahr=1800), "plausible year"),
    (dict(basisjahr=2050, zieljahr=2045), "basisjahr"),
    (dict(aufstellungsbeschluss_datum=datetime.date(2027, 1, 1), beschluss_datum=datetime.date(2026, 1, 1)),
     "aufstellungsbeschluss_datum"),
    (dict(extra={"gibtEsNicht": 1}), "no attribute"),
    (dict(extra={"zieljahr": "2040"}), "set by a field"),
])
def test_plan_config_rejects(kwargs, message):
    with pytest.raises(ValueError, match=message):
        _plan(**kwargs)


def test_plan_config_extra_and_references():
    plan = _plan(extra={"nummer": "WP-1", "istFortschreibung": False},
                 externe_referenzen=[XwpExterneReferenz("Wärmeplan", "https://example.org/wp.pdf", art="1000")])
    assert plan.extra["nummer"] == "WP-1"
    with pytest.raises(ValueError, match="WP_ExterneReferenzTyp"):
        XwpExterneReferenz("x", "https://example.org", art="0")


def test_gemeinde_keys_are_checked():
    with pytest.raises(ValueError, match="12 digits"):
        XwpGemeinde("Steinfurt", "05566")
    with pytest.raises(ValueError, match="9 digits"):
        XwpGemeinde("Steinfurt", regional_schluessel9="12345678X")


@pytest.mark.parametrize("kwargs, message", [
    (dict(formats=("gml", "shp")), "formats"),
    (dict(formats=()), "formats"),
    (dict(privacy_min_buildings=0), "privacy_min_buildings"),
    (dict(precision=9), "precision"),
    (dict(construction_year_sources=("lanuv",)), "construction_year_sources"),
])
def test_xwp_config_rejects(kwargs, message):
    with pytest.raises(ValueError, match=message):
        XwpConfig(plan=_plan(), **kwargs)


def test_suitability_bounds_must_descend():
    with pytest.raises(ValueError, match="descending"):
        XwpSuitabilityConfig(heat_density=(70.0, 175.0, 415.0))
    assert XwpSuitabilityConfig(heat_line_density=[2.0, 1.0, 0.0]).heat_line_density == (2.0, 1.0, 0.0)
