"""Step NETWORK: dispatch to the configured network backend.

The step no longer contains an algorithm. It prepares the input frames
(filtering + CRS), hands them to the backend selected by
``config.network_mode``, validates the result against ``NetSchema`` and merges
a backend-decided connection status back into the full buildings frame.
"""
from __future__ import annotations

import logging

from fheat_core import columns as cols
from fheat_core.errors import PipelineInputError
from fheat_core.network import get_backend
from fheat_core.schemas import NetSchema
from fheat_core.selection import connected_mask
from fheat_core.state import Phase, PipelineState

logger = logging.getLogger(__name__)


def run(state: PipelineState, config, adapter) -> PipelineState:
    if state.source_gdf is None or state.source_gdf.empty:
        raise PipelineInputError(
            "The NETWORK step needs a heat source. Set PipelineState.source_gdf "
            "or let the adapter provide one (fetch_source)."
        )

    buildings_all = state.buildings_gdf
    # All routable streets are kept, also outside the planning area: the heat
    # source may lie outside and the route to it must follow the streets.
    streets = state.streets_gdf.copy()
    source = state.source_gdf.copy()

    # restrict to connectable routes and buildings with heat connection
    if cols.ROUTABLE in streets.columns:
        streets = streets[streets[cols.ROUTABLE] == 1]

    buildings = buildings_all[connected_mask(buildings_all, state.planning_area_gdf)].copy()
    if buildings.empty:
        raise PipelineInputError(
            "No building to connect: no building with connect == 1 lies in the planning area."
        )

    # CRS: source to buildings CRS
    if source.crs != buildings.crs:
        source = source.to_crs(buildings.crs)

    backend = get_backend(config.network_mode)
    logger.info("NETWORK phase using backend '%s' for %d building(s)", backend.name, len(buildings))
    net_gdf, buildings_out = backend.build(buildings, streets, source, config, adapter)

    NetSchema.validate(net_gdf)

    state.net_gdf = net_gdf
    state.buildings_gdf = _merge_connect(buildings_all, buildings_out)
    state.phase = Phase.NETWORK
    return state


def _merge_connect(buildings_all, buildings_out):
    """Write a backend-decided ``connect`` flag back onto the full frame.

    Only the ``connect`` column travels back — helper columns a backend may
    have added (centroid, connection_point) must not leak into the export.
    Buildings that were already excluded before the step keep ``connect = 0``.
    """
    if cols.CONNECT not in buildings_all.columns or cols.CONNECT not in buildings_out.columns:
        return buildings_all
    if buildings_out[cols.CONNECT].equals(
        buildings_all.loc[buildings_out.index, cols.CONNECT]
    ):
        return buildings_all  # unchanged (Phase 0) — keep the original object

    merged = buildings_all.copy()
    # Replace the whole column rather than setting a slice: the adapter's
    # ``connect`` may be int32, and an int64 slice assignment into it is a
    # dtype-incompatible setitem (a FutureWarning today, an error later).
    connect = merged[cols.CONNECT].astype("int64")
    connect.loc[buildings_out.index] = (
        buildings_out[cols.CONNECT].astype("int64").to_numpy()
    )
    merged[cols.CONNECT] = connect
    n_dropped = int(
        (buildings_all[cols.CONNECT] == 1).sum() - (merged[cols.CONNECT] == 1).sum()
    )
    if n_dropped:
        logger.info("Backend left %d building(s) unconnected; connect set to 0.", n_dropped)
    return merged
