"""FHeat Orchestrator — step-skip capable pipeline.

The pipeline has two stages. Every step can also be run on its own
(:meth:`FHeatOrchestrator.run_step`); the stage runners are a convenience.

* Analysis (*Potenzialanalyse*): download → adjust → status (WLD &
  suitability polygons) on the complete input area. Needs no heat source.
* Planning (*Netzplanung*): network → results for the buildings inside the
  planning area (``PipelineState.planning_area_gdf``). Needs a heat source.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable, Optional

import geopandas as gpd

from fheat_core import columns as cols
from fheat_core.adapters.base import DataAdapter
from fheat_core.config import FHeatConfig
from fheat_core.errors import PipelineInputError
from fheat_core.export.plots import render_charts, write_charts
from fheat_core.export.tables import write_tables
from fheat_core.selection import clip_to_area, in_planning_area
from fheat_core.state import Phase, PipelineState
from fheat_core.steps import adjust, download, network, results, status

logger = logging.getLogger(__name__)

#: Step name → phase the step starts from (the argument of ``run_step``).
STEP_INPUT_PHASE = {
    "download": Phase.INITIAL,
    "adjust": Phase.DOWNLOADED,
    "status": Phase.ADJUSTED,
    "network": Phase.STATUS,
    "results": Phase.NETWORK,
}
#: Step name → phase the state is in after the step.
STEP_OUTPUT_PHASE = {
    "download": Phase.DOWNLOADED,
    "adjust": Phase.ADJUSTED,
    "status": Phase.STATUS,
    "network": Phase.NETWORK,
    "results": Phase.RESULTS,
}
#: Stage *Potenzialanalyse*: ends with WLD & suitability polygons.
ANALYSIS_STEPS = ("download", "adjust", "status")
#: Stage *Netzplanung*: needs a heat source and usually a planning area.
PLANNING_STEPS = ("network", "results")

_STEP_ORDER = [
    Phase.INITIAL,
    Phase.DOWNLOADED,
    Phase.ADJUSTED,
    Phase.STATUS,
    Phase.NETWORK,
    Phase.RESULTS,
]

_STEP_FN = {
    Phase.INITIAL:    download.run,
    Phase.DOWNLOADED: adjust.run,
    Phase.ADJUSTED:   status.run,
    Phase.STATUS:     network.run,
    Phase.NETWORK:    results.run,
}

_FORMAT_MAP = {
    "gpkg":    ("GPKG",       ".gpkg"),
    "fgb":     ("FlatGeobuf", ".fgb"),
    "geojson": ("GeoJSON",    ".geojson"),
    "gml":     ("GML",        ".gml"),
}


class FHeatOrchestrator:
    """Runs the FHeat pipeline with step-skip support.

    Parameters
    ----------
    config : FHeatConfig
    adapter : DataAdapter
    state : PipelineState, optional
        Pre-populated state to resume from a later phase.
    """

    def __init__(
        self,
        config: FHeatConfig,
        adapter: DataAdapter,
        state: Optional[PipelineState] = None,
    ) -> None:
        self.config = config
        self.adapter = adapter
        self.state = state or PipelineState()
        self._out_dir = Path(config.output_dir)
        self._out_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_all(self) -> PipelineState:
        """Run all pipeline steps from the current phase."""
        return self._run_from(self.state.phase)

    def run_from(self, phase: Phase) -> PipelineState:
        """Resume from a specific phase."""
        return self._run_from(phase)

    def run_until(self, target: Phase) -> PipelineState:
        """Run the steps from the current phase until the state is in ``target``."""
        order = _STEP_ORDER.index
        if order(target) < order(self.state.phase):
            raise ValueError(
                f"State is already past {target.value!r} (current: {self.state.phase.value!r})."
            )
        while self.state.phase != target:
            self.run_step(self.state.phase)
        return self.state

    def run_analysis(self) -> PipelineState:
        """Stage *Potenzialanalyse*: run the missing steps up to WLD & suitability polygons."""
        return self.run_until(Phase.STATUS)

    def run_planning(self) -> PipelineState:
        """Stage *Netzplanung*: run network and results.

        Expects the analysis stage to be done. Set ``state.source_gdf`` and,
        to plan only part of the analysed area, ``state.planning_area_gdf``
        first.
        """
        if _STEP_ORDER.index(self.state.phase) < _STEP_ORDER.index(Phase.STATUS):
            raise PipelineInputError(
                "Run the analysis stage (download, adjust, status) before the network planning."
            )
        return self.run_until(Phase.RESULTS)

    def run_step(self, phase: Phase) -> PipelineState:
        """Execute a single step: the one that advances the state from ``phase``."""
        if phase not in _STEP_FN:
            raise ValueError(f"Phase {phase!r} has no associated step.")
        _check_inputs(phase, self.state)
        logger.info("Running step: %s", phase.value)
        self.state = _STEP_FN[phase](self.state, self.config, self.adapter)
        return self.state

    def save_outputs(
        self,
        layers: Optional[Iterable[str]] = None,
        clip_to_planning_area: bool = False,
    ) -> dict[str, str]:
        """Save all non-None GeoDataFrames to output_dir.

        Internally the pipeline uses canonical, language-neutral column names.
        With ``config.output_language == "de"`` (default) the columns are
        translated to the German display labels at write time, so the on-disk
        files remain unchanged for German users. ``"raw"`` keeps the canonical
        identifiers.

        With ``config.table_format`` set, the result tables are written as
        well (see :func:`fheat_core.export.tables.write_tables`); with
        ``config.plot_format`` set, the load profile charts (see
        :mod:`fheat_core.export.plots`), which an xlsx workbook also embeds.

        ``layers`` limits the geodata to the given names (keys of the returned
        dict, e.g. ``["wld", "eignungspolygone"]`` after the analysis stage).
        ``clip_to_planning_area`` writes only the features in the planning
        area, so the results of a small network do not carry the buildings and
        parcels of a whole town; network and source are always complete.
        """
        driver, ext = _FORMAT_MAP[self.config.output_format]
        translate = self.config.output_language == "de"
        saved = {}
        gdf_map = {
            "buildings": self.state.buildings_gdf,
            "streets": self.state.streets_gdf,
            "parcels": self.state.parcels_gdf,
            "source": self.state.source_gdf,
            "wld": self.state.wld_gdf,
            "eignungspolygone": self.state.polygons_gdf,
            "netz": self.state.net_gdf,
        }
        if layers is not None:
            wanted = set(layers)
            unknown = wanted - set(gdf_map)
            if unknown:
                raise ValueError(f"Unknown layers {sorted(unknown)}. Allowed: {sorted(gdf_map)}")
            gdf_map = {name: gdf for name, gdf in gdf_map.items() if name in wanted}
        if clip_to_planning_area:
            gdf_map = {
                name: _clip_layer(name, gdf, self.state.planning_area_gdf)
                for name, gdf in gdf_map.items()
            }
        for name, gdf in gdf_map.items():
            if gdf is not None and not gdf.empty:
                out_path = self._out_dir / (name + ext)
                out_path.unlink(missing_ok=True)  # avoid "layer already exists" on re-runs
                out_gdf = cols.to_display(gdf) if translate else gdf
                out_gdf.to_file(str(out_path), driver=driver)
                saved[name] = str(out_path)
                logger.info("Saved %s → %s", name, out_path)
        figures = render_charts(self.state) if self.config.plot_format else {}
        saved.update(write_charts(figures, self._out_dir, self.config.plot_format))
        saved.update(
            write_tables(self.state, self._out_dir, self.config.table_format, translate, figures=figures)
        )
        return saved

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_from(self, start_phase: Phase) -> PipelineState:
        idx = _STEP_ORDER.index(start_phase)
        for phase in _STEP_ORDER[idx:]:
            if phase not in _STEP_FN:
                break
            logger.info("=== Phase: %s ===", phase.value)
            _check_inputs(phase, self.state)
            self.state = _STEP_FN[phase](self.state, self.config, self.adapter)
        return self.state


# Frames a step needs on the state before it starts (keyed by its input phase).
# The heat source of NETWORK is checked by the step itself.
_REQUIRED_FRAMES = {
    Phase.DOWNLOADED: ("buildings_gdf", "streets_gdf", "parcels_gdf"),
    Phase.ADJUSTED: ("buildings_gdf", "streets_gdf"),
    Phase.STATUS: ("buildings_gdf", "streets_gdf"),
    Phase.NETWORK: ("buildings_gdf", "net_gdf"),
}


def _check_inputs(phase: Phase, state: PipelineState) -> None:
    missing = [name for name in _REQUIRED_FRAMES.get(phase, ()) if getattr(state, name) is None]
    if missing:
        raise PipelineInputError(
            f"Step from phase {phase.value!r} is missing {', '.join(missing)}; "
            "run the earlier steps first."
        )


def _clip_layer(name: str, gdf, planning_area):
    """Planning-area extract of one export layer (network and source stay complete)."""
    if gdf is None or gdf.empty or name in {"netz", "source"}:
        return gdf
    if name == "buildings":
        return gdf[in_planning_area(gdf, planning_area)]
    return clip_to_area(gdf, planning_area)
