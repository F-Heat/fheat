"""The generated XWaermeplan model (phase 1): generator, completeness, validate()."""
from __future__ import annotations

import dataclasses
import datetime
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from shapely.geometry import LineString, MultiLineString, Point, Polygon

from fheat_core.xwp.model import Issue, Measure, Ref, validate
from fheat_core.xwp.model import v0_9_6 as m
from fheat_core.xwp.model.base import XwpFeature

ROOT = Path(__file__).resolve().parents[1]
MODEL_JSON = ROOT / "docs" / "xwaermeplan" / "xwp_0.9.6_modell.json"
BEREICH = "1ed3e4dc-32ad-4b54-8be5-df953493469f"


@pytest.fixture(scope="module")
def reference():
    return json.loads(MODEL_JSON.read_text(encoding="utf-8"))


def _codes(issues: list[Issue]) -> list[tuple[str, str]]:
    return [(i.path, i.code) for i in issues]


# --------------------------------------------------------------------------
# generator


def test_generator_reproduces_the_checked_in_module():
    pytest.importorskip("lxml")
    spec = importlib.util.spec_from_file_location("gen_xwp_model", ROOT / "scripts" / "gen_xwp_model.py")
    gen = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = gen  # its dataclasses look the module up
    try:
        spec.loader.exec_module(gen)
    finally:
        del sys.modules[spec.name]
    expected = gen.module_path().read_text(encoding="utf-8")
    assert gen.generate() == expected, "v0_9_6.py is out of date; run scripts/gen_xwp_model.py"


# --------------------------------------------------------------------------
# completeness against the model export


def test_same_classes_and_enums_as_the_model_export(reference):
    assert set(m.CLASSES) == set(reference["classes"])
    assert set(m.ENUMS) == set(reference["enums"])
    assert m.VERSION == "0.9.6"
    assert m.NAMESPACE == "http://www.xwaermeplan.de/0/9/6"


def test_attributes_match_the_model_export(reference):
    for name, cls in m.CLASSES.items():
        info = cls.__xwp__
        ref = reference["classes"][name]
        assert info.abstract == ref["abstract"], name
        assert info.stereotype == ref["stereotype"], name
        expected = [a for a in ref["attrs"] if a["name"] != "id" and (name, a["name"]) != ("WP_Objekt", "uuid")]
        assert [a.name for a in info.own_attrs] == [a["name"] for a in expected], name
        for a, r in zip(info.own_attrs, expected):
            assert a.multiplicity == r["mult"], f"{name}.{a.name}"
            assert a.uom == r["uom"], f"{name}.{a.name}"


def test_enum_codes_match_the_model_export(reference):
    for name, enum_cls in m.ENUMS.items():
        assert [e.code for e in enum_cls] == [v["code"] for v in reference["enums"][name]["values"]], name
        assert all(e.label for e in enum_cls), name


def test_inherited_attributes_come_first():
    names = [a.name for a in m.WP_Waermenetz.__xwp__.attrs]
    assert names[:5] == ["aufschrift", "refTextInhalt", "refMassnahme", "gehoertZuBereich", "position"]
    assert m.WP_Waermenetz.__xwp__.ancestors == ("WP_ThermischeNetze", "WP_Flaechenobjekt", "WP_Objekt")


def test_dataclass_fields_follow_the_metadata():
    for cls in m.CLASSES.values():
        fields = [f.name for f in dataclasses.fields(cls) if f.name != "id"]
        assert fields == [a.name for a in cls.__xwp__.attrs], cls.__name__
        assert issubclass(cls, XwpFeature) == (cls.__xwp__.stereotype == "FeatureType")


def test_reference_targets_and_reverse_roles_are_consistent():
    for cls in m.CLASSES.values():
        for a in cls.__xwp__.own_attrs:
            if a.kind == "ref":
                assert a.type in m.CLASSES, a
                if a.reverse:
                    back = m.CLASSES[a.type].__xwp__.attr(a.reverse)
                    assert back.kind == "ref" and m.CLASSES[cls.__name__].__xwp__.is_a(back.type), a
            elif a.kind == "datatype":
                assert m.CLASSES[a.type].__xwp__.stereotype == "DataType", a
            elif a.kind == "enum":
                assert a.type in m.ENUMS, a


