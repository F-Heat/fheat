"""Temperature year of the load profile and its key figures."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

# Heating degree days after VDI 3807: indoor 20 °C, heating limit 15 °C
DEGREE_DAY_INDOOR = 20.0
DEGREE_DAY_LIMIT = 15.0


class WeatherDataError(RuntimeError):
    """No usable temperature year for the requested place and year."""


@dataclass(frozen=True)
class TemperatureYear:
    """Hourly outdoor temperatures of one calendar year and where they come from.

    ``series`` is in °C. A DWD year has an hourly DatetimeIndex in CET
    (UTC+1 all year, no daylight saving time, like the test reference years
    and the BDEW profiles) covering exactly the year. The example year and an
    adapter series may come without a DatetimeIndex; the load profile then
    aligns them by position.
    """

    series: pd.Series
    source: str                       # "dwd" | "example" | "adapter"
    station_id: Optional[str] = None
    station_name: Optional[str] = None
    distance_km: Optional[float] = None
    coverage: float = 1.0             # share of measured hours before gap filling


def heating_degree_days(series: pd.Series) -> float:
    """Heating degree days G20/15 [K·d] of an hourly series (VDI 3807).

    Sum of (20 °C − daily mean) over the days with a daily mean below 15 °C.
    Days are taken as blocks of 24 values, so a series without a
    DatetimeIndex works too; an incomplete last day is ignored.
    """
    values = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    n_days = len(values) // 24
    daily = values[: n_days * 24].reshape(n_days, 24).mean(axis=1)
    heating = daily[daily < DEGREE_DAY_LIMIT]
    return float(np.sum(DEGREE_DAY_INDOOR - heating))
