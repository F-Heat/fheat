"""Step DOWNLOADED: fetch data from adapter."""
from __future__ import annotations

from fheat_core.state import Phase, PipelineState


def run(state: PipelineState, config, adapter) -> PipelineState:
    state.buildings_gdf = adapter.fetch_buildings()
    state.streets_gdf = adapter.fetch_streets()
    state.parcels_gdf = adapter.fetch_parcels()
    state.source_gdf = adapter.fetch_source()
    state.phase = Phase.DOWNLOADED
    return state
