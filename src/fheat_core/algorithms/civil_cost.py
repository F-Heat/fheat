"""Civil works cost factor per route from land use and road surface layers.

The standardised pipe costs (``cost_main`` / ``cost_h-connect`` in €/m) are
split into two parts:

* **civil works** (trench, backfill, surface restoration) — the share
  ``civil_cost_share`` of the €/m value. It depends strongly on what lies on
  top (asphalt road, paving, green space …) and is multiplied by a factor
  per route.
* **pipe material and installation** — the rest, independent of the place.

Cost multiplier of an edge with civil works factor ``f`` and share ``s``::

    m = (1 − s) + s · f

The factor of a line is the area-weighted mean over a buffered overlay with
each layer's polygons (not a point query), multiplied over the layers — the
legal axis (ALKIS land use) times the physical axis (OSM road surface).

Each layer is a polygon GeoDataFrame with the column ``civil_cost_factor``
and optionally ``civil_class`` (the class the factor stands for). Which data
source fills them is an adapter concern (e.g. :mod:`fheat_nrw.civil_cost`).
"""
from __future__ import annotations

import re
from typing import Optional, Sequence

import geopandas as gpd
import numpy as np
import pandas as pd

from fheat_core import columns as cols

#: Column of a layer that carries the civil works factor (1.0 = neutral).
CIVIL_FACTOR_COLUMN: str = cols.CIVIL_COST_FACTOR

#: Column of a layer that names the class behind the factor (e.g. ``asphalt``).
CIVIL_CLASS_COLUMN: str = "civil_class"

