"""Lower Saxony DataAdapter — produces BuildingsSchema-compliant data."""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from importlib.resources import files
from pathlib import Path
from typing import Callable, Optional, Tuple

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, box

from fheat_core.adapters.base import DataAdapter
from fheat_de import heat_demand, zensus
from fheat_de.alkis import annotate_landuse_costs
from fheat_de.area import boundary_from_parcels, clip_to_boundary, read_catalog
from fheat_de.osm_surface import OVERPASS_URL, annotate_osm_surface_costs, buffer_osm_lines, get_osm_surface_via_overpass
from fheat_de.streets import process_streets
from fheat_nds import download as dl
from fheat_nds.processing import process_buildings

logger = logging.getLogger(__name__)

CRS = dl.CRS


class NDSDataAdapter(DataAdapter):
    """Downloads Lower Saxony open geodata (LGLN) and calculates the heat demand.

    All Lower-Saxony-specific configuration lives here (NOT in FHeatConfig).
    The heat demand is calculated for every building (see
    :mod:`fheat_nds.processing`); there is no heat demand of the data source,
    so ``heat_demand_dataset`` is missing and both heat demand bases of
    FHeatConfig give the calculated one.

    Parameters
    ----------
    municipality_name : str | None
        Gemeinde-Name wie im Katalog (z. B. "Bad Bentheim, Stadt"). Lädt die ganze Gemeinde.
    district_key : str | None
        Gemarkungsschlüssel (Spalte "schluessel" im Katalog, z. B. "34204").
        Hat Vorrang vor municipality_name; schneidet auf die Gemarkung zu.
    source_coordinates : tuple[float, float] | None
        (lat, lon) der Wärmequelle in WGS84. Erst für den NETWORK-Schritt nötig.
    area_bbox : tuple[float, float, float, float] | None
        (minx, miny, maxx, maxy) in EPSG:25832. Mit Angabe laden ``fetch_landuse``/
        ``fetch_osm_surface`` nur ihre Layer, ohne die Gebäude.
    cities_path : Path | None
        Eigener Gebietskatalog (Spalten wie ``fheat_nds/data/cities.csv``).
    building_functions_path, building_age_classes_path : Path | None
        Eigene Tabellen statt derer von :mod:`fheat_de.heat_demand`.
    storey_height : float
        Geschosshöhe [m], mit der die Traufhöhe aus LoD2 in Geschosse umgerechnet wird.
    download_lod2 : bool
        Wenn True (Standard), kommen die Geschosse aus der Traufhöhe des 3D-
        Gebäudemodells LoD2 (Kacheln im Zwischenspeicher). Fehler → Warnung,
        Geschosse angenommen.
    download_zensus : bool
        Wenn True (Standard), kommt die Baualtersklasse aus dem Zensus 2022
        (100-m-Gitter, einmal in den Zwischenspeicher). Fehler → Warnung,
        Baualtersklasse angenommen.
    download_landuse, landuse_path, download_osm_surface, osm_surface_path, osm_overpass_url
        Tiefbau-Layer wie beim NRWDataAdapter: ALKIS-Nutzung vom WFS des LGLN
        und OSM-Straßenbeläge von der Overpass-API. Fehler → Warnung + Faktor 1.0.
    cache_dir : Path | None
        Ordner für große Downloads (Standard: ``FHEAT_CACHE_DIR`` oder ``~/.cache/fheat``).
    """

    def __init__(
        self,
        municipality_name: Optional[str] = None,
        district_key: Optional[str] = None,
        source_coordinates: Optional[Tuple[float, float]] = None,
        area_bbox: Optional[Tuple[float, float, float, float]] = None,
        cities_path: Optional[Path] = None,
        building_functions_path: Optional[Path] = None,
        building_age_classes_path: Optional[Path] = None,
        storey_height: float = heat_demand.STOREY_HEIGHT_M,
        download_lod2: bool = True,
        download_zensus: bool = True,
        download_landuse: bool = True,
        landuse_path: Optional[Path] = None,
        download_osm_surface: bool = True,
        osm_surface_path: Optional[Path] = None,
        osm_overpass_url: Optional[str] = None,
        cache_dir: Optional[Path] = None,
    ) -> None:
        if not municipality_name and not district_key:
            raise ValueError("NDSDataAdapter benoetigt 'municipality_name' oder 'district_key'.")
        self._municipality_name = municipality_name
        self._district_key = str(district_key) if district_key else None
        self._source_coords = source_coordinates
        self._area_bbox = tuple(float(v) for v in area_bbox) if area_bbox is not None else None
        self._cities_path = Path(cities_path) if cities_path is not None else None
        self._building_functions_path = building_functions_path
        self._building_age_classes_path = building_age_classes_path
        self._storey_height = float(storey_height)
        self._download_lod2 = bool(download_lod2)
        self._download_zensus = bool(download_zensus)
        self._download_landuse = bool(download_landuse)
        self._landuse_path = Path(landuse_path) if landuse_path is not None else None
        self._download_osm_surface = bool(download_osm_surface)
        self._osm_surface_path = Path(osm_surface_path) if osm_surface_path is not None else None
        self._osm_overpass_url = osm_overpass_url
        self._cache_dir = Path(cache_dir) if cache_dir is not None else None

        self._buildings: Optional[gpd.GeoDataFrame] = None
        self._streets: Optional[gpd.GeoDataFrame] = None
        self._parcels: Optional[gpd.GeoDataFrame] = None
        self._source: Optional[gpd.GeoDataFrame] = None
        self._boundary: Optional[gpd.GeoDataFrame] = None
        # optional layers, loaded once: a failed download stays None
        self._layers: dict[str, Optional[gpd.GeoDataFrame]] = {}

    # ------------------------------------------------------------------
    # DataAdapter API
    # ------------------------------------------------------------------

    def fetch_buildings(self) -> gpd.GeoDataFrame:
        self._ensure_loaded()
        return self._buildings

    def fetch_streets(self) -> gpd.GeoDataFrame:
        self._ensure_loaded()
        return self._streets

    def fetch_parcels(self) -> gpd.GeoDataFrame:
        self._ensure_loaded()
        return self._parcels

    def fetch_source(self) -> Optional[gpd.GeoDataFrame]:
        self._ensure_loaded()
        return self._source

    @property
    def municipality_key(self) -> str:
        """Amtlicher Gemeindeschlüssel (AGS, 8 digits) of the area, from the catalogue; no download."""
        return str(self._select_area()["gmdschl"].iloc[0]).zfill(8)

    def provide_boundary(self) -> gpd.GeoDataFrame:
        """Outline of the downloaded municipality or district (union of its parcels)."""
        self._ensure_loaded()
        return self._boundary

    def fetch_landuse(self) -> Optional[gpd.GeoDataFrame]:
        """ALKIS land use of the loaded area with ``civil_cost_factor`` (None on failure)."""
        return self._optional_layer(
            "landuse", self._load_landuse,
            "ALKIS-Flaechennutzung konnte nicht geladen werden (%s) — Tiefbau-Faktor 1.0 fuer diesen Layer.",
        )

    def fetch_osm_surface(self) -> Optional[gpd.GeoDataFrame]:
        """Buffered OSM roads of the loaded area with ``civil_cost_factor`` (None on failure)."""
        return self._optional_layer(
            "osm_surface", self._load_osm_surface,
            "OSM-Strassenbelaege konnten nicht geladen werden (%s) — Tiefbau-Faktor 1.0 fuer diesen Layer.",
        )

    # ------------------------------------------------------------------
    # Internal: optional layers
    # ------------------------------------------------------------------

    def _optional_layer(self, key: str, load: Callable, warning: str) -> Optional[gpd.GeoDataFrame]:
        if key not in self._layers:
            try:
                layer = load()
            except Exception as e:  # network/IO dependent: never stop the pipeline
                logger.warning(warning, e)
                layer = None
            self._layers[key] = layer if layer is not None and not layer.empty else None
        return self._layers[key]

    def _load_landuse(self) -> Optional[gpd.GeoDataFrame]:
        if self._landuse_path is not None:
            raw = gpd.read_file(str(self._landuse_path))
        elif self._download_landuse:
            raw = dl.get_landuse(tuple(float(v) for v in self._area_box().to_crs(CRS).total_bounds))
        else:
            return None
        if raw is None or raw.empty:
            return None
        raw = raw.copy()
        raw["geometry"] = raw.geometry.buffer(0)
        return annotate_landuse_costs(self._to_area_crs(raw))

    def _load_osm_surface(self) -> Optional[gpd.GeoDataFrame]:
        if self._osm_surface_path is not None:
            raw = gpd.read_file(str(self._osm_surface_path))
        elif self._download_osm_surface:
            # Overpass expects (south, west, north, east) in lat/lon
            minx, miny, maxx, maxy = self._area_box().to_crs("EPSG:4326").total_bounds
            raw = get_osm_surface_via_overpass(
                (float(miny), float(minx), float(maxy), float(maxx)),
                overpass_url=self._osm_overpass_url or OVERPASS_URL,
            )
        else:
            return None
        if raw is None or raw.empty:
            return None
        return annotate_osm_surface_costs(buffer_osm_lines(self._to_area_crs(raw)))

    def _area_box(self) -> gpd.GeoSeries:
        """Bounding box of buildings, streets and source, or ``area_bbox``."""
        if self._area_bbox is not None:
            return gpd.GeoSeries([box(*self._area_bbox)], crs=CRS)
        self._ensure_loaded()
        frames = [g for g in (self._buildings, self._streets, self._source) if g is not None and not g.empty]
        bounds = [g.to_crs(CRS).total_bounds for g in frames]
        return gpd.GeoSeries(
            [box(min(b[0] for b in bounds), min(b[1] for b in bounds),
                 max(b[2] for b in bounds), max(b[3] for b in bounds))],
            crs=CRS,
        )

    def _to_area_crs(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        crs = CRS if self._buildings is None else self._buildings.crs
        if gdf.crs is not None and crs is not None and gdf.crs != crs:
            return gdf.to_crs(crs)
        return gdf

    # ------------------------------------------------------------------
    # Internal: download + processing
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        if self._buildings is not None:
            return
        rows = self._select_area()
        municipality_key = str(rows["gmdschl"].iloc[0]).zfill(8)
        bbox = _union_bounds(rows["bbox"])

        parcels = dl.get_parcels(bbox, self._district_key)
        if self._district_key is None:
            parcels = parcels[parcels[dl.MUNICIPALITY_COLUMN].astype(str).str.zfill(8) == municipality_key]
        parcels = parcels.reset_index(drop=True)
        if parcels.empty:
            raise RuntimeError(f"Keine Flurstuecke fuer {self._area_label()} gefunden.")
        parcels["geometry"] = parcels.geometry.buffer(0)
        self._boundary = boundary_from_parcels(parcels)

        alkis = dl.get_alkis_buildings(bbox, municipality_key)
        if self._district_key is not None:
            alkis = clip_to_boundary(alkis, self._boundary).reset_index(drop=True)
        points = alkis.geometry.representative_point()

        functions = heat_demand.load_building_functions(self._building_functions_path)
        age_table = heat_demand.load_age_classes(self._building_age_classes_path)
        self._buildings = process_buildings(
            alkis, self._load_lod2(alkis), self._load_age_classes(points), functions, age_table,
            storey_height=self._storey_height,
        )
        streets = clip_to_boundary(dl.get_streets(bbox), self._boundary).reset_index(drop=True)
        self._streets = process_streets(streets)
        self._parcels = parcels
        self._source = self._build_source(self._buildings.crs)

    def _load_lod2(self, alkis: gpd.GeoDataFrame) -> Optional[gpd.GeoDataFrame]:
        if not self._download_lod2 or alkis.empty:
            return None
        try:
            return dl.load_lod2(alkis.to_crs(CRS).geometry, self._cache_dir)
        except (RuntimeError, OSError, ET.ParseError) as e:
            logger.warning("LoD2 nicht geladen, Geschosse angenommen: %s", e)
            return None

    def _load_age_classes(self, points: gpd.GeoSeries) -> pd.Series:
        if self._download_zensus:
            try:
                return zensus.construction_classes(points, self._cache_dir)
            except (RuntimeError, OSError, KeyError, ValueError) as e:
                logger.warning("Zensus 2022 nicht geladen, Baualtersklasse angenommen: %s", e)
        return pd.Series(pd.NA, index=points.index, dtype="object")

    def _select_area(self) -> pd.DataFrame:
        """Catalogue rows of the requested district or of all districts of the municipality."""
        cities = self._load_cities()
        if self._district_key is not None:
            rows = cities[cities["schluessel"].str.lstrip("0") == self._district_key.lstrip("0")]
        else:
            rows = cities[cities["gemeinde"].astype(str) == str(self._municipality_name)]
        if rows.empty:
            raise RuntimeError(f"Kein Eintrag fuer {self._area_label()} im Gebietskatalog.")
        return rows.reset_index(drop=True)

    def _area_label(self) -> str:
        return f"district_key='{self._district_key}'" if self._district_key else f"municipality='{self._municipality_name}'"

    def _load_cities(self) -> pd.DataFrame:
        if self._cities_path is not None:
            return read_catalog(self._cities_path)
        with files("fheat_nds.data").joinpath("cities.csv").open("rb") as f:
            return read_catalog(f)

    def _build_source(self, target_crs) -> Optional[gpd.GeoDataFrame]:
        if self._source_coords is None:
            return None
        lat, lon = self._source_coords
        gdf = gpd.GeoDataFrame({"geometry": [Point(lon, lat)]}, crs="EPSG:4326")
        return gdf.to_crs(target_crs) if target_crs is not None else gdf


def _union_bounds(bboxes) -> tuple[float, float, float, float]:
    boxes = list(bboxes)
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
