from dataclasses import dataclass
from enum import Enum
from typing import Optional

import geopandas as gpd
import pandas as pd


class Phase(str, Enum):
    INITIAL = "initial"
    DOWNLOADED = "downloaded"
    ADJUSTED = "adjusted"
    STATUS = "status"
    NETWORK = "network"
    RESULTS = "results"


@dataclass
class PipelineState:
    phase: Phase = Phase.INITIAL

    # Input data — populated by the adapter, must satisfy input schemas
    buildings_gdf: Optional[gpd.GeoDataFrame] = None
    streets_gdf: Optional[gpd.GeoDataFrame] = None
    parcels_gdf: Optional[gpd.GeoDataFrame] = None
    source_gdf: Optional[gpd.GeoDataFrame] = None  # only needed from NETWORK on

    # Civil works layers (optional, see DataAdapter.fetch_landuse /
    # fetch_osm_surface). None → civil works factor 1.0.
    landuse_gdf: Optional[gpd.GeoDataFrame] = None
    osm_surface_gdf: Optional[gpd.GeoDataFrame] = None

    # Planning area of the network (one or more polygons). The analysis steps
    # always work on the whole area of the input frames; NETWORK and RESULTS
    # connect only the buildings inside this area. None → all buildings.
    planning_area_gdf: Optional[gpd.GeoDataFrame] = None

    # Pipeline outputs — created by the core, satisfy output schemas
    wld_gdf: Optional[gpd.GeoDataFrame] = None
    polygons_gdf: Optional[gpd.GeoDataFrame] = None
    net_gdf: Optional[gpd.GeoDataFrame] = None

    # Results
    load_profile_df: Optional[pd.DataFrame] = None
    pipe_summary_df: Optional[pd.DataFrame] = None       # pipe quantities per DN
    building_summary_df: Optional[pd.DataFrame] = None   # connected buildings per load profile
    result_summary: Optional[dict] = None
