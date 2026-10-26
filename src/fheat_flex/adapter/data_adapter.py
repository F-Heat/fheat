"""Flexible DataAdapter — accepts user-supplied files with column mapping."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Tuple, Union

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, box

from fheat_core import columns as cols
from fheat_core.adapters.base import DataAdapter
from fheat_eu.loader import HeatSourceLoader

logger = logging.getLogger(__name__)

SourceInput = Union[Tuple[float, float], str, Path, gpd.GeoDataFrame]


class FlexDataAdapter(DataAdapter):
    """Adapter for user-supplied files with column mapping.

    Caller supplies file paths and (optionally) a column-name mapping that
    translates the user's column names into the schema-required names. Any
    missing schema columns are filled with sensible defaults.

    Parameters
    ----------
    buildings_path : str | Path
        Pfad zu den Gebäudedaten (Polygon-Geometrie). Muss eine
        Wärmebedarfsspalte und eine Geometriespalte enthalten.
    streets_path : str | Path
        Pfad zu den Straßendaten (LineString-Geometrie).
    parcels_path : str | Path
        Pfad zu den Flurstücksdaten (Polygon-Geometrie).
    source : tuple[float, float] | str | Path | GeoDataFrame | None
        (lat, lon) in WGS84, ODER Pfad zu einer Punkt-Geodaten-Datei,
        ODER ein bereits geladener GeoDataFrame. Erst für den NETWORK-Schritt
        nötig; None → download, adjust und status laufen ohne Quelle.
    column_map : dict[str, str] | None
        Mapping: ``{user_spalte: schema_spalte}``. Wird auf das Buildings-
        GeoDataFrame angewandt. Zielnamen sind die kanonischen Identifier aus
        :mod:`fheat_core.columns`:
          - ``heat_demand`` (Pflicht)
          - ``thermal_power`` (optional, sonst aus heat_demand/full_load_hours berechnet)
          - ``full_load_hours`` (optional, sonst default_vlh)
          - ``load_profile`` (optional, sonst default_lastprofil)
          - ``building_id``, ``connect`` (optional, sonst automatisch)
          - optional: ``construction_year`` (Baujahr), ``function``
            (ALKIS-Gebäudefunktion), ``building_type`` (EFH, RH, MFH, GMFH)
    default_vlh : float
        Volllaststunden, wenn die Spalte fehlt. Standard: 1600.
    default_lastprofil : str
        Lastprofil-Code, wenn die Spalte fehlt. Standard: "GMK".
    download_heat_sources : bool
        Wenn True, werden die Wärmequellen im Umkreis der Gebäude aus dem
        Datensatz des Fraunhofer ISI geladen (Manz et al. 2024, EU, Stand
        2050, einmal in den Zwischenspeicher): Kläranlagen, Industrie-
        Abwärme, Müllverbrennung, Flüsse und Seen, Hydrothermie. Standard
        False: der Adapter lädt sonst
        nichts aus dem Netz. Braucht ein metrisches KBS der Gebäude. Fehler →
        Warnung, kein Layer.
    lau_id : str | None
        Gemeinde der Studie (``LAU_ID``, z. B. ``DE_05566084``) für ihre
        Wärmenetzgebiete und Werte. None → beides nicht.
    heat_source_buffers : dict | None
        Umkreis je Wärmequelle in m (Standard: Höchstabstände des Papers).
    fordatis_path : Path | None
        Eigener Ordner mit den Fordatis-Dateien (statt des Downloads).
    cache_dir : Path | None
        Ordner für die Downloads (Standard: ``FHEAT_CACHE_DIR`` oder
        ``~/.cache/fheat``).
    """

    def __init__(
        self,
        buildings_path: Union[str, Path],
        streets_path: Union[str, Path],
        parcels_path: Union[str, Path],
        source: Optional[SourceInput] = None,
        column_map: Optional[dict] = None,
        default_vlh: float = 1600.0,
        default_lastprofil: str = "GMK",
        download_heat_sources: bool = False,
        lau_id: Optional[str] = None,
        heat_source_buffers: Optional[dict] = None,
        fordatis_path: Optional[Union[str, Path]] = None,
        cache_dir: Optional[Union[str, Path]] = None,
    ) -> None:
        self._buildings_path = Path(buildings_path)
        self._streets_path = Path(streets_path)
        self._parcels_path = Path(parcels_path)
        self._source_input = source
        self._column_map = column_map or {}
        self._default_vlh = default_vlh
        self._default_lastprofil = default_lastprofil
        self._download_heat_sources = bool(download_heat_sources)
        self._lau_id = lau_id
        self._heat_source_buffers = dict(heat_source_buffers or {})
        self._fordatis_path = Path(fordatis_path) if fordatis_path is not None else None
        self._cache_dir = Path(cache_dir) if cache_dir is not None else None
        self._heat_layers: dict = {}
        self._heat_loader: Optional[HeatSourceLoader] = None

        self._buildings: Optional[gpd.GeoDataFrame] = None
        self._streets: Optional[gpd.GeoDataFrame] = None
        self._parcels: Optional[gpd.GeoDataFrame] = None
        self._source: Optional[gpd.GeoDataFrame] = None

    # ------------------------------------------------------------------
    # DataAdapter API
    # ------------------------------------------------------------------

    def fetch_buildings(self) -> gpd.GeoDataFrame:
        if self._buildings is None:
            self._buildings = self._load_buildings()
        return self._buildings

    def fetch_streets(self) -> gpd.GeoDataFrame:
        if self._streets is None:
            self._streets = self._load_streets()
        return self._streets

    def fetch_parcels(self) -> gpd.GeoDataFrame:
        if self._parcels is None:
            self._parcels = self._load_parcels()
        return self._parcels

    def fetch_source(self) -> Optional[gpd.GeoDataFrame]:
        if self._source_input is None:
            return None
        if self._source is None:
            self._source = self._load_source()
        return self._source

    def fetch_wastewater(self) -> Optional[gpd.GeoDataFrame]:
        return self._heat_source("wastewater")

    def fetch_industrial_heat(self) -> Optional[gpd.GeoDataFrame]:
        return self._heat_source("industrial_heat")

    def fetch_waste_incineration(self) -> Optional[gpd.GeoDataFrame]:
        return self._heat_source("waste_incineration")

    def fetch_river_heat(self) -> Optional[gpd.GeoDataFrame]:
        return self._heat_source("river_heat")

    def fetch_geothermal_hydrothermal(self) -> Optional[gpd.GeoDataFrame]:
        return self._heat_source("hydrothermal")

    def fetch_study_dh_areas(self) -> Optional[gpd.GeoDataFrame]:
        return self._heat_source("study_dh_areas")

    def fetch_study_potentials(self) -> Optional[pd.DataFrame]:
        return self._heat_source("study_potentials")

    # ------------------------------------------------------------------
    # Heat sources (fheat_eu), loaded once per layer
    # ------------------------------------------------------------------

    def _heat_source(self, key: str):
        if key not in self._heat_layers:
            layer = None
            if self._download_heat_sources or self._fordatis_path is not None:
                try:
                    layer = getattr(self._heat_source_loader(), key)()
                except Exception as e:  # network/IO dependent: never stop the pipeline
                    logger.warning("Wärmequelle '%s' (Fraunhofer ISI) konnte nicht geladen werden (%s) — kein Layer.",
                                   key, e)
            self._heat_layers[key] = layer if layer is not None and not layer.empty else None
        return self._heat_layers[key]

    def _heat_source_loader(self) -> HeatSourceLoader:
        if self._heat_loader is None:
            buildings = self.fetch_buildings()
            if buildings.crs is None or not buildings.crs.is_projected:
                raise RuntimeError("Wärmequellen brauchen Gebäude in einem metrischen KBS (z. B. EPSG:25832).")
            self._heat_loader = HeatSourceLoader(
                box(*buildings.total_bounds), buildings.crs, self._heat_source_buffers,
                self._cache_dir, self._fordatis_path, lau_id=self._lau_id,
            )
        return self._heat_loader

    # ------------------------------------------------------------------
    # Loaders
    # ------------------------------------------------------------------

    def _load_buildings(self) -> gpd.GeoDataFrame:
        gdf = gpd.read_file(self._buildings_path)
        gdf = gdf.rename(columns=self._column_map)

        if cols.HEAT_DEMAND not in gdf.columns:
            raise ValueError(
                f"Buildings: '{cols.HEAT_DEMAND}' fehlt nach Mapping. "
                f"Bitte column_map setzen, z. B. {{'wbedarf': '{cols.HEAT_DEMAND}'}}."
            )

        gdf = gdf[gdf[cols.HEAT_DEMAND] > 0].reset_index(drop=True)
        if gdf.empty:
            raise ValueError("Keine Gebaeude mit heat_demand > 0 vorhanden.")

        if cols.FULL_LOAD_HOURS not in gdf.columns:
            gdf[cols.FULL_LOAD_HOURS] = self._default_vlh
        else:
            vlh = pd.to_numeric(gdf[cols.FULL_LOAD_HOURS], errors="coerce").fillna(self._default_vlh)
            vlh = vlh.where(vlh > 0, self._default_vlh)
            gdf[cols.FULL_LOAD_HOURS] = vlh

        if cols.THERMAL_POWER not in gdf.columns:
            gdf[cols.THERMAL_POWER] = gdf[cols.HEAT_DEMAND] / gdf[cols.FULL_LOAD_HOURS]

        if cols.LOAD_PROFILE not in gdf.columns:
            gdf[cols.LOAD_PROFILE] = self._default_lastprofil
        else:
            gdf[cols.LOAD_PROFILE] = gdf[cols.LOAD_PROFILE].fillna(self._default_lastprofil).astype(str)

        if cols.BUILDING_ID not in gdf.columns:
            gdf[cols.BUILDING_ID] = gdf.index.astype("int32")
        else:
            gdf[cols.BUILDING_ID] = gdf[cols.BUILDING_ID].astype("int32")

        if cols.CONNECT not in gdf.columns:
            gdf[cols.CONNECT] = 1
        else:
            gdf[cols.CONNECT] = gdf[cols.CONNECT].fillna(1).astype("int32")

        if cols.CONSTRUCTION_YEAR in gdf.columns:
            gdf[cols.CONSTRUCTION_YEAR] = pd.to_numeric(gdf[cols.CONSTRUCTION_YEAR], errors="coerce").astype("Int64")

        # Geometry repair
        gdf["geometry"] = gdf["geometry"].buffer(0)
        return gdf

    def _load_streets(self) -> gpd.GeoDataFrame:
        gdf = gpd.read_file(self._streets_path)
        if cols.ROUTABLE not in gdf.columns:
            gdf[cols.ROUTABLE] = 1
        return gdf

    def _load_parcels(self) -> gpd.GeoDataFrame:
        gdf = gpd.read_file(self._parcels_path)
        if not gdf.empty:
            gdf["geometry"] = gdf["geometry"].buffer(0)
        return gdf

    def _load_source(self) -> gpd.GeoDataFrame:
        src = self._source_input
        target_crs = self.fetch_buildings().crs

        if isinstance(src, gpd.GeoDataFrame):
            gdf = src.copy()
        elif isinstance(src, tuple) and len(src) == 2:
            lat, lon = src
            gdf = gpd.GeoDataFrame({"geometry": [Point(lon, lat)]}, crs="EPSG:4326")
        elif isinstance(src, (str, Path)):
            gdf = gpd.read_file(src)
        else:
            raise ValueError(
                f"FlexDataAdapter: 'source' muss tuple[float, float], Pfad oder "
                f"GeoDataFrame sein, bekommen {type(src).__name__}."
            )

        if target_crs is not None and gdf.crs != target_crs:
            gdf = gdf.to_crs(target_crs)
        return gdf
