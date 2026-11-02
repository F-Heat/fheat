"""3D building model LoD2 (CityGML 1.0) of the German states.

Every state publishes its LoD2 buildings as CityGML tiles named by their
lower left corner; what differs is the URL, the tile size and the name
pattern, which the state adapter knows. Read here: the id, the highest
``measuredHeight`` and the footprint of every building, e.g. to estimate the
storeys of buildings the heat demand data does not have. Where a tile has
the generic attribute ``MittlereTraufHoehe`` (mean eaves height above sea
level, Lower Saxony), ``eaves_height`` is its height above the lowest point
of the ground surface; NaN otherwise.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Polygon
from shapely.ops import unary_union

_NS = {
    "bldg": "http://www.opengis.net/citygml/building/1.0",
    "gml": "http://www.opengis.net/gml",
    "gen": "http://www.opengis.net/citygml/generics/1.0",
}
_BUILDING = f"{{{_NS['bldg']}}}Building"
_GML_ID = f"{{{_NS['gml']}}}id"
_EAVES = ".//gen:stringAttribute[@name='MittlereTraufHoehe']/gen:value"
COLUMNS = ["lod2_id", "height", "eaves_height", "geometry"]
#: CRS of the tiles of the states in UTM zone 32.
LOD2_CRS = "EPSG:25832"


def tile_names(geometries: gpd.GeoSeries, pattern: str, size_km: int = 1) -> list[str]:
    """Names of the tiles the points of ``geometries`` lie in, sorted.

    ``pattern`` takes ``x`` and ``y``, the lower left corner in km (e.g.
    ``"LoD2_32_{x}_{y}_1_NW.gml"``); ``size_km`` is the edge of a tile.
    ``geometries`` must be in the CRS of the tiles.
    """
    size = size_km * 1000
    corners = {
        (int(p.x // size) * size_km, int(p.y // size) * size_km) for p in geometries.representative_point()
    }
    return [pattern.format(x=x, y=y) for x, y in sorted(corners)]


def read_lod2(path: Path, crs: str = LOD2_CRS) -> gpd.GeoDataFrame:
    """Buildings of a LoD2 tile: ``lod2_id``, ``height`` (highest measuredHeight), ``eaves_height``, footprint."""
    rows = []
    for _, element in ET.iterparse(str(path), events=("end",)):
        if element.tag != _BUILDING:
            continue
        heights = [float(h.text) for h in element.iterfind(".//bldg:measuredHeight", _NS) if h.text]
        rings = [p.text for p in element.iterfind(".//bldg:GroundSurface//gml:posList", _NS)]
        grounds = [g for g in map(_footprint, rings) if g is not None]
        if heights and grounds:
            rows.append({
                "lod2_id": element.get(_GML_ID),
                "height": max(heights),
                "eaves_height": _eaves_height(element, rings),
                "geometry": unary_union(grounds),
            })
        element.clear()
    return lod2_frame(rows, crs)


def lod2_frame(rows: list[dict], crs: str = LOD2_CRS) -> gpd.GeoDataFrame:
    """LoD2 buildings as a frame with the columns of :func:`read_lod2` (also when empty)."""
    frame = pd.DataFrame(rows, columns=COLUMNS)
    frame["eaves_height"] = frame["eaves_height"].astype("float64")
    return gpd.GeoDataFrame(frame, geometry="geometry", crs=crs)


def _eaves_height(element, rings: list[Optional[str]]) -> float:
    """Highest ``MittlereTraufHoehe`` of the building and its parts above its lowest ground point."""
    eaves = [float(v.text) for v in element.iterfind(_EAVES, _NS) if (v.text or "").strip()]
    ground = [float(z) for ring in rings for z in (ring or "").split()[2::3]]
    if not eaves or not ground:
        return np.nan
    return max(eaves) - min(ground)


def _footprint(pos_list: Optional[str]) -> Optional[Polygon]:
    values = [float(v) for v in (pos_list or "").split()]
    ring = list(zip(values[0::3], values[1::3]))
    if len(ring) < 3:
        return None
    polygon = Polygon(ring)
    return polygon if polygon.is_valid else polygon.buffer(0)
