"""Read XWaermeplan GML (own exports, reference plans of XMAS/XPlan-Tools and ldproxy) into the model.

Driven by the model metadata like the writer. Ids: ``gml:identifier
codeSpace="urn:uuid"`` if present, otherwise the UUID inside ``gml:id``
(``GML_<uuid>``, ``_WP_Plan.<uuid>``), otherwise a UUID derived from the
``gml:id``. Measures with another unit than the model keep it as
:class:`~fheat_core.xwp.model.base.Measure`, so nothing is converted silently.
Geometries in another CRS are transformed to EPSG:25832.
"""
from __future__ import annotations

import datetime
import re
import uuid
from pathlib import Path

from shapely.geometry import LineString, MultiLineString, MultiPoint, MultiPolygon, Point, Polygon
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
    REF,
    AttrInfo,
    Issue,
    Measure,
    Ref,
    XwpObject,
)

GML_NS = "http://www.opengis.net/gml/3.2"
XLINK_HREF = "{http://www.w3.org/1999/xlink}href"
MEMBER_NAMES = {"featureMember", "member", "featureMembers"}
GML_FEATURE_PROPERTIES = {"identifier", "name", "description", "descriptionReference", "boundedBy", "location"}
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
TARGET_EPSG = 25832


def _local(tag) -> str:
    return tag.split("}")[-1] if isinstance(tag, str) else ""


def _ns(tag) -> str:
    return tag[1:].split("}")[0] if isinstance(tag, str) and tag.startswith("{") else ""


def read_gml(source, model=None) -> tuple[XwpPlanDocument, list[Issue]]:
    """Plan document and findings from a GML file path or bytes."""
    from lxml import etree

    if model is None:
        from fheat_core.xwp.model import current as model
    parser = etree.XMLParser(huge_tree=True, no_network=True, remove_comments=True)
    if isinstance(source, (str, Path)):
        root = etree.parse(str(source), parser).getroot()
    elif isinstance(source, bytes):
        root = etree.fromstring(source, parser)
    else:
        root = source.getroot() if hasattr(source, "getroot") else source
    reader = _Reader(model)
    doc = XwpPlanDocument(id=reader.uuid_of(root) if root.get(f"{{{GML_NS}}}id") else str(uuid.uuid4()))
    for el in reader.feature_elements(root):
        obj = reader.feature(el)
        if obj is not None:
            doc.add(obj)
    reader.resolve_refs()
    return doc, reader.issues


