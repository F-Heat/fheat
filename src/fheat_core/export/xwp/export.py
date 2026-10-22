"""Entry point of the XWaermeplan export: F|Heat state -> GML / JSON-FG.

A one-way adapter: reads finished pipeline states, never changes them.
"""
from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Union

import geopandas as gpd
import pandas as pd
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from fheat_core import columns as cols
from fheat_core.export.xwp import builder, mapping, writer
from fheat_core.export.xwp.config import XWPExportConfig
from fheat_core.export.xwp.mappers import (
    MIN_SEGMENT_LENGTH,
    NetworkResult,
    map_plan,
    map_versorgungsgebiete,
    map_waermelinien,
    map_waermenetze,
    named,
    polygonal,
)
from fheat_core.export.xwp.report import ExportReport, Issue
from fheat_core.state import PipelineState

PathLike = Union[str, Path]
BOUNDARY_TOLERANCE = 0.5   # m a feature may reach beyond the plan boundary (rounding, buffers)
SUM_TOLERANCE = 1e-6       # relative, for the heat demand totals


def export_xwaermeplan(
    state: PipelineState,
    config: XWPExportConfig,
    path: Union[PathLike, Sequence[PathLike]],
    *,
    networks: Optional[Sequence[Union[NetworkResult, PipelineState]]] = None,
    boundary=None,
    schema_dir: Optional[PathLike] = None,
) -> ExportReport:
    """Write the F|Heat results as XWaermeplan and report every finding.

    ``state`` is the analysis (``wld_gdf``, ``polygons_gdf``, ``parcels_gdf``,
    phase STATUS or later). ``networks`` are the calculated networks; None
    takes ``state`` itself when it holds a network. ``path`` is one file or
    several, ``.gml`` and/or ``.json`` (JSON-FG). ``boundary`` (geometry or
    GeoDataFrame in the CRS of ``state``, e.g. ``adapter.provide_boundary()``)
    is the plan area; None = the union of the parcels. Areas and heat lines
    are cut to it; a map feature wholly outside is left out and named in the
    notes. ``schema_dir`` with the XSD of the schema version enables the
    schema check of the GML (see :func:`writer.validate_gml`).

    Only verifiably conformant data leave the export: the files are written
    only when no level (structure, consistency, conformity and, with
    ``schema_dir``, schema) has a finding; otherwise the report holds the
    findings and no file is written. Needs the extra ``[xwp]`` (xplan-tools).
    """
    paths = [path] if isinstance(path, (str, Path)) else list(path)
    formats = [writer.format_of(p) for p in paths]
    crs = _crs(state)
    srid = crs.to_epsg()
    nets = named(_networks(state, networks))
    area = _boundary(state, boundary, crs)

    heat_lines = _heat_lines(state.wld_gdf, area)
    features, left_out = _clip([
        *map_waermelinien(state.wld_gdf, area),
        *map_waermenetze(nets, config, crs),
        *map_versorgungsgebiete(state.polygons_gdf, config),
    ], area)
    records = [*map_plan(config, area), *features]
    report = ExportReport(counts=dict(Counter(r["featuretype"] for r in records)),
                          notes=_notes(config, boundary, heat_lines, left_out))
    findings = _consistency(records, state, nets, area, config, heat_lines) + _conformity(records, config)

    collection, structure = builder.build_collection(records, config, srid)
    report.issues = structure + findings
    if collection is None or report.issues:
        return report

    staged = {fmt: writer.write(collection, _staging(Path(p))) for p, fmt in zip(paths, formats)}
    try:
        if schema_dir is not None and "gml" in staged:
            report.schema_checked = True
            report.issues += [Issue("schema", None, m) for m in writer.validate_gml(staged["gml"], schema_dir)]
        elif "gml" in staged:
            report.notes.append("GML not checked against the XSD (no schema_dir given)")
        if not report.issues:
            for p, fmt in zip(paths, formats):
                os.replace(staged[fmt], p)
                report.files[fmt] = Path(p)
    finally:
        for p in staged.values():
            p.unlink(missing_ok=True)
    return report


def _staging(path: Path) -> Path:
    """Where a file is written before the checks: next to its target, same suffix (it picks the format)."""
    return path.with_name(f"{path.stem}.partial{path.suffix}")


@dataclass(frozen=True)
class _HeatLines:
    """Heat demand of the heat lines inside and outside the plan boundary [kWh/a] and how many are cut."""

    inside: float = 0.0
    outside: float = 0.0
    cut: int = 0


