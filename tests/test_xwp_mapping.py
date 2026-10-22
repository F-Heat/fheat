"""The code and unit tables of the export against the model xplan-tools ships.

A new xplan-tools release that changes a code, a class or a unit makes these
tests fail instead of the export writing something else silently.
"""
from __future__ import annotations

import pytest

pytest.importorskip("xplan_tools")
pytestmark = pytest.mark.xwp

from fheat_core.export.xwp import builder, mapping  # noqa: E402

CODES = sorted((c, n) for c, n, a in mapping.attributes() if a.code_list)
MEASURES = sorted((c, n) for c, n, a in mapping.attributes() if a.uom)


@pytest.fixture(scope="module")
def schema():
    return builder.appschema()


def test_schema_version(schema):
    assert str(schema.full_version) == mapping.SCHEMA_VERSION
    assert str(schema.namespace_uri).rstrip("/") == mapping.NAMESPACE


@pytest.mark.parametrize("featuretype", sorted(mapping.CLASSES))
def test_classes_and_attributes_exist(schema, featuretype):
    model = schema.model_factory(featuretype)
    for prop in mapping.CLASSES[featuretype]:
        assert model.get_property_info(prop) is not None


@pytest.mark.parametrize("featuretype, prop", CODES)
def test_code_lists_match_the_enumerations(schema, featuretype, prop):
    code_list = mapping.CLASSES[featuretype][prop].code_list
    enum = schema.model_factory(featuretype).get_property_info(prop).enum
    assert enum.__name__ == code_list
    assert set(mapping.CODE_LISTS[code_list]) == {member.value for member in enum}


@pytest.mark.parametrize("featuretype, prop", MEASURES)
def test_units_match_the_model(schema, featuretype, prop):
    info = schema.model_factory(featuretype).get_property_info(prop)
    assert info.stereotype == "Measure"
    assert mapping.CLASSES[featuretype][prop].uom == info.uom
