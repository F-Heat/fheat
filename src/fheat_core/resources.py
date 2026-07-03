from __future__ import annotations

import importlib.resources
from typing import Optional

import pandas as pd


def _data_path(filename: str):
    return importlib.resources.files("fheat_core.data") / filename


def load_pipe_info() -> pd.DataFrame:
    """Load the pipe catalogue from the core default.

    Columns: DN, di, U-Value, U-Value_extra_insulation, max_volumeFlow
    """
    with importlib.resources.as_file(_data_path("pipe_data.csv")) as p:
        return pd.read_csv(p)


def load_default_temperature() -> pd.Series:
    """8760 hourly outdoor temperatures [°C] from the core example year."""
    with importlib.resources.as_file(_data_path("example_temperature.csv")) as p:
        df = pd.read_csv(p)
    return df["TT_TU"]


def load_default_holidays(year: int) -> dict:
    """German public holidays for the given year via workalendar."""
    try:
        from workalendar.europe import Germany
        cal = Germany()
        return dict(cal.holidays(year))
    except ImportError:
        return {}
