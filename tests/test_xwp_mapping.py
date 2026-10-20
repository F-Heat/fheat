"""The code and unit tables of the export against the model xplan-tools ships.

A new xplan-tools release that changes a code, a class or a unit makes these
tests fail instead of the export writing something else silently.
"""
from __future__ import annotations

import pytest

pytest.importorskip("xplan_tools")
pytestmark = pytest.mark.xwp

from fheat_core.export.xwp import builder, mapping  # noqa: E402

#: code list -> the property the export writes it to
USED_BY = {
    "WP_VerfahrenArt": ("WP_Plan", "verfahrensart"),
    "WP_GesetzlicheGrundlage": ("WP_Plan", "gesetzlicheGrundlage"),
    "WP_Status": ("WP_Waermenetz", "status"),
    "WP_Transportmedium": ("WP_Waermenetz", "medium"),
    "WP_Energietraeger": ("WP_EndenergieEnergietraeger", "energietraeger"),
    "WP_WaermeversorgungsgebietTyp": ("WP_WaermeversorgungsgebietZieljahr", "versorgungsart"),
    "WP_Eignungsstufe": ("WP_WaermeversorgungsgebietZieljahr", "eignungWaermenetz"),
    "WP_Stuetzjahr": ("WP_WaermeversorgungsgebietStuetzjahr", "stuetzjahr"),
}


@pytest.fixture(scope="module")
def schema():
    return builder.appschema()


def test_schema_version(schema):
    assert str(schema.full_version) == mapping.SCHEMA_VERSION
    assert str(schema.namespace_uri).rstrip("/") == mapping.NAMESPACE


def test_every_code_list_is_checked():
    assert set(USED_BY) == set(mapping.CODE_LISTS)


@pytest.mark.parametrize("code_list", sorted(USED_BY))
def test_code_lists_match_the_enumerations(schema, code_list):
    featuretype, prop = USED_BY[code_list]
    enum = schema.model_factory(featuretype).get_property_info(prop).enum
    assert enum.__name__ == code_list
    assert set(mapping.CODE_LISTS[code_list]) == {member.value for member in enum}


@pytest.mark.parametrize("featuretype, prop", sorted(mapping.MEASURES))
def test_units_match_the_model(schema, featuretype, prop):
    info = schema.model_factory(featuretype).get_property_info(prop)
    assert info.stereotype == "Measure"
    assert mapping.MEASURES[(featuretype, prop)].uom == info.uom
