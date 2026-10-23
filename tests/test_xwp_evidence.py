"""The tables of the XWaermeplan export against the original of the XLeitstelle and against F|Heat.

``tests/test_xwp_mapping.py`` compares the tables with the model xplan-tools
ships; this file compares them with the sources that model is generated from:
the XSD 0.9.6 for classes, multiplicities and code lists, and the feature
catalogue (Objektartenkatalog) for the units, which the XSD does not carry.
It also checks that every source of an attribute exists on the F|Heat side,
so renaming a column or summary key fails here and not in the export, and
that every building function the NRW adapter knows has a building type.
Needs neither xplan-tools nor GDAL, so it runs in the normal test matrix.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import xml.etree.ElementTree as ET
from functools import lru_cache
from importlib.resources import files
from pathlib import Path

import pytest

from fheat_core.export.xwp import mapping
from fheat_core.export.xwp.config import XWPExportConfig
from fheat_core.export.xwp.mappers import RULES, NetworkResult
from fheat_core.schemas import RESULT_SUMMARY_SCHEMA, BuildingsSchema, PolygonsSchema, WLDSchema

FIXTURES = Path(__file__).parent / "fixtures" / "xwp"
XSD = FIXTURES / "xsd-0.9.6" / "waermeplan.xsd"
UNITS = FIXTURES / "oak-0.9.6-einheiten.json"
XS = "{http://www.w3.org/2001/XMLSchema}"

#: git blobs of the sources named in tests/fixtures/xwp/README.md
XSD_BLOB = "7898e8bf809b427db4034e35820deba06c55dc6e"
CATALOGUE_BLOB = "874124ca62a76a4d42835e265438896936d6d66d"

#: class -> F|Heat schema of the layer its rows come from (a building block: sums of its buildings)
LAYER_SCHEMAS = {
    mapping.HEAT_LINE: WLDSchema,
    mapping.SUPPLY_AREA_TARGET: PolygonsSchema,
    mapping.SUPPLY_AREA_INTERIM: PolygonsSchema,
    mapping.BUILDING_BLOCK: BuildingsSchema,
}
REFERENCES = {"plan", "area", "areas"}  # what builder.build_collection sets

ATTRIBUTES = sorted((c, n) for c, n, _ in mapping.attributes())


def written(predicate) -> list[tuple[str, str]]:
    """``(class, attribute)`` of every attribute for which ``predicate(attribute)`` holds."""
    return sorted((c, n) for c, n, a in mapping.attributes() if predicate(a))


@lru_cache(maxsize=None)
def schema() -> tuple[dict, dict]:
    """Complex types by name and the codes of every simple type of the XSD."""
    root = ET.parse(XSD).getroot()
    types = {t.get("name"): t for t in root.findall(f"{XS}complexType")}
    enums = {t.get("name"): {e.get("value") for e in t.iter(f"{XS}enumeration")}
             for t in root.findall(f"{XS}simpleType")}
    return types, enums


@lru_cache(maxsize=None)
def code_documentation(code_list: str) -> dict[str, str]:
    """``{code: documentation}`` of a code list of the XSD."""
    root = ET.parse(XSD).getroot()
    simple_type = next(t for t in root.findall(f"{XS}simpleType") if t.get("name") == f"{code_list}Type")
    return {e.get("value"): e.find(f"{XS}annotation/{XS}documentation").text.strip()
            for e in simple_type.iter(f"{XS}enumeration")}


@lru_cache(maxsize=None)
def properties(class_name: str) -> dict[str, tuple[int, str]]:
    """``{property: (minOccurs, type)}`` of a class with everything it inherits."""
    types, _ = schema()
    complex_type = types[f"{class_name}Type"]
    props = {}
    extension = complex_type.find(f"{XS}complexContent/{XS}extension")
    if extension is not None:
        base = extension.get("base").split(":")[-1]
        if base in types:  # stops at the GML base types
            props.update(properties(base.removesuffix("Type")))
    for element in complex_type.iter(f"{XS}element"):
        props[element.get("name")] = (int(element.get("minOccurs", "1")), element.get("type"))
    return props


def git_blob(path: Path) -> str:
    """Git object id of a text file as stored, i.e. with LF line endings (checkouts may have CRLF)."""
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


@lru_cache(maxsize=None)
def catalogue() -> dict:
    return json.loads(UNITS.read_text(encoding="utf-8"))


def test_fixtures_are_the_named_sources():
    assert git_blob(XSD) == XSD_BLOB
    assert catalogue()["source"]["git_blob"] == CATALOGUE_BLOB


@pytest.mark.parametrize("code_list", sorted(mapping.CODE_LISTS))
def test_code_lists_equal_the_xsd_enumerations(code_list):
    _, enums = schema()
    assert set(mapping.CODE_LISTS[code_list]) == enums[f"{code_list}Type"]


def test_every_code_list_is_written():
    assert {a.code_list for _, _, a in mapping.attributes() if a.code_list} == set(mapping.CODE_LISTS)


@pytest.mark.parametrize("class_name, prop", written(lambda a: a.code_list))
def test_code_lists_are_the_type_of_their_property(class_name, prop):
    code_list = mapping.CLASSES[class_name][prop].code_list
    assert properties(class_name)[prop][1] == f"xwp:{code_list}Type"


@pytest.mark.parametrize("field, code_list", sorted(mapping.CONFIG_CODE_LISTS.items()))
def test_config_defaults_are_codes_of_the_xsd(field, code_list):
    _, enums = schema()
    default = next(f.default for f in dataclasses.fields(XWPExportConfig) if f.name == field)
    assert default is None or default in enums[f"{code_list}Type"]


@pytest.mark.parametrize("class_name, prop", ATTRIBUTES)
def test_attributes_exist_in_the_xsd(class_name, prop):
    assert prop in properties(class_name)


@pytest.mark.parametrize("class_name", sorted(mapping.CLASSES))
def test_mandatory_attributes_are_written(class_name):
    mandatory = {name for name, (min_occurs, _) in properties(class_name).items() if min_occurs >= 1}
    assert mandatory <= set(mapping.CLASSES[class_name])


@pytest.mark.parametrize("class_name, prop", written(lambda a: a.source == "nested"))
def test_data_types_are_the_type_of_their_property(class_name, prop):
    data_type = mapping.CLASSES[class_name][prop].name
    assert properties(class_name)[prop][1] == f"xwp:{data_type}PropertyType"


@pytest.mark.parametrize("class_name, prop", written(lambda a: a.uom))
def test_measures_are_measures_in_the_xsd(class_name, prop):
    assert properties(class_name)[prop][1] == "gml:MeasureType"


@pytest.mark.parametrize("class_name, prop", written(lambda a: a.uom))
def test_units_equal_the_feature_catalogue(class_name, prop):
    assert mapping.CLASSES[class_name][prop].uom == catalogue()["units"][class_name][prop]


@pytest.mark.parametrize("condition", mapping.CONFORMITY, ids=lambda c: c.class_name)
def test_conformity_conditions_name_optional_written_attributes(condition):
    """A condition makes attributes mandatory that the XSD leaves optional, and the export can write them."""
    for name in condition.attributes:
        assert name in mapping.CLASSES[condition.class_name]
        assert properties(condition.class_name)[name][0] == 0


def test_codes_of_the_rules_are_codes_of_the_xsd():
    _, enums = schema()
    assert mapping.NO_STATEMENT in enums["WP_EignungsstufeType"]
    assert mapping.NO_STATEMENT_SUPPLY_TYPES <= enums["WP_WaermeversorgungsgebietTypType"]
    assert mapping.NO_STATEMENT_PROCEDURES | {mapping.SMALL_HEAT_PLANNING} <= enums["WP_VerfahrenArtType"]
    assert mapping.EXISTING in enums["WP_StatusType"]
    assert mapping.UNKNOWN in enums["WP_GebaeudeTypType"] & enums["WP_BaualtersklasseType"]
    assert {*mapping.FUNCTION_TYPES.values(), *mapping.BUILDING_TYPE_CODES.values()} <= enums["WP_GebaeudeTypType"]
    assert set(mapping.AGE_PERIODS.values()) <= enums["WP_BaualtersklasseType"]


def test_construction_periods_are_the_main_categories_of_the_xsd():
    """``mapping.PERIOD_YEARS`` holds the years the XSD gives the main categories of WP_Baualtersklasse."""
    def text(first, last):
        return f"bis {last}" if first is None else f"ab {first}" if last is None else f"{first} bis {last}"

    documentation = code_documentation("WP_Baualtersklasse")
    main = {code for code in documentation if len(code) == 4 and code != mapping.UNKNOWN}
    assert set(mapping.PERIOD_YEARS) == main
    for code, years in mapping.PERIOD_YEARS.items():
        assert documentation[code].removesuffix(" (Oberkategorie)") == text(*years)


def test_lanuv_age_classes_fall_into_the_category_with_most_of_their_years():
    """E15: a class across two categories gets the one with the larger part."""
    assert mapping.AGE_PERIODS == {
        "1900": "1000", "1945": "1000", "1960": "2000", "1970": "2000", "1980": "3000", "1985": "3000",
        "1995": "4000", "2000": "4000", "2005": "4000", "2010": "4000", "2015": "4000", "2022": "5000",
    }


def test_every_function_of_the_nrw_adapter_has_a_building_type():
    known = json.loads(files("fheat_nrw.data").joinpath("building_functions.json").read_text(encoding="utf-8"))
    assert set(mapping.FUNCTION_TYPES) == set(known)


@pytest.mark.parametrize("class_name, prop", ATTRIBUTES)
def test_sources_exist_in_fheat(class_name, prop):
    attribute = mapping.CLASSES[class_name][prop]
    if attribute.source == "column":
        layer = LAYER_SCHEMAS[class_name]
        assert attribute.name in {**layer.required_columns, **layer.optional_columns}
    elif attribute.source == "summary":
        assert attribute.name in (*RESULT_SUMMARY_SCHEMA.required_keys, *RESULT_SUMMARY_SCHEMA.optional_keys)
    elif attribute.source == "config":
        fields = {f.name for f in dataclasses.fields(XWPExportConfig)}
        assert attribute.name in fields or isinstance(getattr(XWPExportConfig, attribute.name, None), property)
    elif attribute.source == "network":
        assert attribute.name in {f.name for f in dataclasses.fields(NetworkResult)}
    elif attribute.source == "rule":
        assert attribute.name in RULES
    elif attribute.source == "nested":
        assert attribute.name in mapping.CLASSES
    elif attribute.source == "reference":
        assert attribute.name in REFERENCES
    else:
        assert attribute.source == "geometry"
