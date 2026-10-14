"""WP_Baualtersklasse from a construction year, with the source deciding the detail.

XWaermeplan has upper classes (bis 1949, 1950-1969, 1970-1989, 1990-2015,
ab 2016) and decade-like subclasses. A true construction year gets the
subclass. The LANUV age (a representative year of a LANUV age class whose
exact bounds are not known here) and the parcel year (validFrom, a proxy)
only get the upper class (docs/xwaermeplan/datenbasis.md).
"""
from __future__ import annotations

import re

import pandas as pd

from fheat_core import columns as cols

UNKNOWN = "9999"
# (last year of the class, code); a year above all bounds -> "ab 2016"
_UPPER = [(1949, "1000"), (1969, "2000"), (1989, "3000"), (2015, "4000")]
_SUB = [(1918, "10001"), (1949, "10002"), (1959, "20001"), (1969, "20002"), (1979, "30001"),
        (1989, "30002"), (1999, "40001"), (2009, "40002"), (2015, "40003")]
LATEST = "5000"
# which column feeds which source name of XwpConfig.construction_year_sources, and whether it yields subclasses
SOURCES = {
    "construction_year": (cols.CONSTRUCTION_YEAR, True),
    "age": (cols.AGE, False),
    "parcel_year": (cols.PARCEL_YEAR, False),
}


def upper_class(year: int) -> str:
    return next((code for last, code in _UPPER if year <= last), LATEST)


def subclass(year: int) -> str:
    return next((code for last, code in _SUB if year <= last), LATEST)


def to_upper(code: str) -> str:
    """Upper class of a class code (1000 for 10002); 5000 and 9999 stay."""
    return code[:1] + "000" if len(code) == 5 else code


def parse_year(value) -> int | None:
    """First plausible four-digit year in a value ("1945", 1945.0, "1945, 1960"), else None."""
    if value is None or value is pd.NA or (isinstance(value, float) and pd.isna(value)):
        return None
    match = re.search(r"(1[5-9]\d\d|20\d\d)", str(value))
    return int(match.group(1)) if match else None


def age_class(row, sources: tuple[str, ...]) -> str:
    """Class code for one building (a mapping with canonical columns); the first source with a year wins."""
    for source in sources:
        column, detailed = SOURCES[source]
        year = parse_year(row.get(column)) if hasattr(row, "get") else None
        if year is not None:
            return subclass(year) if detailed else upper_class(year)
    return UNKNOWN


def assign_age_classes(buildings: pd.DataFrame, sources: tuple[str, ...]) -> pd.Series:
    records = buildings.to_dict("records")
    return pd.Series([age_class(r, sources) for r in records], index=buildings.index, dtype="string")