def _heat_lines(wld: Optional[gpd.GeoDataFrame], area: BaseGeometry) -> _HeatLines:
    """The heat lines against the plan boundary, computed apart from the mapper to check it."""
    if wld is None or wld.empty:
        return _HeatLines()
    length = pd.to_numeric(wld[cols.LENGTH], errors="coerce")
    density = pd.to_numeric(wld[cols.HEAT_LINE_DENSITY], errors="coerce")
    if cols.HEAT_DEMAND in wld.columns:
        demand = pd.to_numeric(wld[cols.HEAT_DEMAND], errors="coerce")
        density = density.fillna(demand / length)
    else:
        demand = density * length
    carried = (wld.geometry.notna() & ~wld.geometry.is_empty & length.notna() & (length != 0)
               & demand.notna() & (demand != 0))
    cut = carried & ~wld.geometry.covered_by(area)
    inside = length.where(~cut, wld.geometry.intersection(area).length)
    inside = inside.where(~cut | (inside >= MIN_SEGMENT_LENGTH), 0.0)
    return _HeatLines(
        inside=float((density * inside)[carried].sum()),
        outside=float((density * (length - inside))[carried].sum()),
        cut=int(cut.sum()),
    )


def _notes(config: XWPExportConfig, boundary, heat_lines: _HeatLines, left_out: list[str]) -> list[str]:
    """What the user should know about the written plan; no findings."""
    notes = ["plan boundary: the boundary passed to the export" if boundary is not None
             else "plan boundary: the union of the parcels (no boundary passed)"]
    if left_out:
        counts = ", ".join(f"{n} {name}" for name, n in sorted(Counter(left_out).items()))
        notes.append(f"outside the plan boundary, left out: {counts}")
    if heat_lines.cut:
        _, attribute = mapping.written_from(mapping.HEAT_LINE, "column", cols.HEAT_DEMAND)
        notes.append(f"heat lines cut at the plan boundary: {heat_lines.cut}; "
                     f"{heat_lines.outside * attribute.factor:.1f} {attribute.uom} of their heat demand "
                     "lies outside and is not exported")
    if config.mode == "fragment":
        if not config.plan_id:
            to_plan, _ = mapping.written_from(mapping.AREA, "reference", "plan")
            notes.append(f"no plan_id: {mapping.AREA}.{to_plan} refers to the derived id {builder.plan_id(config)}; "
                         "replace it with the id of the municipality's plan when merging")
        number, _ = mapping.written_from(mapping.AREA, "config", "area_number")
        notes.append(f"{mapping.AREA}.{number} {config.area_number} has to be unique within the municipality's plan")
    return notes


def _crs(state: PipelineState):
    frame = next((f for f in (state.wld_gdf, state.polygons_gdf, state.buildings_gdf) if f is not None), None)
    if frame is None or frame.crs is None:
        raise ValueError("The export needs the analysis (wld_gdf / polygons_gdf) with a CRS.")
    crs = frame.crs
    if not crs.is_projected or crs.axis_info[0].unit_name not in ("metre", "meter") or crs.to_epsg() is None:
        raise ValueError(f"XWaermeplan needs a projected CRS in metres with an EPSG code, not {crs.name}.")
    return crs


def _networks(state: PipelineState, networks) -> list[NetworkResult]:
    if networks is None:
        has_net = state.net_gdf is not None and not state.net_gdf.empty
        networks = [state] if has_net else []
    return [n if isinstance(n, NetworkResult) else NetworkResult(n) for n in networks]


def _boundary(state: PipelineState, boundary, crs) -> BaseGeometry:
    if boundary is None:
        if state.parcels_gdf is None or state.parcels_gdf.empty:
            raise ValueError("The export needs a plan boundary: pass boundary= or provide parcels_gdf.")
        boundary = state.parcels_gdf
    if isinstance(boundary, (gpd.GeoDataFrame, gpd.GeoSeries)):
        if boundary.crs is not None and boundary.crs != crs:
            boundary = boundary.to_crs(crs)
        boundary = unary_union(list(boundary.geometry))
    area = polygonal(boundary)
    if area is None:
        raise ValueError("The plan boundary has no area.")
    return area


