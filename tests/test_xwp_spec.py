"""The vendored XWaermeplan specification validates offline (phase 0).

Checks that src/fheat_core/xwp/spec/0.9.6 is complete: the XSD and everything
it imports resolve through the XML catalog without network access, the
reference plan excerpts in tests/fixtures/xwp are valid against it, and the
JSON schema resolves through catalog.json. See docs/xwaermeplan/kodierung.md.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

etree = pytest.importorskip("lxml.etree")

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "src" / "fheat_core" / "xwp" / "spec" / "0.9.6"
FIXTURES = ROOT / "tests" / "fixtures" / "xwp"
XWP_NS = "http://www.xwaermeplan.de/0/9/6"


@pytest.fixture(scope="module")
def xsd_schema():
    from fheat_core.xwp.specfiles import xsd_schema

    return xsd_schema("0.9.6")


def test_xsd_is_version_0_9_6():
    root = etree.parse(str(SPEC / "xsd" / "waermeplan.xsd")).getroot()
    assert root.get("targetNamespace") == XWP_NS
    assert root.get("version") == "0.9.6"


@pytest.mark.parametrize("name", sorted(p.name for p in FIXTURES.glob("*.gml")))
def test_reference_excerpt_is_valid_gml(xsd_schema, name):
    doc = etree.parse(str(FIXTURES / name), etree.XMLParser(no_network=True))
    assert xsd_schema.validate(doc), str(xsd_schema.error_log.last_error)


def test_gml_and_json_excerpts_hold_the_same_features():
    for gml in FIXTURES.glob("*_xmas_auszug.gml"):
        doc = etree.parse(str(gml))
        ids = {
            el.text
            for el in doc.iter("{http://www.opengis.net/gml/3.2}identifier")
            if el.get("codeSpace") == "urn:uuid"
        }
        data = json.loads(gml.with_suffix(".json").read_text(encoding="utf-8"))
        assert ids == {f["id"] for f in data["features"]}


@pytest.fixture(scope="module")
def json_registry():
    pytest.importorskip("jsonschema")
    from fheat_core.xwp.specfiles import json_registry

    return json_registry("0.9.6")


def _validator(json_registry, feature_type):
    from jsonschema import Draft202012Validator

    registry, base = json_registry
    return Draft202012Validator({"$ref": f"{base}#{feature_type}"}, registry=registry)


def test_schema_conformant_feature_is_valid(json_registry):
    """The form fixed in kodierung.md: plain numbers, link objects, UUID id."""
    feature = {
        "type": "Feature",
        "id": "da2ccadc-8e3f-4ede-b6b5-6e64de551205",
        "featureType": "WP_Waermelinie",
        "time": None,
        "place": {"type": "MultiLineString", "coordinates": [[[332288.068, 5715935.097], [332287.844, 5715927.035]]]},
        "geometry": {"type": "MultiLineString", "coordinates": [[[6.5799991, 51.5695116], [6.5799997, 51.5694391]]]},
        "properties": {
            "gehoertZuBereich": {"href": "#1ed3e4dc-32ad-4b54-8be5-df953493469f", "rel": "related"},
            "waermeMenge": 22.23,
            "waermelinienDichte": 0.16,
            "laenge": 142.0,
        },
    }
    errors = list(_validator(json_registry, "WP_Waermelinie").iter_errors(feature))
    assert errors == []


def test_xplan_tools_style_feature_is_invalid(json_registry):
    """Finding J1 in abgleich.md: the XMAS reference plans do not follow the schema."""
    data = json.loads((FIXTURES / "rheinberg_xmas_auszug.json").read_text(encoding="utf-8"))
    line = next(f for f in data["features"] if f["featureType"] == "WP_Waermelinie")
    messages = [e.message for e in _validator(json_registry, "WP_Waermelinie").iter_errors(line)]
    assert any("is not of type 'object'" in m for m in messages)  # bare UUID instead of a link
    assert any("is not of type 'number'" in m for m in messages)  # {value, uom} instead of a number
