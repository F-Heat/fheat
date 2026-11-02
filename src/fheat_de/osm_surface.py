"""OpenStreetMap ``highway``/``surface`` → civil works factor.

OSM records the actual **surface material** of a road (``surface=*``:
asphalt, paving_stones, gravel, …) — the axis that ALKIS "Tatsächliche
Nutzung" (legal use) does not describe. Both factors are multiplied (see
:func:`fheat_core.algorithms.civil_cost.civil_factors_for_lines`).

Steps:

1. OSM ``highway`` lines are buffered to narrow polygons with a width per
   ``highway`` class.
2. ``surface=*`` (if present) is translated via
   ``DEFAULT_OSM_SURFACE_COST_TABLE``.
3. Without ``surface``, ``DEFAULT_OSM_HIGHWAY_FALLBACK`` gives a conservative
   assumption per ``highway`` class.
4. Otherwise ``default_factor = 1.0`` (neutral).

The values are centred on 1.0: they model only the difference in material
and construction, not the legal part (see :mod:`fheat_de.alkis`).
Tables taken unchanged from the previous F|Heat package; calibration with
values from practice is pending.

The ways come from the Overpass API (:func:`get_osm_surface_via_overpass`)
or a prepared file; OSM covers every state, so any adapter can use both.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from importlib.metadata import PackageNotFoundError, version

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString

from fheat_core import cancel
from fheat_core.algorithms.civil_cost import (
    CIVIL_CLASS_COLUMN,
    CIVIL_FACTOR_COLUMN,
    apply_cost_table,
)

#: Default Overpass endpoint; an adapter can select a mirror.
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OSM_TIMEOUT = 90
# The public instance is often busy (HTTP 504/429). On 2026-10-09 two of three
# requests for Burgsteinfurt failed that way, and a whole-municipality request
# for Steinfurt failed three times in a row while the next one answered in
# 1.3 s (3.8 MB) - the size is no problem, the instance is just busy at times.
# So busy answers are retried with growing pauses (5+10+15+20 s).
OSM_RETRIES = 5
OSM_RETRY_WAIT = 5  # s, multiplied by the attempt number
_OSM_RETRY_STATUS = frozenset({429, 502, 503, 504})
_OSM_COLUMNS = ("osm_id", "highway", "surface", "tracktype", "width", "lanes")

#: Factor for ways without a recognisable class.
DEFAULT_OSM_FACTOR: float = 1.0

#: OSM ``surface`` value → civil works factor (multiplicative, 1.0 = neutral).
DEFAULT_OSM_SURFACE_COST_TABLE: dict[str, float] = {
    # bound surfaces (costly excavation, restoration to standard)
    "asphalt": 1.15,
    "concrete": 1.20,
    "concrete_plates": 1.15,
    "concrete_lanes": 1.15,
    "metal": 1.25,
    "wood": 1.10,
    # unbound paving / modular surfaces (cheaper, the stones can be reused)
    "paving_stones": 0.95,
    "sett": 1.00,
    "cobblestone": 1.00,
    "bricks": 1.05,
    "unhewn_cobblestone": 1.00,
    # generic
    "paved": 1.10,
    "unpaved": 0.85,
    # gravel
    "compacted": 0.85,
    "gravel": 0.80,
    "fine_gravel": 0.80,
    "pebblestone": 0.85,
    "rock": 1.20,
    # natural surfaces
    "ground": 0.80,
    "dirt": 0.80,
    "earth": 0.80,
    "mud": 0.85,
    "sand": 0.90,
    "grass": 0.75,
    "grass_paver": 0.85,
    "stepping_stones": 1.00,
}

#: Fallback per ``highway`` class when ``surface`` is missing.
DEFAULT_OSM_HIGHWAY_FALLBACK: dict[str, float] = {
    "motorway": 1.20,
    "motorway_link": 1.15,
    "trunk": 1.20,
    "trunk_link": 1.15,
    "primary": 1.15,
    "primary_link": 1.10,
    "secondary": 1.15,
    "secondary_link": 1.10,
    "tertiary": 1.10,
    "tertiary_link": 1.05,
    "unclassified": 1.05,
    "residential": 1.05,
    "living_street": 0.95,
    "pedestrian": 0.95,
    "service": 1.00,
    "track": 0.85,
    "path": 0.85,
    "footway": 0.95,
    "cycleway": 0.95,
    "bridleway": 0.85,
    "construction": 1.00,
    "road": 1.05,
}

#: Half width [m] per ``highway`` class, used to buffer the OSM lines into
#: narrow polygons before the overlay.
DEFAULT_OSM_HALFWIDTH_M: dict[str, float] = {
    "motorway": 6.0,
    "motorway_link": 4.0,
    "trunk": 5.0,
    "trunk_link": 4.0,
    "primary": 5.0,
    "primary_link": 4.0,
    "secondary": 4.5,
    "secondary_link": 3.5,
    "tertiary": 4.0,
    "tertiary_link": 3.0,
    "unclassified": 3.5,
    "residential": 3.5,
    "living_street": 3.0,
    "pedestrian": 2.0,
    "service": 2.5,
    "track": 2.0,
    "path": 1.0,
    "footway": 1.0,
    "cycleway": 1.0,
    "bridleway": 1.0,
    "construction": 3.0,
    "road": 3.0,
}

#: Half width for a ``highway`` class missing from the table.
DEFAULT_OSM_HALFWIDTH_FALLBACK: float = 2.5


def _is_missing(value) -> bool:
    return value is None or (isinstance(value, float) and pd.isna(value)) or str(value).strip() == ""


def annotate_osm_surface_costs(
    osm_gdf: gpd.GeoDataFrame,
    *,
    surface_column: str = "surface",
    highway_column: str = "highway",
    surface_table: dict | None = None,
    highway_fallback: dict | None = None,
    default_factor: float = DEFAULT_OSM_FACTOR,
    out_column: str = CIVIL_FACTOR_COLUMN,
) -> gpd.GeoDataFrame:
    """Add ``civil_cost_factor`` and ``civil_class`` to an OSM way frame.

    Per row:

    1. ``surface`` value in ``surface_table`` (contains match, umlaut-robust)
       → factor, class = the surface value.
    2. Otherwise the ``highway`` class in ``highway_fallback`` → factor,
       class = ``highway:<class>``.
    3. Otherwise ``default_factor``.
    """
    surf_table = surface_table if surface_table is not None else DEFAULT_OSM_SURFACE_COST_TABLE
    hw_table = highway_fallback if highway_fallback is not None else DEFAULT_OSM_HIGHWAY_FALLBACK

    out = osm_gdf.copy()
    if surface_column in out.columns:
        with_surface = apply_cost_table(
            out, class_column=surface_column,
            cost_table=surf_table, default_factor=float("nan"),
            match="contains", out_column=out_column,
        )
        out[out_column] = with_surface[out_column]
    else:
        out[out_column] = float("nan")

    if highway_column in out.columns:
        fallback = apply_cost_table(
            out, class_column=highway_column,
            cost_table=hw_table, default_factor=default_factor,
            match="contains", out_column="_hw_fallback",
        )
        # surface wins where present, otherwise the highway fallback
        mask = out[out_column].isna()
        out.loc[mask, out_column] = fallback.loc[mask, "_hw_fallback"]
    out[out_column] = pd.to_numeric(out[out_column], errors="coerce").fillna(default_factor)

    surface = out[surface_column] if surface_column in out.columns else pd.Series(None, index=out.index)
    highway = out[highway_column] if highway_column in out.columns else pd.Series(None, index=out.index)
    out[CIVIL_CLASS_COLUMN] = [
        str(s) if not _is_missing(s) else (f"highway:{h}" if not _is_missing(h) else None)
        for s, h in zip(surface, highway)
    ]
    return out


def buffer_osm_lines(
    osm_gdf: gpd.GeoDataFrame,
    *,
    highway_column: str = "highway",
    halfwidth_m: dict | None = None,
    fallback_m: float = DEFAULT_OSM_HALFWIDTH_FALLBACK,
) -> gpd.GeoDataFrame:
    """Turn OSM lines into narrow polygons for the overlay.

    The half width follows the ``highway`` class; flat caps avoid half
    circles at junctions. Expects a metric CRS.
    """
    widths = halfwidth_m if halfwidth_m is not None else DEFAULT_OSM_HALFWIDTH_M
    out = osm_gdf.copy()

    def _width(hw):
        if _is_missing(hw):
            return fallback_m
        return float(widths.get(str(hw), fallback_m))

    if highway_column in out.columns:
        half = out[highway_column].map(_width).astype(float)
    else:
        half = pd.Series(fallback_m, index=out.index, dtype=float)

    out["geometry"] = out.geometry.buffer(half.to_numpy(), cap_style="flat")
    return out


def _user_agent() -> str:
    # overpass-api.de answers 406 to requests without a meaningful User-Agent.
    try:
        v = version("fheat")
    except PackageNotFoundError:
        v = "dev"
    return f"fheat/{v} (+https://github.com/F-Heat/fheat)"


def get_osm_surface_via_overpass(
    bbox_wgs84: tuple[float, float, float, float],
    overpass_url: str = OVERPASS_URL,
    timeout: int = OSM_TIMEOUT,
    retries: int = OSM_RETRIES,
) -> gpd.GeoDataFrame:
    """OSM ``highway`` lines in a bbox via the Overpass API.

    ``bbox_wgs84`` = (south, west, north, east) in EPSG:4326. Returns a
    GeoDataFrame in EPSG:4326 with the columns ``osm_id``, ``highway``,
    ``surface`` (often missing), ``tracktype``, ``width`` and ``lanes``.
    """
    south, west, north, east = bbox_wgs84
    query = (
        f"[out:json][timeout:{int(timeout)}];"
        f'way["highway"]({south},{west},{north},{east});'
        "out tags geom;"
    )
    data = urllib.parse.urlencode({"data": query}).encode("utf-8")
    req = urllib.request.Request(
        overpass_url, data=data, headers={"User-Agent": _user_agent()}
    )
    for attempt in range(1, max(1, retries) + 1):
        cancel.raise_if_cancelled()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            if e.code in _OSM_RETRY_STATUS and attempt < retries:
                cancel.sleep(OSM_RETRY_WAIT * attempt)
                continue
            raise RuntimeError(f"Overpass-Anfrage an '{overpass_url}' fehlgeschlagen: {e}") from e
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
            raise RuntimeError(f"Overpass-Anfrage an '{overpass_url}' fehlgeschlagen: {e}") from e

    rows: list[dict] = []
    geoms: list = []
    for el in payload.get("elements", []):
        if el.get("type") != "way":
            continue
        geom = el.get("geometry")
        if not geom or len(geom) < 2:
            continue
        line = LineString([(pt["lon"], pt["lat"]) for pt in geom])
        if line.is_empty:
            continue
        tags = el.get("tags", {}) or {}
        rows.append({"osm_id": el.get("id"), **{c: tags.get(c) for c in _OSM_COLUMNS[1:]}})
        geoms.append(line)
    if not rows:
        return gpd.GeoDataFrame({c: [] for c in _OSM_COLUMNS}, geometry=[], crs="EPSG:4326")
    return gpd.GeoDataFrame(rows, geometry=geoms, crs="EPSG:4326")
