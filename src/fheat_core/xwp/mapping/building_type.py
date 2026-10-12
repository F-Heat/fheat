"""Building type after WP_GebaeudeTyp (XWaermeplan) from the data a source provides.

Order of evidence:

1. the residential type of the source (LANUV ``GEBAEUDETY``: EFH, RH, MFH,
   GMFH) gives the subtypes 10001-10004,
2. otherwise the ALKIS building function (last four digits of
   ``citygml_fu``) via ``fheat_core/data/xwp_gebaeudetyp.json``,
3. otherwise the load profile, but only to the upper category (1000 for
   EFH/MFH, 2000 for the commercial profiles): a default profile must not
   pretend a detached house,
4. otherwise 9999 (unknown).
"""
from __future__ import annotations

import functools
import json
from importlib.resources import files

import pandas as pd

from fheat_core import columns as cols

UNKNOWN = "9999"
RESIDENTIAL, NON_RESIDENTIAL = "1000", "2000"
SOURCE_TYPES = {"EFH": "10001", "RH": "10002", "MFH": "10003", "GMFH": "10004"}
LOAD_PROFILES = {"EFH": RESIDENTIAL, "MFH": RESIDENTIAL, "GKO": NON_RESIDENTIAL,
                 "GMK": NON_RESIDENTIAL, "GHA": NON_RESIDENTIAL}


@functools.lru_cache(maxsize=1)
def function_table() -> dict[str, str]:
    """ALKIS function code (four digits) -> WP_GebaeudeTyp code."""
    data = json.loads(files("fheat_core.data").joinpath("xwp_gebaeudetyp.json").read_text(encoding="utf-8"))
    return {code: entry["xwp_gebaeudetyp"] for code, entry in data["funktionen"].items()}


def building_type_code(function=None, building_type=None, load_profile=None) -> str:
    """WP_GebaeudeTyp code for one building; arguments may be None/NA."""
    if _present(building_type):
        code = SOURCE_TYPES.get(str(building_type).strip().upper())
        if code:
            return code
    if _present(function):
        code = function_table().get(str(function).strip()[-4:])
        if code:
            return code
    if _present(load_profile):
        code = LOAD_PROFILES.get(str(load_profile).strip().upper())
        if code:
            return code
    return UNKNOWN


def assign_building_types(buildings: pd.DataFrame) -> pd.Series:
    """WP_GebaeudeTyp codes for a buildings frame with canonical columns."""

    def column(name):
        return buildings[name] if name in buildings.columns else pd.Series(None, index=buildings.index)

    codes = [
        building_type_code(f, t, p)
        for f, t, p in zip(column(cols.FUNCTION), column(cols.BUILDING_TYPE), column(cols.LOAD_PROFILE))
    ]
    return pd.Series(codes, index=buildings.index, dtype="string")


def _present(v) -> bool:
    return v is not None and not (isinstance(v, float) and pd.isna(v)) and v is not pd.NA and str(v).strip() != ""
