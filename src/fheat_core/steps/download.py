"""Step DOWNLOADED: fetch data from adapter."""
from __future__ import annotations

from fheat_core.algorithms.potentials import attach_potentials
from fheat_core.schemas import (
    BiogasClustersSchema,
    BiogasSchema,
    GeothermalBlocksSchema,
    GeothermalCellsSchema,
    GeothermalDeepSchema,
    GeothermalShallowSchema,
    IndustrialHeatSchema,
    RiverHeatSchema,
    SolarThermalSchema,
    StudyDHAreasSchema,
    StudyPotentialsSchema,
    WasteIncinerationSchema,
    WastewaterSchema,
)
from fheat_core.state import Phase, PipelineState


def run(state: PipelineState, config, adapter) -> PipelineState:
    state.buildings_gdf = adapter.fetch_buildings()
    state.streets_gdf = adapter.fetch_streets()
    state.parcels_gdf = adapter.fetch_parcels()
    state.source_gdf = adapter.fetch_source()
    state.landuse_gdf = adapter.fetch_landuse()
    state.osm_surface_gdf = adapter.fetch_osm_surface()
    _fetch_potentials(state, adapter)
    state.phase = Phase.DOWNLOADED
    return state


def _fetch_potentials(state: PipelineState, adapter) -> None:
    """Optional potential and heat source layers; the buildings get their block and shallow geothermal values."""
    layers = {
        "geothermal_shallow_gdf": (adapter.fetch_geothermal_shallow, GeothermalShallowSchema),
        "geothermal_blocks_gdf": (adapter.fetch_geothermal_blocks, GeothermalBlocksSchema),
        "geothermal_deep_gdf": (adapter.fetch_geothermal_deep, GeothermalDeepSchema),
        "solar_thermal_gdf": (adapter.fetch_solar_thermal, SolarThermalSchema),
        "wastewater_gdf": (adapter.fetch_wastewater, WastewaterSchema),
        "industrial_heat_gdf": (adapter.fetch_industrial_heat, IndustrialHeatSchema),
        "waste_incineration_gdf": (adapter.fetch_waste_incineration, WasteIncinerationSchema),
        "river_heat_gdf": (adapter.fetch_river_heat, RiverHeatSchema),
        "hydrothermal_gdf": (adapter.fetch_geothermal_hydrothermal, GeothermalCellsSchema),
        "study_dh_areas_gdf": (adapter.fetch_study_dh_areas, StudyDHAreasSchema),
        "study_potentials_df": (adapter.fetch_study_potentials, StudyPotentialsSchema),
        "biogas_gdf": (adapter.fetch_biogas, BiogasSchema),
        "biogas_clusters_gdf": (adapter.fetch_biogas_clusters, BiogasClustersSchema),
    }
    for attr, (fetch, schema) in layers.items():
        gdf = fetch()
        if gdf is not None and not gdf.empty:
            schema.validate(gdf)
        setattr(state, attr, gdf if gdf is not None and not gdf.empty else None)
    if state.geothermal_blocks_gdf is not None or state.geothermal_shallow_gdf is not None:
        state.buildings_gdf = attach_potentials(
            state.buildings_gdf, state.geothermal_blocks_gdf, state.geothermal_shallow_gdf
        )
