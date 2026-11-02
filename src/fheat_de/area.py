"""Analysis areas: the outline of a district (Gemarkung) from its ALKIS parcels.

A municipality is downloaded as a whole; a district is the part of it whose
parcels carry the district key. Which parcel attribute holds the key differs
by state (see the state packages); the outline and the clip are the same
everywhere. These helpers work on any parcel frame, also on a cached
municipality download, so a district can be cut out of it without
downloading again.
"""
from __future__ import annotations

from pathlib import Path
from typing import IO, Union

import geopandas as gpd
import pandas as pd
from shapely.ops import unary_union

#: Columns of an area catalogue ``cities.csv``: one row per district with its
#: name and key, its municipality and AGS, and a bbox in EPSG:25832.
CATALOG_COLUMNS = ("schluessel", "gmdschl", "name", "gemeinde", "bbox")


def parse_bbox(value) -> list[float]:
    if pd.isna(value):
        raise ValueError("bbox-Wert ist leer/NaN")
    s = str(value).strip().replace("(", "").replace(")", "")
    parts = [p.strip() for p in s.split(",")]
    if len(parts) != 4:
        raise ValueError(f"bbox muss 4 Komponenten haben, gefunden {len(parts)}: '{value}'")
    return [float(p) for p in parts]


def read_catalog(source: Union[str, Path, IO[bytes]]) -> pd.DataFrame:
    """An area catalogue with string keys and parsed bboxes; RuntimeError if it is incomplete."""
    df = pd.read_csv(source)
    df = df.rename(columns={c: c.strip().lower() for c in df.columns})
    missing = set(CATALOG_COLUMNS) - set(df.columns)
    if missing:
        raise RuntimeError(f"cities.csv fehlen Spalten: {sorted(missing)}")
    df["schluessel"] = df["schluessel"].astype(str)
    df["gmdschl"] = df["gmdschl"].astype(str)
    try:
        df["bbox"] = df["bbox"].apply(parse_bbox)
    except (ValueError, TypeError) as e:
        raise RuntimeError(f"Ungueltiges bbox-Format in cities.csv: {e}") from e
    return df


def boundary_from_parcels(parcels: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Outline of the area covered by the parcels, as one (Multi)Polygon."""
    if parcels.empty:
        return gpd.GeoDataFrame(geometry=[], crs=parcels.crs)
    return gpd.GeoDataFrame(geometry=[unary_union(parcels.geometry.values)], crs=parcels.crs)


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
