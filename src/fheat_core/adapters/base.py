from abc import ABC, abstractmethod
from typing import Optional

import geopandas as gpd
import pandas as pd


class DataAdapter(ABC):
    """
    Contract between the data source and fheat_core.

    Implementations MUST provide pre-processed data that satisfies the
    schemas in `fheat_core.schemas`.

    In particular, for `fetch_buildings`: buildings are already merged,
    annotated with heat demand, thermal power, full load hours, and load
    profile. The adapter is responsible for ALL state- and data-source-specific
    adjustments.

    Adapter configuration (paths, column names, regional parameters)
    is handled in the constructor of the concrete adapter class — NOT via
    `FHeatConfig` and NOT as method parameters.
    """

    @abstractmethod
    def fetch_buildings(self) -> gpd.GeoDataFrame:
        """Buildings conforming to BuildingsSchema."""
        ...

    @abstractmethod
    def fetch_streets(self) -> gpd.GeoDataFrame:
        """Streets conforming to StreetsSchema."""
        ...

    @abstractmethod
    def fetch_parcels(self) -> gpd.GeoDataFrame:
        """Parcels conforming to ParcelsSchema."""
        ...

    @abstractmethod
    def fetch_source(self) -> gpd.GeoDataFrame:
        """Heat source(s) conforming to SourceSchema (Point geometry)."""
        ...

    # Optional data — default implementation returns None;
    # the core then loads its own default.
    def provide_pipe_info(self) -> Optional[pd.DataFrame]:
        """Optional: pipe catalogue (DN, di, U-Value, max_volumeFlow). None → core default."""
        return None

    def provide_temperature(self) -> Optional[pd.Series]:
        """Optional: 8760 hourly temperatures [°C]. None → core default."""
        return None

    def provide_holidays(self) -> Optional[dict]:
        """Optional: public holidays as {date: name} dict. None → core default."""
        return None
