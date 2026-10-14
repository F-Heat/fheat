"""XWaermeplan GML writer (phase 2): every class can be written and is XSD-valid."""
from __future__ import annotations

from pathlib import Path

import pytest

etree = pytest.importorskip("lxml.etree")

from shapely.geometry import LinearRing, Polygon  # noqa: E402

from fheat_core.xwp.document import XwpPlanDocument, XwpValidationError  # noqa: E402
from fheat_core.xwp.encode.gml import to_gml, validate_gml, write_gml  # noqa: E402
from fheat_core.xwp.model import Ref  # noqa: E402
from fheat_core.xwp.model import v0_9_6 as m  # noqa: E402
from tests.xwp_synth import document, square  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "xwp"
NS = {"xwp": m.NAMESPACE, "gml": "http://www.opengis.net/gml/3.2", "xlink": "http://www.w3.org/1999/xlink",
      "sf": "http://www.opengis.net/ogcapi-features-1/1.0/sf"}
VARIABLE = [n for n in m.FEATURE_TYPES if m.CLASSES[n].__xwp__.geometry_attr
            and m.CLASSES[n].__xwp__.geometry_attr.type == "Geometry"]


# --------------------------------------------------------------------------
# completeness: every concrete class, minimal and maximal


@pytest.mark.parametrize("maximal", [False, True], ids=["minimal", "maximal"])
@pytest.mark.parametrize("feature_type", m.FEATURE_TYPES)
def test_every_feature_type_is_written_xsd_valid(feature_type, maximal):
    doc, obj, _ = document(m, feature_type, maximal)
    assert doc.errors() == []
    tree = to_gml(doc)
    assert validate_gml(tree) == []
    written = tree.getroot().find(f".//xwp:{feature_type}[@gml:id='GML_{obj.id}']", NS)
    assert written is not None
    if maximal:  # every attribute of the class appears
        names = {etree.QName(ch).localname for ch in written}
        assert {a.name for a in type(obj).__xwp__.attrs} <= names


@pytest.mark.parametrize("feature_type", VARIABLE)
def test_variable_geometry_as_points(feature_type):
    for maximal in (False, True):
        doc, _, _ = document(m, feature_type, maximal, variable_as="point")
        assert validate_gml(to_gml(doc)) == []


def test_maximal_objects_reach_every_data_type():
    seen: set[str] = set()
    for name in m.FEATURE_TYPES:
        seen |= document(m, name, True)[2].datatypes_seen
    datatypes = {n for n, c in m.CLASSES.items() if c.__xwp__.stereotype == "DataType"}
    assert seen == datatypes


# --------------------------------------------------------------------------
# structure


def _plan_with_line():
    doc, _, _ = document(m, "WP_Waermelinie", False)
    return doc


def test_structure_follows_kodierung():
    root = to_gml(_plan_with_line()).getroot()
    assert etree.QName(root).localname == "FeatureCollection" and root.nsmap[None] == m.NAMESPACE
    members = root.findall("sf:featureMember", NS)
    names = [etree.QName(mb[0]).localname for mb in members]
    assert names[:2] == ["WP_Plan", "WP_Bereich"] and names[-1] == "WP_Waermelinie"
    line = members[-1][0]
    assert etree.QName(line[0]).localname == "identifier" and line[0].get("codeSpace") == "urn:uuid"
    assert line.get(f"{{{NS['gml']}}}id") == "GML_" + line[0].text
    bereich = line.find("xwp:gehoertZuBereich", NS)
    assert bereich.get(f"{{{NS['xlink']}}}href").startswith("#GML_")
    multi = line.find("xwp:position/gml:MultiCurve", NS)
    assert multi.get("srsName") == "EPSG:25832"
    assert line.find("xwp:laenge", NS) is None  # optional and unset
    assert line.find("xwp:waermeMenge", NS) is None