_UMLAUT_MAP = str.maketrans(
    {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue"}
)


def _normalize_class(value) -> str:
    """Resolve umlauts/ß, lower-case and drop everything non-alphanumeric.

    So ``"Wohnbauflaeche"`` (ALKIS object type), ``"Wohnbaufläche"`` (WFS
    plain text) and ``"AX_Wohnbauflaeche"`` all match the same key.
    """
    text = str(value).translate(_UMLAUT_MAP).lower()
    return re.sub(r"[^a-z0-9]+", "", text)


def apply_cost_table(
    landuse_gdf: gpd.GeoDataFrame,
    *,
    class_column: str,
    cost_table: dict,
    default_factor: float = 1.0,
    out_column: str = CIVIL_FACTOR_COLUMN,
    match: str = "exact",
) -> gpd.GeoDataFrame:
    """Give every polygon the civil works factor of its class in ``cost_table``.

    ``match="exact"``    – the class value must be a key.
    ``match="contains"`` – a key must occur in the normalised class value
                           (robust against export variants such as
                           ``"AX_Strassenverkehr"`` vs. ``"Straßenverkehr"``).
                           Longer keys are checked first.
    """
    out = landuse_gdf.copy()
    if class_column not in out.columns:
        out[out_column] = float(default_factor)
        return out

    norm_table = sorted(
        ((_normalize_class(k), float(v)) for k, v in cost_table.items()),
        key=lambda kv: len(kv[0]),
        reverse=True,
    )

    def _lookup(value) -> float:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return float(default_factor)
        if match == "exact":
            return float(cost_table.get(value, default_factor))
        norm_text = _normalize_class(value)
        if not norm_text:
            return float(default_factor)
        for norm_key, factor in norm_table:
            if norm_key and norm_key in norm_text:
                return factor
        return float(default_factor)

    out[out_column] = out[class_column].map(_lookup).astype(float)
    return out


def cost_multiplier(factor, share):
    """Cost multiplier ``(1 − share) + share · factor`` of an edge.

    The only place of this formula: ``share`` is the civil works part of the
    pipe costs, only that part scales with the civil works factor.
    """
    m = (1.0 - float(share)) + float(share) * np.asarray(factor, dtype=float)
    return float(m) if m.ndim == 0 else m


def usable_layers(layers: Optional[Sequence]) -> list:
    """The layers that can contribute a factor (not None, not empty, with factor column)."""
    return [
        g for g in (layers or [])
        if g is not None and len(g) > 0 and CIVIL_FACTOR_COLUMN in g.columns
    ]


def civil_factors_for_lines(
    lines: gpd.GeoSeries,
    layers: Optional[Sequence[Optional[gpd.GeoDataFrame]]],
    *,
    crs,
    buffer_m: float = 1.5,
    default_factor: float = 1.0,
    class_column: str = CIVIL_CLASS_COLUMN,
    surface_layer: Optional[int] = -1,
) -> pd.DataFrame:
    """Civil works factor and dominant road surface per line.

    Every line is buffered by ``buffer_m`` (flat caps) and intersected with
    each layer. Per layer the factor is the area-weighted mean of the hit
    polygons; the line's factor is the product over the layers. A layer
    without a hit contributes 1.0; a line without a hit in any layer (or no
    usable layer at all) gets ``default_factor``.

    ``road_surface`` is the ``class_column`` value with the largest
    intersection area in ``layers[surface_layer]`` (by default the last
    layer, the road surface), ``None`` without a hit there.

    Returns a DataFrame on ``lines.index`` with the columns
    ``civil_cost_factor`` and ``road_surface``.
    """
    result = pd.DataFrame(
        {
            cols.CIVIL_COST_FACTOR: float(default_factor),
            cols.ROAD_SURFACE: pd.Series([None] * len(lines), index=lines.index, dtype=object),
        },
        index=lines.index,
    )
    layers = list(layers or [])
    if lines.empty or not usable_layers(layers):
        return result

    lines = gpd.GeoSeries(lines)
    if lines.crs is None:
        lines = lines.set_crs(crs)
    elif crs is not None and lines.crs != crs:
        lines = lines.to_crs(crs)
    crs = lines.crs

    pos = np.arange(len(lines))
    buffered = gpd.GeoDataFrame(
        {"_line": pos},
        geometry=lines.buffer(float(buffer_m), cap_style="flat").to_numpy(),
        crs=crs,
    )
    buffered = buffered[~buffered.geometry.is_empty & buffered.geometry.notna()]
    surface_idx = surface_layer % len(layers) if surface_layer is not None else None

    combined = np.ones(len(lines), dtype=float)
    hit = np.zeros(len(lines), dtype=bool)
    surface = pd.Series([None] * len(lines), index=pos, dtype=object)

    for i, layer in enumerate(layers):
        if layer is None or len(layer) == 0 or CIVIL_FACTOR_COLUMN not in layer.columns:
            continue
        with_class = i == surface_idx and class_column in layer.columns
        lu = layer[[CIVIL_FACTOR_COLUMN, *([class_column] if with_class else []), "geometry"]]
        lu = lu[lu.geometry.notna() & ~lu.geometry.is_empty]
        if lu.empty or buffered.empty:
            continue
        if lu.crs is None:
            lu = lu.set_crs(crs)
        elif lu.crs != crs:
            lu = lu.to_crs(crs)
        lu = lu.copy()
        lu[CIVIL_FACTOR_COLUMN] = pd.to_numeric(lu[CIVIL_FACTOR_COLUMN], errors="coerce").fillna(1.0)

        inter = gpd.overlay(buffered, lu, how="intersection", keep_geom_type=False)
        if inter.empty:
            continue
        area = inter.geometry.area
        inter = inter[area > 0]
        area = area[area > 0]
        if inter.empty:
            continue

        line = inter["_line"].to_numpy()
        weighted = (inter[CIVIL_FACTOR_COLUMN] * area).groupby(line).sum()
        total = area.groupby(line).sum()
        mean = (weighted / total).reindex(pos, fill_value=1.0).to_numpy()
        combined *= mean
        hit[total.index.to_numpy()] = True

        if with_class:
            by_class = (
                pd.DataFrame({"line": line, "cls": inter[class_column].to_numpy(), "area": area.to_numpy()})
                .dropna(subset=["cls"])
                .groupby(["line", "cls"], sort=False)["area"].sum()
                .reset_index()
                .sort_values(["line", "area"], ascending=[True, False], kind="stable")
                .drop_duplicates("line")
            )
            surface.loc[by_class["line"].to_numpy()] = by_class["cls"].to_numpy()

    result[cols.CIVIL_COST_FACTOR] = np.where(hit, combined, float(default_factor))
    result[cols.ROAD_SURFACE] = surface.to_numpy()
    return result
