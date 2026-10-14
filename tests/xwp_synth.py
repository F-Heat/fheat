"""Synthetic XWaermeplan objects for encoder tests, built from the model metadata alone.

``minimal`` objects carry only the required attributes, ``maximal`` objects
every attribute (two values where the multiplicity allows it). Used by the
completeness tests of the GML, JSON-FG and GeoPackage encoders.
"""
from __future__ import annotations

import datetime

from shapely.geometry import LineString, MultiLineString, MultiPoint, MultiPolygon, Point, Polygon

from fheat_core.xwp.document import XwpPlanDocument
from fheat_core.xwp.model.base import (
    BOOLEAN, DATATYPE, DATE, ENUM, GEOMETRY, INTEGER, MEASURE, MULTI_CURVE, MULTI_SURFACE, REF,
    STRING, URI, AttrInfo, Measure, Ref, XwpObject,
)

X0, Y0 = 400_000.0, 5_760_000.0  # somewhere in NRW, EPSG:25832

# non-spatial feature types the plan points to; every synthetic document holds one of each
PLAN_PARTS = (
    "WP_TextAbschnitt", "WP_Massnahme", "WP_Energiebilanz",
    "WP_WaermeinfrastrukturAggregiert", "WP_PotenzialanalyseAggregiert",
)


def square(x: float, y: float, size: float = 20.0) -> Polygon:
    return Polygon([(x, y), (x + size, y), (x + size, y + size), (x, y + size)])


def geometry(kind: str, maximal: bool, variable_as: str = "surface"):
    if kind == MULTI_SURFACE or (kind == "Geometry" and variable_as == "surface"):
        if not maximal:
            return square(X0, Y0)
        holed = Polygon(square(X0, Y0, 30).exterior.coords, [list(square(X0 + 10, Y0 + 10, 5).exterior.coords)])
        return MultiPolygon([holed, square(X0 + 50, Y0)])
    if kind == MULTI_CURVE:
        if not maximal:
            return LineString([(X0, Y0), (X0 + 40, Y0 + 3)])
        return MultiLineString([[(X0, Y0), (X0 + 40, Y0 + 3)], [(X0 + 40, Y0 + 3), (X0 + 40, Y0 + 60)]])
    return MultiPoint([(X0, Y0), (X0 + 5, Y0 + 5)]) if maximal else Point(X0, Y0)


class Synth:
    """Builds objects of one model version; ``refs`` maps class names to features to point at."""

    def __init__(self, model, variable_as: str = "surface"):
        self.m = model
        self.variable_as = variable_as
        self.refs: dict[str, object] = {}
        self.datatypes_seen: set[str] = set()

    def build(self, name: str, maximal: bool, seed: int = 0) -> XwpObject:
        cls = self.m.CLASSES[name]
        info = cls.__xwp__
        if info.stereotype == "DataType":
            self.datatypes_seen.add(name)
        kwargs = {}
        for a in info.attrs:
            n = a.min if not maximal else (2 if a.max is None else min(a.max, 2))
            if a.kind == REF and a.max is None:
                continue  # list side of a bidirectional pair, filled by link_reverse()
            vals = [self.value(a, maximal, i, seed) for i in range(n)]
            vals = [v for v in vals if v is not None]
            if vals:
                kwargs[a.name] = vals if a.many else vals[0]
        return cls(**kwargs)

    def value(self, a: AttrInfo, maximal: bool, i: int, seed: int = 0):
        """The ``i``-th value of ``a``; ``seed`` keeps repeated data types apart (uniqueItems)."""
        k = a.kind
        if k in (STRING,):
            return f"{a.name} {seed + i + 1}"
        if k == URI:
            return f"https://example.org/{a.name}/{seed + i + 1}"
        if k == INTEGER:
            return 3 + seed + i
        if k == BOOLEAN:
            return i == 0
        if k == DATE:
            return datetime.date(2025, 1, 1 + i)
        if k == MEASURE:
            return Measure(12.5 + seed + i) if i else 12.5 + seed + i
        if k == ENUM:
            members = list(self.m.ENUMS[a.type])
            return members[-1 - i] if maximal else members[i]
        if k == DATATYPE:
            return self.build(self._concrete(a.type), maximal, seed=10 * (seed + i))
        if k == REF:
            target = next((f for f in self.refs.values() if type(f).__xwp__.is_a(a.type)), None)
            return Ref.to(target) if target is not None else None
        if k == GEOMETRY:
            return geometry(a.type, maximal, self.variable_as)
        raise AssertionError(k)

    def _concrete(self, name: str) -> str:
        if not self.m.CLASSES[name].__xwp__.abstract:
            return name
        return next(n for n, c in self.m.CLASSES.items() if not c.__xwp__.abstract and c.__xwp__.is_a(name))


