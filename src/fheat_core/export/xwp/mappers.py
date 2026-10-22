"""F|Heat results -> XWaermeplan feature records (plain dicts).

One function per target class picks the F|Heat objects (rows, networks)
and their geometry; :func:`fill` takes every attribute from the class's table
in :mod:`fheat_core.export.xwp.mapping`, the values F|Heat derives from
:data:`RULES`. They need no xplan-tools. A record is

    {"featuretype": "WP_Waermelinie", "key": "<stable F|Heat key>",
     "geometry": <shapely geometry or None>, "geometry_property": "position",
     "properties": {...}}

The builder adds ids and references and turns the records into xplan-tools
models. The attribute choices are documented in ``docs/xwp_mapping.md``.
"""
from __future__ import annotations

import dataclasses
import hashlib
import math
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

import geopandas as gpd
import shapely
from shapely.geometry import MultiLineString, MultiPolygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from fheat_core import columns as cols
from fheat_core.export.xwp import mapping
from fheat_core.export.xwp.config import XWPExportConfig
from fheat_core.state import PipelineState

KEY_PRECISION = 0.1  # m; geometries that differ less get the same key
MIN_SEGMENT_LENGTH = 0.5  # m; a heat line cut to the plan boundary shorter than this is left out


@dataclass
class NetworkResult:
    """One calculated network for the export.

    ``state`` needs ``net_gdf`` and ``result_summary`` (phase RESULTS).
    ``key`` keeps the feature id stable across reruns; default: ``name``,
    else the position in the list. Every network gets
    ``XWPExportConfig.network_status``.
    """

    state: PipelineState
    name: Optional[str] = None
    key: Optional[str] = None
    operator: Optional[str] = None


@dataclass
class Source:
    """What one feature is filled from: the config, an F|Heat row or a network, as far as the class needs them."""

    config: Optional[XWPExportConfig] = None
    row: Optional[dict] = None
    network: Optional[NetworkResult] = None

    @property
    def summary(self) -> dict:
        return self.network.state.result_summary


def suitability_stage(heat_demand_density, thresholds: Optional[tuple[float, float, float]]) -> Optional[str]:
    """Proposed suitability stage for a heat network from the heat demand density [MWh/(ha·a)]."""
    value = _number(heat_demand_density)
    if value is None or thresholds is None:
        return None
    for stage, bound in zip(mapping.SUITABILITY_STAGES, thresholds):
        if value >= bound:
            return stage
    return mapping.SUITABILITY_STAGES[-1]


def _heat_fed_in(source: Source) -> float:
    """Heat fed into the network: demand of the connected buildings plus the losses [MWh/a]."""
    return float(source.summary[cols.TOTAL_HEAT_DEMAND]) + float(source.summary.get(cols.TOTAL_LOSS) or 0.0)


#: Values F|Heat derives, by the name the tables give as source "rule"
RULES: dict[str, Callable[[Source], object]] = {
    "heat_fed_in": _heat_fed_in,
    "suitability": lambda source: suitability_stage(
        source.row.get(cols.HEAT_DEMAND_DENSITY), source.config.suitability_thresholds),
    "interim_year": lambda source: mapping.INTERIM_YEAR_CODE[source.config.supply_year],
}


def fill(class_name: str, source: Source) -> dict:
    """The attributes of ``class_name`` from its table; missing values, geometry and references left out."""
    properties = {}
    for name, attribute in mapping.CLASSES[class_name].items():
        value = _value(attribute, source)
        if value is not None:
            properties[name] = value
    return properties


def _value(attribute: mapping.Attribute, source: Source):
    if attribute.source in ("geometry", "reference"):
        return None
    if attribute.source == "nested":
        nested = {}
        for name, inner in mapping.CLASSES[attribute.name].items():
            value = _value(inner, source)
            if value is None:
                return None  # a data type is written whole or not at all
            nested[name] = value
        return nested
    if attribute.source == "column":
        raw = source.row.get(attribute.name)
    elif attribute.source == "summary":
        raw = source.summary.get(attribute.name)
    elif attribute.source == "config":
        raw = getattr(source.config, attribute.name)
    elif attribute.source == "network":
        raw = getattr(source.network, attribute.name)
    elif attribute.source == "rule":
        raw = RULES[attribute.name](source)
    else:
        raise ValueError(f"unknown source {attribute.source!r}")
    return attribute.convert(raw)


# ------------------------------------------------------------------
# Plan and area
# ------------------------------------------------------------------

def plan_key(config: XWPExportConfig) -> str:
    """Stable key of the plan: its name (mode plan), the municipality's plan id or "" (fragment)."""
    return config.plan_name if config.mode == "plan" else (config.plan_id or "")


def map_plan(config: XWPExportConfig, boundary: BaseGeometry) -> list[dict]:
    """The plan (mode "plan" only) and its one area, both with the plan boundary.

    The key of the area includes its boundary, so two exports into the same
    plan with different boundaries get different areas.
    """
    area = polygonal(boundary)
    source = Source(config)
    records = []
    if config.mode == "plan":
        records.append(_record(mapping.PLAN, plan_key(config), area, fill(mapping.PLAN, source)))
    key = f"{plan_key(config)}/{config.area_number}/{geometry_key(area)}"
    records.append(_record(mapping.AREA, key, area, fill(mapping.AREA, source)))
    return records


# ------------------------------------------------------------------
# Heat lines (WPG Anlage 2 I.2.2)
# ------------------------------------------------------------------

