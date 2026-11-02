"""Streets of any source as the core expects them: LineStrings, all routable."""
from __future__ import annotations

import geopandas as gpd
from shapely.geometry import LineString, MultiLineString

from fheat_core import columns as cols


def process_streets(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Round coordinates to 3 decimals, force LineString, add Moegliche_Route=1."""
    gdf = gdf.copy()

    def to_linestring(geom):
        if isinstance(geom, MultiLineString):
            return LineString(list(geom.geoms)[0].coords)
        return geom

    def round_coords(line):
        return LineString([(round(x, 3), round(y, 3)) for x, y in line.coords])

    gdf["geometry"] = gdf["geometry"].apply(to_linestring).apply(round_coords)
    gdf[cols.ROUTABLE] = 1
    return gdf
