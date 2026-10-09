"""Step RESULTS: load profiles, result summary and result tables."""
from __future__ import annotations

import pandas as pd

from fheat_core import columns as cols
from fheat_core.algorithms.network import calculate_glf
from fheat_core.algorithms.slp import build_load_profile
from fheat_core.algorithms.summary import network_length_split, summarize_buildings, summarize_pipes
from fheat_core.errors import PipelineInputError
from fheat_core.resources import load_default_holidays, load_default_temperature, resolve_pipe_info
from fheat_core.schemas import (
    LOAD_PROFILE_SCHEMA,
    RESULT_SUMMARY_SCHEMA,
    BuildingSummarySchema,
    PipeSummarySchema,
)
from fheat_core.selection import connected_mask
from fheat_core.state import Phase, PipelineState


def run(state: PipelineState, config, adapter) -> PipelineState:
    if state.net_gdf is None:
        raise PipelineInputError("The RESULTS step needs the network of the NETWORK step.")
    net_gdf = state.net_gdf
    buildings = state.buildings_gdf
    buildings = buildings[connected_mask(buildings, state.planning_area_gdf)]

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
    summary.update(_civil_cost_summary(net_gdf, config.civil_cost_share))

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


def _civil_cost_summary(net_gdf, civil_cost_share: float) -> dict:
    """Pipe investment and civil works keys of the summary.

    Left out (not set to 0) when the net carries no civil works factors or
    no pipe costs, e.g. a net computed before they existed or a pipe
    catalogue without cost columns.
    """
    out: dict = {}
    if net_gdf.empty:
        return out
    length = pd.to_numeric(net_gdf[cols.LENGTH], errors="coerce").fillna(0.0)
    if cols.PIPE_COST in net_gdf.columns and net_gdf[cols.PIPE_COST].notna().any():
        out["civil_cost_share"] = civil_cost_share
        out["total_pipe_cost_eur"] = round(float(net_gdf[cols.PIPE_COST].sum()), 2)
        if cols.CIVIL_COST in net_gdf.columns:
            out["total_civil_cost_eur"] = round(float(net_gdf[cols.CIVIL_COST].sum()), 2)
    if cols.CIVIL_COST_FACTOR in net_gdf.columns:
        factor = pd.to_numeric(net_gdf[cols.CIVIL_COST_FACTOR], errors="coerce")
        weight = length.where(factor.notna(), 0.0)
        if weight.sum() > 0:
            out.setdefault("civil_cost_share", civil_cost_share)
            out["mean_civil_cost_factor"] = round(float((factor.fillna(0.0) * weight).sum() / weight.sum()), 4)
    return out