def map_waermelinien(wld_gdf: Optional[gpd.GeoDataFrame], boundary: Optional[BaseGeometry] = None) -> list[dict]:
    """One heat line per street segment with heat demand and length.

    The WLD schema does not require the heat demand; without the column it
    is density times length. A segment that leaves ``boundary`` is cut to
    it: the length is the part inside, the density stays, the heat demand is
    density times that length. A part shorter than
    :data:`MIN_SEGMENT_LENGTH` is left out.
    """
    if wld_gdf is None or wld_gdf.empty:
        return []
    records = []
    for row in wld_gdf.to_dict("records"):
        length = _number(row.get(cols.LENGTH))
        density = _number(row.get(cols.HEAT_LINE_DENSITY))
        demand = _number(row.get(cols.HEAT_DEMAND)) if cols.HEAT_DEMAND in row else (
            density * length if density is not None and length is not None else None
        )
        line = lineal(row["geometry"])
        if not length or not demand or line is None:
            continue  # segments without heat demand carry no heat line
        if density is None:
            density = demand / length
        if boundary is not None and not boundary.covers(line):
            line = lineal(line.intersection(boundary))
            if line is None or line.length < MIN_SEGMENT_LENGTH:
                continue
            length, demand = line.length, density * line.length
        values = {cols.LENGTH: length, cols.HEAT_DEMAND: demand, cols.HEAT_LINE_DENSITY: density}
        records.append(_record(mapping.HEAT_LINE, geometry_key(line), line,
                               fill(mapping.HEAT_LINE, Source(row=values))))
    return records


# ------------------------------------------------------------------
# Heat networks (WPG Anlage 2 I.2.8 a)
# ------------------------------------------------------------------

def map_waermenetze(networks: Sequence[NetworkResult], config: XWPExportConfig, crs) -> list[dict]:
    """One heat network per calculated network.

    The area is a buffer of ``config.resolved_network_buffer`` around every
    edge of the network (route, house and source connections), dissolved, as
    in the technical plan. Without a name a network is "Netz <n>", without
    a key it takes its name, else "N<nn>".
    """
    records = []
    for i, net in enumerate(networks, start=1):
        net = dataclasses.replace(net, name=net.name or f"Netz {i}", key=net.key or net.name or f"N{i:02d}")
        state = net.state
        if state.net_gdf is None or state.net_gdf.empty or not state.result_summary:
            raise ValueError(f"network {net.name!r} has no result (net_gdf and result_summary of phase RESULTS).")
        edges = _to_crs(state.net_gdf, crs)
        area = polygonal(unary_union(list(edges.geometry)).buffer(config.resolved_network_buffer))
        records.append(_record(mapping.HEAT_NETWORK, net.key, area,
                               fill(mapping.HEAT_NETWORK, Source(config, network=net))))
    return records


# ------------------------------------------------------------------
# Supply areas
# ------------------------------------------------------------------

def map_versorgungsgebiete(polygons_gdf: Optional[gpd.GeoDataFrame], config: XWPExportConfig) -> list[dict]:
    """One supply area per suitability polygon, class after ``config.supply_year``.

    Every area gets ``config.supply_type``; F|Heat makes no decision per
    area. The target-year class gets a proposed suitability from the heat
    demand density when ``config.suitability_thresholds`` is set.
    """
    if polygons_gdf is None or polygons_gdf.empty:
        return []
    class_name = config.supply_area_class
    records = []
    for row in polygons_gdf.to_dict("records"):
        area = polygonal(row["geometry"])
        if area is None:
            continue
        records.append(_record(class_name, geometry_key(area), area, fill(class_name, Source(config, row=row))))
    return records


# ------------------------------------------------------------------
# Geometry helpers
# ------------------------------------------------------------------

def polygonal(geometry) -> Optional[MultiPolygon]:
    """The polygon parts of a geometry as one valid MultiPolygon; None if there are none."""
    if geometry is None or geometry.is_empty:
        return None
    parts = [g for g in shapely.get_parts(shapely.make_valid(geometry)) if g.geom_type in ("Polygon", "MultiPolygon")]
    polys = [p for g in parts for p in shapely.get_parts(g) if not p.is_empty]
    return MultiPolygon(polys) if polys else None


def lineal(geometry) -> Optional[MultiLineString]:
    """The line parts of a geometry as one MultiLineString; None if there are none."""
    if geometry is None or geometry.is_empty:
        return None
    lines = [g for g in shapely.get_parts(geometry) if g.geom_type == "LineString" and not g.is_empty]
    return MultiLineString(lines) if lines else None


def geometry_key(geometry: BaseGeometry) -> str:
    """Stable key of a geometry: hash of its normalised WKT at 0.1 m."""
    rounded = shapely.normalize(shapely.set_precision(geometry, KEY_PRECISION))
    return hashlib.sha1(shapely.to_wkt(rounded, rounding_precision=1).encode()).hexdigest()[:16]


def _to_crs(gdf: gpd.GeoDataFrame, crs) -> gpd.GeoDataFrame:
    if crs is None or gdf.crs is None or gdf.crs == crs:
        return gdf
    return gdf.to_crs(crs)


def _record(class_name: str, key: str, geometry, properties: dict) -> dict:
    return {
        "featuretype": class_name,
        "key": str(key),
        "geometry": geometry,
        "geometry_property": mapping.geometry_property(class_name),
        "properties": properties,
    }


def _number(value) -> Optional[float]:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None
