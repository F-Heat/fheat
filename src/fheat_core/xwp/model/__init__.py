"""XWaermeplan data model.

``v0_9_6`` is generated from the XSD (``scripts/gen_xwp_model.py``); ``base``
holds the version-independent types and :func:`validate`. ``current`` is the
model version F|Heat writes.
"""
from fheat_core.xwp.model import v0_9_6 as current
from fheat_core.xwp.model.base import (
    AttrInfo,
    ClassInfo,
    Issue,
    Measure,
    Ref,
    XwpDataType,
    XwpEnum,
    XwpFeature,
    XwpObject,
    validate,
)

__all__ = [
    "AttrInfo", "ClassInfo", "Issue", "Measure", "Ref", "XwpDataType", "XwpEnum",
    "XwpFeature", "XwpObject", "current", "validate",
]