def test_concrete_feature_types():
    assert len(m.FEATURE_TYPES) == 29
    assert "WP_Waermenetz" in m.FEATURE_TYPES and "WP_Objekt" not in m.FEATURE_TYPES
    assert m.WP_Waermenetz.__xwp__.geometry_attr.type == "MultiSurface"  # an area in 0.9.6
    assert m.WP_Waermelinie.__xwp__.geometry_attr.type == "MultiCurve"
    assert m.WP_Grossverbraucher.__xwp__.geometry_attr.type == "Geometry"
    assert m.WP_Plan.__xwp__.geometry_attr.name == "raeumlicherGeltungsbereich"


def test_enums_are_codes_with_labels():
    assert m.WP_Status("1000") is m.WP_Status.Bestehend
    assert str(m.WP_Status.Bestehend) == "1000" and m.WP_Status.Bestehend == "1000"
    assert m.WP_Stuetzjahr.J2030.code == "1000"
    assert m.WP_Baualtersklasse.unbekannt.label == "unbekannt"


# --------------------------------------------------------------------------
# validate()


def _line(**kw):
    defaults = dict(
        gehoertZuBereich=Ref(BEREICH, "WP_Bereich"),
        position=MultiLineString([[(0, 0), (10, 0)]]),
        waermeMenge=12.5,
        laenge=10.0,
    )
    return m.WP_Waermelinie(**{**defaults, **kw})


def test_minimal_valid_feature_has_no_issues():
    assert validate(_line()) == []
    assert validate(_line(position=LineString([(0, 0), (1, 1)]), waermeMenge=Measure(1.0, "MWh/a"))) == []


def test_missing_required_attributes():
    issues = validate(m.WP_Waermelinie())
    assert ("WP_Waermelinie.gehoertZuBereich", "missing") in _codes(issues)
    assert ("WP_Waermelinie.position", "missing") in _codes(issues)


def test_measures_check_type_and_unit():
    assert _codes(validate(_line(waermeMenge=Measure(1.0, "kWh/a")))) == [("WP_Waermelinie.waermeMenge", "uom")]
    assert _codes(validate(_line(waermeMenge="12"))) == [("WP_Waermelinie.waermeMenge", "type")]
    assert _codes(validate(_line(waermeMenge=True))) == [("WP_Waermelinie.waermeMenge", "type")]
    assert _codes(validate(_line(waermeMenge=float("nan")))) == [("WP_Waermelinie.waermeMenge", "type")]


def test_geometry_type_is_checked():
    assert _codes(validate(_line(position=Point(0, 0)))) == [("WP_Waermelinie.position", "geometry")]
    bow_tie = Polygon([(0, 0), (1, 1), (1, 0), (0, 1)])
    block = m.WP_GebaeudeBaublock(
        gehoertZuBereich=Ref(BEREICH), position=bow_tie,
        gebaeudetyp=m.WP_GebaeudeTyp.Reihenhaus, ueberwiegendBaujahr=m.WP_Baualtersklasse.J1970_1979,
    )
    [issue] = validate(block)
    assert (issue.code, issue.severity) == ("geometry", "warning")


def test_references_check_the_target_class():
    other = m.WP_Massnahme(gehoertZuPlan=Ref.to(m.WP_Plan(name="x")))
    assert _codes(validate(_line(gehoertZuBereich=other))) == [("WP_Waermelinie.gehoertZuBereich", "ref")]
    assert _codes(validate(_line(gehoertZuBereich=Ref(BEREICH, "WP_Plan")))) == [("WP_Waermelinie.gehoertZuBereich", "ref")]
    assert _codes(validate(_line(gehoertZuBereich=Ref("nicht-uuid")))) == [("WP_Waermelinie.gehoertZuBereich", "ref")]
    assert validate(_line(gehoertZuBereich=Ref(BEREICH))) == []  # target unknown: accepted
    assert validate(_line(gehoertZuBereich=m.WP_Bereich(nummer=0, name="B", gehoertZuPlan=Ref(BEREICH)))) == []


