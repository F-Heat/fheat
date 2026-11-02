"""Build the area catalogue of Lower Saxony, ``src/fheat_nds/data/cities.csv``.

One row per Gemarkung of the LGLN "ALKIS vereinfacht" WFS (``ave:KatasterBezirk``,
``art`` "Gemarkung") with its name and key, the municipality
(``ave:VerwaltungsEinheit``, ``art`` "Gemeinde") holding most of its area with
its AGS, and its bbox in EPSG:25832 — the columns of ``fheat_nrw/data/cities.csv``.
A Gemarkung reaching into a second municipality belongs to one only, so its
key stays unique. Municipality names are unique as well: a name several
municipalities share gets the county ("Neuenkirchen (Heidekreis)"). Areas
of no municipality ("Zugehörigkeit ungeklärt", waters off the coast) are
left out.

    python scripts/build_nds_catalog.py src/fheat_nds/data/cities.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

from fheat_nds import download as dl

#: Lower Saxony and some margin, EPSG:25832
STATE_BBOX = (250_000.0, 5_650_000.0, 700_000.0, 6_000_000.0)
#: name of the areas that belong to no municipality
UNRESOLVED = "Zugehörigkeit ungeklärt"


def build_catalog() -> pd.DataFrame:
    districts = dl.get_features(dl.URL_ALKIS, dl.LAYER_DISTRICTS, STATE_BBOX)
    districts = districts[districts["art"] == "Gemarkung"][["name", "schluessel", "geometry"]]
    units = dl.get_features(dl.URL_ALKIS, dl.LAYER_UNITS, STATE_BBOX)
    municipalities = units[(units["art"] == "Gemeinde") & (units["name"] != UNRESOLVED)]
    municipalities = municipalities[["name", "ags", "geometry"]].rename(columns={"name": "gemeinde", "ags": "gmdschl"})
    counties = units[units["art"] == "Kreis / kreisfreie Stadt"].set_index("ags")["name"]
    shared = municipalities["gemeinde"].duplicated(keep=False)
    county = municipalities["gmdschl"].astype(str).str.zfill(8).str[:5].map(counties)
    municipalities.loc[shared, "gemeinde"] = municipalities.loc[shared, "gemeinde"] + " (" + county[shared] + ")"
    if municipalities["gemeinde"].duplicated().any():
        raise RuntimeError("municipality names are not unique even with the county")
    districts = districts.drop_duplicates("schluessel").reset_index(drop=True)
    districts["geometry"] = districts.geometry.buffer(0)
    municipalities["geometry"] = municipalities.geometry.buffer(0)

    parts = gpd.overlay(districts.reset_index(names="district"), municipalities, how="intersection")
    parts["_area"] = parts.geometry.area
    owner = parts.sort_values("_area", ascending=False).drop_duplicates("district").set_index("district")
    out = districts.join(owner[["gemeinde", "gmdschl"]])
    missing = out["gmdschl"].isna()
    if missing.any():
        print(f"{int(missing.sum())} Gemarkungen without municipality left out:", out.loc[missing, "name"].tolist()[:10])
    out = out[~missing]
    out["bbox"] = [f"({b[0]:.2f}, {b[1]:.2f}, {b[2]:.2f}, {b[3]:.2f})" for b in out.geometry.bounds.to_numpy()]
    # keys as numbers, like the NRW catalogue ("034204" -> 34204, "03456001" -> 3456001)
    out["schluessel"] = out["schluessel"].astype(int)
    out["gmdschl"] = out["gmdschl"].astype(int)
    return out[["name", "schluessel", "gemeinde", "gmdschl", "bbox"]].sort_values(["gemeinde", "name"])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    catalog = build_catalog()
    catalog.to_csv(args.output, index=False)
    print(f"{len(catalog)} Gemarkungen of {catalog['gmdschl'].nunique()} municipalities -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
