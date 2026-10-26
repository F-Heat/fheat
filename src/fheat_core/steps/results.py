"""Step RESULTS: load profiles, result summary and result tables."""
from __future__ import annotations

import logging

import geopandas as gpd
import pandas as pd
from shapely.ops import unary_union

from fheat_core import columns as cols
from fheat_core.algorithms.network import calculate_glf
from fheat_core.algorithms.potentials import heat_source_summary, potential_summary
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
from fheat_core.weather import TemperatureYear, WeatherDataError, heating_degree_days, load_dwd_temperature

logger = logging.getLogger(__name__)


def run(state: PipelineState, config, adapter) -> PipelineState:
    if state.net_gdf is None:
        raise PipelineInputError("The RESULTS step needs the network of the NETWORK step.")
    net_gdf = state.net_gdf
    buildings = state.buildings_gdf
    buildings = buildings[connected_mask(buildings, state.planning_area_gdf)]

    temperature_year, fallback_reason = _temperature_year(state, buildings, config, adapter)

    holidays = adapter.provide_holidays()
    if holidays is None:
        holidays = load_default_holidays(config.year)

    load_profile_df = build_load_profile(
        buildings_gdf=buildings,
        net_gdf=net_gdf,
        year=config.year,
        temperature=temperature_year.series,
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
        cols.TOTAL_HEAT_DEMAND: round(total_heat, 3),
        cols.TOTAL_BUILDINGS: n_buildings,
        cols.TOTAL_POWER_GLF: round(total_power_glf, 1),
        cols.GLF: round(glf, 4),
        cols.TOTAL_NETWORK_LENGTH: round(net_length, 1),
        cols.TOTAL_LOSS: round(total_loss, 3),
        cols.SUPPLY_TEMPERATURE: config.supply_temperature,
        cols.RETURN_TEMPERATURE: config.return_temperature,
        cols.TOTAL_HOUSE_CONNECTION_LENGTH: round(house_connection_length, 1),
        cols.TOTAL_ROUTE_LENGTH: round(route_length, 1),
        cols.TOTAL_LOSS_EXTRA_INSULATION: round(total_loss_extra, 3),
    }
    summary.update(_temperature_summary(temperature_year, config.year, fallback_reason))
    summary.update(_civil_cost_summary(net_gdf, config.civil_cost_share))
    summary.update(potential_summary(
        buildings, state.geothermal_blocks_gdf, state.geothermal_deep_gdf, state.solar_thermal_gdf
    ))
    summary.update(heat_source_summary(
        state.wastewater_gdf, state.industrial_heat_gdf, state.waste_incineration_gdf, state.river_heat_gdf,
        state.hydrothermal_gdf,
    ))

    RESULT_SUMMARY_SCHEMA.validate(summary)

    pipe_summary_df = summarize_pipes(net_gdf, resolve_pipe_info(adapter))
    building_summary_df = summarize_buildings(buildings)
    PipeSummarySchema.validate(pipe_summary_df)
    BuildingSummarySchema.validate(building_summary_df)

    state.load_profile_df = load_profile_df
    state.result_summary = summary
    state.temperature_info = {
        "source": temperature_year.source,
        "station_id": temperature_year.station_id,
        "station_name": temperature_year.station_name,
        "distance_km": temperature_year.distance_km,
        "coverage": temperature_year.coverage,
        "year": config.year if temperature_year.source == "dwd" else None,
        "fallback_reason": fallback_reason,
    }
    state.pipe_summary_df = pipe_summary_df
    state.building_summary_df = building_summary_df
    state.phase = Phase.RESULTS
    return state


def _temperature_year(state: PipelineState, buildings, config, adapter) -> tuple[TemperatureYear, str | None]:
    """Outdoor temperatures of the load profile and, after a fallback, why.

    Order: the series of the adapter, the DWD year at the centre of the
    planning area (else of the connected buildings) when
    ``config.temperature_source == "dwd"``, the example year.
    """
    temperature = adapter.provide_temperature()
    if temperature is not None:
        return TemperatureYear(series=temperature, source="adapter"), None
    reason = None
    if config.temperature_source == "dwd":
        try:
            lat, lon = _area_centre(state.planning_area_gdf, buildings)
            return load_dwd_temperature(lat, lon, config.year), None
        except (WeatherDataError, ImportError) as e:
            if not config.temperature_fallback:
                raise
            logger.warning("DWD temperature year not available, using the example year: %s", e)
            reason = str(e)
    return TemperatureYear(series=load_default_temperature(), source="example"), reason


def _area_centre(planning_area_gdf, buildings) -> tuple[float, float]:
    """(lat, lon) in WGS84 of the planning area, else of the buildings."""
    frame = planning_area_gdf if planning_area_gdf is not None and not planning_area_gdf.empty else buildings
    if frame is None or frame.empty or frame.crs is None:
        raise WeatherDataError("The place of the DWD temperature year is unknown: no planning area or buildings with a CRS.")
    # centroid in the projected CRS of the data, then to WGS84
    centre = gpd.GeoSeries([unary_union(list(frame.geometry)).centroid], crs=frame.crs).to_crs("EPSG:4326").iloc[0]
    return centre.y, centre.x


def _temperature_summary(temperature_year: TemperatureYear, year: int, fallback_reason: str | None) -> dict:
    """Temperature keys of the summary (source, station, plausibility figures)."""
    series = temperature_year.series
    out: dict = {cols.TEMPERATURE_SOURCE: temperature_year.source}
    if temperature_year.source == "dwd":
        out[cols.WEATHER_STATION_ID] = temperature_year.station_id
        out[cols.WEATHER_STATION_NAME] = temperature_year.station_name
        out[cols.WEATHER_STATION_DISTANCE] = temperature_year.distance_km
        out[cols.WEATHER_YEAR] = year
    out[cols.MEAN_OUTDOOR_TEMPERATURE] = round(float(series.mean()), 2)
    out[cols.MIN_OUTDOOR_TEMPERATURE] = round(float(series.min()), 1)
    out[cols.HEATING_DEGREE_DAYS] = round(heating_degree_days(series))
    if fallback_reason:
        out[cols.TEMPERATURE_FALLBACK_REASON] = fallback_reason
    return out


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
        out[cols.CIVIL_COST_SHARE] = civil_cost_share
        out[cols.TOTAL_PIPE_COST] = round(float(net_gdf[cols.PIPE_COST].sum()), 2)
        if cols.CIVIL_COST in net_gdf.columns:
            out[cols.TOTAL_CIVIL_COST] = round(float(net_gdf[cols.CIVIL_COST].sum()), 2)
    if cols.CIVIL_COST_FACTOR in net_gdf.columns:
        factor = pd.to_numeric(net_gdf[cols.CIVIL_COST_FACTOR], errors="coerce")
        weight = length.where(factor.notna(), 0.0)
        if weight.sum() > 0:
            out.setdefault(cols.CIVIL_COST_SHARE, civil_cost_share)
            out[cols.MEAN_CIVIL_COST_FACTOR] = round(float((factor.fillna(0.0) * weight).sum() / weight.sum()), 4)
    return out
