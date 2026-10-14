"""XWaermeplan JSON-FG writer (phase 3): every class is written valid against the official schema."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

pytest.importorskip("jsonschema")

from fheat_core.xwp.encode.jsonfg import CONFORMS_TO, to_jsonfg, validate_jsonfg, write_jsonfg  # noqa: E402
from fheat_core.xwp.model import v0_9_6 as m  # noqa: E402
from fheat_core.xwp.specfiles import spec_dir  # noqa: E402
from tests.xwp_synth import X0, Y0, document  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "xwp"
DEFS = json.loads((spec_dir("0.9.6") / "json" / "features.json").read_text(encoding="utf-8"))["$defs"]
VARIABLE = [n for n in m.FEATURE_TYPES if m.CLASSES[n].__xwp__.geometry_attr
            and m.CLASSES[n].__xwp__.geometry_attr.type == "Geometry"]


def schema_properties(name: str) -> set[str]:
    """Property names the schema defines for a feature type, including inherited ones."""
    names: set[str] = set()
    stack = [DEFS[name]]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            ref = node.get("$ref", "")
            if ref.startswith("#") and ref[1:] in DEFS:
                stack.append(DEFS[ref[1:]])
            inner = node.get("properties", {}).get("properties", {})
            if isinstance(inner, dict) and isinstance(inner.get("properties"), dict):
                names |= set(inner["properties"])
            stack.extend(node.get("allOf", []))
    return names


def test_model_and_json_schema_define_the_same_properties():
    for name in m.FEATURE_TYPES:
        info = m.CLASSES[name].__xwp__
        assert {a.name for a in info.attrs if a is not info.geometry_attr} == schema_properties(name), name


def _feature(data, feature_id):
    return next(f for f in data["features"] if f["id"] == feature_id)


# --------------------------------------------------------------------------
# completeness


@pytest.mark.parametrize("maximal", [False, True], ids=["minimal", "maximal"])
@pytest.mark.parametrize("feature_type", m.FEATURE_TYPES)
def test_every_feature_type_is_schema_valid(feature_type, maximal):
    doc, obj, _ = document(m, feature_type, maximal)
    data = to_jsonfg(doc)
    assert validate_jsonfg(data) == []
    written = _feature(data, obj.id)
    assert written["featureType"] == feature_type
    assert set(written["properties"]) <= schema_properties(feature_type)
    if maximal:
        info = type(obj).__xwp__
        expected = {a.name for a in info.attrs if a is not info.geometry_attr}
        assert set(written["properties"]) == expected


@pytest.mark.parametrize("feature_type", VARIABLE)
def test_variable_geometry_as_points(feature_type):
    for maximal in (False, True):
        doc, obj, _ = document(m, feature_type, maximal, variable_as="point")
        data = to_jsonfg(doc)
        assert validate_jsonfg(data) == []
        assert _feature(data, obj.id)["place"]["type"] == "MultiPoint"


def test_data_types_use_schema_property_names():
    doc, obj, _ = document(m, "WP_Plan", True)
    props = _feature(to_jsonfg(doc), obj.id)["properties"]
    assert set(props["planungsverantwortlicheStelle"]) <= set(
        DEFS["WP_Gemeinde"]["properties"]
    )


# --------------------------------------------------------------------------
# encoding rules (kodierung.md, 4.)


def test_encoding_follows_the_schema_not_the_reference_plans():
    doc, line, _ = document(m, "WP_Waermelinie", False)
    line.waermeMenge, line.laenge = 22.23, 142
    data = to_jsonfg(doc)
    assert data["conformsTo"] == CONFORMS_TO
    assert data["coordRefSys"] == "http://www.opengis.net/def/crs/EPSG/0/25832"
    f = _feature(data, line.id)
    assert str(uuid.UUID(f["id"])) == f["id"]
    assert f["time"] is None
    assert f["properties"]["waermeMenge"] == 22.23 and f["properties"]["laenge"] == 142.0  # plain numbers
    bereich = doc.of_type("WP_Bereich")[0]
    assert f["properties"]["gehoertZuBereich"] == {"href": f"#{bereich.id}", "rel": "related"}
    assert "position" not in f["properties"]


def test_place_in_utm_and_geometry_in_wgs84():
    doc, line, _ = document(m, "WP_Waermelinie", False)
    f = _feature(to_jsonfg(doc), line.id)
    assert f["place"]["type"] == f["geometry"]["type"] == "MultiLineString"
    x, y = f["place"]["coordinates"][0][0]
    assert (x, y) == (X0, Y0)
    lon, lat = f["geometry"]["coordinates"][0][0]
    assert 5.5 < lon < 10 and 50 < lat < 53  # NRW
    assert len(str(lon).split(".")[1]) <= 7


def test_plan_lists_and_enums():
    doc, plan, _ = document(m, "WP_Plan", True)
    props = _feature(to_jsonfg(doc), plan.id)["properties"]
    assert isinstance(props["bereich"], list) and props["bereich"][0]["rel"] == "related"
    assert props["verfahrensart"] in {e.code for e in m.WP_VerfahrenArt}
    assert isinstance(props["technischePlanerstellung"], list)


def test_features_without_geometry():
    doc, obj, _ = document(m, "WP_Massnahme", False)
    f = _feature(to_jsonfg(doc), obj.id)
    assert f["place"] is None and f["geometry"] is None


def test_same_features_and_order_as_gml():
    etree = pytest.importorskip("lxml.etree")
    from fheat_core.xwp.encode.gml import to_gml

    doc, _, _ = document(m, "WP_GebaeudeBaublock", True)
    root = to_gml(doc).getroot()
    gml_ids = [el.text for el in root.iter(etree.QName("http://www.opengis.net/gml/3.2", "identifier").text)]
    assert gml_ids == [f["id"] for f in to_jsonfg(doc)["features"]]


def test_write_is_deterministic_and_readable(tmp_path):
    doc, _, _ = document(m, "WP_Waermelinie", True)
    a = write_jsonfg(doc, tmp_path / "a.json").read_bytes()
    b = write_jsonfg(doc, tmp_path / "b.json").read_bytes()
    assert a == b
    assert validate_jsonfg(tmp_path / "a.json") == []
    assert validate_jsonfg(str(tmp_path / "a.json")) == []
    assert json.loads(write_jsonfg(doc, tmp_path / "c.json", indent=2).read_text(encoding="utf-8")) == json.loads(a)


# --------------------------------------------------------------------------
# validate_jsonfg


def test_reference_plan_encoding_is_rejected():
    """Finding J1: XPlan-Tools writes {value, uom} and bare UUIDs."""
    messages = validate_jsonfg(FIXTURES / "rheinberg_xmas_auszug.json")
    assert any("is not of type 'number'" in msg for msg in messages)
    assert any("is not of type 'object'" in msg for msg in messages)


def test_validation_checks_each_feature_against_its_type():
    doc, line, _ = document(m, "WP_Waermelinie", True)
    data = to_jsonfg(doc)
    f = _feature(data, line.id)
    f["properties"]["laenge"] = {"value": 1.0, "uom": "m"}
    del f["properties"]["gehoertZuBereich"]
    messages = validate_jsonfg(data)
    assert any("laenge" in msg and "number" in msg for msg in messages)
    assert any("'gehoertZuBereich' is a required property" in msg for msg in messages)
    data["features"].append({"type": "Feature", "featureType": "WP_Gibtsnicht", "properties": {}})
    assert any("unbekannte Objektart" in msg for msg in validate_jsonfg(data))
