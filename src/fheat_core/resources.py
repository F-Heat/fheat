from __future__ import annotations

import importlib.resources
from typing import Optional

import pandas as pd


def _data_path(filename: str):
    return importlib.resources.files("fheat_core.data") / filename


def load_pipe_info() -> pd.DataFrame:
    """Rohrkatalog aus dem Core-Default laden.

    Spalten: DN, di, U-Value, U-Value_extra_insulation, max_volumeFlow
    """
    with importlib.resources.as_file(_data_path("pipe_data.csv")) as p:
        return pd.read_csv(p)


def load_default_temperature() -> pd.Series:
    """8760 Stunden-Außentemperaturen [°C] aus dem Core-Beispieljahr."""
    with importlib.resources.as_file(_data_path("example_temperature.csv")) as p:
        df = pd.read_csv(p)
    return df["TT_TU"]


def load_default_holidays(year: int) -> dict:
    """Deutsche Feiertage für das gegebene Jahr via workalendar."""
    try:
        from workalendar.europe import Germany
        cal = Germany()
        return dict(cal.holidays(year))
    except ImportError:
        return {}
