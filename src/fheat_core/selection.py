"""Which buildings the network planning connects.

The analysis steps (download, adjust, status) always work on the complete
input area, e.g. a whole town, so that the heat line density and the
suitability polygons show where a network makes sense. The planning steps
(network, results) then connect only the buildings that

* have ``connect == 1`` and
* lie inside ``PipelineState.planning_area_gdf`` (if set).

The ``connect`` flags themselves are never changed for the planning area, so
user edits survive and a different planning area can be tried at any time.
"""
from __future__ import annotations

from typing import Optional

import geopandas as gpd
import pandas as pd
from shapely.ops import unary_union

from fheat_core import columns as cols


def _area_set(planning_area: Optional[gpd.GeoDataFrame]) -> bool:
    return planning_area is not None and not planning_area.empty


def area_union(planning_area: gpd.GeoDataFrame, crs):
    """Planning area as one geometry in ``crs``."""
    area = planning_area
    if crs is not None and area.crs is not None and area.crs != crs:
        area = area.to_crs(crs)
    return unary_union(area.geometry.values)


def in_planning_area(
    buildings: gpd.GeoDataFrame,
    planning_area: Optional[gpd.GeoDataFrame],
) -> pd.Series:
    """True for buildings whose representative point lies inside the area.

    Without a planning area every building counts as inside.
    """
    if not _area_set(planning_area) or buildings.empty:
        return pd.Series(True, index=buildings.index)
    area = area_union(planning_area, buildings.crs)
    return buildings.geometry.representative_point().within(area)


def connected_mask(
    buildings: gpd.GeoDataFrame,
    planning_area: Optional[gpd.GeoDataFrame] = None,
) -> pd.Series:
    """Buildings the network planning connects: ``connect == 1`` and inside the area."""
    if cols.CONNECT in buildings.columns:
        mask = buildings[cols.CONNECT] == 1
    else:
        mask = pd.Series(True, index=buildings.index)
    return mask & in_planning_area(buildings, planning_area)


def clip_to_area(
    gdf: gpd.GeoDataFrame,
    planning_area: Optional[gpd.GeoDataFrame],
) -> gpd.GeoDataFrame:
    """Features intersecting the planning area (unchanged without an area)."""
    if gdf is None or gdf.empty or not _area_set(planning_area):
        return gdf
    area = area_union(planning_area, gdf.crs)
    return gdf[gdf.geometry.intersects(area)]