class _Reader:
    def __init__(self, model):
        self.m = model
        self.issues: list[Issue] = []
        self.gml_ids: dict[str, str] = {}  # gml:id -> uuid
        self.pending: list[tuple[XwpObject, AttrInfo, str, int | None]] = []  # refs to resolve

    # -- ids

    def uuid_of(self, el) -> str:
        for child in el:
            if child.tag == f"{{{GML_NS}}}identifier" and child.get("codeSpace") == "urn:uuid" and child.text:
                return child.text.strip().lower()
        gid = el.get(f"{{{GML_NS}}}id") or ""
        match = _UUID.search(gid)
        if match:
            return match.group(0).lower()
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"gml:id/{gid}"))

    # -- structure

    def feature_elements(self, root):
        if _local(root.tag) in self.m.CLASSES:
            yield root
            return
        for member in root:
            if _local(member.tag) not in MEMBER_NAMES:
                continue
            for el in member:
                if isinstance(el.tag, str):
                    yield el

    def feature(self, el) -> XwpObject | None:
        name = _local(el.tag)
        where = f"{name}[{el.get(f'{{{GML_NS}}}id')}]"
        if _ns(el.tag) != self.m.NAMESPACE:
            self.issues.append(Issue(where, "namespace", f"{where}: Namespace {_ns(el.tag)} ist nicht XWärmeplan {self.m.VERSION}."))
            return None
        cls = self.m.CLASSES.get(name)
        if cls is None or cls.__xwp__.stereotype != "FeatureType" or cls.__xwp__.abstract:
            self.issues.append(Issue(where, "type", f"{where}: unbekannte oder abstrakte Objektart."))
            return None
        obj = cls(id=self.uuid_of(el))
        gid = el.get(f"{{{GML_NS}}}id")
        if gid:
            self.gml_ids[gid] = obj.id
        self.fill(obj, el, where)
        return obj

    def fill(self, obj: XwpObject, el, where: str) -> None:
        info = type(obj).__xwp__
        attrs = {a.name: a for a in info.attrs}
        for child in el:
            if not isinstance(child.tag, str):
                continue
            name = _local(child.tag)
            if _ns(child.tag) == GML_NS and name in GML_FEATURE_PROPERTIES:
                continue
            attr = attrs.get(name)
            if attr is None:
                self.issues.append(Issue(f"{where}.{name}", "attribute", f"{where}: {info.name} hat kein Attribut {name}."))
                continue
            index = len(getattr(obj, attr.name)) if attr.many else None
            value = self.value(obj, attr, child, f"{where}.{name}", index)
            if value is None:
                continue
            if attr.many:
                getattr(obj, attr.name).append(value)
            else:
                setattr(obj, attr.name, value)

    def value(self, obj, attr: AttrInfo, el, where: str, index):
        text = (el.text or "").strip()
        try:
            if attr.kind == REF:
                href = el.get(XLINK_HREF) or ""
                if not href:
                    raise ValueError("ohne xlink:href")
                self.pending.append((obj, attr, href.split("#")[-1], index))
                return Ref("00000000-0000-0000-0000-000000000000", attr.type)  # placeholder, see resolve_refs
            if attr.kind == DATATYPE:
                inner = next((c for c in el if isinstance(c.tag, str)), None)
                cls = self.m.CLASSES.get(_local(inner.tag)) if inner is not None else None
                if cls is None or not cls.__xwp__.is_a(attr.type):
                    raise ValueError(f"erwartet {attr.type}")
                value = cls()
                self.fill(value, inner, where)
                return value
            if attr.kind == GEOMETRY:
                inner = next((c for c in el if isinstance(c.tag, str)), None)
                if inner is None:
                    raise ValueError("ohne Geometrie")
                return parse_geometry(inner)
            if attr.kind == MEASURE:
                value, uom = float(text), el.get("uom")
                return Measure(value, uom) if uom and uom != attr.uom else value
            if attr.kind == ENUM:
                return self.m.ENUMS[attr.type](text)
            if attr.kind == INTEGER:
                return int(text)
            if attr.kind == BOOLEAN:
                if text not in ("true", "false", "1", "0"):
                    raise ValueError(text)
                return text in ("true", "1")
            if attr.kind == DATE:
                return datetime.date.fromisoformat(text[:10])
            return el.text or ""
        except (ValueError, KeyError, TypeError) as exc:
            self.issues.append(Issue(where, "type", f"{where}: Wert nicht lesbar ({exc})."))
            return None

    def resolve_refs(self) -> None:
        """Replace the placeholders by references to the UUID behind each gml:id."""
        for obj, attr, gid, index in self.pending:
            target = self.gml_ids.get(gid)
            if target is None:
                match = _UUID.search(gid)
                target = match.group(0).lower() if match else None
            if target is None:
                self.issues.append(Issue(f"{type(obj).__name__}.{attr.name}", "ref", f"Verweis auf {gid} nicht auflösbar."))
            ref = Ref(target, None) if target else None
            if attr.many:
                getattr(obj, attr.name)[index] = ref
            else:
                setattr(obj, attr.name, ref)
        for obj, attr, _, _ in self.pending:
            if attr.many:
                setattr(obj, attr.name, [v for v in getattr(obj, attr.name) if v is not None])


# --------------------------------------------------------------------------
# geometry


def _epsg(srs_name: str | None) -> int | None:
    if not srs_name:
        return None
    match = re.search(r"(\d{4,5})\s*$", srs_name.replace("::", ":"))
    return int(match.group(1)) if match else None


