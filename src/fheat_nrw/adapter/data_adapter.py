"""NRW DataAdapter — produces BuildingsSchema-compliant data."""
from __future__ import annotations

import json
import logging
import xml.etree.ElementTree as ET
from importlib.resources import files
from pathlib import Path
from typing import Callable, Optional, Tuple

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, box
from shapely.ops import unary_union

from fheat_core import cache, cancel
from fheat_core import columns as cols
from fheat_core.adapters.base import DataAdapter

from fheat_de import biogas, mastr
from fheat_eu.loader import HeatSourceLoader
from fheat_nrw import building_gaps as gaps_mod
from fheat_nrw import download as dl
from fheat_nrw import potentials as pot
from fheat_nrw.area import boundary_from_parcels, clip_to_boundary
from fheat_nrw.civil_cost import annotate_landuse_costs
from fheat_nrw.osm_surface import annotate_osm_surface_costs, buffer_osm_lines
from fheat_nrw.processing import DATA_SOURCE, process_buildings, process_streets

logger = logging.getLogger(__name__)

#: CRS of the ALKIS WFS bbox (default CRS of the service).
LANDUSE_BBOX_CRS = "EPSG:25832"

REQUIRED_CITIES_COLUMNS = ("schluessel", "gmdschl", "name", "gemeinde", "bbox")


def _optional_path(value) -> Optional[Path]:
    return Path(value) if value is not None else None


def _read_local(path: Path, layer: Optional[str], area: gpd.GeoSeries, missing_ok: bool = False):
    """Features of a local file (ZIP, GeoPackage, Shape, Geodatabase) in ``area``.

    ``missing_ok``: a layer the file does not have gives None instead of an error.
    """
    try:
        if path.suffix.lower() == ".zip":
            return cache.read_layer_bbox(path, layer, tuple(area.total_bounds))
        kwargs = {"layer": layer} if layer else {}
        return gpd.read_file(str(path), bbox=area, **kwargs)
    except Exception:
        if missing_ok:
            return None
        raise


