"""XWaermeplan GML writer, driven by the model metadata.

Writes an ``sf:FeatureCollection`` as fixed in docs/xwaermeplan/kodierung.md:
``gml:id="GML_<uuid>"``, ``gml:identifier codeSpace="urn:uuid"``, local
``xlink:href="#GML_<uuid>"`` references, measures with ``uom`` in the unit of
the model, multi geometries with ``srsName`` and their own ``gml:id``. Element
order follows the XSD because the metadata lists attributes in that order.
Needs lxml (extra ``[xwp]``).
"""
from __future__ import annotations

import uuid
from pathlib import Path

from shapely.geometry import MultiLineString, MultiPoint, MultiPolygon
from shapely.geometry.base import BaseGeometry
from shapely.geometry.polygon import orient

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
    model_module,
    values,
)
from fheat_core.xwp.specfiles import SF_NAMESPACE, SF_XSD, xsd_schema

GML_NS = "http://www.opengis.net/gml/3.2"
XLINK_NS = "http://www.w3.org/1999/xlink"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
XWP_XSD_URL = "https://gitlab.opencode.de/xleitstelle/xwaermeplan/spezifikation/-/raw/main/xsd/waermeplan.xsd"
GML_XSD_URL = "https://schemas.opengis.net/gml/3.2.1/gml.xsd"


def gml_id(feature_id: str) -> str:
    return f"GML_{feature_id}"


def to_gml(
    doc: XwpPlanDocument,
    *,
    precision: int = 3,
    srs_name: str = "EPSG:25832",
    check: bool = True,
):
    """The plan as ``lxml.etree._ElementTree``.

    ``check`` raises :class:`~fheat_core.xwp.document.XwpValidationError` if the
    document has errors (warnings do not stop the export).
    """
    from lxml import etree

    if check:
        doc.check()
    if not doc.features:
        raise ValueError("the document has no features")
    module = model_module(doc.features[0])
    ns = module.NAMESPACE
    root = etree.Element(
        f"{{{SF_NAMESPACE}}}FeatureCollection",
        nsmap={None: ns, "gml": GML_NS, "xlink": XLINK_NS, "xsi": XSI_NS, "sf": SF_NAMESPACE},
    )
    root.set(
        f"{{{XSI_NS}}}schemaLocation",
        f"{ns} {XWP_XSD_URL} {SF_NAMESPACE} {SF_XSD} {GML_NS} {GML_XSD_URL}",
    )
    root.set(f"{{{GML_NS}}}id", gml_id(doc.id))
    writer = _Writer(etree, ns, precision, srs_name)
    for feature in doc.ordered():
        member = etree.SubElement(root, f"{{{SF_NAMESPACE}}}featureMember")
        member.append(writer.feature(feature))
    return etree.ElementTree(root)


def write_gml(doc: XwpPlanDocument, path: str | Path, **kwargs) -> Path:
    """Write the plan to ``path`` (UTF-8, indented); keyword arguments as in :func:`to_gml`."""
    path = Path(path)
    to_gml(doc, **kwargs).write(str(path), xml_declaration=True, encoding="UTF-8", pretty_print=True)
    return path


def validate_gml(source, version: str = "0.9.6") -> list[str]:
    """XSD findings for a GML file, bytes or element tree (empty list = valid). Works offline."""
    from lxml import etree

    if isinstance(source, (str, Path)):
        tree = etree.parse(str(source), etree.XMLParser(no_network=True, huge_tree=True))
    elif isinstance(source, bytes):
        tree = etree.ElementTree(etree.fromstring(source, etree.XMLParser(no_network=True, huge_tree=True)))
    else:
        tree = source
    schema = xsd_schema(version)
    if schema.validate(tree):
        return []
    return [f"Zeile {e.line}: {e.message}" for e in schema.error_log]


