"""Cut a small, self-consistent excerpt out of an XWaermeplan reference plan.

The reference plans of the XLeitstelle (repo xleitstelle/xwaermeplan/implementierung,
folder Referenzplaene) are 17-90 MB. For tests we keep every feature without
geometry (plan, areas, balances, measures, texts) and the first ``--per-type``
features of every spatial feature type whose geometry has at most
``--max-coords`` coordinates (large net polygons would bloat the fixtures), so
that all references still resolve.

    python scripts/excerpt_xwp_reference.py Rheinberg_v096_xmas.gml tests/fixtures/xwp/rheinberg_auszug.gml
    python scripts/excerpt_xwp_reference.py Rheinberg_v096_xmas.json tests/fixtures/xwp/rheinberg_auszug.json

GML and JSON excerpts of the same plan contain the same features when both
inputs are XPlan-Tools ("xmas") exports, which use the same UUIDs.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from lxml import etree

GML = "{http://www.opengis.net/gml/3.2}"
SPATIAL_PROPS = {"position"}


def local(tag: str) -> str:
    return tag.split("}")[-1]


def keep(feature_type: str, is_spatial: bool, seen: Counter, per_type: int,
         n_coords: int = 0, max_coords: int = 0) -> bool:
    if not is_spatial:
        return True
    if max_coords and n_coords > max_coords:
        return False
    seen[feature_type] += 1
    return seen[feature_type] <= per_type


def gml_coords(feature) -> int:
    n = 0
    for el in feature.iter(f"{GML}posList", f"{GML}pos"):
        n += len((el.text or "").split()) // int(el.get("srsDimension", "2"))
    return n


def json_coords(geom) -> int:
    if not geom:
        return 0

    def count(c):
        return 1 if isinstance(c[0], (int, float)) else sum(count(x) for x in c)
    return count(geom["coordinates"])


def excerpt_gml(src: Path, dst: Path, per_type: int, max_coords: int) -> Counter:
    parser = etree.XMLParser(huge_tree=True, remove_blank_text=True)
    root = etree.parse(str(src), parser).getroot()
    seen: Counter = Counter()
    kept: Counter = Counter()
    for member in list(root):
        feature = member[0]
        ft = local(feature.tag)
        spatial = any(local(ch.tag) in SPATIAL_PROPS for ch in feature)
        if keep(ft, spatial, seen, per_type, gml_coords(feature), max_coords):
            kept[ft] += 1
        else:
            root.remove(member)
    etree.ElementTree(root).write(str(dst), xml_declaration=True, encoding="UTF-8", pretty_print=True)
    return kept


def excerpt_json(src: Path, dst: Path, per_type: int, max_coords: int) -> Counter:
    data = json.loads(src.read_text(encoding="utf-8"))
    seen: Counter = Counter()
    kept: Counter = Counter()
    features = []
    for f in data["features"]:
        ft = f.get("featureType")
        spatial = f.get("place") is not None or f.get("geometry") is not None
        n = json_coords(f.get("place") or f.get("geometry"))
        if ft == "WP_Plan" or keep(ft, spatial and ft != "WP_Bereich", seen, per_type, n, max_coords):
            features.append(f)
            kept[ft] += 1
    data["features"] = features
    dst.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    return kept


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=Path)
    ap.add_argument("dst", type=Path)
    ap.add_argument("--per-type", type=int, default=5)
    ap.add_argument("--max-coords", type=int, default=400)
    args = ap.parse_args()
    fn = excerpt_gml if args.src.suffix.lower() == ".gml" else excerpt_json
    kept = fn(args.src, args.dst, args.per_type, args.max_coords)
    print(f"{args.dst.name}: {dict(kept)}")


if __name__ == "__main__":
    main()
