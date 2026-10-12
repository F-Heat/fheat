"""XWaermeplan: model, mapping and encodings of the German heat planning standard.

See docs/xwaermeplan/ for the implementation plan and the encoding rules.
Writers (GML, JSON-FG, GeoPackage) follow in later phases; the encoders need
the ``[xwp]`` extra (lxml).
"""
from fheat_core.xwp.model import Issue, Measure, Ref, current, validate

__all__ = ["Issue", "Measure", "Ref", "current", "validate"]