def test_measures_carry_the_model_unit():
    doc = _plan_with_line()
    line = doc.of_type("WP_Waermelinie")[0]
    line.waermeMenge, line.waermelinienDichte, line.laenge = 22.23, 0.16, 142
    el = to_gml(doc).getroot().find(".//xwp:WP_Waermelinie", NS)
    got = {etree.QName(c).localname: (c.get("uom"), c.text) for c in el if c.get("uom")}
    assert got == {"waermeMenge": ("MWh/a", "22.23"), "waermelinienDichte": ("MWh/(m*a)", "0.16"),
                   "laenge": ("m", "142.0")}


def test_element_order_matches_reference_plan():
    """Same attributes as the Rheinberg reference line -> same element sequence."""
    ref = etree.parse(str(FIXTURES / "rheinberg_xmas_auszug.gml"))
    ref_line = ref.find(".//xwp:WP_Waermelinie", NS)
    doc = _plan_with_line()
    line = doc.of_type("WP_Waermelinie")[0]
    line.waermeMenge, line.waermelinienDichte, line.laenge = 1.0, 1.0, 1.0
    ours = to_gml(doc).getroot().find(".//xwp:WP_Waermelinie", NS)

    def skeleton(el):
        return [(etree.QName(e).localname, sorted(etree.QName(k).localname for k in e.attrib)) for e in el.iter()
                if not isinstance(e, etree._Comment)]

    assert skeleton(ours) == skeleton(ref_line)


def test_rings_are_oriented_and_rounded():
    doc = _plan_with_line()
    plan = doc.of_type("WP_Plan")[0]
    hole = list(square(400_005.0, 5_760_005.0, 2).exterior.coords)[::-1]  # wrong orientation on purpose
    plan.raeumlicherGeltungsbereich = Polygon(
        list(square(400_000.12345, 5_760_000.0, 20).exterior.coords)[::-1], [hole]
    )
    root = to_gml(doc).getroot()
    poly = root.find(".//xwp:raeumlicherGeltungsbereich//gml:Polygon", NS)
    ext = poly.find("gml:exterior//gml:posList", NS).text.split()
    inn = poly.find("gml:interior//gml:posList", NS).text.split()
    assert ext[0] == "400000.123"

    def ring(t):
        return LinearRing(list(zip(map(float, t[0::2]), map(float, t[1::2]))))

    assert ring(ext).is_ccw and not ring(inn).is_ccw
    assert validate_gml(root.getroottree()) == []


def test_output_is_deterministic(tmp_path):
    doc = _plan_with_line()
    a = write_gml(doc, tmp_path / "a.gml").read_bytes()
    b = write_gml(doc, tmp_path / "b.gml").read_bytes()
    assert a == b
    assert a.startswith(b"<?xml version='1.0' encoding='UTF-8'?>")


def test_invalid_documents_are_refused():
    doc = _plan_with_line()
    doc.of_type("WP_Waermelinie")[0].gehoertZuBereich = Ref("6f1c1b8e-0000-4000-8000-000000000000", "WP_Bereich")
    with pytest.raises(XwpValidationError, match="zeigt auf kein Objekt"):
        to_gml(doc)
    assert validate_gml(to_gml(doc, check=False)) == []  # the XSD itself does not see dangling links


def test_document_checks_reverse_references():
    doc = _plan_with_line()
    plan = doc.of_type("WP_Plan")[0]
    plan.bereich = []
    assert any("Gegenrichtung fehlt" in i.message for i in doc.errors())
    doc.link_reverse()
    assert doc.errors() == []
    doc.link_reverse()  # idempotent
    assert len(plan.bereich) == 1


def test_empty_document():
    with pytest.raises(XwpValidationError, match="keinen WP_Plan"):
        to_gml(XwpPlanDocument())


def test_validate_gml_reports_schema_errors():
    tree = to_gml(_plan_with_line())
    line = tree.getroot().find(".//xwp:WP_Waermelinie", NS)
    line.remove(line.find("xwp:gehoertZuBereich", NS))  # required element missing
    errors = validate_gml(tree)
    assert errors and "gehoertZuBereich" in errors[0]


def test_reference_plans_pass_validate_gml():
    for path in FIXTURES.glob("*.gml"):
        assert validate_gml(path) == [], path.name
