"""Optional result charts: hourly load profile and load duration curve.

Reproduces the four charts the former QGIS plugin wrote after the result step
(``LoadProfile.plot_bar_chart`` in ``load_curve.py``): the hourly total heat
demand with network loss, once with the normal and once with the extra
insulation, each in time order and sorted descending (load duration curve).

Charts are drawn with matplotlib's object API (no pyplot, no GUI backend), so
they also work in worker processes. Labels are German, like the plugin's.
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from fheat_core import columns as cols
from fheat_core.state import PipelineState

logger = logging.getLogger(__name__)

_PLOTS_HINT = 'plot_format requires matplotlib. Install it with: pip install "fheat[plots]"'

_DEMAND_COLOR = "#1f4fa8"
_DEMAND_EXTRA_COLOR = "#2f7a4b"
_LOSS_COLOR = "#f28e2b"


@dataclass(frozen=True)
class ChartSpec:
    name: str            # file stem, as in the QGIS plugin
    total_column: str
    loss_column: str
    ordered: bool        # True = sorted descending (load duration curve)
    title: str
    ylabel: str
    total_label: str
    loss_label: str
    total_color: str


CHARTS = (
    ChartSpec(
        "Lastprofil", cols.TOTAL, cols.LOSS, False,
        "Wärmebedarf und Verlust pro Stunde im Jahr", "Wärmebedarf und Verlust [MW]",
        "Gesamtsumme", "Verlust", _DEMAND_COLOR,
    ),
    ChartSpec(
        "Lastprofil_geordnet", cols.TOTAL, cols.LOSS, True,
        "Geordnetes Lastprofil", "Wärmebedarf und Verlust [MW]",
        "Gesamtsumme", "Verlust", _DEMAND_COLOR,
    ),
    ChartSpec(
        "Lastprofil_extra_Daemmung", cols.TOTAL_EXTRA_INSULATION, cols.LOSS_EXTRA_INSULATION, False,
        "Wärmebedarf und Verlust bei extra Dämmung pro Stunde im Jahr",
        "Wärmebedarf und Verlust bei extra Dämmung [MW]",
        "Gesamtsumme (extra Dämmung)", "Verlust bei extra Dämmung", _DEMAND_EXTRA_COLOR,
    ),
    ChartSpec(
        "Lastprofil_extra_Daemmung_geordnet", cols.TOTAL_EXTRA_INSULATION, cols.LOSS_EXTRA_INSULATION, True,
        "Geordnetes Lastprofil (extra Dämmung)", "Wärmebedarf und Verlust bei extra Dämmung [MW]",
        "Gesamtsumme (extra Dämmung)", "Verlust bei extra Dämmung", _DEMAND_EXTRA_COLOR,
    ),
)


def chart_series(load_profile_df: pd.DataFrame, spec: ChartSpec) -> tuple[np.ndarray, np.ndarray]:
    """Total and loss values [MW] in plot order.

    For the ordered charts the hours are sorted by total demand, descending;
    the loss of the same hour moves with it, as in the plugin.
    """
    frame = load_profile_df[[spec.total_column, spec.loss_column]]
    if spec.ordered:
        frame = frame.sort_values(spec.total_column, ascending=False, kind="stable")
    return frame[spec.total_column].to_numpy(float), frame[spec.loss_column].to_numpy(float)


def _require_matplotlib():
    try:
        from matplotlib.figure import Figure
    except ImportError as exc:
        raise ImportError(_PLOTS_HINT) from exc
    return Figure


def render_charts(state: PipelineState) -> dict:
    """matplotlib figures keyed by chart name; empty before the RESULTS step."""
    load_profile = state.load_profile_df
    if load_profile is None or load_profile.empty:
        return {}
    Figure = _require_matplotlib()

    figures = {}
    for spec in CHARTS:
        if spec.total_column not in load_profile.columns or spec.loss_column not in load_profile.columns:
            continue
        total, loss = chart_series(load_profile, spec)
        edges = np.arange(len(total) + 1) - 0.5  # one 1-h wide bar per hour, like the plugin's bar chart
        fig = Figure(figsize=(18, 4))
        ax = fig.add_subplot()
        ax.stairs(total, edges, fill=True, color=spec.total_color, label=spec.total_label)
        ax.stairs(loss, edges, fill=True, color=_LOSS_COLOR, label=spec.loss_label)
        ax.set_xlim(edges[0], edges[-1])
        ax.set_ylim(bottom=0)
        ax.set_xlabel("Stunden im Jahr, absteigend sortiert [h]" if spec.ordered else "Zeit [h]")
        ax.set_ylabel(spec.ylabel)
        ax.set_title(spec.title)
        ax.legend(loc="upper right")
        ax.grid(axis="y", alpha=0.3)
        figures[spec.name] = fig
    return figures


def figure_png_bytes(fig) -> bytes:
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", bbox_inches="tight", dpi=100)
    return buffer.getvalue()


def write_charts(figures: dict, out_dir: str | Path, plot_format: str | None) -> dict[str, str]:
    """Save the figures as ``<name>.<plot_format>`` and return ``{key: path}``."""
    if plot_format is None or not figures:
        return {}
    if plot_format not in ("png", "svg"):
        raise ValueError(f"plot_format '{plot_format}' is not allowed. Allowed values: None, 'png', 'svg'")
    out_dir = Path(out_dir)
    saved = {}
    for name, fig in figures.items():
        path = out_dir / f"{name}.{plot_format}"
        fig.savefig(path, format=plot_format, bbox_inches="tight", dpi=100)
        saved[f"grafik_{name.lower()}"] = str(path)
        logger.info("Saved chart %s → %s", name, path)
    return saved
