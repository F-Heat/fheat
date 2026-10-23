"""Inspect the NRW potential data sources (solar thermal and geothermal).

Exploration only, no production code: downloads the source files into a local
folder and prints layers, fields, types, CRS, feature counts and three sample
rows per layer, plus the checks behind ``docs/potenzialdaten.md``:

* does the LANUK ``block_id`` match ``Block_ID`` of the heat demand model?
* does IS GT contain an extraction rate for borehole heat exchangers?
* does the GD WFS leave gaps where nothing is assessed?
* can a geodatabase inside a ZIP be read with a bbox?

    python scripts/inspect_potential_sources.py --dir <download folder>
    python scripts/inspect_potential_sources.py --dir <folder> --skip-large

``--skip-large`` leaves out the NRW-wide ONG/MTG geodatabase (553 MB).
Needs network access and pyogrio.
"""
from __future__ import annotations

import argparse
import ast
import time
import urllib.request
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio
from shapely.geometry import box

URL_KWP = "https://www.opengeodata.nrw.de/produkte/umwelt_klima/energie/kwp/"
URL_ISGT = "https://www.opengeodata.nrw.de/produkte/geologie/geologie/RK/ISGT/"
URL_GT50 = "https://www.wfs.nrw.de/gd/wfs_nw_inspire-gt50"

KWP_FILES = {
    "tg": "KWP-NRW-Potenzial_TG_Raster_EPSG25832_Geodatabase.zip",
    "ff_st": "KWP-NRW-Potenzial_FF_Solarthermie_Flur_EPSG25832_Geodatabase.zip",
    "ong_mtg": "KWP-NRW-Potenzial_ONG_MTG_Baublock_EPSG25832_Geodatabase.zip",
    "meta": "KWP-NRW_meta.zip",
}
ISGT_FILES = {
    "isgt_gpkg": "ISGT_EPSG25832_GeoPackage.zip",
    "isgt_raster": "ISGT-raster_EPSG25832_TIFF.zip",
}
# Burgsteinfurt (municipality Steinfurt) as sample area
SAMPLE_AGS = "05566084"
SAMPLE_MUNICIPALITY_ZIP = "KWP-NRW_05566084_Steinfurt_EPSG25832_Shape.zip"
SAMPLE_BBOX = (384000.0, 5777000.0, 390000.0, 5782000.0)  # EPSG:25832
GT50_LAYERS = ("EWS40", "EWS60", "EWS80", "EWS100", "EWK1800", "EWK2400")


def download(url: str, target: Path) -> Path:
    if target.exists():
        return target
    print(f"lade {url} ...")
    part = target.with_suffix(target.suffix + ".part")
    urllib.request.urlretrieve(url, part)
    part.replace(target)
    return target


def index(url: str) -> list[dict]:
    with urllib.request.urlopen(url + "index.json", timeout=120) as resp:
        data = ast.literal_eval(resp.read().decode("latin1"))
    files = [f for ds in data.get("datasets", []) for f in ds.get("files", [])]
    return files + list(data.get("metafiles", []))


def vector_sources(zip_path: Path) -> list[str]:
    """GDAL paths of the geodatabases, GeoPackages and shapefiles in a ZIP."""
    names = zipfile.ZipFile(zip_path).namelist()
    gdbs = sorted({n.split(".gdb/")[0] + ".gdb" for n in names if ".gdb/" in n})
    others = [n for n in names if n.endswith((".gpkg", ".shp"))]
    return [f"/vsizip/{zip_path.as_posix()}/{n}" for n in gdbs + others]


def describe(path: str) -> None:
    for layer, geom_type in pyogrio.list_layers(path):
        info = pyogrio.read_info(path, layer=layer)
        print(f"\n## {path.rsplit('/', 1)[-1]} :: {layer} ({geom_type})")
        print(f"   CRS {info['crs']}, {info['features']} Objekte")
        for field, dtype in zip(info["fields"], info["dtypes"]):
            print(f"   - {field}: {dtype}")
        sample = pyogrio.read_dataframe(path, layer=layer, read_geometry=False, max_features=3)
        print(sample.to_string(max_colwidth=50))