def _coords(el, dim: int) -> list[tuple[float, float]]:
    pos_list = el.find(f"{{{GML_NS}}}posList")
    if pos_list is not None:
        dim = int(pos_list.get("srsDimension", dim))
        nums = [float(x) for x in (pos_list.text or "").split()]
        return [(nums[i], nums[i + 1]) for i in range(0, len(nums) - dim + 1, dim)]
    pos = el.findall(f"{{{GML_NS}}}pos")
    if pos:
        out = []
        for p in pos:
            nums = [float(x) for x in (p.text or "").split()]
            out.append((nums[0], nums[1]))
        return out
    coordinates = el.find(f"{{{GML_NS}}}coordinates")
    if coordinates is not None:
        pairs = [c.split(",") for c in (coordinates.text or "").split()]
        return [(float(a), float(b)) for a, b, *_ in pairs]
    raise ValueError("keine Koordinaten")


def _ring(el, dim) -> list:
    ring = next(c for c in el if isinstance(c.tag, str))  # LinearRing or Ring
    if _local(ring.tag) == "Ring":
        coords = []
        for member in ring.iter(f"{{{GML_NS}}}LineStringSegment", f"{{{GML_NS}}}LineString"):
            coords.extend(_coords(member, dim))
        return coords
    return _coords(ring, dim)


def _polygon(el, dim) -> Polygon:
    if _local(el.tag) == "Surface":  # Surface/patches/PolygonPatch
        polys = [_polygon(p, dim) for p in el.iter(f"{{{GML_NS}}}PolygonPatch")]
        return polys[0] if len(polys) == 1 else MultiPolygon(polys)
    exterior = el.find(f"{{{GML_NS}}}exterior")
    interiors = el.findall(f"{{{GML_NS}}}interior")
    return Polygon(_ring(exterior, dim), [_ring(i, dim) for i in interiors])


def _line(el, dim) -> LineString:
    if _local(el.tag) == "Curve":
        coords = []
        for seg in el.iter(f"{{{GML_NS}}}LineStringSegment"):
            part = _coords(seg, dim)
            coords.extend(part if not coords else part[1:])
        return LineString(coords)
    return LineString(_coords(el, dim))


def _members(el, names: set[str]):
    for member in el:
        if _local(member.tag) in names:
            for g in member:
                if isinstance(g.tag, str):
                    yield g


def _parts(geom, kind):
    return list(geom.geoms) if isinstance(geom, kind) else [geom]


def parse_geometry(el, target_epsg: int = TARGET_EPSG):
    """shapely geometry of a GML 3.2 geometry element, in ``target_epsg``."""
    name = _local(el.tag)
    dim = int(el.get("srsDimension", 2))
    if name in ("MultiSurface", "CompositeSurface"):
        polys = []
        for g in _members(el, {"surfaceMember", "surfaceMembers"}):
            polys.extend(_parts(parse_geometry(g, target_epsg=0), MultiPolygon))
        geom = MultiPolygon(polys)
    elif name in ("Polygon", "Surface"):
        geom = _polygon(el, dim)
    elif name in ("MultiCurve", "CompositeCurve"):
        lines = []
        for g in _members(el, {"curveMember", "curveMembers"}):
            lines.extend(_parts(parse_geometry(g, target_epsg=0), MultiLineString))
        geom = MultiLineString(lines)
    elif name in ("LineString", "Curve"):
        geom = _line(el, dim)
    elif name == "MultiPoint":
        geom = MultiPoint([parse_geometry(g, target_epsg=0) for g in _members(el, {"pointMember", "pointMembers"})])
    elif name == "Point":
        geom = Point(_coords(el, dim)[0])
    else:
        raise ValueError(f"Geometrietyp {name} nicht unterstützt")
    if not target_epsg:  # a member: the CRS of the enclosing geometry applies
        return geom
    epsg = _epsg(el.get("srsName"))
    if epsg and epsg != target_epsg:
        from pyproj import CRS, Transformer

        source = CRS.from_epsg(epsg)
        # URN/URL forms of geographic CRS state latitude first; the xy flag of pyproj handles "EPSG:x" only
        always_xy = not (source.is_geographic and ("urn:" in el.get("srsName", "") or "http" in el.get("srsName", "")))
        transformer = Transformer.from_crs(source, CRS.from_epsg(target_epsg), always_xy=always_xy)
        geom = transform(transformer.transform, geom)
    return geom


__all__ = ["parse_geometry", "read_gml"]
