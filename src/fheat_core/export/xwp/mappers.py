"""F|Heat results -> XWaermeplan feature records (plain dicts).

One pure function per target class; they hold all F|Heat knowledge of the
export and need no xplan-tools. A record is

    {"featuretype": "WP_Waermelinie", "key": "<stable F|Heat key>",
     "geometry": <shapely geometry or None>, "geometry_property": "position",
     "properties": {...}}

The builder adds ids and references and turns the records into xplan-tools
models. Units and codes come from :mod:`fheat_core.export.xwp.mapping`; the
attribute choices are documented in ``docs/xwp_mapping.md``.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Optional, Sequence

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


@dataclass
class NetworkResult:
    """One calculated network for the export.

    ``state`` needs ``net_gdf`` and ``result_summary`` (phase RESULTS) and
    may carry the network's ``planning_area_gdf``. ``key`` keeps the feature
    id stable across reruns; default: ``name``, else the position in the list.
    """

    state: PipelineState
    name: Optional[str] = None       # WP_Waermenetz.name
    key: Optional[str] = None
    status: Optional[str] = None     # WP_Status; None = XWPExportConfig.network_status
    operator: Optional[str] = None   # WP_Waermenetz.betreiber

    def __post_init__(self) -> None:
        if self.status is not None:
            self.status = mapping.check_code("WP_Status", self.status)


@dataclass
class SupplyDecision:
    """The planner's supply type for an area, in the CRS of the analysis.

    A suitability polygon whose representative point lies in ``geometry``
    gets ``supply_type`` instead of ``XWPExportConfig.supply_type``, and
    ``suitability`` (if set) instead of the proposal from its heat density.
    """

    geometry: BaseGeometry
    supply_type: str                 # WP_WaermeversorgungsgebietTyp
    suitability: Optional[str] = None  # WP_Eignungsstufe

    def __post_init__(self) -> None:
        self.supply_type = mapping.check_code("WP_WaermeversorgungsgebietTyp", self.supply_type)
        if self.suitability is not None:
            self.suitability = mapping.check_code("WP_Eignungsstufe", self.suitability)


# ------------------------------------------------------------------
# WP_Plan, WP_Bereich
# ------------------------------------------------------------------

def plan_key(config: XWPExportConfig) -> str:
    """Stable key of the plan: its name (mode plan) or the municipality's plan id (fragment)."""
    return config.plan_name if config.mode == "plan" else config.plan_id


def map_plan(config: XWPExportConfig, boundary: BaseGeometry) -> list[dict]:
    """WP_Plan (mode "plan" only) and its one WP_Bereich, both with the plan boundary."""
    area = polygonal(boundary)
    records = []
    if config.mode == "plan":
        records.append(_record("WP_Plan", plan_key(config), area, {
            "name": config.plan_name,
            "planungsverantwortlicheStelle": {
                "name": config.municipality_name,
                "regionalSchluessel12": config.resolved_regional_key,
            },
            "verfahrensart": config.procedure,
            "gesetzlicheGrundlage": config.legal_basis,
            "zieljahr": str(config.target_year),
            "basisJahrDatenerfassung": str(config.base_year),
            "beschlussDatum": config.decision_date,
        }, geometry_property="raeumlicherGeltungsbereich"))
    records.append(_record("WP_Bereich", f"{plan_key(config)}/{config.area_number}", area, {
        "nummer": config.area_number,
        "name": config.area_name,
    }, geometry_property="geltungsbereich"))
    return records


# ------------------------------------------------------------------
# WP_Waermelinie
# ------------------------------------------------------------------

def map_waermelinien(wld_gdf: Optional[gpd.GeoDataFrame]) -> list[dict]:
    """One WP_Waermelinie per street segment with heat demand and length (WPG Anlage 2 I.2.2)."""
    if wld_gdf is None or wld_gdf.empty:
        return []
    records = []
    has_demand = cols.HEAT_DEMAND in wld_gdf.columns
    for row in wld_gdf.itertuples(index=False):
        length = _number(getattr(row, cols.LENGTH))
        density = _number(getattr(row, cols.HEAT_LINE_DENSITY))
        demand = _number(getattr(row, cols.HEAT_DEMAND)) if has_demand else (
            density * length if density is not None and length is not None else None
        )
        line = lineal(row.geometry)
        if not length or not demand or line is None:
            continue  # segments without heat demand carry no heat line
        if density is None:
            density = demand / length
        records.append(_record("WP_Waermelinie", geometry_key(line), line, {
            "waermeMenge": mapping.measure("WP_Waermelinie", "waermeMenge", demand),
            "waermelinienDichte": mapping.measure("WP_Waermelinie", "waermelinienDichte", density),
            "laenge": mapping.measure("WP_Waermelinie", "laenge", length),
        }))
    return records


# ------------------------------------------------------------------
# WP_Waermenetz
# ------------------------------------------------------------------

