"""Version-independent building blocks of the XWaermeplan model.

The generated module (``v0_9_6.py``) defines one dataclass per XWaermeplan
class and one enum per enumeration. Every class carries its metadata in
``__xwp__`` (a :class:`ClassInfo`): all attributes in the order of the XSD
``sequence``, inherited ones first, with multiplicity, unit and reference
target. Encoders and :func:`validate` only read this metadata, so they work
for any generated version.

Attribute values:

* string, URI: ``str``; integer: ``int``; boolean: ``bool``; date: ``datetime.date``
* measure: ``float`` in the unit of the model, or :class:`Measure`
* enumeration: a member of the generated enum (``WP_Status.Bestehend``)
* data type: an instance of the generated data type class
* reference: :class:`Ref` or the referenced feature object itself
* geometry: a shapely geometry in EPSG:25832
* multiplicity above 1: a list of such values
"""
from __future__ import annotations

import dataclasses
import datetime
import enum
import math
import sys
import uuid
from types import ModuleType
from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar

from shapely.geometry.base import BaseGeometry

# attribute kinds of AttrInfo.kind
STRING, URI, INTEGER, BOOLEAN, DATE = "string", "uri", "integer", "boolean", "date"
MEASURE, ENUM, DATATYPE, REF, GEOMETRY = "measure", "enum", "datatype", "ref", "geometry"

# geometry types of AttrInfo.type for kind GEOMETRY, and the shapely types they accept
MULTI_SURFACE, MULTI_CURVE, VARIABLE = "MultiSurface", "MultiCurve", "Geometry"
GEOMETRY_TYPES = {
    MULTI_SURFACE: ("Polygon", "MultiPolygon"),
    MULTI_CURVE: ("LineString", "MultiLineString"),
    # WP_Geometrieobjekt: "Punkt- oder Flächengeometrie"
    VARIABLE: ("Point", "MultiPoint", "Polygon", "MultiPolygon"),
}

FEATURE_TYPE, DATA_TYPE = "FeatureType", "DataType"


class XwpEnum(str, enum.Enum):
    """Enumeration whose value is the XWaermeplan code, with a German label."""

    label: str

    def __new__(cls, code: str, label: str):
        obj = str.__new__(cls, code)
        obj._value_ = code
        obj.label = label
        return obj

    @property
    def code(self) -> str:
        return self.value

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class Measure:
    """A measured value; ``uom`` None means the unit of the model attribute."""

    value: float
    uom: str | None = None


@dataclass(frozen=True)
class Ref:
    """Reference to a feature by its UUID; ``target`` is its class name if known."""

    id: str
    target: str | None = None

    @classmethod
    def to(cls, feature: XwpFeature) -> Ref:
        return cls(feature.id, type(feature).__name__)


@dataclass(frozen=True)
class AttrInfo:
    """One attribute of an XWaermeplan class."""

    name: str  # also the XML element and JSON property name
    kind: str  # STRING, URI, INTEGER, BOOLEAN, DATE, MEASURE, ENUM, DATATYPE, REF, GEOMETRY
    type: str  # enum, data type or target class name; geometry type; else the kind
    min: int
    max: int | None  # None = unbounded
    owner: str  # class that declares the attribute
    uom: str | None = None  # MEASURE only
    reverse: str | None = None  # REF only: attribute of the target pointing back
    doc: str = ""

    @property
    def many(self) -> bool:
        return self.max is None or self.max > 1

    @property
    def required(self) -> bool:
        return self.min > 0

    @property
    def multiplicity(self) -> str:
        hi = "*" if self.max is None else str(self.max)
        return str(self.min) if str(self.min) == hi else f"{self.min}..{hi}"


@dataclass(frozen=True)
class ClassInfo:
    """Metadata of an XWaermeplan class (feature type or data type)."""

    name: str
    stereotype: str  # FEATURE_TYPE or DATA_TYPE
    abstract: bool
    base: str | None
    own_attrs: tuple[AttrInfo, ...]
    doc: str = ""
    attrs: tuple[AttrInfo, ...] = ()  # inherited + own, in XSD order; filled by register()
    ancestors: tuple[str, ...] = ()  # base classes, nearest first; filled by register()

    def attr(self, name: str) -> AttrInfo:
        for a in self.attrs:
            if a.name == name:
                return a
        raise KeyError(f"{self.name} has no attribute {name!r}")

    @property
    def geometry_attr(self) -> AttrInfo | None:
        """The attribute holding the main geometry (``position``, ``raeumlicherGeltungsbereich`` …)."""
        return next((a for a in self.attrs if a.kind == GEOMETRY), None)

    def is_a(self, name: str) -> bool:
        return name == self.name or name in self.ancestors


