"""OSM road surfaces → civil works factor: moved to :mod:`fheat_de.osm_surface`, the same in every state."""
from fheat_de.osm_surface import (  # noqa: F401
    DEFAULT_OSM_FACTOR,
    DEFAULT_OSM_HALFWIDTH_FALLBACK,
    DEFAULT_OSM_HALFWIDTH_M,
    DEFAULT_OSM_HIGHWAY_FALLBACK,
    DEFAULT_OSM_SURFACE_COST_TABLE,
    annotate_osm_surface_costs,
    buffer_osm_lines,
)