def map_waermenetze(networks: Sequence[NetworkResult], config: XWPExportConfig, crs) -> list[dict]:
    """One WP_Waermenetz per network (WPG Anlage 2 I.2.8 a).

    The area is the network's planning area, without one a buffer of
    ``config.network_buffer`` around the route (pipes without house
    connections). ``laenge`` is the route length, ``anzahlGebaeudeAnschluss``
    the connected buildings, both from the result summary.
    """
    records = []
    for i, net in enumerate(networks, start=1):
        label = net.name or f"Netz {i}"
        state = net.state
        summary = state.result_summary
        if state.net_gdf is None or state.net_gdf.empty or not summary:
            raise ValueError(f"network {label!r} has no result (net_gdf and result_summary of phase RESULTS).")
        edges = _to_crs(state.net_gdf, crs)
        if cols.TYPE in edges.columns:
            edges = edges[edges[cols.TYPE] != cols.EDGE_TYPE_HOUSE_CONNECTION]
        area = None
        if state.planning_area_gdf is not None and not state.planning_area_gdf.empty:
            area = polygonal(unary_union(list(_to_crs(state.planning_area_gdf, crs).geometry)))
        if area is None:
            area = polygonal(unary_union(list(edges.geometry)).buffer(config.network_buffer))
        props = {
            "netzID": net.key or net.name or f"N{i:02d}",
            "name": label,
            "betreiber": net.operator,
            "medium": config.network_medium,
            "laenge": mapping.measure("WP_Waermenetz", "laenge", summary["total_route_length_m"]),
            "anzahlGebaeudeAnschluss": int(summary["total_buildings"]),
            "status": net.status or config.network_status,
            "temperatur": mapping.measure("WP_Waermenetz", "temperatur", summary.get("supply_temperature_c")),
        }
        if config.source_energy_carrier is not None:
            fed_in = float(summary["total_heat_demand_mwh_a"]) + float(summary.get("total_loss_mwh_a") or 0.0)
            props["eeNachEnergietraeger"] = {
                "energietraeger": config.source_energy_carrier,
                "endenergie": mapping.measure("WP_EndenergieEnergietraeger", "endenergie", fed_in),
            }
        records.append(_record("WP_Waermenetz", props["netzID"], area, _drop_none(props)))
    return records


# ------------------------------------------------------------------
# WP_WaermeversorgungsgebietZieljahr / ...Stuetzjahr
# ------------------------------------------------------------------

def suitability_stage(heat_demand_density, thresholds: Optional[tuple[float, float, float]]) -> Optional[str]:
    """Proposed WP_Eignungsstufe for a heat network from the heat demand density [MWh/(ha·a)]."""
    value = _number(heat_demand_density)
    if value is None or thresholds is None:
        return None
    for stage, bound in zip(mapping.SUITABILITY_STAGES, thresholds):
        if value >= bound:
            return stage
    return mapping.SUITABILITY_STAGES[-1]


def map_versorgungsgebiete(
    polygons_gdf: Optional[gpd.GeoDataFrame],
    config: XWPExportConfig,
    decisions: Sequence[SupplyDecision] = (),
) -> list[dict]:
    """One supply area per suitability polygon, class after ``config.supply_year``.

    ``versorgungsart`` is ``config.supply_type`` unless a planner's decision
    covers the polygon. The target-year class gets ``eignungWaermenetz`` from
    the decision, else from the heat demand density when
    ``config.suitability_thresholds`` is set.
    """
    if polygons_gdf is None or polygons_gdf.empty:
        return []
    featuretype = config.supply_area_class
    records = []
    for row in polygons_gdf.itertuples(index=False):
        area = polygonal(row.geometry)
        if area is None:
            continue
        point = area.representative_point()
        decision = next((d for d in decisions if d.geometry.covers(point)), None)
        props = {
            "versorgungsart": decision.supply_type if decision else config.supply_type,
            "waermeMenge": mapping.measure(featuretype, "waermeMenge", getattr(row, cols.HEAT_DEMAND, None)),
        }
        if featuretype == "WP_WaermeversorgungsgebietZieljahr":
            props["eignungWaermenetz"] = (decision.suitability if decision else None) or suitability_stage(
                getattr(row, cols.HEAT_DEMAND_DENSITY, None), config.suitability_thresholds
            )
        else:
            props["stuetzjahr"] = mapping.INTERIM_YEAR_CODE[config.supply_year]
        records.append(_record(featuretype, geometry_key(area), area, _drop_none(props)))
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


def _record(featuretype: str, key: str, geometry, properties: dict, geometry_property: str = "position") -> dict:
    return {
        "featuretype": featuretype,
        "key": str(key),
        "geometry": geometry,
        "geometry_property": geometry_property,
        "properties": properties,
    }


def _number(value) -> Optional[float]:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _drop_none(props: dict) -> dict:
    return {k: v for k, v in props.items() if v is not None}
