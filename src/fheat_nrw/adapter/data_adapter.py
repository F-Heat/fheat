"""NRW DataAdapter — produces BuildingsSchema-compliant data."""
from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import Optional, Tuple

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point
from shapely.ops import unary_union

from fheat_core.adapters.base import DataAdapter

from fheat_nrw import download as dl
from fheat_nrw.processing import process_buildings, process_streets

REQUIRED_CITIES_COLUMNS = ("schluessel", "gmdschl", "name", "gemeinde", "bbox")


class NRWDataAdapter(DataAdapter):
    """Downloads and processes NRW Open Geodata into schema-conformant GeoDataFrames.

    All NRW-specific configuration lives here (NOT in FHeatConfig).

    Parameters
    ----------
    municipality_name : str | None
        Gemeinde-Name (z. B. "Münster"). Erforderlich, falls city_name nicht gesetzt.
    city_name : str | None
        Stadtteil/Gemarkungs-Name. Wenn gesetzt, werden Daten auf das Stadtteilgebiet
        zugeschnitten.
    source_coordinates : tuple[float, float]
        (lat, lon) der Wärmequelle in WGS84. Pflichtparameter.
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
    """

    def __init__(
        self,
        source_coordinates: Tuple[float, float],
        municipality_name: Optional[str] = None,
        city_name: Optional[str] = None,
        cities_path: Optional[Path] = None,
        building_functions_path: Optional[Path] = None,
        building_age_classes_path: Optional[Path] = None,
        heat_attribute: str = "RW_WW",
    ) -> None:
        if not municipality_name and not city_name:
            raise ValueError("NRWDataAdapter benoetigt 'municipality_name' oder 'city_name'.")
        if source_coordinates is None:
            raise ValueError("NRWDataAdapter benoetigt 'source_coordinates' (lat, lon).")

        self._municipality_name = municipality_name
        self._city_name = city_name
        self._source_coords = source_coordinates  # (lat, lon)
        self._cities_path = cities_path
        self._building_functions_path = building_functions_path
        self._building_age_classes_path = building_age_classes_path
        self._heat_attribute = heat_attribute

        self._buildings: Optional[gpd.GeoDataFrame] = None
        self._streets: Optional[gpd.GeoDataFrame] = None
        self._parcels: Optional[gpd.GeoDataFrame] = None
        self._source: Optional[gpd.GeoDataFrame] = None

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

    def fetch_source(self) -> gpd.GeoDataFrame:
        self._ensure_loaded()
        return self._source

    # ------------------------------------------------------------------
    # Internal: download + processing
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        if self._buildings is not None:
            return

        cities_df = self._load_cities()
        if self._city_name:
            name, parameter = self._city_name, "city"
        else:
            name, parameter = self._municipality_name, "municipality"

        filtered = self._filter_cities(name, cities_df, parameter)
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

        # Clip to city polygon if applicable
        if parameter == "city" and not parcels.empty:
            union = gpd.GeoDataFrame(geometry=[unary_union(parcels.geometry)], crs=parcels.crs)
            raw_buildings = gpd.sjoin(raw_buildings, union, predicate="intersects").drop(
                columns=["index_right"], errors="ignore"
            )
            raw_streets = gpd.sjoin(raw_streets, union, predicate="intersects").drop(
                columns=["index_right"], errors="ignore"
            )

        # Process into schema-compliant outputs
        info_db, wg_demand = self._load_building_info()

        self._buildings = process_buildings(
            raw=raw_buildings,
            parcels=parcels,
            building_info_db=info_db,
            wg_demand_data=wg_demand,
            heat_attribute=self._heat_attribute,
        )
        self._streets = process_streets(raw_streets)
        self._parcels = parcels
        self._source = self._build_source(self._buildings.crs)

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
        col = "name" if parameter == "city" else "gemeinde"
        result = df.loc[df[col] == name].reset_index(drop=True)
        if result.empty:
            raise RuntimeError(f"Kein Eintrag fuer {parameter}='{name}' in cities.csv.")
        return result

    def _build_source(self, target_crs) -> gpd.GeoDataFrame:
        lat, lon = self._source_coords
        gdf = gpd.GeoDataFrame({"geometry": [Point(lon, lat)]}, crs="EPSG:4326")
        if target_crs is not None:
            gdf = gdf.to_crs(target_crs)
        return gdf
