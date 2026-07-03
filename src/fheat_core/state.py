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
    source_gdf: Optional[gpd.GeoDataFrame] = None

    # Pipeline outputs — created by the core, satisfy output schemas
    wld_gdf: Optional[gpd.GeoDataFrame] = None
    polygons_gdf: Optional[gpd.GeoDataFrame] = None
    net_gdf: Optional[gpd.GeoDataFrame] = None

    # Results
    load_profile_df: Optional[pd.DataFrame] = None
    result_summary: Optional[dict] = None
