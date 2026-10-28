"""Residential ALKIS buildings that the heat demand model WBM-NRW does not have.

WBM-NRW (LANUV, Stand 01.09.2024) lacks the buildings built since; ALKIS has
them. The residential ones (Wohnen and gemischt genutzt mit Wohnen) are added,
except annexes of houses in WBM-NRW, and estimated the way WBM-NRW computes
its buildings, from the WBM-NRW buildings of the same municipality (checked
on Vreden, 2026-10-28):

- net floor area = 0.7 × footprint × storeys, as in WBM-NRW (exact for all
  12 133 residential buildings of Vreden);
- storeys from the measured height of the 3D building model LoD2 NRW. That
  height is not the WBM-NRW height, so the storeys per metre of LoD2 height
  are learned from the WBM-NRW buildings in the same LoD2 tiles (right for
  81 % of them in Vreden, for 72 % of the new ones). A building without LoD2
  height (built after its footprints) gets the median storeys of the WBM-NRW
  buildings since 2015;
- the newest age class: a building missing in WBM-NRW is new;
- type EFH, MFH above the largest EFH floor area, GMFH above the largest
  MFH floor area (WBM-NRW separates them at 280 m² and 400 m², the largest
  EFH and MFH of Vreden); row houses stay EFH, they are told apart only by
  touching buildings;
- specific heat demand: median of the WBM-NRW buildings of the newest age
  class and the type.

The rows have the columns of the WBM-NRW buildings that
:func:`fheat_nrw.processing.process_buildings` reads; ``DATA_SOURCE`` says
how the storeys were found.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Polygon
from shapely.ops import unary_union

from fheat_core import cancel
from fheat_nrw import download as dl
from fheat_nrw.processing import DATA_SOURCE, _resolve_heat_col

SOURCE_LOD2 = "alkis_lod2"        # added from ALKIS, storeys from the LoD2 height
SOURCE_ASSUMED = "alkis_assumed"  # added from ALKIS, storeys assumed

#: ALKIS functions (last four digits of "31001_xxxx") of residential buildings:
#: 1000-1299 are Wohnen and gemischt genutzt mit Wohnen; 13xx (Freizeit,
#: Ferien-, Wochenend-, Gartenhaus) and all others are not added.
RESIDENTIAL_FUNCTIONS = (1000, 1299)
NET_FLOOR_FACTOR = 0.7
#: WBM-NRW age classes from this year on count as new buildings.
NEW_SINCE = 2015
#: With fewer WBM-NRW buildings in the LoD2 footprints, all storeys are assumed.
MIN_HEIGHT_SAMPLES = 30

_NS = {"bldg": "http://www.opengis.net/citygml/building/1.0", "gml": "http://www.opengis.net/gml"}
_BUILDING = f"{{{_NS['bldg']}}}Building"
_GML_ID = f"{{{_NS['gml']}}}id"
_LOD2_CRS = "EPSG:25832"


def residential_gaps(
    alkis: gpd.GeoDataFrame, raw: gpd.GeoDataFrame, municipality_key: str, heat_attribute: str
) -> gpd.GeoDataFrame:
    """Residential ALKIS buildings of the municipality without a WBM-NRW building at their point.

    Not the annexes of houses in WBM-NRW (no address, touching a building
    with heat demand): they get no house connection of their own.
    """
    code = alkis["gfkzshh"].astype(str)
    function = pd.to_numeric(code.str[-4:], errors="coerce")
    residential = code.str.startswith("31001_") & function.between(*RESIDENTIAL_FUNCTIONS)
    own = alkis["gmdschl"].astype(str).str.zfill(8) == str(municipality_key).zfill(8)
    candidates = alkis[residential & own]
    if candidates.empty or raw.empty:
        return candidates.reset_index(drop=True)
    raw = raw.to_crs(candidates.crs)
    points = gpd.GeoDataFrame(geometry=candidates.geometry.representative_point(), crs=candidates.crs)
    known = gpd.sjoin(points, raw[["geometry"]], predicate="within").index.unique()
    gaps = candidates.drop(index=known)
    houses = raw.loc[raw[_resolve_heat_col(raw, heat_attribute)] > 0, ["geometry"]]
    no_address = gaps[dl.ADDRESS_COLUMN].fillna("").astype(str).str.strip() == ""
    annexes = gpd.sjoin(gaps.loc[no_address, ["geometry"]], houses, predicate="intersects").index.unique()
    return gaps.drop(index=annexes).reset_index(drop=True)


def lod2_tiles(geometries: gpd.GeoSeries) -> list[str]:
    """Names of the LoD2 tiles the points of ``geometries`` (EPSG:25832) lie in."""
    corners = {(int(p.x // 1000), int(p.y // 1000)) for p in geometries.representative_point()}
    return [dl.LOD2_TILE.format(x=x, y=y) for x, y in sorted(corners)]


def load_lod2(geometries: gpd.GeoSeries, cache_dir: Optional[Path] = None) -> gpd.GeoDataFrame:
    """LoD2 buildings of the tiles ``geometries`` lie in, through the cache."""
    files = dl.file_list_from_url(dl.URL_LOD2 + "index.json")
    frames = []
    for name in lod2_tiles(geometries):
        cancel.raise_if_cancelled()
        if dl.find_file(files, name) is not None:
            frames.append(read_lod2(dl.cached_file(dl.URL_LOD2, name, cache_dir, files)))
    if not frames:
        return _lod2_frame([])
    return gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), geometry="geometry", crs=_LOD2_CRS)


def read_lod2(path: Path) -> gpd.GeoDataFrame:
    """Buildings of a LoD2 tile: ``lod2_id``, ``height`` (highest measuredHeight), footprint."""
    rows = []
    for _, element in ET.iterparse(str(path), events=("end",)):
        if element.tag != _BUILDING:
            continue
        heights = [float(h.text) for h in element.iterfind(".//bldg:measuredHeight", _NS) if h.text]
        grounds = [_footprint(p.text) for p in element.iterfind(".//bldg:GroundSurface//gml:posList", _NS)]
        grounds = [g for g in grounds if g is not None]
        if heights and grounds:
            rows.append({"lod2_id": element.get(_GML_ID), "height": max(heights), "geometry": unary_union(grounds)})
        element.clear()
    return _lod2_frame(rows)


def estimate_gaps(
    gaps: gpd.GeoDataFrame,
    raw: gpd.GeoDataFrame,
    heat_attribute: str,
    lod2: Optional[gpd.GeoDataFrame] = None,
) -> gpd.GeoDataFrame:
    """The gaps as WBM-NRW buildings (see the module docstring); empty without new WBM-NRW buildings."""
    heat_col = _resolve_heat_col(raw, heat_attribute)
    homes = raw[(raw["WG_NWG"] == "WG") & (raw[heat_col] > 0)]
    kind = homes["GEBAEUDETY"].astype(str).str.split("_", n=1, expand=True).reindex(columns=[0, 1])
    age = pd.to_numeric(kind[1], errors="coerce")
    if gaps.empty or age.isna().all():
        return gaps.iloc[0:0]
    newest_age = int(age.max())
    new_storeys = homes.loc[(age >= NEW_SINCE) & (homes["STKW"] > 0), "STKW"]
    assumed_storeys = max(1, int(round(new_storeys.median()))) if not new_storeys.empty else 2
    newest = age == newest_age
    specific_by_type = homes.loc[newest, "RW_WW_spez"].groupby(kind.loc[newest, 0]).median()
    efh_limit = homes.loc[kind[0] == "EFH", "NF"].max()
    mfh_limit = homes.loc[kind[0] == "MFH", "NF"].max()

    heights = pd.Series(np.nan, index=gaps.index)
    storeys = pd.Series(np.nan, index=gaps.index)
    if lod2 is not None and not lod2.empty:
        lod2 = lod2.to_crs(raw.crs)
        heights = gaps["oid"].astype(str).str[:16].map(lod2.drop_duplicates("lod2_id").set_index("lod2_id")["height"])
        table = storeys_per_height(homes, lod2)
        if table is not None:
            storeys = _storeys(heights, table)
    measured = storeys.notna()
    storeys = storeys.fillna(assumed_storeys)
    floor_area = NET_FLOOR_FACTOR * gaps.geometry.area * storeys
    building_type = pd.Series(
        np.where(floor_area > mfh_limit, "GMFH", np.where(floor_area > efh_limit, "MFH", "EFH")), index=gaps.index
    )
    specific = building_type.map(specific_by_type).fillna(homes.loc[newest, "RW_WW_spez"].median())
    return gpd.GeoDataFrame(
        {
            "gml_id": gaps["oid"],
            "citygml_fu": gaps["gfkzshh"].astype(str),
            "Nutzung": gaps["funktion"],
            "WG_NWG": "WG",
            "GEBAEUDETY": building_type + f"_{newest_age}",
            "Hoehe": heights,
            "STKW": storeys,
            "NF": floor_area,
            "RW_WW_spez": specific,
            heat_col: floor_area * specific,
            # an own parcel key: an added building is never merged with another one
            "Flurstueck": gaps["oid"],
            "Fortschrei": "",
            DATA_SOURCE: np.where(measured, SOURCE_LOD2, SOURCE_ASSUMED),
        },
        geometry=gaps.geometry.to_numpy(),
        crs=gaps.crs,
    )


def storeys_per_height(homes: gpd.GeoDataFrame, lod2: gpd.GeoDataFrame) -> Optional[pd.Series]:
    """Most frequent WBM-NRW storeys per whole metre of LoD2 height.

    Learned from the residential WBM-NRW buildings ``homes`` whose point lies
    in a LoD2 footprint; None with fewer than :data:`MIN_HEIGHT_SAMPLES`.
    """
    homes = homes[homes["STKW"] > 0]
    points = gpd.GeoDataFrame(
        {"STKW": homes["STKW"].to_numpy()}, geometry=homes.geometry.representative_point().to_numpy(), crs=homes.crs
    )
    hit = gpd.sjoin(points, lod2[["height", "geometry"]], predicate="within")
    hit = hit[~hit.index.duplicated()]
    if len(hit) < MIN_HEIGHT_SAMPLES:
        return None
    metres = np.floor(hit["height"]).astype(int)
    return hit["STKW"].groupby(metres).agg(lambda s: s.mode().iloc[0])


def _storeys(heights: pd.Series, table: pd.Series) -> pd.Series:
    """Storeys of the nearest learned metre of height (NaN without height)."""
    metres = table.index.to_numpy()

    def lookup(height):
        if pd.isna(height):
            return np.nan
        return table.iloc[np.abs(metres - np.floor(height)).argmin()]

    return heights.map(lookup).astype("float64")


def _footprint(pos_list: Optional[str]) -> Optional[Polygon]:
    values = [float(v) for v in (pos_list or "").split()]
    ring = list(zip(values[0::3], values[1::3]))
    if len(ring) < 3:
        return None
    polygon = Polygon(ring)
    return polygon if polygon.is_valid else polygon.buffer(0)


def _lod2_frame(rows: list[dict]) -> gpd.GeoDataFrame:
    frame = pd.DataFrame(rows, columns=["lod2_id", "height", "geometry"])
    return gpd.GeoDataFrame(frame, geometry="geometry", crs=_LOD2_CRS)