def document(model, feature_type: str, maximal: bool, variable_as: str = "surface") -> tuple[XwpPlanDocument, XwpObject, Synth]:
    """A valid plan document that contains ``feature_type`` in its minimal or maximal form."""
    s = Synth(model, variable_as)
    doc = XwpPlanDocument()

    def make(name: str):
        obj = s.build(name, maximal and name == feature_type)
        s.refs[name] = obj
        doc.add(obj)
        return obj

    make("WP_Plan")
    make("WP_Bereich")
    for name in PLAN_PARTS:
        make(name)
    obj = doc.of_type(feature_type)[0] if feature_type in s.refs else make(feature_type)
    doc.link_reverse()
    return doc, obj, s


def document_all(model, maximal: bool, variable_as: str = "surface") -> tuple[XwpPlanDocument, dict[str, XwpObject]]:
    """One valid document with an object of every concrete feature type; returns it and the objects by type."""
    s = Synth(model, variable_as)
    doc = XwpPlanDocument()
    objects: dict[str, XwpObject] = {}
    for name in ("WP_Plan", "WP_Bereich", *PLAN_PARTS):
        obj = s.build(name, maximal)
        s.refs[name] = obj
        objects[name] = obj
        doc.add(obj)
    for name in model.FEATURE_TYPES:
        if name not in objects:
            objects[name] = s.build(name, maximal)
            doc.add(objects[name])
    doc.link_reverse()
    return doc, objects


def small_town():
    """Two street blocks (100 m × 100 m each): west holds 6 houses, east 2 commercial buildings
    (one unheated). Returns buildings, heat lines, streets and the outline in EPSG:25832."""
    import geopandas as gpd
    import pandas as pd
    from shapely.geometry import box

    from fheat_core import columns as cols

    CRS = "EPSG:25832"
    streets = gpd.GeoDataFrame(geometry=[
        LineString([(X0, Y0), (X0 + 200, Y0)]), LineString([(X0, Y0 + 100), (X0 + 200, Y0 + 100)]),
        LineString([(X0, Y0), (X0, Y0 + 100)]), LineString([(X0 + 100, Y0), (X0 + 100, Y0 + 100)]),
        LineString([(X0 + 200, Y0), (X0 + 200, Y0 + 100)]),
    ], crs=CRS)
    points = [(X0 + 15 * i + 10, Y0 + 50) for i in range(6)] + [(X0 + 150, Y0 + 30), (X0 + 150, Y0 + 70)]
    buildings = gpd.GeoDataFrame({
        cols.BUILDING_ID: list(range(8)),
        cols.CONNECT: [1] * 8,
        cols.HEAT_DEMAND: [20_000.0] * 6 + [100_000.0, 0.0],
        cols.FLOOR_AREA: [150.0] * 6 + [1_000.0, 500.0],
        cols.XWP_BUILDING_TYPE: ["10001"] * 5 + ["10002", "20001", "20001"],
        cols.CONSTRUCTION_YEAR: pd.array([1965] * 4 + [1985, None, 2005, 2005], dtype="Int64"),
    }, geometry=[Point(p).buffer(4, cap_style=3) for p in points], crs=CRS)
    wld = streets.copy()
    wld[cols.LENGTH] = wld.length
    wld[cols.HEAT_DEMAND] = [120_000.0, 0.0, 0.0, 100_000.0, 0.0]
    wld[cols.HEAT_LINE_DENSITY] = wld[cols.HEAT_DEMAND] / wld[cols.LENGTH]
    wld[cols.CONNECTED_IDS] = ["0,1,2,3,4,5", "", "", "6,7", ""]
    boundary = box(X0, Y0, X0 + 200, Y0 + 100)
    return buildings, wld, streets, boundary
