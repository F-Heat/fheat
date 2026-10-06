"""Analysis areas: districts (Gemarkungen) and their outline from ALKIS parcels.

A municipality is downloaded as a whole; a district is the part of it whose
parcels carry the district key. These helpers work on any parcel frame, also
on a cached municipality download, so a district can be cut out of it without
downloading again.
"""
from __future__ import annotations

import geopandas as gpd
from shapely.ops import unary_union

#: ALKIS parcel attribute that carries the district key.
PARCEL_KEY_COLUMN = "nationalCadastralReference"


def parcel_key_prefix(district_key) -> str:
    """Prefix of ``nationalCadastralReference`` for a district.

    The reference starts with "0" + district key (e.g. "55190" → "055190…").
    """
    return "0" + str(district_key)


def district_parcels(parcels: gpd.GeoDataFrame, district_key) -> gpd.GeoDataFrame:
    """Parcels of one district."""
    if parcels.empty or PARCEL_KEY_COLUMN not in parcels.columns:
        return parcels.iloc[0:0]
    prefix = parcel_key_prefix(district_key)
    mask = parcels[PARCEL_KEY_COLUMN].astype(str).str.startswith(prefix)
    return parcels[mask]


def boundary_from_parcels(parcels: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Outline of the area covered by the parcels, as one (Multi)Polygon."""
    if parcels.empty:
        return gpd.GeoDataFrame(geometry=[], crs=parcels.crs)
    return gpd.GeoDataFrame(geometry=[unary_union(parcels.geometry.values)], crs=parcels.crs)


def district_boundary(parcels: gpd.GeoDataFrame, district_key) -> gpd.GeoDataFrame:
    """Outline of one district."""
    return boundary_from_parcels(district_parcels(parcels, district_key))


def clip_to_boundary(gdf: gpd.GeoDataFrame, boundary: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Features intersecting the boundary (features on the border are kept whole)."""
    if gdf.empty or boundary.empty:
        return gdf
    if boundary.crs is not None and gdf.crs is not None and boundary.crs != gdf.crs:
        boundary = boundary.to_crs(gdf.crs)
    if len(boundary) > 1:  # one row, otherwise sjoin duplicates features
        boundary = gpd.GeoDataFrame(geometry=[unary_union(boundary.geometry.values)], crs=boundary.crs)
    return gpd.sjoin(gdf, boundary[["geometry"]], predicate="intersects").drop(
        columns=["index_right"], errors="ignore"
    )