class NRWDataAdapter(DataAdapter):
    """Downloads and processes NRW Open Geodata into schema-conformant GeoDataFrames.

    All NRW-specific configuration lives here (NOT in FHeatConfig).

    Parameters
    ----------
    municipality_name : str | None
        Gemeinde-Name (z. B. "Münster"). Lädt die ganze Gemeinde.
    city_name : str | None
        Stadtteil/Gemarkungs-Name. Wenn gesetzt, werden Daten auf das Stadtteilgebiet
        zugeschnitten. Gibt es den Namen in mehreren Gemeinden, ist district_key nötig.
    source_coordinates : tuple[float, float] | None
        (lat, lon) der Wärmequelle in WGS84. Erst für den NETWORK-Schritt nötig;
        ohne Quelle laufen download, adjust und status (WLD & Eignung).
    cities_path : Path | None
        Optionaler Pfad zu eigener cities.csv. None → Package-Default.
    building_functions_path : Path | None
        Optionaler Pfad zu eigener building_functions.json (Lookup nach Funktionscode).
        None → Package-Default.
    building_age_classes_path : Path | None
        Optionaler Pfad zu eigener building_age_classes.json (Lookup nach Baualtersklasse).
        None → Package-Default.
    heat_attribute : str
        Name der Wärmebedarfsspalte in den NRW-Rohdaten. Standard: "RW_WW".
    district_key : str | None
        Eindeutiger Stadtteil-/Gemarkungsschlüssel (Spalte "schluessel" in cities.csv).
        Hat Vorrang vor city_name und municipality_name.
    fill_building_gaps : bool
        Wenn True (Standard), werden Wohngebäude aus ALKIS ergänzt, die das
        Wärmebedarfsmodell noch nicht hat (Neubauten nach dessen Stand),
        und wie im Modell geschätzt; die Geschosse kommen aus der Höhe des
        3D-Gebäudemodells LoD2 NRW (Kacheln im Zwischenspeicher), sonst aus
        dem Median der Neubauten (siehe ``fheat_nrw.building_gaps``). Die
        Spalte ``data_source`` kennzeichnet sie. Fehler → Warnung, ohne
        Ergänzung bzw. mit angenommenen Geschossen.
    download_landuse : bool
        Wenn True (Standard), wird die ALKIS-„Tatsächliche Nutzung" für das
        geladene Gebiet vom WFS geladen und liefert je Trasse einen
        Tiefbau-Kostenfaktor. Schlägt der Download fehl, wird eine Warnung
        geloggt und der Faktor 1.0 verwendet. ``False`` schaltet den Layer ab.
    landuse_path : Path | None
        Optionaler Pfad zu einer lokalen ALKIS-Nutzungsdatei (GeoPackage/Shape).
        Hat Vorrang vor dem WFS-Download.
    landuse_wfs : tuple[str, str] | None
        Optional ``(wfs_url, layer)`` statt ``download.URL_LANDUSE`` /
        ``download.LAYER_LANDUSE``.
    download_osm_surface : bool
        Wenn True (Standard), werden zusätzlich die OSM-Wege (``highway``/
        ``surface``) für das Gebiet von der Overpass-API geladen und als
        zweiter Tiefbau-Layer (Straßenbelag) verwendet. Fehler → Warnung +
        Faktor 1.0.
    osm_surface_path : Path | None
        Optionaler Pfad zu einer lokal vorbereiteten OSM-Wege-Datei mit den
        Spalten ``highway`` und ``surface``. Hat Vorrang vor Overpass.
    osm_overpass_url : str | None
        Anderer Overpass-Endpunkt (Standard: ``download.OVERPASS_URL``).
    area_bbox : tuple[float, float, float, float] | None
        (minx, miny, maxx, maxy) in EPSG:25832 für die beiden Tiefbau-Layer.
        Ohne Angabe folgen sie den geladenen Gebäuden, Straßen und der Quelle.
        Mit Angabe laden ``fetch_landuse``/``fetch_osm_surface`` nur die Layer,
        ohne die Gebäude herunterzuladen (z. B. für ein schon gespeichertes
        Gebiet); die Layer kommen dann in EPSG:25832. Das gilt auch für die
        Potenzial-Layer.
    download_geothermal_shallow : bool
        Wenn True (Standard), werden die Kennwerte der oberflächennahen
        Geothermie vom WFS des GD NRW (IS GT 50) geladen: Wärmeleitfähigkeit
        für Sonden von 40 bis 100 m, Entzugsleistung für Kollektoren und ein
        daraus abgeleiteter Richtwert für die Entzugsleistung der Sonden.
        Fehler → Warnung, kein Layer.
    geothermal_shallow_path : Path | None
        GeoPackage mit den Layern ``ews40`` … ``ewk2400`` (Rohattribute wie
        vom WFS). Hat Vorrang vor dem WFS.
    geothermal_wfs : str | None
        Anderer WFS-Endpunkt (Standard: ``download.URL_GEOTHERMAL``).
    borehole_extraction_path : Path | None
        Eigene Tabelle Wärmeleitfähigkeit → Entzugsleistung der Sonden (JSON
        wie ``fheat_nrw/data/borehole_extraction.json``, Standard VDI 4640
        Blatt 2 von 2001). Ein Screening-Richtwert, nicht für die Auslegung.
    download_geothermal_blocks : bool
        Wenn True (Standard), wird das Potenzial der oberflächennahen und
        mitteltiefen Geothermie je Baublock aus der Wärmestudie des LANUK
        geladen (aus dem Gemeinde-ZIP, im Zwischenspeicher). Fehler → Warnung,
        kein Layer.
    geothermal_blocks_path : Path | None
        Lokale ONG/MTG-Datei der Wärmestudie (Shape, GeoPackage, Geodatabase
        oder ZIP). Hat Vorrang vor dem Download.
    download_geothermal_deep : bool
        Wenn True (Standard), werden die Rasterzellen (3 × 3 km) der LANUK-
        Wärmestudie zur hydrothermalen Geothermie (Dublette, mitteltief und
        tief) im Umkreis des Gebiets geladen (NRW-Datei, 2 MB, im
        Zwischenspeicher). Grobe Abschätzung, Fündigkeit unbekannt; der
        Zellmittelpunkt ist ein Vorschlag für ``source_coordinates``, es wird
        keine Quelle gesetzt. Fehler → Warnung, kein Layer.
    geothermal_deep_path : Path | None
        Lokale TG-Rasterdatei der Wärmestudie. Hat Vorrang vor dem Download.
    geothermal_deep_buffer : float
        Umkreis um das Gebiet in m (Standard 5000), weil eine Dublette nicht
        im Wohngebiet stehen muss.
    download_solar_thermal : bool
        Wenn True (Standard), wird das Potenzial der Freiflächen-Solarthermie
        je Flur aus der LANUK-Wärmestudie im Umkreis des Gebiets geladen
        (NRW-Datei, 63 MB, im Zwischenspeicher), mit Abstand zum Gebiet und
        zum nächsten Gebäude mit Wärmebedarf. Fehler → Warnung, kein Layer.
    solar_thermal_path : Path | None
        Lokale FF-Solarthermie-Datei der Wärmestudie. Hat Vorrang vor dem Download.
    solar_thermal_buffer : float
        Umkreis um das Gebiet in m (Standard 2000).
    download_heat_sources : bool
        Wenn True (Standard), werden die Wärmequellen im Umkreis geladen:
        Kläranlagen aus der LANUK-Liste der kommunalen Kläranlagen (Wärme aus
        der Jahresabwassermenge), dazu aus dem Datensatz des Fraunhofer ISI
        (Manz et al. 2024, Stand 2050, einmal in den Zwischenspeicher)
        Industrie-Abwärme, Müllverbrennung, Flüsse und Seen sowie
        Wärmenetzgebiete und Werte der Studie für die Gemeinde. Die
        Hydrothermie kommt in NRW aus dem LANUK-Raster
        (``fetch_geothermal_deep``). Außerdem die Biogas-BHKW im Gebiet aus
        dem Marktstammdatenregister (Bestand, einmal in den
        Zwischenspeicher) und ihre Cluster. Fehler → Warnung, kein Layer.
    heat_source_buffers : dict | None
        Umkreis je Wärmequelle in m, z. B. ``{"industrial_heat": 10000}``
        (Standard: Höchstabstände des Papers, siehe
        ``fheat_eu.heat_sources.DEFAULT_BUFFERS``).
    fordatis_path : Path | None
        Eigener Ordner mit den Fordatis-Dateien; dann wird von Fordatis
        nichts geladen.
    wastewater_path : Path | None
        Lokale Datei der LANUK-Kläranlagen. Hat Vorrang vor dem Download.
    cache_dir : Path | None
        Ordner für große Downloads (Standard: ``FHEAT_CACHE_DIR`` oder
        ``~/.cache/fheat``).
    """

    def __init__(
        self,
        source_coordinates: Optional[Tuple[float, float]] = None,
        municipality_name: Optional[str] = None,
        city_name: Optional[str] = None,
        cities_path: Optional[Path] = None,
        building_functions_path: Optional[Path] = None,
        building_age_classes_path: Optional[Path] = None,
        heat_attribute: str = "RW_WW",
        district_key: Optional[str] = None,
        fill_building_gaps: bool = True,
        download_landuse: bool = True,
        landuse_path: Optional[Path] = None,
        landuse_wfs: Optional[Tuple[str, str]] = None,
        download_osm_surface: bool = True,
        osm_surface_path: Optional[Path] = None,
        osm_overpass_url: Optional[str] = None,
        area_bbox: Optional[Tuple[float, float, float, float]] = None,
        download_geothermal_shallow: bool = True,
        geothermal_shallow_path: Optional[Path] = None,
        geothermal_wfs: Optional[str] = None,
        borehole_extraction_path: Optional[Path] = None,
        download_geothermal_blocks: bool = True,
        geothermal_blocks_path: Optional[Path] = None,
        download_geothermal_deep: bool = True,
        geothermal_deep_path: Optional[Path] = None,
        geothermal_deep_buffer: float = 5000.0,
        download_solar_thermal: bool = True,
        solar_thermal_path: Optional[Path] = None,
        solar_thermal_buffer: float = 2000.0,
        download_heat_sources: bool = True,
        heat_source_buffers: Optional[dict] = None,
        fordatis_path: Optional[Path] = None,
        wastewater_path: Optional[Path] = None,
        cache_dir: Optional[Path] = None,
    ) -> None:
        if not municipality_name and not city_name and not district_key:
            raise ValueError(
                "NRWDataAdapter benoetigt 'municipality_name', 'city_name' oder 'district_key'."
            )

        self._municipality_name = municipality_name
        self._city_name = city_name
        self._district_key = str(district_key) if district_key else None
        self._source_coords = source_coordinates  # (lat, lon) or None
        self._cities_path = cities_path
        self._building_functions_path = building_functions_path
        self._building_age_classes_path = building_age_classes_path
        self._heat_attribute = heat_attribute
        self._fill_building_gaps = bool(fill_building_gaps)
        self._download_landuse = bool(download_landuse)
        self._landuse_path = Path(landuse_path) if landuse_path is not None else None
        self._landuse_wfs = landuse_wfs
        self._download_osm_surface = bool(download_osm_surface)
        self._osm_surface_path = Path(osm_surface_path) if osm_surface_path is not None else None
        self._osm_overpass_url = osm_overpass_url
        self._area_bbox = tuple(float(v) for v in area_bbox) if area_bbox is not None else None
        self._download_geothermal_shallow = bool(download_geothermal_shallow)
        self._geothermal_shallow_path = _optional_path(geothermal_shallow_path)
        self._geothermal_wfs = geothermal_wfs
        self._borehole_extraction_path = _optional_path(borehole_extraction_path)
        self._download_geothermal_blocks = bool(download_geothermal_blocks)
        self._geothermal_blocks_path = _optional_path(geothermal_blocks_path)
        self._download_geothermal_deep = bool(download_geothermal_deep)
        self._geothermal_deep_path = _optional_path(geothermal_deep_path)
        self._geothermal_deep_buffer = float(geothermal_deep_buffer)
        self._download_solar_thermal = bool(download_solar_thermal)
        self._solar_thermal_path = _optional_path(solar_thermal_path)
        self._solar_thermal_buffer = float(solar_thermal_buffer)
        self._download_heat_sources = bool(download_heat_sources)
        self._heat_source_buffers = dict(heat_source_buffers or {})
        self._fordatis_path = _optional_path(fordatis_path)
        self._wastewater_path = _optional_path(wastewater_path)
        self._cache_dir = _optional_path(cache_dir)
        self._heat_source_loader: Optional[HeatSourceLoader] = None

        self._buildings: Optional[gpd.GeoDataFrame] = None
        self._streets: Optional[gpd.GeoDataFrame] = None
        self._parcels: Optional[gpd.GeoDataFrame] = None
        self._source: Optional[gpd.GeoDataFrame] = None
        self._boundary: Optional[gpd.GeoDataFrame] = None
        # Optional layers (civil works, potentials), loaded once: a failed
        # download stays None instead of being tried again by every step that asks.
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
        """Amtlicher Gemeindeschlüssel (AGS, 8 digits) of the area, from cities.csv; no download."""
        filtered, _ = self._select_area(self._load_cities())
        return str(filtered["gmdschl"].iloc[0]).zfill(8)

    def provide_boundary(self) -> gpd.GeoDataFrame:
        """Outline of the downloaded municipality or district (union of its parcels)."""
        self._ensure_loaded()
        if self._boundary is None:
            self._boundary = boundary_from_parcels(self._parcels)
        return self._boundary

    def fetch_landuse(self) -> Optional[gpd.GeoDataFrame]:
        """ALKIS land use of the loaded area with ``civil_cost_factor`` (None on failure)."""
        return self._optional_layer(
            "landuse", self._load_landuse,
            "ALKIS-Flaechennutzung konnte nicht geladen werden (%s) — Tiefbau-Faktor 1.0 "
            "fuer diesen Layer. Endpunkt via landuse_wfs=(url, layer) oder landuse_path=... "
            "setzen, oder download_landuse=False zum Abschalten.",
        )

    def fetch_osm_surface(self) -> Optional[gpd.GeoDataFrame]:
        """Buffered OSM roads of the loaded area with ``civil_cost_factor`` (None on failure)."""
        return self._optional_layer(
            "osm_surface", self._load_osm_surface,
            "OSM-Strassenbelaege konnten nicht geladen werden (%s) — Tiefbau-Faktor 1.0 "
            "fuer diesen Layer. Endpunkt via osm_overpass_url=... oder osm_surface_path=... "
            "setzen, oder download_osm_surface=False zum Abschalten.",
        )

    def fetch_geothermal_shallow(self) -> Optional[gpd.GeoDataFrame]:
        """GD NRW shallow geothermal parameters of the loaded area (None on failure)."""
        return self._optional_layer(
            "geothermal_shallow", self._load_geothermal_shallow,
            "Kennwerte oberflaechennahe Geothermie (GD NRW) konnten nicht geladen werden (%s) — "
            "kein Layer. Endpunkt via geothermal_wfs=... oder geothermal_shallow_path=... setzen, "
            "oder download_geothermal_shallow=False zum Abschalten.",
        )

    def fetch_geothermal_blocks(self) -> Optional[gpd.GeoDataFrame]:
        """LANUK ONG/MTG potential per building block of the loaded area (None on failure)."""
        return self._optional_layer(
            "geothermal_blocks", self._load_geothermal_blocks,
            "Geothermie-Potenzial je Baublock (LANUK) konnte nicht geladen werden (%s) — "
            "kein Layer. Lokale Datei via geothermal_blocks_path=... setzen, "
            "oder download_geothermal_blocks=False zum Abschalten.",
        )

    def fetch_geothermal_deep(self) -> Optional[gpd.GeoDataFrame]:
        """LANUK doublet raster cells around the loaded area (None on failure)."""
        return self._optional_layer(
            "geothermal_deep", self._load_geothermal_deep,
            "Raster tiefe Geothermie (LANUK) konnte nicht geladen werden (%s) — kein Layer. "
            "Lokale Datei via geothermal_deep_path=... setzen, "
            "oder download_geothermal_deep=False zum Abschalten.",
        )

    def fetch_solar_thermal(self) -> Optional[gpd.GeoDataFrame]:
        """LANUK ground-mounted solar thermal per Flur around the loaded area (None on failure)."""
        return self._optional_layer(
            "solar_thermal", self._load_solar_thermal,
            "Freiflaechen-Solarthermie (LANUK) konnte nicht geladen werden (%s) — kein Layer. "
            "Lokale Datei via solar_thermal_path=... setzen, "
            "oder download_solar_thermal=False zum Abschalten.",
        )

    def fetch_wastewater(self) -> Optional[gpd.GeoDataFrame]:
        """LANUK municipal wastewater plants near the loaded area (None on failure)."""
        return self._optional_layer(
            "wastewater", self._load_wastewater,
            "Kläranlagen (LANUK) konnten nicht geladen werden (%s) — kein Layer. "
            "Lokale Datei via wastewater_path=... setzen, "
            "oder download_heat_sources=False zum Abschalten.",
        )

    def fetch_industrial_heat(self) -> Optional[gpd.GeoDataFrame]:
        """Industrial excess heat (Fraunhofer ISI) around the loaded area (None on failure)."""
        return self._heat_source_layer("industrial_heat", "Industrie-Abwärme")

    def fetch_waste_incineration(self) -> Optional[gpd.GeoDataFrame]:
        """Waste incineration plants (Fraunhofer ISI) around the loaded area (None on failure)."""
        return self._heat_source_layer("waste_incineration", "Müllverbrennung")

    def fetch_river_heat(self) -> Optional[gpd.GeoDataFrame]:
        """Zones of rivers and lakes (Fraunhofer ISI) around the loaded area (None on failure)."""
        return self._heat_source_layer("river_heat", "Flüsse und Seen")

    def fetch_study_dh_areas(self) -> Optional[gpd.GeoDataFrame]:
        """District heating areas of the study in the municipality (None without or on failure)."""
        return self._heat_source_layer("study_dh_areas", "Wärmenetzgebiete der Studie")

    def fetch_study_potentials(self) -> Optional[pd.DataFrame]:
        """Table of the study for the municipality (None without or on failure)."""
        return self._heat_source_layer("study_potentials", "Werte der Studie")

    def fetch_biogas(self) -> Optional[gpd.GeoDataFrame]:
        """Biogas CHP units of the Marktstammdatenregister in the loaded area (None on failure)."""
        return self._optional_layer(
            "biogas", self._load_biogas,
            "Biogas-BHKW (Marktstammdatenregister) konnten nicht geladen werden (%s) — kein Layer. "
            "download_heat_sources=False zum Abschalten.",
        )

    def fetch_biogas_clusters(self) -> Optional[gpd.GeoDataFrame]:
        """Clusters of the biogas CHP units in the loaded area (None without units)."""
        return self._optional_layer(
            "biogas_clusters", self._load_biogas_clusters,
            "Biogas-Cluster konnten nicht gebildet werden (%s) — kein Layer.",
        )

    # ------------------------------------------------------------------
    # Internal: optional layers (civil works, potentials)
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
            url, layer = self._landuse_wfs or (dl.URL_LANDUSE, dl.LAYER_LANDUSE)
            bbox = tuple(float(v) for v in self._area_box().to_crs(LANDUSE_BBOX_CRS).total_bounds)
            raw = dl.get_landuse_from_wfs(url, bbox, layer)
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
            raw = dl.get_osm_surface_via_overpass(
                (float(miny), float(minx), float(maxy), float(maxx)),
                overpass_url=self._osm_overpass_url or dl.OVERPASS_URL,
            )
        else:
            return None
        if raw is None or raw.empty:
            return None
        # buffer in the metric CRS of the buildings
        return annotate_osm_surface_costs(buffer_osm_lines(self._to_area_crs(raw)))

    def _load_geothermal_shallow(self) -> Optional[gpd.GeoDataFrame]:
        box_25832 = self._area_box().to_crs(LANDUSE_BBOX_CRS)
        if self._geothermal_shallow_path is not None:
            raw = {
                key: _read_local(self._geothermal_shallow_path, key, box_25832, missing_ok=True)
                for key in dl.LAYERS_GEOTHERMAL
            }
        elif self._download_geothermal_shallow:
            url = self._geothermal_wfs or dl.URL_GEOTHERMAL
            bbox = tuple(float(v) for v in box_25832.total_bounds)
            raw = {}
            for key, layer in dl.LAYERS_GEOTHERMAL.items():
                cancel.raise_if_cancelled()
                raw[key] = dl.get_geothermal_from_wfs(url, bbox, layer)
        else:
            return None
        for key, gdf in raw.items():
            if gdf is not None:
                dl.check_geothermal_unit(gdf, key)
        if all(gdf is None or gdf.empty for gdf in raw.values()):
            return None
        table = pot.load_borehole_table(self._borehole_extraction_path)
        merged = pot.merge_geothermal_layers(raw, box_25832.iloc[0], LANDUSE_BBOX_CRS, table)
        return self._to_area_crs(merged)

    def _load_geothermal_blocks(self) -> Optional[gpd.GeoDataFrame]:
        box_25832 = self._area_box().to_crs(LANDUSE_BBOX_CRS)
        buildings = self._buildings
        if self._geothermal_blocks_path is not None:
            raw = _read_local(self._geothermal_blocks_path, None, box_25832)
        elif self._download_geothermal_blocks:
            zip_path, padded_key = self._municipality_zip()
            bbox = tuple(box_25832.total_bounds)
            raw = cache.read_layer_bbox(zip_path, f"Potenzial-ONG-MTG-Baublock_{padded_key}", bbox)
            if buildings is None and pot.BLOCK_ID_FIELD not in raw.columns:
                # The municipality shapefile has no block_id: take it from the
                # buildings of the same ZIP (0.5 s), also when only area_bbox is known.
                buildings = cache.read_layer_bbox(zip_path, f"WBM-NRW_{padded_key}", bbox)
                buildings = buildings[["Block_ID", "geometry"]].rename(columns={"Block_ID": cols.BLOCK_ID})
        else:
            return None
        if raw is None or raw.empty:
            return None
        blocks = pot.process_blocks(self._to_area_crs(raw), buildings)
        return self._inside_outline(blocks)

    def _load_geothermal_deep(self) -> Optional[gpd.GeoDataFrame]:
        raw = self._load_nrw_layer(
            self._geothermal_deep_path, self._download_geothermal_deep,
            dl.FILE_DEEP_GEOTHERMAL, dl.LAYER_DEEP_GEOTHERMAL, self._geothermal_deep_buffer,
        )
        if raw is None or raw.empty:
            return None
        cells = pot.process_deep_cells(raw, self._area_outline())
        cells = cells[cells[cols.DISTANCE_TO_AREA] <= self._geothermal_deep_buffer]
        return self._to_area_crs(cells.reset_index(drop=True))

    def _load_solar_thermal(self) -> Optional[gpd.GeoDataFrame]:
        raw = self._load_nrw_layer(
            self._solar_thermal_path, self._download_solar_thermal,
            dl.FILE_SOLAR_THERMAL, dl.LAYER_SOLAR_THERMAL, self._solar_thermal_buffer,
        )
        if raw is None or raw.empty:
            return None
        fields = pot.process_solar_thermal(raw, self._area_outline(), self._buildings)
        fields = fields[fields[cols.DISTANCE_TO_AREA] <= self._solar_thermal_buffer]
        return self._to_area_crs(fields.reset_index(drop=True))

    def _load_wastewater(self) -> Optional[gpd.GeoDataFrame]:
        buffer = self._heat_sources().buffers["wastewater"]
        raw = self._load_nrw_layer(
            self._wastewater_path, self._download_heat_sources,
            dl.FILE_WASTEWATER, dl.LAYER_WASTEWATER, buffer, url=dl.URL_WASTEWATER,
        )
        if raw is None or raw.empty:
            return None
        plants = pot.process_wastewater_plants(raw, self._area_outline())
        plants = plants[plants[cols.DISTANCE_TO_AREA] <= buffer]
        return self._to_area_crs(plants.reset_index(drop=True))

    def _load_biogas(self) -> Optional[gpd.GeoDataFrame]:
        if not self._download_heat_sources:
            return None
        units = biogas.process_biogas(mastr.read_biomass_tables(self._cache_dir), self._area_outline(), LANDUSE_BBOX_CRS)
        return self._to_area_crs(units)

    def _load_biogas_clusters(self) -> Optional[gpd.GeoDataFrame]:
        units = self.fetch_biogas()
        return None if units is None else biogas.biogas_clusters(units)

    def _heat_source_layer(self, key: str, label: str):
        """A layer of :class:`fheat_eu.loader.HeatSourceLoader` (method ``key``), None on failure."""
        return self._optional_layer(
            key, lambda: self._load_heat_source(key),
            f"{label} (Fraunhofer ISI) konnte nicht geladen werden (%s) — kein Layer. "
            "Eigene Kopie der Fordatis-Dateien via fordatis_path=... setzen, "
            "oder download_heat_sources=False zum Abschalten.",
        )

    def _load_heat_source(self, key: str):
        if not self._download_heat_sources and self._fordatis_path is None:
            return None
        layer = getattr(self._heat_sources(), key)()
        if layer is None or not isinstance(layer, gpd.GeoDataFrame):
            return layer  # the study table has no geometry
        return self._to_area_crs(layer)

    def _heat_sources(self) -> HeatSourceLoader:
        """Loader of the heat sources around the area outline (EPSG:25832)."""
        if self._heat_source_loader is None:
            cities = self._load_cities()
            names = set(cities["gemeinde"].astype(str)) | set(cities["name"].astype(str))
            self._heat_source_loader = HeatSourceLoader(
                self._area_outline(), LANDUSE_BBOX_CRS, self._heat_source_buffers, self._cache_dir,
                self._fordatis_path, lau_id=f"DE_{self.municipality_key}", known_names=names,
            )
        return self._heat_source_loader

    def _load_nrw_layer(
        self, path: Optional[Path], download: bool, filename: str, layer: str, buffer: float,
        url: str = dl.URL_BUILDINGS,
    ) -> Optional[gpd.GeoDataFrame]:
        """Features of an NRW-wide LANUK file in the area box widened by ``buffer`` m, EPSG:25832."""
        around = self._area_box().to_crs(LANDUSE_BBOX_CRS).buffer(buffer, join_style=2)
        if path is not None:
            raw = _read_local(path, None, around)
        elif download:
            zip_path = dl.cached_file(url, filename, self._cache_dir)
            raw = cache.read_layer_bbox(zip_path, layer, tuple(around.total_bounds))
        else:
            return None
        if raw is None or raw.empty:
            return raw
        if raw.crs is not None and raw.crs != LANDUSE_BBOX_CRS:
            raw = raw.to_crs(LANDUSE_BBOX_CRS)
        return raw[raw.intersects(around.iloc[0])].reset_index(drop=True)

    def _area_outline(self):
        """Outline of the loaded area in EPSG:25832 (the area box without buildings)."""
        if self._buildings is not None:
            outline = self.provide_boundary()
            if outline is not None and not outline.empty:
                return unary_union(outline.to_crs(LANDUSE_BBOX_CRS).geometry.values)
        return self._area_box().to_crs(LANDUSE_BBOX_CRS).iloc[0]

    def _municipality_zip(self) -> tuple[Path, str]:
        """Cached municipality ZIP of the heat study and its 8-digit key."""
        filtered, _ = self._select_area(self._load_cities())
        municipality_key = str(filtered["gmdschl"].iloc[0])
        files = dl.file_list_from_url(dl.URL_BUILDINGS + "index.json")
        name = dl.search_filename(files, municipality_key)
        if name == "No data found":
            raise RuntimeError(f"Keine NRW-Daten fuer Gemeindeschluessel '{municipality_key}' gefunden.")
        return dl.cached_file(dl.URL_BUILDINGS, name, self._cache_dir, files), municipality_key.zfill(8)

    def _inside_outline(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """Features whose inner point lies in the loaded area (all of them if it is not loaded)."""
        if self._buildings is None or gdf.empty:
            return gdf
        outline = self.provide_boundary()
        if outline is None or outline.empty:
            return gdf
        if outline.crs != gdf.crs:
            outline = outline.to_crs(gdf.crs)
        inside = gdf.geometry.representative_point().within(unary_union(outline.geometry.values))
        return gdf[inside].reset_index(drop=True)

    def _area_box(self) -> gpd.GeoSeries:
        """Bounding box of everything a network can use: buildings, streets, source.

        Taken from the loaded data, not from the catalogue bbox, so it also
        fits a district cut out of its municipality — unless ``area_bbox`` was
        given.
        """
        if self._area_bbox is not None:
            return gpd.GeoSeries([box(*self._area_bbox)], crs=LANDUSE_BBOX_CRS)
        self._ensure_loaded()
        crs = self._buildings.crs
        frames = [g for g in (self._buildings, self._streets, self._source) if g is not None and not g.empty]
        bounds = [(g.to_crs(crs) if g.crs != crs else g).total_bounds for g in frames]
        return gpd.GeoSeries(
            [box(min(b[0] for b in bounds), min(b[1] for b in bounds),
                 max(b[2] for b in bounds), max(b[3] for b in bounds))],
            crs=crs,
        )

    def _to_area_crs(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        if self._area_bbox is not None and self._buildings is None:
            crs = LANDUSE_BBOX_CRS
        else:
            self._ensure_loaded()
            crs = self._buildings.crs
        if gdf.crs is not None and crs is not None and gdf.crs != crs:
            return gdf.to_crs(crs)
        return gdf

    # ------------------------------------------------------------------
    # Internal: download + processing
    # ------------------------------------------------------------------

    def _select_area(self, cities_df: pd.DataFrame) -> tuple[pd.DataFrame, str]:
        """Catalogue rows of the requested area and whether it is a district ("city")."""
        if self._district_key:
            return self._filter_cities(self._district_key, cities_df, "district"), "city"
        if self._city_name:
            return self._filter_cities(self._city_name, cities_df, "city"), "city"
        return self._filter_cities(self._municipality_name, cities_df, "municipality"), "municipality"

    def _ensure_loaded(self) -> None:
        if self._buildings is not None:
            return

        cities_df = self._load_cities()
        filtered, parameter = self._select_area(cities_df)
        municipality_key = str(filtered["gmdschl"].iloc[0])
        padded_key = municipality_key.zfill(8)  # ZIP internals use 8-digit zero-padded keys

        # Download buildings + streets ZIP
        all_files = dl.file_list_from_url(dl.URL_BUILDINGS + "index.json")
        buildings_zip = dl.search_filename(all_files, municipality_key)
        if buildings_zip == "No data found":
            raise RuntimeError(
                f"Keine NRW-Daten fuer Gemeindeschluessel '{municipality_key}' gefunden."
            )

        raw_buildings = dl.read_shapefile_from_zip(
            dl.URL_BUILDINGS, buildings_zip, f"WBM-NRW_{padded_key}"
        )
        raw_streets = dl.read_shapefile_from_zip(
            dl.URL_BUILDINGS, buildings_zip, f"WBM-NRW-Waermelinien_{padded_key}"
        )

        # Download parcels via WFS
        parcel_list = []
        for row in filtered.itertuples():
            parcel_list.append(
                dl.get_parcels_from_wfs(dl.URL_PARCELS, row.schluessel, row.bbox, dl.LAYER_PARCELS)
            )
        parcels = pd.concat(parcel_list, ignore_index=True)

        # Repair geometries
        if not raw_buildings.empty:
            raw_buildings["geometry"] = raw_buildings["geometry"].buffer(0)
        if not parcels.empty:
            parcels["geometry"] = parcels["geometry"].buffer(0)

        # Clip to the district outline if applicable
        if parameter == "city" and not parcels.empty:
            self._boundary = boundary_from_parcels(parcels)
            raw_buildings = clip_to_boundary(raw_buildings, self._boundary)
            raw_streets = clip_to_boundary(raw_streets, self._boundary)

        alkis = self._load_alkis_buildings(raw_buildings)
        if self._fill_building_gaps and alkis is not None:
            raw_buildings = self._with_building_gaps(raw_buildings, alkis, padded_key)

        # Process into schema-compliant outputs
        info_db, wg_demand = self._load_building_info()

        self._buildings = process_buildings(
            raw=raw_buildings,
            parcels=parcels,
            building_info_db=info_db,
            wg_demand_data=wg_demand,
            heat_attribute=self._heat_attribute,
            addresses=alkis,
        )
        self._streets = process_streets(raw_streets)
        self._parcels = parcels
        self._source = self._build_source(self._buildings.crs)

    def _load_alkis_buildings(self, raw_buildings: gpd.GeoDataFrame) -> Optional[gpd.GeoDataFrame]:
        """ALKIS buildings of the area: their addresses, and the buildings to add."""
        if raw_buildings.empty:
            return None
        bbox = tuple(float(v) for v in raw_buildings.to_crs(LANDUSE_BBOX_CRS).total_bounds)
        try:
            alkis = dl.get_alkis_buildings_from_wfs(dl.URL_LANDUSE, bbox, dl.LAYER_ALKIS_BUILDINGS)
        except RuntimeError as e:
            logger.warning(
                "ALKIS-Gebaeude nicht geladen: Gebaeude nur nach Beruehrung zusammengefasst, "
                "keine fehlenden Wohngebaeude ergaenzt: %s", e,
            )
            return None
        return alkis.set_crs(LANDUSE_BBOX_CRS) if alkis.crs is None else alkis

    def _with_building_gaps(
        self, raw_buildings: gpd.GeoDataFrame, alkis: gpd.GeoDataFrame, municipality_key: str
    ) -> gpd.GeoDataFrame:
        """The WBM-NRW buildings and the residential ALKIS buildings it does not have."""
        gaps = gaps_mod.residential_gaps(
            alkis.to_crs(raw_buildings.crs), raw_buildings, municipality_key, self._heat_attribute
        )
        if self._boundary is not None:
            gaps = clip_to_boundary(gaps, self._boundary).reset_index(drop=True)
        if gaps.empty:
            return raw_buildings
        try:
            lod2 = gaps_mod.load_lod2(gaps.to_crs(LANDUSE_BBOX_CRS).geometry, self._cache_dir)
        except (RuntimeError, OSError, ET.ParseError) as e:
            logger.warning("LoD2 nicht geladen, Geschosse der ergaenzten Gebaeude angenommen: %s", e)
            lod2 = None
        added = gaps_mod.estimate_gaps(gaps, raw_buildings, self._heat_attribute, lod2)
        logger.info(
            "%d Wohngebaeude aus ALKIS ergaenzt (%d mit LoD2-Hoehe)",
            len(added), int((added[DATA_SOURCE] == gaps_mod.SOURCE_LOD2).sum()) if len(added) else 0,
        )
        if added.empty:
            return raw_buildings
        return gpd.GeoDataFrame(pd.concat([raw_buildings, added], ignore_index=True), crs=raw_buildings.crs)

    def _load_cities(self) -> pd.DataFrame:
        df = self._read_cities_csv()
        rename_map = {c: c.strip().lower() for c in df.columns if str(c).strip().lower() != c}
        if rename_map:
            df = df.rename(columns=rename_map)
        missing = set(REQUIRED_CITIES_COLUMNS) - set(df.columns)
        if missing:
            raise RuntimeError(f"cities.csv fehlen Spalten: {sorted(missing)}")
        df["schluessel"] = df["schluessel"].astype(str)
        df["gmdschl"] = df["gmdschl"].astype(str)
        try:
            df["bbox"] = df["bbox"].apply(dl.parse_bbox)
        except (ValueError, TypeError) as e:
            raise RuntimeError(f"Ungueltiges bbox-Format in cities.csv: {e}") from e
        return df

    def _read_cities_csv(self) -> pd.DataFrame:
        if self._cities_path is not None:
            return pd.read_csv(self._cities_path)
        with (files("fheat_nrw.data").joinpath("cities.csv")).open("rb") as f:
            return pd.read_csv(f)

    @staticmethod
    def _keyed_json_to_df(raw: dict, key_name: str) -> pd.DataFrame:
        """Object-keyed JSON (TEASER-Stil) → DataFrame mit Schlüssel als Spalte."""
        return pd.DataFrame.from_dict(raw, orient="index").reset_index(names=key_name)

    def _load_building_info(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Lädt Funktions- und Baualtersklassen-Lookup als DataFrames.

        Quelle sind zwei JSON-Dateien (gekeyt nach Funktionscode bzw. Baualtersklasse);
        zurückgegeben wird die DataFrame-Form, die die Merge-Logik in processing.py erwartet.
        """
        if self._building_functions_path is not None:
            functions = json.loads(Path(self._building_functions_path).read_text(encoding="utf-8"))
        else:
            with (files("fheat_nrw.data").joinpath("building_functions.json")).open(
                "r", encoding="utf-8"
            ) as f:
                functions = json.load(f)

        if self._building_age_classes_path is not None:
            age = json.loads(Path(self._building_age_classes_path).read_text(encoding="utf-8"))
        else:
            with (files("fheat_nrw.data").joinpath("building_age_classes.json")).open(
                "r", encoding="utf-8"
            ) as f:
                age = json.load(f)

        db = self._keyed_json_to_df(functions, "Funktion")
        wg = self._keyed_json_to_df(age, "Baualtersklasse")
        return db, wg

    @staticmethod
    def _filter_cities(name: str, df: pd.DataFrame, parameter: str) -> pd.DataFrame:
        col = {"city": "name", "municipality": "gemeinde", "district": "schluessel"}[parameter]
        result = df.loc[df[col].astype(str) == str(name)].reset_index(drop=True)
        if result.empty:
            raise RuntimeError(f"Kein Eintrag fuer {parameter}='{name}' in cities.csv.")
        if parameter == "city" and result["schluessel"].nunique() > 1:
            options = ", ".join(
                f"{row.gemeinde}: {row.schluessel}" for row in result.itertuples()
            )
            raise RuntimeError(
                f"Stadtteil '{name}' ist mehrdeutig ({options}). "
                "Bitte district_key (schluessel) angeben."
            )
        return result

    def _build_source(self, target_crs) -> Optional[gpd.GeoDataFrame]:
        if self._source_coords is None:
            return None
        lat, lon = self._source_coords
        gdf = gpd.GeoDataFrame({"geometry": [Point(lon, lat)]}, crs="EPSG:4326")
        if target_crs is not None:
            gdf = gdf.to_crs(target_crs)
        return gdf
