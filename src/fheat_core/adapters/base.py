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

    # Potential layers — information for the planner, no input of the
    # network calculation. None → no layer, no error.
    def fetch_geothermal_shallow(self) -> Optional[gpd.GeoDataFrame]:
        """Optional: polygons with shallow geothermal parameters.

        Columns of :mod:`fheat_core.columns` (``ground_conductivity_*``,
        ``collector_extraction_*``, ``borehole_extraction_*``,
        ``geothermal_status``); a value nobody assessed is NaN, never 0.
        """
        return None

    def fetch_geothermal_blocks(self) -> Optional[gpd.GeoDataFrame]:
        """Optional: building blocks with their geothermal potential.

        ``block_id`` (as in the buildings) and ``ong_*``/``mtg_*`` in MWh/a,
        a value of the whole block.
        """
        return None

    def fetch_geothermal_deep(self) -> Optional[gpd.GeoDataFrame]:
        """Optional: grid cells with a hydrothermal doublet potential around the area.

        ``deep_potential_mwh`` (upper bound per cell), ``distance_to_area`` and
        the cell centre as ``source_candidate_lat``/``_lon``. A suggestion
        only: the heat source is never placed automatically.
        """
        return None

    def fetch_solar_thermal(self) -> Optional[gpd.GeoDataFrame]:
        """Optional: areas for ground-mounted solar thermal around the area.

        Yield per collector type (``solar_*_mwh``) and per m², the usable area,
        ``distance_to_area`` and ``distance_to_demand``.
        """
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
        """Optional: hourly temperatures [°C] of ``FHeatConfig.year``. None → core default.

        Either a series with a DatetimeIndex covering every hour of the year,
        or 8760 values taken by position (a leap year repeats 28 February).
        The core default is the DWD year (``temperature_source="dwd"``) or
        the example year.
        """
        return None

    def provide_holidays(self) -> Optional[dict]:
        """Optional: public holidays as {date: name} dict. None → core default."""
        return None
