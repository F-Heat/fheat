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

    # Eingangsdaten — vom Adapter befüllt, müssen Eingangs-Schemas erfüllen
    buildings_gdf: Optional[gpd.GeoDataFrame] = None
    streets_gdf: Optional[gpd.GeoDataFrame] = None
    parcels_gdf: Optional[gpd.GeoDataFrame] = None
    source_gdf: Optional[gpd.GeoDataFrame] = None

    # Pipeline-Outputs — vom Core erzeugt, erfüllen Output-Schemas
    wld_gdf: Optional[gpd.GeoDataFrame] = None
    polygons_gdf: Optional[gpd.GeoDataFrame] = None
    net_gdf: Optional[gpd.GeoDataFrame] = None

    # Resultate
    load_profile_df: Optional[pd.DataFrame] = None
    result_summary: Optional[dict] = None
