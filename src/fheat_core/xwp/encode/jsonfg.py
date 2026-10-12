"""XWaermeplan JSON-FG writer, driven by the model metadata.

Follows the official JSON schema (JSON-FG 0.2.2), not the reference plans
(docs/xwaermeplan/abgleich.md, J1/J2): measures are plain numbers in the unit
of the model, references are JSON-FG link objects ``{"href": "#<uuid>",
"rel": "related"}``, ``id`` is the bare UUID. The main geometry goes to
``place`` (EPSG:25832) and, converted to WGS84, to ``geometry``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pyproj import Transformer
from shapely.geometry import MultiLineString, MultiPoint, MultiPolygon, mapping
from shapely.geometry.base import BaseGeometry
from shapely.geometry.polygon import orient
from shapely.ops import transform

from fheat_core.xwp.document import XwpPlanDocument
from fheat_core.xwp.model.base import (
    BOOLEAN,
    DATATYPE,
    DATE,
    ENUM,
    GEOMETRY,
    INTEGER,
    MEASURE,
    MULTI_CURVE,
    MULTI_SURFACE,
    REF,
    AttrInfo,
    Measure,
    XwpFeature,
    XwpObject,
    values,
)

CONFORMS_TO = [
    "http://www.opengis.net/spec/json-fg-1/0.2/conf/core",
    "http://www.opengis.net/spec/json-fg-1/0.2/conf/types-schemas",
]
LINK_REL = "related"


def crs_uri(epsg: int) -> str:
    return f"http://www.opengis.net/def/crs/EPSG/0/{epsg}"


def to_jsonfg(
    doc: XwpPlanDocument,
    *,
    epsg: int = 25832,
    precision: int = 3,
    wgs84_precision: int = 7,
    check: bool = True,
) -> dict[str, Any]:
    """The plan as JSON-FG FeatureCollection (a dict ready for ``json.dump``).

    ``check`` raises :class:`~fheat_core.xwp.document.XwpValidationError` if the
    document has errors.
    """
    if check:
        doc.check()
    to_wgs84 = Transformer.from_crs(epsg, 4326, always_xy=True).transform
    writer = _Writer(precision, wgs84_precision, to_wgs84)
    return {
        "type": "FeatureCollection",
        "conformsTo": CONFORMS_TO,
        "coordRefSys": crs_uri(epsg),
        "features": [writer.feature(f) for f in doc.ordered()],
    }


def write_jsonfg(doc: XwpPlanDocument, path: str | Path, *, indent: int | None = None, **kwargs) -> Path:
    """Write the plan to ``path`` (UTF-8); keyword arguments as in :func:`to_jsonfg`."""
    path = Path(path)
    data = to_jsonfg(doc, **kwargs)
    text = json.dumps(data, ensure_ascii=False, indent=indent, separators=None if indent else (",", ":"))
    path.write_text(text + "\n", encoding="utf-8", newline="\n")
    return path


def validate_jsonfg(source, version: str = "0.9.6") -> list[str]:
    """Schema findings for a JSON-FG file, string or dict (empty list = valid). Works offline.

    Each feature is checked against the definition of its ``featureType``: the
    FeatureCollection definition alone would only check mixed collections
    against the generic JSON-FG feature (kodierung.md, 1.).
    Needs jsonschema >= 4.18.
    """
    from jsonschema import Draft202012Validator

    from fheat_core.xwp.specfiles import json_registry

    if isinstance(source, Path) or (isinstance(source, str) and not source.lstrip().startswith("{")):
        data = json.loads(Path(source).read_text(encoding="utf-8"))
    elif isinstance(source, str):
        data = json.loads(source)
    else:
        data = source
    registry, base = json_registry(version)
    checker = Draft202012Validator.FORMAT_CHECKER
    collection_uri = base.replace("features.json", "featurecollection.json")
    messages = [
        f"FeatureCollection {_path(e)}: {e.message}"
        for e in Draft202012Validator({"$ref": collection_uri}, registry=registry, format_checker=checker).iter_errors(data)
    ]
    validators: dict[str, Draft202012Validator] = {}
    for i, f in enumerate(data.get("features", [])):
        ft = f.get("featureType")
        if not isinstance(ft, str):
            messages.append(f"Feature {i}: featureType fehlt")
            continue
        if ft not in validators:
            validators[ft] = Draft202012Validator({"$ref": f"{base}#{ft}"}, registry=registry, format_checker=checker)
        try:
            errors = list(validators[ft].iter_errors(f))
        except Exception as exc:  # unknown featureType: the anchor does not resolve
            messages.append(f"Feature {f.get('id')} ({ft}): unbekannte Objektart ({exc.__class__.__name__})")
            continue
        messages.extend(f"Feature {f.get('id')} ({ft}) {_path(e)}: {e.message}" for e in errors)
    return messages


def _path(error) -> str:
    return "/".join(str(p) for p in error.absolute_path) or "/"


class _Writer:
    def __init__(self, precision: int, wgs84_precision: int, to_wgs84):
        self.precision = precision
        self.wgs84_precision = wgs84_precision
        self.to_wgs84 = to_wgs84

    def feature(self, f: XwpFeature) -> dict[str, Any]:
        info = type(f).__xwp__
        geom_attr = info.geometry_attr
        geom = getattr(f, geom_attr.name) if geom_attr else None
        place = self.geometry(geom, geom_attr.type, self.precision) if geom is not None else None
        wgs84 = (
            self.geometry(transform(self.to_wgs84, geom), geom_attr.type, self.wgs84_precision)
            if geom is not None else None
        )
        return {
            "type": "Feature",
            "id": f.id,
            "featureType": info.name,
            "time": None,
            "place": place,
            "geometry": wgs84,
            "properties": self.properties(f, skip=geom_attr),
        }

    def properties(self, obj: XwpObject, skip: AttrInfo | None = None) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for attr in type(obj).__xwp__.attrs:
            if attr is skip:
                continue
            if attr.kind == GEOMETRY:
                raise NotImplementedError(f"{attr.owner}.{attr.name}: a second geometry has no JSON-FG encoding")
            vals = [self.value(attr, v) for v in values(obj, attr)]
            if vals:
                out[attr.name] = vals if attr.many else vals[0]
        return out

    def value(self, attr: AttrInfo, v) -> Any:
        kind = attr.kind
        if kind == MEASURE:
            return float(v.value if isinstance(v, Measure) else v)
        if kind == ENUM:
            return v.code
        if kind == BOOLEAN:
            return bool(v)
        if kind == INTEGER:
            return int(v)
        if kind == DATE:
            return v.isoformat()
        if kind == REF:
            return {"href": f"#{v.id}", "rel": LINK_REL}
        if kind == DATATYPE:
            return self.properties(v)
        return v  # string, uri

    def geometry(self, geom: BaseGeometry, kind: str, precision: int) -> dict[str, Any]:
        """Always the multi type, like the GML writer; rings oriented counter-clockwise outside."""
        t = geom.geom_type
        if kind == MULTI_SURFACE or t in ("Polygon", "MultiPolygon"):
            polys = list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom]
            geom = MultiPolygon([orient(p, 1.0) for p in polys])
        elif kind == MULTI_CURVE or t in ("LineString", "MultiLineString"):
            geom = geom if isinstance(geom, MultiLineString) else MultiLineString([geom])
        else:
            geom = geom if isinstance(geom, MultiPoint) else MultiPoint([geom])
        gj = mapping(geom)
        return {"type": gj["type"], "coordinates": _round(gj["coordinates"], precision)}


def _round(coords, precision: int):
    if isinstance(coords[0], (int, float)):
        return [round(float(c), precision) for c in coords[:2]]
    return [_round(c, precision) for c in coords]


__all__ = ["CONFORMS_TO", "to_jsonfg", "validate_jsonfg", "write_jsonfg"]
