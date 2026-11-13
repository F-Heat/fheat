"""Estimate a building that no data source has.

For a building added by hand (a new or planned one, or one the data source
lacks): its footprint, ALKIS building function (AdV, the same in every
state), storeys and age class give the other attributes, the way the NRW
adapter estimates its buildings (:mod:`fheat_nrw.processing`,
:mod:`fheat_nrw.building_gaps`):

- net floor area = :data:`NET_FLOOR_FACTOR` × footprint × storeys;
- load profile and full load hours of the function
  (``building_functions.json``); a house (a function with load profile EFH)
  is an EFH or MFH, as given, else an MFH above :data:`EFH_MAX_FLOOR_AREA`;
- specific heat demand of the age class for EFH and MFH
  (``building_age_classes.json``), of the function for all others;
- heat demand = net floor area × specific heat demand, thermal power = heat
  demand / full load hours.

Every derived value may be given instead (``floor_area``, ``load_profile``,
``specific_heat_demand``, ``full_load_hours``, ``heat_demand``); what follows
from it is calculated with the given value.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from importlib.resources import files
from typing import Any, Optional

from fheat_core import columns as cols

#: ALKIS function of a building without one: Wohnhaus.
DEFAULT_FUNCTION = "1010"
#: Storeys of a building without any (the median of the new WBM-NRW buildings in Vreden).
DEFAULT_STOREYS = 2
#: Net floor area per m² footprint and storey, as WBM-NRW computes it.
NET_FLOOR_FACTOR = 0.7
#: Largest net floor area [m²] of a single-family house (the largest EFH of WBM-NRW in Vreden).
EFH_MAX_FLOOR_AREA = 280.0
#: Full load hours of a building whose function has none.
DEFAULT_FULL_LOAD_HOURS = 1600
#: Building type of a building that is no single- or multi-family house.
NON_RESIDENTIAL = "NWG"
#: Building types of a house: single- and multi-family house, also their load profiles.
HOUSE_TYPES = ("EFH", "MFH")


@lru_cache(maxsize=None)
def building_functions() -> dict[str, dict[str, Any]]:
    """The ALKIS building functions by their four digits ("1010"): ``Lastprofil``, ``Vlh``, ``WVBRpEBF``, ``bez`` …"""
    return _read("building_functions.json")


@lru_cache(maxsize=None)
def age_classes() -> dict[str, dict[str, Any]]:
    """The age classes ("A" … "L"): ``baujahre``, ``waerme_efh_kwh_m2a``, ``waerme_mfh_kwh_m2a``."""
    return _read("building_age_classes.json")


def load_profiles() -> set[str]:
    """The BDEW load profiles of the building functions, and MFH for the larger houses."""
    return {info["Lastprofil"] for info in building_functions().values() if info.get("Lastprofil")} | {"MFH"}


def house_functions() -> set[str]:
    """The functions of houses (load profile EFH): they are an EFH or MFH, with the demand of their age class."""
    return {code for code, info in building_functions().items() if info.get("Lastprofil") == "EFH"}


def newest_age_class() -> str:
    """The newest age class, the one of a building built today."""
    return max(age_classes())


def function_code(function: Any) -> str:
    """The four digits of an ALKIS building function, also in the CityGML form "31001_1010"."""
    match = re.fullmatch(r"(?:\d+_)?(\d{4})", str(function).strip())
    if not match:
        raise ValueError(f"{function!r} is no ALKIS building function (four digits, e.g. 1010).")
    return match.group(1)


def estimate_building(
    footprint_area: float,
    *,
    function: Any = DEFAULT_FUNCTION,
    storeys: float = DEFAULT_STOREYS,
    age_class: Optional[str] = None,
    building_type: Optional[str] = None,
    floor_area: Optional[float] = None,
    load_profile: Optional[str] = None,
    specific_heat_demand: Optional[float] = None,
    full_load_hours: Optional[float] = None,
    heat_demand: Optional[float] = None,
) -> dict[str, Any]:
    """The attributes of one building, by the canonical column names.

    ``footprint_area`` [m²] of the building's polygon; ``age_class`` defaults
    to the newest one. ``building_type`` EFH or MFH makes a house one; other
    functions ignore it. A given ``heat_demand`` is the building's heat demand
    under every heat demand basis: the result then has no
    ``heat_demand_calculated`` (``FHeatConfig.heat_demand_basis`` falls back
    to ``heat_demand``). Raises ValueError for an unknown function or age
    class, building type or load profile, for a function F|Heat has no load profile for and
    for values that are not positive.
    """
    _positive("footprint_area", footprint_area)
    _positive("storeys", storeys)
    code = function_code(function)
    info = building_functions().get(code)
    if info is None:
        raise ValueError(f"Unknown ALKIS building function {code}.")
    age_class = newest_age_class() if age_class is None else str(age_class).strip().upper()
    age = age_classes().get(age_class)
    if age is None:
        raise ValueError(f"Unknown age class {age_class!r}, known are {', '.join(age_classes())}.")

    if floor_area is None:
        floor_area = NET_FLOOR_FACTOR * footprint_area * storeys
    _positive("floor_area", floor_area)
    house = code in house_functions()
    if house:
        if building_type is not None:
            building_type = str(building_type).strip().upper()
            if building_type not in HOUSE_TYPES:
                raise ValueError(f"A house is an EFH or MFH, not {building_type!r}.")
        elif load_profile in HOUSE_TYPES:
            building_type = load_profile
        else:
            building_type = "MFH" if floor_area > EFH_MAX_FLOOR_AREA else "EFH"
    if load_profile is None:
        load_profile = building_type if house else info.get("Lastprofil")
        if not load_profile:
            raise ValueError(f"F|Heat has no load profile for the building function {code} ({info.get('bez')}).")
    elif load_profile not in load_profiles():
        raise ValueError(f"Unknown load profile {load_profile!r}, known are {', '.join(sorted(load_profiles()))}.")
    if full_load_hours is None:
        full_load_hours = info.get("Vlh") or DEFAULT_FULL_LOAD_HOURS
    _positive("full_load_hours", full_load_hours)

    if specific_heat_demand is not None:
        if not specific_heat_demand >= 0:
            raise ValueError(f"specific_heat_demand must not be negative, got {specific_heat_demand!r}.")
        specific = specific_heat_demand
    elif load_profile == "EFH":
        specific = age["waerme_efh_kwh_m2a"]
    elif load_profile == "MFH":
        specific = age["waerme_mfh_kwh_m2a"]
    else:
        specific = info.get("WVBRpEBF") or 0.0
    calculated = float(floor_area) * float(specific)

    out = {
        cols.FUNCTION: str(function).strip(),
        cols.USAGE: info.get("bez"),
        cols.BUILDING_TYPE: building_type if house else NON_RESIDENTIAL,
        cols.CONSTRUCTION_CLASS: age_class,
        cols.STOREYS: float(storeys),
        cols.FLOOR_AREA: float(floor_area),
        cols.SPECIFIC_HEAT_DEMAND: float(specific),
        cols.LOAD_PROFILE: load_profile,
        cols.FULL_LOAD_HOURS: float(full_load_hours),
    }
    if heat_demand is None:
        out[cols.HEAT_DEMAND_CALCULATED] = calculated
        heat_demand = calculated
    elif not heat_demand >= 0:  # also rejects NaN, e.g. an empty table cell
        raise ValueError(f"heat_demand must not be negative, got {heat_demand!r}.")
    out[cols.HEAT_DEMAND] = float(heat_demand)
    out[cols.THERMAL_POWER] = float(heat_demand) / float(full_load_hours)
    return out


def _positive(name: str, value) -> None:
    if value is None or not value > 0:
        raise ValueError(f"{name} must be positive, got {value!r}.")


def _read(name: str) -> dict:
    with files("fheat_de.data").joinpath(name).open("r", encoding="utf-8") as f:
        return json.load(f)