class _Writer:
    def __init__(self, etree, ns: str, precision: int, srs_name: str):
        self.etree = etree
        self.ns = ns
        self.precision = precision
        self.srs_name = srs_name

    def _el(self, parent, name: str, ns: str | None = None):
        return self.etree.SubElement(parent, f"{{{ns or self.ns}}}{name}")

    def feature(self, f: XwpFeature):
        el = self.etree.Element(f"{{{self.ns}}}{type(f).__xwp__.name}")
        el.set(f"{{{GML_NS}}}id", gml_id(f.id))
        ident = self._el(el, "identifier", GML_NS)
        ident.set("codeSpace", "urn:uuid")
        ident.text = f.id
        self.attributes(el, f, uuid.UUID(f.id), "")
        return el

    def attributes(self, parent, obj: XwpObject, feature_uuid: uuid.UUID, path: str) -> None:
        for attr in type(obj).__xwp__.attrs:
            for i, v in enumerate(values(obj, attr)):
                child = self._el(parent, attr.name)
                self.value(child, attr, v, feature_uuid, f"{path}{attr.name}[{i}]")

    def value(self, el, attr: AttrInfo, v, feature_uuid: uuid.UUID, path: str) -> None:
        kind = attr.kind
        if kind == MEASURE:
            el.set("uom", attr.uom)
            el.text = repr(float(v.value if isinstance(v, Measure) else v))
        elif kind == ENUM:
            el.text = v.code
        elif kind == BOOLEAN:
            el.text = "true" if v else "false"
        elif kind == DATE:
            el.text = v.isoformat()
        elif kind == INTEGER:
            el.text = str(int(v))
        elif kind == REF:
            el.set(f"{{{XLINK_NS}}}href", "#" + gml_id(v.id))
        elif kind == DATATYPE:
            inner = self._el(el, type(v).__xwp__.name)
            self.attributes(inner, v, feature_uuid, path + ".")
        elif kind == GEOMETRY:
            # stable ids: the same feature yields the same geometry ids on every export
            gid = gml_id(str(uuid.uuid5(feature_uuid, path)))
            self.geometry(el, v, attr.type, gid)
        else:  # string, uri
            el.text = v

    # -- geometry

    def geometry(self, parent, geom: BaseGeometry, kind: str, gid: str) -> None:
        t = geom.geom_type
        if kind == MULTI_SURFACE or t in ("Polygon", "MultiPolygon"):
            polys = list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom]
            multi = self._multi(parent, "MultiSurface", gid)
            for i, poly in enumerate(polys):
                member = self._el(multi, "surfaceMember", GML_NS)
                self._polygon(member, orient(poly, 1.0), f"{gid}.{i}")
        elif kind == MULTI_CURVE or t in ("LineString", "MultiLineString"):
            lines = list(geom.geoms) if isinstance(geom, MultiLineString) else [geom]
            multi = self._multi(parent, "MultiCurve", gid)
            for i, line in enumerate(lines):
                member = self._el(multi, "curveMember", GML_NS)
                ls = self._el(member, "LineString", GML_NS)
                ls.set(f"{{{GML_NS}}}id", f"{gid}.{i}")
                self._el(ls, "posList", GML_NS).text = self._coords(line.coords)
        else:  # Point / MultiPoint of a variable geometry
            points = list(geom.geoms) if isinstance(geom, MultiPoint) else [geom]
            multi = self._multi(parent, "MultiPoint", gid)
            for i, point in enumerate(points):
                member = self._el(multi, "pointMember", GML_NS)
                pt = self._el(member, "Point", GML_NS)
                pt.set(f"{{{GML_NS}}}id", f"{gid}.{i}")
                self._el(pt, "pos", GML_NS).text = self._coords(point.coords)

    def _multi(self, parent, name: str, gid: str):
        el = self._el(parent, name, GML_NS)
        el.set("srsName", self.srs_name)
        el.set(f"{{{GML_NS}}}id", gid)
        return el

    def _polygon(self, parent, poly, pid: str) -> None:
        el = self._el(parent, "Polygon", GML_NS)
        el.set(f"{{{GML_NS}}}id", pid)
        ring = self._el(self._el(el, "exterior", GML_NS), "LinearRing", GML_NS)
        self._el(ring, "posList", GML_NS).text = self._coords(poly.exterior.coords)
        for interior in poly.interiors:
            ring = self._el(self._el(el, "interior", GML_NS), "LinearRing", GML_NS)
            self._el(ring, "posList", GML_NS).text = self._coords(interior.coords)

    def _coords(self, coords) -> str:
        p = self.precision
        return " ".join(f"{c[0]:.{p}f} {c[1]:.{p}f}" for c in coords)


__all__ = ["gml_id", "to_gml", "validate_gml", "write_gml"]
