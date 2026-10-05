"""Step RESULTS: load profiles, result summary and result tables."""
from __future__ import annotations

from fheat_core import columns as cols
from fheat_core.algorithms.network import calculate_glf
from fheat_core.algorithms.slp import build_load_profile
from fheat_core.algorithms.summary import network_length_split, summarize_buildings, summarize_pipes
from fheat_core.resources import load_default_holidays, load_default_temperature, resolve_pipe_info
from fheat_core.schemas import (
    LOAD_PROFILE_SCHEMA,
    RESULT_SUMMARY_SCHEMA,
    BuildingSummarySchema,
    PipeSummarySchema,
)
from fheat_core.state import Phase, PipelineState


def run(state: PipelineState, config, adapter) -> PipelineState:
    net_gdf = state.net_gdf
    buildings = state.buildings_gdf

    if cols.CONNECT in buildings.columns:
        buildings = buildings[buildings[cols.CONNECT] == 1]

    temperature = adapter.provide_temperature()
    if temperature is None:
        temperature = load_default_temperature()

    holidays = adapter.provide_holidays()
    if holidays is None:
        holidays = load_default_holidays(config.year)

    load_profile_df = build_load_profile(
        buildings_gdf=buildings,
        net_gdf=net_gdf,
        year=config.year,
        temperature=temperature,
        holidays=holidays,
        building_class=config.building_class,
        wind_class=config.wind_class,
    )

    LOAD_PROFILE_SCHEMA.validate(load_profile_df)

    # result summary
    n_buildings = int((buildings[cols.CONNECT] == 1).sum()) if cols.CONNECT in buildings.columns else len(buildings)
    total_heat = buildings[cols.HEAT_DEMAND].sum() / 1000  # → MWh/a
    total_power_kw = net_gdf[cols.THERMAL_POWER].max() if cols.THERMAL_POWER in net_gdf.columns else 0.0
    glf = calculate_glf(n_buildings)
    total_power_glf = total_power_kw * glf
    net_length = net_gdf[cols.LENGTH].sum() if cols.LENGTH in net_gdf.columns else 0.0
    total_loss = net_gdf[cols.HEAT_LOSS].sum() / 1000 if cols.HEAT_LOSS in net_gdf.columns else 0.0
    total_loss_extra = (
        net_gdf[cols.HEAT_LOSS_EXTRA_INSULATION].sum() / 1000
        if cols.HEAT_LOSS_EXTRA_INSULATION in net_gdf.columns
        else 0.0
    )
    house_connection_length, route_length = network_length_split(net_gdf)

    summary = {
        "total_heat_demand_mwh_a": round(total_heat, 3),
        "total_buildings": n_buildings,
        "total_power_glf_kw": round(total_power_glf, 1),
        "glf": round(glf, 4),
        "total_network_length_m": round(net_length, 1),
        "total_loss_mwh_a": round(total_loss, 3),
        "supply_temperature_c": config.supply_temperature,
        "return_temperature_c": config.return_temperature,
        "total_house_connection_length_m": round(house_connection_length, 1),
        "total_route_length_m": round(route_length, 1),
        "total_loss_extra_insulation_mwh_a": round(total_loss_extra, 3),
    }

    RESULT_SUMMARY_SCHEMA.validate(summary)

    pipe_summary_df = summarize_pipes(net_gdf, resolve_pipe_info(adapter))
    building_summary_df = summarize_buildings(buildings)
    PipeSummarySchema.validate(pipe_summary_df)
    BuildingSummarySchema.validate(building_summary_df)

    state.load_profile_df = load_profile_df
    state.result_summary = summary
    state.pipe_summary_df = pipe_summary_df
    state.building_summary_df = building_summary_df
    state.phase = Phase.RESULTS
    return state
