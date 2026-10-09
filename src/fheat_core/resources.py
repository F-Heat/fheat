from __future__ import annotations

import importlib.resources
from typing import Optional

import pandas as pd


def _data_path(filename: str):
    return importlib.resources.files("fheat_core.data") / filename


def load_pipe_info() -> pd.DataFrame:
    """Load the pipe catalogue from the core default.

    Columns: DN, di, U-Value, U-Value_extra_insulation, max_volumeFlow and the
    standardised pipe costs cost_main (route) and cost_h-connect (house
    connection) in € per metre of trench, used by
    :func:`fheat_core.network.costs.annotate_network_costs`.
    """
    with importlib.resources.as_file(_data_path("pipe_data.csv")) as p:
        return pd.read_csv(p)


def resolve_pipe_info(adapter) -> pd.DataFrame:
    """Pipe catalogue actually used by the pipeline.

    The adapter may supply its own catalogue; otherwise the core default is
    used. Network backends and the result summary must agree on it, so both
    go through this function.
    """
    pipe_info = adapter.provide_pipe_info()
    if pipe_info is None:
        pipe_info = load_pipe_info()
    return pipe_info


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
