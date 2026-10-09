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

    def fetch_source(self) -> Optional[gpd.GeoDataFrame]:
        """Heat source(s) conforming to SourceSchema (Point geometry).

        Optional: only the NETWORK step needs a heat source. ``None`` lets the
        analysis steps (download, adjust, status) run without one; the source
        can be set later on ``PipelineState.source_gdf``.
        """
        return None

    def provide_boundary(self) -> Optional[gpd.GeoDataFrame]:
        """Optional: outline of the analysed area (one (Multi)Polygon). None → unknown."""
        return None

    # Civil works layers — each one yields a factor per route (see
    # fheat_core.algorithms.civil_cost). None → factor 1.0, no error.
    def fetch_landuse(self) -> Optional[gpd.GeoDataFrame]:
        """Optional: land use polygons with a ``civil_cost_factor`` column.

        An optional ``civil_class`` column names the land use class.
        """
        return None

    def fetch_osm_surface(self) -> Optional[gpd.GeoDataFrame]:
        """Optional: buffered road polygons with ``civil_cost_factor`` and
        ``civil_class`` (the road surface, e.g. ``asphalt``)."""
        return None

    # Optional data — default implementation returns None;
    # the core then loads its own default.
    def provide_pipe_info(self) -> Optional[pd.DataFrame]:
        """Optional: pipe catalogue (DN, di, U-Value, max_volumeFlow). None → core default.

        The cost columns cost_main and cost_h-connect [€/m] are optional:
        without them the network gets no pipe costs (a warning is logged).
        """
        return None

    def provide_temperature(self) -> Optional[pd.Series]:
        """Optional: 8760 hourly temperatures [°C]. None → core default."""
        return None

    def provide_holidays(self) -> Optional[dict]:
        """Optional: public holidays as {date: name} dict. None → core default."""
        return None