def test_enums_must_be_members():
    net = m.WP_Waermenetz(
        gehoertZuBereich=Ref(BEREICH), position=Polygon([(0, 0), (1, 0), (1, 1)]),
        laenge=10.0, anzahlGebaeudeAnschluss=3, status="2000",
    )
    assert ("WP_Waermenetz.status", "enum") in _codes(validate(net))
    net.status = m.WP_Status.InPlanung_Genehmigt
    assert validate(net) == []


def test_multiplicity():
    big = m.WP_Grossverbraucher(
        gehoertZuBereich=Ref(BEREICH), position=Point(0, 0), status=m.WP_Status.Bestehend,
        energiebedarf=m.WP_EnergiebedarfArt.Waerme, energieeinsatz=m.WP_EnergieeinsatzArt.Thermisch,
        versorgungsmedium=[],
    )
    assert ("WP_Grossverbraucher.versorgungsmedium", "missing") in _codes(validate(big))  # 1..*
    big.versorgungsmedium = m.WP_Versorgungsmedium.Erdgas
    assert ("WP_Grossverbraucher.versorgungsmedium", "type") in _codes(validate(big))  # not a list
    big.versorgungsmedium = [m.WP_Versorgungsmedium.Erdgas]
    assert validate(big) == []
    big.status = [m.WP_Status.Bestehend]
    assert ("WP_Grossverbraucher.status", "multiplicity") in _codes(validate(big))


def test_bounded_multiplicity_above_one():
    bounded = [(c, a) for c in m.CLASSES.values() for a in c.__xwp__.own_attrs if a.max not in (None, 1)]
    assert bounded, "the XSD has attributes with maxOccurs=2"
    cls, attr = bounded[0]
    assert attr.many


def test_nested_data_types_are_validated():
    plan = m.WP_Plan(
        name="Wärmeplan Test",
        planungsverantwortlicheStelle=m.WP_Gemeinde(regionalSchluessel12="051700032032"),
        raeumlicherGeltungsbereich=Polygon([(0, 0), (1, 0), (1, 1)]),
    )
    codes = _codes(validate(plan))
    assert ("WP_Plan.planungsverantwortlicheStelle.name", "missing") in codes
    plan.planungsverantwortlicheStelle = m.WP_Bereich(nummer=0, name="x", gehoertZuPlan=Ref(BEREICH))
    assert ("WP_Plan.planungsverantwortlicheStelle", "type") in _codes(validate(plan))


def test_dates_and_booleans():
    plan = m.WP_Plan(
        name="Wärmeplan Test",
        planungsverantwortlicheStelle=m.WP_Gemeinde(name="Test"),
        raeumlicherGeltungsbereich=Polygon([(0, 0), (1, 0), (1, 1)]),
        beschlussDatum=datetime.date(2025, 12, 11),
        istFortschreibung=False,
    )
    assert [i for i in validate(plan) if i.code != "missing"] == []
    plan.beschlussDatum = "2025-12-11"
    plan.istFortschreibung = 0
    codes = _codes(validate(plan))
    assert ("WP_Plan.beschlussDatum", "type") in codes and ("WP_Plan.istFortschreibung", "type") in codes


def test_abstract_classes_and_ids():
    assert ("WP_Waermversorgungsgebiet", "abstract") in _codes(
        validate(m.WP_Waermversorgungsgebiet(gehoertZuBereich=Ref(BEREICH), position=Polygon([(0, 0), (1, 0), (1, 1)])))
    )
    assert ("WP_Waermelinie.id", "id") in _codes(validate(_line(id="WP_Waermelinie.1")))


def test_every_concrete_feature_type_can_be_built_and_validated():
    for name in m.FEATURE_TYPES:
        obj = m.CLASSES[name]()
        issues = validate(obj)
        assert {i.code for i in issues} <= {"missing"}, (name, issues)
