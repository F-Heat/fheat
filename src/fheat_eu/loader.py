"""Heat source layers around one area, for any adapter.

The adapter knows its area and CRS; this loader reads the Fordatis files for
the box around it (:mod:`fheat_eu.download`), turns them into canonical
frames (:mod:`fheat_eu.heat_sources`) and keeps the features within the
maximum distance of the paper. Errors are raised; the adapter decides what
a failed layer means.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable, Mapping, Optional

import geopandas as gpd
import pandas as pd
from shapely.geometry.base import BaseGeometry

from fheat_core import cancel
from fheat_core import columns as cols
from fheat_eu import download as dl
from fheat_eu import heat_sources as hs

logger = logging.getLogger(__name__)


class HeatSourceLoader:
    """Fordatis heat source layers within the paper's distances of ``area``.

    Parameters
    ----------
    area : shapely geometry
        Outline of the loaded area in ``crs`` (a metric CRS).
    crs :
        CRS of ``area`` and of the returned frames.
    buffers : mapping | None
        Maximum distance per layer in m, overriding
        :data:`fheat_eu.heat_sources.DEFAULT_BUFFERS` key by key.
    cache_dir, fordatis_dir : Path | None
        Cache folder of the downloads; own folder with the Fordatis files
        (then nothing is downloaded from Fordatis).
    lau_id : str | None
        Municipality of the study (``LAU_ID`` such as ``DE_05566084``) for its
        district heating areas and its table. None → neither.
    known_names : iterable of str
        Place names that restore the lost umlauts of the waste incineration
        plants (:func:`fheat_eu.heat_sources.repair_name`).
    """

    def __init__(
        self,
        area: BaseGeometry,
        crs,
        buffers: Optional[Mapping[str, float]] = None,
        cache_dir: Optional[Path] = None,
        fordatis_dir: Optional[Path] = None,
        lau_id: Optional[str] = None,
        known_names: Iterable[str] = (),
    ) -> None:
        self._area = area
        self._crs = crs
        self.buffers = {**hs.DEFAULT_BUFFERS, **{k: float(v) for k, v in (buffers or {}).items()}}
        unknown = set(self.buffers) - set(hs.DEFAULT_BUFFERS)
        if unknown:
            raise ValueError(f"Unbekannte Wärmequellen {sorted(unknown)}. Bekannt: {sorted(hs.DEFAULT_BUFFERS)}")
        self._cache_dir = cache_dir
        self._fordatis_dir = fordatis_dir
        self._lau_id = lau_id
        self._known_names = list(known_names)
        self._study: Optional[tuple[pd.DataFrame, pd.DataFrame]] = None

    @property
    def area(self) -> BaseGeometry:
        """Outline of the loaded area in :attr:`crs`."""
        return self._area

    @property
    def crs(self):
        return self._crs

    # ------------------------------------------------------------------
    # Layers
    # ------------------------------------------------------------------

    def wastewater(self) -> gpd.GeoDataFrame:
        """Wastewater plants of Fordatis (Hotmaps power) within 2 km."""
        raw = self._raw(dl.FILE_WASTEWATER, self.buffers["wastewater"])
        return self._within(hs.process_wastewater(raw, self._area), "wastewater")

    def industrial_heat(self) -> gpd.GeoDataFrame:
        """Industrial excess heat within 20 km, with the Hotmaps names."""
        raw = self._raw(dl.FILE_INDUSTRIAL, self.buffers["industrial_heat"])
        names = None
        if not raw.empty:
            try:
                names = dl.hotmaps_industry_names(self._cache_dir)
            except RuntimeError as e:  # the values stand without the names
                logger.warning("Namen der Industriestandorte (Hotmaps) nicht geladen (%s) — ohne Namen.", e)
        return self._within(hs.process_industrial(raw, self._area, names), "industrial_heat")

    def waste_incineration(self) -> gpd.GeoDataFrame:
        """Waste incineration plants within 20 km."""
        raw = self._raw(dl.FILE_WASTE_INCINERATION, self.buffers["waste_incineration"])
        return self._within(hs.process_waste_incineration(raw, self._area, self._known_names), "waste_incineration")

    def river_heat(self) -> gpd.GeoDataFrame:
        """Zones of rivers and lakes for a heat pump within 5 km."""
        raw = self._raw(dl.FILE_RIVERS, self.buffers["river_heat"])
        return self._within(hs.process_rivers(raw, self._area), "river_heat")

    def hydrothermal(self) -> gpd.GeoDataFrame:
        """Hydrothermal 1 km cells within 15 km (only where GeoDH maps an aquifer)."""
        return self._geothermal(dl.FILES_HYDROTHERMAL, "Energy_TWh", "hydrothermal")

    def study_dh_areas(self) -> Optional[gpd.GeoDataFrame]:
        """The study's district heating areas of the municipality (None without ``lau_id``)."""
        if not self._lau_id:
            return None
        labels = hs.study_dh_labels(self._study_sheets()[0], self._lau_id)
        if not labels:
            return None
        return hs.process_study_dh_areas(self._raw(dl.FILE_DH_AREAS, 0.0), labels)

    def study_potentials(self) -> Optional[pd.DataFrame]:
        """The study's supply and utilization potentials of the municipality (None without one)."""
        if not self._lau_id:
            return None
        return hs.study_table(self._study_sheets()[1], self._lau_id)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _around(self, buffer: float) -> gpd.GeoSeries:
        area = gpd.GeoSeries([self._area], crs=self._crs)
        return area.buffer(buffer, join_style=2) if buffer > 0 else area

    def _raw(self, name: str, buffer: float, keep_grid: bool = False) -> gpd.GeoDataFrame:
        """Features of a Fordatis file in the box around the area (in ``crs``, or EPSG:3035)."""
        cancel.raise_if_cancelled()
        around = self._around(buffer)
        raw = dl.read_fordatis(name, tuple(around.to_crs(dl.FORDATIS_CRS).total_bounds),
                               self._cache_dir, self._fordatis_dir)
        if raw.crs is None:
            raw = raw.set_crs(dl.FORDATIS_CRS)
        return raw if keep_grid else raw.to_crs(self._crs)

    def _geothermal(self, files: tuple[str, str], field: str, key: str) -> gpd.GeoDataFrame:
        ht, lt = (self._raw(name, self.buffers[key], keep_grid=True) for name in files)
        return self._within(hs.process_geothermal_cells(ht, lt, field, self._area, self._crs), key)

    def _within(self, gdf: gpd.GeoDataFrame, key: str) -> gpd.GeoDataFrame:
        return gdf[gdf[cols.DISTANCE_TO_AREA] <= self.buffers[key]].reset_index(drop=True)

    def _study_sheets(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        if self._study is None:
            self._study = dl.read_study_results(self._cache_dir, self._fordatis_dir)
        return self._study
