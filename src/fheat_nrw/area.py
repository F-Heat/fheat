"""NRW districts (Gemarkungen): which parcels carry a district key.

The outline and the clip are the same in every state (:mod:`fheat_de.area`).
"""
from __future__ import annotations

import geopandas as gpd

from fheat_de.area import boundary_from_parcels, clip_to_boundary  # noqa: F401

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


def district_boundary(parcels: gpd.GeoDataFrame, district_key) -> gpd.GeoDataFrame:
    """Outline of one district."""
    return boundary_from_parcels(district_parcels(parcels, district_key))
