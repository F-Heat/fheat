"""The tables of the XWaermeplan export against the original of the XLeitstelle.

``tests/test_xwp_mapping.py`` compares the tables with the model xplan-tools
ships; this file compares them with the sources that model is generated from:
the XSD 0.9.6 for classes, multiplicities and code lists, and the feature
catalogue (Objektartenkatalog) for the units, which the XSD does not carry.
Needs neither xplan-tools nor GDAL, so it runs in the normal test matrix.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path

import pytest

from fheat_core.export.xwp import mapping
from fheat_core.export.xwp.config import XWPExportConfig

FIXTURES = Path(__file__).parent / "fixtures" / "xwp"
XSD = FIXTURES / "xsd-0.9.6" / "waermeplan.xsd"
UNITS = FIXTURES / "oak-0.9.6-einheiten.json"
XS = "{http://www.w3.org/2001/XMLSchema}"

#: git blobs of the sources named in tests/fixtures/xwp/README.md
XSD_BLOB = "7898e8bf809b427db4034e35820deba06c55dc6e"
CATALOGUE_BLOB = "874124ca62a76a4d42835e265438896936d6d66d"

#: XWPExportConfig field -> code list of its default
CONFIG_CODES = {
    "procedure": "WP_VerfahrenArt",
    "legal_basis": "WP_GesetzlicheGrundlage",
    "network_status": "WP_Status",
    "network_medium": "WP_Transportmedium",
    "supply_type": "WP_WaermeversorgungsgebietTyp",
}


@lru_cache(maxsize=None)
def schema() -> tuple[dict, dict]:
    """Complex types by name and the codes of every simple type of the XSD."""
    root = ET.parse(XSD).getroot()
    types = {t.get("name"): t for t in root.findall(f"{XS}complexType")}
    enums = {t.get("name"): {e.get("value") for e in t.iter(f"{XS}enumeration")}
             for t in root.findall(f"{XS}simpleType")}
    return types, enums


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


def set_by_builder(class_name: str) -> set[str]:
    """References ``builder.build_collection`` adds to the mappers' properties."""
    if class_name == "WP_Plan":
        return {"bereich"}
    if class_name == "WP_Bereich":
        return {"gehoertZuPlan"}
    return {"gehoertZuBereich"} & set(properties(class_name))


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


def test_every_code_list_names_its_property():
    assert set(mapping.CODE_LIST_PROPERTIES) == set(mapping.CODE_LISTS)


@pytest.mark.parametrize("code_list", sorted(mapping.CODE_LISTS))
def test_code_lists_equal_the_xsd_enumerations(code_list):
    _, enums = schema()
    assert set(mapping.CODE_LISTS[code_list]) == enums[f"{code_list}Type"]


@pytest.mark.parametrize("code_list", sorted(mapping.CODE_LIST_PROPERTIES))
def test_code_lists_are_the_type_of_their_property(code_list):
    class_name, prop = mapping.CODE_LIST_PROPERTIES[code_list]
    assert properties(class_name)[prop][1] == f"xwp:{code_list}Type"


@pytest.mark.parametrize("field, code_list", sorted(CONFIG_CODES.items()))
def test_config_defaults_are_codes_of_the_xsd(field, code_list):
    _, enums = schema()
    default = next(f.default for f in dataclasses.fields(XWPExportConfig) if f.name == field)
    assert default in enums[f"{code_list}Type"]


@pytest.mark.parametrize("class_name", sorted(mapping.WRITTEN_PROPERTIES))
def test_written_properties_exist_in_the_xsd(class_name):
    assert set(mapping.WRITTEN_PROPERTIES[class_name]) <= set(properties(class_name))


@pytest.mark.parametrize("class_name", sorted(mapping.WRITTEN_PROPERTIES))
def test_mandatory_properties_are_written(class_name):
    mandatory = {name for name, (min_occurs, _) in properties(class_name).items() if min_occurs >= 1}
    assert mandatory <= set(mapping.WRITTEN_PROPERTIES[class_name]) | set_by_builder(class_name)


@pytest.mark.parametrize("class_name, prop", sorted(mapping.DATA_TYPES))
def test_data_types_are_the_type_of_their_property(class_name, prop):
    assert properties(class_name)[prop][1] == f"xwp:{mapping.DATA_TYPES[(class_name, prop)]}PropertyType"


@pytest.mark.parametrize("class_name, prop", sorted(mapping.MEASURES))
def test_measures_are_measures_in_the_xsd(class_name, prop):
    assert properties(class_name)[prop][1] == "gml:MeasureType"


@pytest.mark.parametrize("class_name, prop", sorted(mapping.MEASURES))
def test_units_equal_the_feature_catalogue(class_name, prop):
    assert mapping.MEASURES[(class_name, prop)].uom == catalogue()["units"][class_name][prop]