@dataclass(kw_only=True)
class XwpObject:
    """Root of all generated classes."""

    __xwp__: ClassVar[ClassInfo]
    __xwp_registry__: ClassVar[dict[str, type[XwpObject]]]  # all classes of the model version
    __xwp_enums__: ClassVar[dict[str, type[XwpEnum]]]  # all enums of the model version


@dataclass(kw_only=True)
class XwpFeature(XwpObject):
    """An object with identity; ``id`` is its UUID (gml:id / JSON-FG id)."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass(kw_only=True)
class XwpDataType(XwpObject):
    """A value object nested in a feature (no identity)."""


def model_module(obj: XwpObject | type[XwpObject]) -> ModuleType:
    """The generated module (``VERSION``, ``NAMESPACE``, ``CLASSES`` …) an object belongs to."""
    cls = obj if isinstance(obj, type) else type(obj)
    return sys.modules[cls.__module__]


def make_register(
    registry: dict[str, type[XwpObject]], enums: dict[str, type[XwpEnum]]
) -> Callable[[type], type]:
    """Class decorator for generated classes: completes ``__xwp__`` and fills ``registry``.

    Base classes must be registered before their subclasses.
    """

    def register(cls: type) -> type:
        info: ClassInfo = cls.__dict__["__xwp__"]
        inherited: tuple[AttrInfo, ...] = ()
        ancestors: tuple[str, ...] = ()
        if info.base:
            base_info = registry[info.base].__xwp__
            inherited, ancestors = base_info.attrs, (info.base,) + base_info.ancestors
        cls.__xwp__ = dataclasses.replace(info, attrs=inherited + info.own_attrs, ancestors=ancestors)
        cls.__xwp_registry__ = registry
        cls.__xwp_enums__ = enums
        registry[info.name] = cls
        return cls

    return register


# --------------------------------------------------------------------------
# validation


ERROR, WARNING = "error", "warning"


@dataclass(frozen=True)
class Issue:
    """A finding of :func:`validate`. ``path`` points to the value, e.g. ``WP_Plan.planungsverantwortlicheStelle.name``."""

    path: str
    code: str  # abstract, missing, multiplicity, duplicate, type, enum, uom, geometry, ref, id
    message: str  # German, meant for planners
    severity: str = ERROR


def values(obj: XwpObject, attr: AttrInfo) -> list[Any]:
    """The values of ``attr`` as a list (empty if unset)."""
    v = getattr(obj, attr.name)
    if v is None:
        return []
    return list(v) if isinstance(v, list) else [v]


def validate(obj: XwpObject, path: str | None = None) -> list[Issue]:
    """Check ``obj`` against its model metadata.

    Checks abstract classes, required attributes, multiplicities, value types,
    enum membership, units of :class:`Measure` values, geometry types and
    reference targets; nested data types are checked recursively. Geometry
    that is not valid (shapely ``is_valid``) is reported as a warning.
    """
    info = type(obj).__xwp__
    path = path or info.name
    issues: list[Issue] = []
    if info.abstract:
        issues.append(Issue(path, "abstract", f"{info.name} ist abstrakt und kann nicht ausgegeben werden."))
    if isinstance(obj, XwpFeature) and not _is_uuid(obj.id):
        issues.append(Issue(f"{path}.id", "id", f"id {obj.id!r} ist keine UUID."))
    for attr in info.attrs:
        raw = getattr(obj, attr.name)
        p = f"{path}.{attr.name}"
        if attr.many and raw is not None and not isinstance(raw, list):
            issues.append(Issue(p, "type", f"{attr.name} erwartet eine Liste (Multiplizität {attr.multiplicity})."))
            continue
        if not attr.many and isinstance(raw, list):
            issues.append(Issue(p, "multiplicity", f"{attr.name} erlaubt nur einen Wert (Multiplizität {attr.multiplicity})."))
            continue
        vals = values(obj, attr)
        if len(vals) < attr.min:
            if not vals:
                issues.append(Issue(p, "missing", f"Pflichtangabe {attr.name} fehlt."))
            else:
                issues.append(Issue(p, "multiplicity", f"{attr.name} braucht mindestens {attr.min} Werte, hat {len(vals)}."))
        if attr.max is not None and len(vals) > attr.max:
            issues.append(Issue(p, "multiplicity", f"{attr.name} erlaubt höchstens {attr.max} Werte, hat {len(vals)}."))
        if _has_duplicates(vals):  # the JSON schema demands uniqueItems
            issues.append(Issue(p, "duplicate", f"{attr.name} enthält denselben Wert mehrfach."))
        for i, v in enumerate(vals):
            issues.extend(_check_value(obj, attr, v, f"{p}[{i}]" if attr.many else p))
    return issues


def _check_value(obj: XwpObject, attr: AttrInfo, v: Any, p: str) -> list[Issue]:
    kind = attr.kind
    if kind in (STRING, URI):
        if not isinstance(v, str):
            return [Issue(p, "type", f"{attr.name} erwartet Text, nicht {type(v).__name__}.")]
        if attr.required and not v.strip():
            return [Issue(p, "missing", f"Pflichtangabe {attr.name} ist leer.")]
    elif kind == INTEGER:
        if isinstance(v, bool) or not isinstance(v, int):
            return [Issue(p, "type", f"{attr.name} erwartet eine ganze Zahl, nicht {v!r}.")]
    elif kind == BOOLEAN:
        if not isinstance(v, bool):
            return [Issue(p, "type", f"{attr.name} erwartet true/false, nicht {v!r}.")]
    elif kind == DATE:
        if not isinstance(v, datetime.date) or isinstance(v, datetime.datetime):
            return [Issue(p, "type", f"{attr.name} erwartet ein Datum, nicht {v!r}.")]
    elif kind == MEASURE:
        return _check_measure(attr, v, p)
    elif kind == ENUM:
        if not isinstance(v, type(obj).__xwp_enums__[attr.type]):
            return [Issue(p, "enum", f"{attr.name} erwartet einen Wert aus {attr.type}, nicht {v!r}.")]
    elif kind == DATATYPE:
        if not isinstance(v, XwpDataType) or not type(v).__xwp__.is_a(attr.type):
            return [Issue(p, "type", f"{attr.name} erwartet {attr.type}, nicht {type(v).__name__}.")]
        return validate(v, p)
    elif kind == REF:
        return _check_ref(obj, attr, v, p)
    elif kind == GEOMETRY:
        return _check_geometry(attr, v, p)
    return []


def _check_measure(attr: AttrInfo, v: Any, p: str) -> list[Issue]:
    if isinstance(v, Measure):
        if v.uom is not None and v.uom != attr.uom:
            return [Issue(p, "uom", f"{attr.name} ist in {attr.uom} anzugeben, nicht in {v.uom}.")]
        v = v.value
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return [Issue(p, "type", f"{attr.name} erwartet eine Zahl in {attr.uom}, nicht {v!r}.")]
    if not math.isfinite(v):
        return [Issue(p, "type", f"{attr.name} ist keine endliche Zahl ({v}).")]
    return []


def _check_ref(obj: XwpObject, attr: AttrInfo, v: Any, p: str) -> list[Issue]:
    if isinstance(v, XwpFeature):
        rid, name, ok = v.id, type(v).__name__, type(v).__xwp__.is_a(attr.type)
    elif isinstance(v, Ref):
        rid, name = v.id, v.target
        target = type(obj).__xwp_registry__.get(name) if name else None
        ok = name is None or (target is not None and target.__xwp__.is_a(attr.type))
    else:
        return [Issue(p, "ref", f"{attr.name} erwartet einen Verweis auf {attr.type}, nicht {type(v).__name__}.")]
    issues = []
    if not ok:
        issues.append(Issue(p, "ref", f"{attr.name} muss auf {attr.type} verweisen, nicht auf {name}."))
    if not _is_uuid(rid):
        issues.append(Issue(p, "ref", f"Verweis {attr.name} hat keine UUID ({rid!r})."))
    return issues


def _check_geometry(attr: AttrInfo, v: Any, p: str) -> list[Issue]:
    if not isinstance(v, BaseGeometry):
        return [Issue(p, "geometry", f"{attr.name} erwartet eine Geometrie, nicht {type(v).__name__}.")]
    allowed = GEOMETRY_TYPES[attr.type]
    if v.geom_type not in allowed:
        return [Issue(p, "geometry", f"{attr.name} erwartet {' oder '.join(allowed)}, nicht {v.geom_type}.")]
    if v.is_empty:
        return [Issue(p, "geometry", f"{attr.name} ist leer.")]
    if not v.is_valid:
        return [Issue(p, "geometry", f"{attr.name} ist geometrisch ungültig.", WARNING)]
    return []


def _has_duplicates(vals: list[Any]) -> bool:
    keys = [v.id if isinstance(v, (Ref, XwpFeature)) else v for v in vals]
    return any(keys[i] == keys[j] for i in range(len(keys)) for j in range(i))


def _is_uuid(s: Any) -> bool:
    try:
        return isinstance(s, str) and str(uuid.UUID(s)) == s.lower()
    except ValueError:
        return False