def check_block_ids(folder: Path, ong_zip: Path | None) -> None:
    municipality = download(URL_KWP + SAMPLE_MUNICIPALITY_ZIP, folder / SAMPLE_MUNICIPALITY_ZIP)
    base = f"/vsizip/{municipality.as_posix()}/"
    buildings = pyogrio.read_dataframe(
        base + f"WBM-NRW_{SAMPLE_AGS}_Steinfurt.shp", columns=["Block_ID"], read_geometry=False
    )
    blocks_shp = pyogrio.read_info(base + f"Potenzial-ONG-MTG-Baublock_{SAMPLE_AGS}_Steinfurt.shp")
    print("\n# Baublock-ID")
    print(f"   Gemeinde-Shape ONG/MTG: Felder {list(blocks_shp['fields'])}")
    ids = set(buildings["Block_ID"].dropna())
    print(f"   Wärmemodell: {len(buildings)} Gebäude, {len(ids)} Block_ID, "
          f"{buildings['Block_ID'].isna().sum()} ohne Block_ID")
    if ong_zip is None:
        return
    gdb = vector_sources(ong_zip)[0]
    t = time.time()
    blocks = pyogrio.read_dataframe(gdb, where=f"AGS='{SAMPLE_AGS}'", read_geometry=False)
    print(f"   NRW-GDB: {len(blocks)} Baublöcke der Gemeinde ({time.time() - t:.0f} s), "
          f"davon {len(ids & set(blocks['block_id']))} mit Block_ID aus dem Wärmemodell")


def check_bbox_read(path: str) -> None:
    layer = pyogrio.list_layers(path)[0][0]
    t = time.time()
    gdf = gpd.read_file(path, layer=layer, bbox=SAMPLE_BBOX)
    print(f"\n# bbox-Lesen {path.rsplit('/', 1)[-1]}: {len(gdf)} Objekte in {time.time() - t:.2f} s")


def check_wfs_gaps() -> None:
    from owslib.wfs import WebFeatureService

    srs = "urn:ogc:def:crs:EPSG::25832"
    wfs = WebFeatureService(URL_GT50, version="2.0.0", timeout=120)
    area = box(*SAMPLE_BBOX)
    print("\n# GD-WFS IS GT 50")
    for name in GT50_LAYERS:
        response = wfs.getfeature(
            typename=f"er:Geothermie_{name}", bbox=(*SAMPLE_BBOX, srs), srsname=srs,
            outputFormat="GEOJSON",
        )
        gdf = gpd.read_file(response)
        covered = gdf.geometry.union_all().intersection(area).area / area.area if len(gdf) else 0.0
        print(f"   {name}: {len(gdf)} Objekte, Einheit {sorted(gdf['capacity_uom'].unique())}, "
              f"Werte {sorted(gdf['capacity'].unique())}, Box zu {covered:.0%} bedeckt")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", type=Path, required=True, help="Ordner für die Downloads")
    parser.add_argument("--skip-large", action="store_true", help="ONG/MTG-GDB (553 MB) auslassen")
    args = parser.parse_args()
    args.dir.mkdir(parents=True, exist_ok=True)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)

    for url, files in ((URL_KWP, KWP_FILES), (URL_ISGT, ISGT_FILES)):
        stamps = {f["name"]: f for f in index(url)}
        for key, name in files.items():
            print(f"{name}: {stamps.get(name, {}).get('size')} Byte, Stand {stamps.get(name, {}).get('timestamp')}")

    paths = {}
    for key, name in {**KWP_FILES, **ISGT_FILES}.items():
        if key == "ong_mtg" and args.skip_large:
            continue
        url = (URL_KWP if key in KWP_FILES else URL_ISGT) + name
        paths[key] = download(url, args.dir / name)

    print("\n# Metadaten (KWP-NRW_meta.zip)")
    for name in zipfile.ZipFile(paths["meta"]).namelist():
        print(f"   {name}")
    print("\n# Raster IS GT")
    for name in zipfile.ZipFile(paths["isgt_raster"]).namelist():
        if name.endswith(".tif"):
            print(f"   {name}")

    for key in ("tg", "ff_st", "ong_mtg", "isgt_gpkg"):
        if key in paths:
            for source in vector_sources(paths[key]):
                describe(source)
    for key in ("tg", "ff_st", "ong_mtg"):
        if key in paths:
            check_bbox_read(vector_sources(paths[key])[0])
    check_block_ids(args.dir, paths.get("ong_mtg"))
    check_wfs_gaps()


if __name__ == "__main__":
    main()