def _clip(records, area) -> tuple[list[dict], list[str]]:
    """Cut the areas of the map features to the plan boundary; ``(kept, classes left out)``.

    The suitability polygons are parcels buffered by ``buffer_distance`` and
    the network areas buffers around routes, so at the edge of the analysis
    they reach beyond it; a plan content outside the plan makes no sense, and
    an area wholly outside is left out. Their attributes stay those of the
    F|Heat result. The heat lines are cut by their mapper, which recalculates
    length and heat demand.
    """
    kept, left_out = [], []
    for r in records:
        geom = r["geometry"]
        if geom is None or geom.geom_type != "MultiPolygon" or area.covers(geom):
            kept.append(r)
            continue
        inside = polygonal(geom.intersection(area))
        if inside is None:
            left_out.append(r["featuretype"])
            continue
        kept.append({**r, "geometry": inside})
    return kept, left_out


def _consistency(records, state, nets, area, config, heat_lines: _HeatLines) -> list[Issue]:
    """The export must agree with the F|Heat result it came from."""
    issues = []
    reach = area.buffer(BOUNDARY_TOLERANCE)
    for r in records:
        label = f"{r['featuretype']} {r['key']}"
        geom = r["geometry"]
        if geom is None or geom.is_empty:
            issues.append(Issue("consistency", label, "geometry is empty"))
        elif not geom.is_valid:
            issues.append(Issue("consistency", label, "geometry is not valid"))
        elif not reach.covers(geom):
            issues.append(Issue("consistency", label, "geometry reaches beyond the plan boundary"))

    heat, attribute = mapping.written_from(mapping.HEAT_LINE, "column", cols.HEAT_DEMAND)
    exported = sum(r["properties"].get(heat, {}).get("value", 0.0) for r in records
                   if r["featuretype"] == mapping.HEAT_LINE)
    expected = heat_lines.inside * attribute.factor
    if abs(exported - expected) > SUM_TOLERANCE * max(abs(expected), 1.0) + 1e-3:
        issues.append(Issue("consistency", None,
                            f"{heat} of the heat lines {exported:.3f} {attribute.uom} != heat demand of the "
                            f"street segments inside the plan boundary {expected:.3f} {attribute.uom}"))

    length, attribute = mapping.written_from(mapping.HEAT_NETWORK, "summary", cols.TOTAL_ROUTE_LENGTH)
    by_key = {net.key: net for net in nets}
    for record in (r for r in records if r["featuretype"] == mapping.HEAT_NETWORK):
        expected = float(by_key[record["key"]].state.result_summary[cols.TOTAL_ROUTE_LENGTH]) * attribute.factor
        exported = record["properties"].get(length, {}).get("value")
        if exported is None or abs(exported - expected) > 1e-6:
            issues.append(Issue("consistency", f"{mapping.HEAT_NETWORK} {record['key']}",
                                f"{length} {exported} {attribute.uom} != route length {expected} {attribute.uom}"))

    polygons = state.polygons_gdf
    if polygons is not None and not polygons.empty and cols.HEAT_DEMAND in polygons.columns:
        heat, attribute = mapping.written_from(config.supply_area_class, "column", cols.HEAT_DEMAND)
        areas = [r for r in records if r["featuretype"] == config.supply_area_class]
        exported = sum(r["properties"].get(heat, {}).get("value", 0.0) for r in areas)
        inside = polygons.geometry.intersection(area).area > 0
        expected = float(polygons.loc[inside, cols.HEAT_DEMAND].fillna(0.0).sum()) * attribute.factor
        if abs(exported - expected) > SUM_TOLERANCE * max(abs(expected), 1.0) + 1e-3:
            issues.append(Issue("consistency", None,
                                f"{heat} of the supply areas {exported:.3f} {attribute.uom} != heat demand "
                                f"of the suitability polygons inside the plan boundary {expected:.3f} {attribute.uom}"))
    return issues


def _conformity(records, config: XWPExportConfig) -> list[Issue]:
    """The conformity conditions of the schema documentation (``mapping.CONFORMITY``)."""
    issues = []
    for condition in mapping.CONFORMITY:
        for r in (r for r in records if r["featuretype"] == condition.class_name):
            if not condition.applies(config, r["properties"]):
                continue
            missing = [name for name in condition.attributes if name not in r["properties"]]
            if missing:
                issues.append(Issue("conformity", f"{r['featuretype']} {r['key']}",
                                    f"{', '.join(missing)} missing: {condition.reason}"))
    return issues
