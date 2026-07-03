"""FHeat Orchestrator — step-skip capable pipeline."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import geopandas as gpd

from fheat_core import columns as cols
from fheat_core.adapters.base import DataAdapter
from fheat_core.config import FHeatConfig
from fheat_core.state import Phase, PipelineState
from fheat_core.steps import adjust, download, network, results, status

logger = logging.getLogger(__name__)

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

    def run_step(self, phase: Phase) -> PipelineState:
        """Execute a single step."""
        if phase not in _STEP_FN:
            raise ValueError(f"Phase {phase!r} has no associated step.")
        logger.info("Running step: %s", phase.value)
        self.state = _STEP_FN[phase](self.state, self.config, self.adapter)
        return self.state

    def save_outputs(self) -> dict[str, str]:
        """Save all non-None GeoDataFrames to output_dir.

        Internally the pipeline uses canonical, language-neutral column names.
        With ``config.output_language == "de"`` (default) the columns are
        translated to the German display labels at write time, so the on-disk
        files remain unchanged for German users. ``"raw"`` keeps the canonical
        identifiers.
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
        for name, gdf in gdf_map.items():
            if gdf is not None and not gdf.empty:
                out_path = self._out_dir / (name + ext)
                out_path.unlink(missing_ok=True)  # avoid "layer already exists" on re-runs
                out_gdf = cols.to_display(gdf) if translate else gdf
                out_gdf.to_file(str(out_path), driver=driver)
                saved[name] = str(out_path)
                logger.info("Saved %s → %s", name, out_path)
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
            self.state = _STEP_FN[phase](self.state, self.config, self.adapter)
        return self.state
