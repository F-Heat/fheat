"""Building blocks (Baublöcke, WPG § 3) for WP_GebaeudeBaublock and WP_EnergieBaublock.

Two sources, decided per building:

* the source's block id (``block_id``; NRW: LANUV ``Block_ID``). The block
  area is the union of the parcels its buildings stand on; a parcel with
  buildings of several blocks goes to the block with most of them.
* otherwise the street network: the faces between the streets (closed by the
  outline of the analysis area) that are not covered by blocks of the first
  kind. Railways and waters are not in F|Heat's data, so such faces can be
  larger than official blocks.

Blocks with fewer buildings than the privacy threshold are merged into the
nearest block (ties: the longest shared border) until every block reaches
it; see :func:`merge_small_blocks`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import STRtree
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import polygonize, unary_union
from shapely.validation import make_valid

from fheat_core import columns as cols

FALLBACK_BUFFER_M = 5.0  # area around buildings when nothing else bounds a block


@dataclass
class Block:
    key: str  # source block id, or "S<n>" for a street block
    geometry: BaseGeometry
    members: list = field(default_factory=list)  # index labels of the buildings

    @property
    def n(self) -> int:
        return len(self.members)


def build_blocks(
    buildings: gpd.GeoDataFrame,
    *,
    parcels: gpd.GeoDataFrame | None = None,
    streets: gpd.GeoDataFrame | None = None,
    boundary: BaseGeometry | None = None,
) -> list[Block]:
    """Blocks that together hold every building of ``buildings`` exactly once."""
    if buildings.empty:
        return []
    points = buildings.geometry.representative_point()
    ids = buildings[cols.BLOCK_ID] if cols.BLOCK_ID in buildings.columns else pd.Series(pd.NA, index=buildings.index)
    has_id = ids.notna() & (ids.astype("string").str.strip() != "")
    blocks = _source_blocks(buildings[has_id], points[has_id], ids[has_id].astype(str), parcels)
    rest = buildings.index[~has_id]
    if len(rest):
        covered = unary_union([b.geometry for b in blocks]) if blocks else None
        blocks += _street_blocks(buildings.loc[rest], points.loc[rest], streets, boundary, covered)
    return blocks


def _source_blocks(buildings, points, ids, parcels) -> list[Block]:
    if buildings.empty:
        return []
    members = {key: list(group.index) for key, group in ids.groupby(ids, sort=True)}
    parcel_union: dict[str, list] = {key: [] for key in members}
    if parcels is not None and not parcels.empty:
        pts = gpd.GeoDataFrame({"block": ids.values}, geometry=points.values, index=buildings.index, crs=buildings.crs)
        hit = gpd.sjoin(pts, parcels[["geometry"]].reset_index(drop=True), how="inner", predicate="within")
        hit = hit[~hit.index.duplicated(keep="first")]
        # a parcel belongs to the block with most of its buildings (ties: the smaller block id)
        votes = hit.groupby(["index_right", "block"]).size().reset_index(name="n")
        votes = votes.sort_values(["index_right", "n", "block"], ascending=[True, False, True])
        owner = votes.drop_duplicates("index_right")
        geoms = parcels.geometry.reset_index(drop=True)
        for parcel_idx, block in zip(owner["index_right"], owner["block"]):
            parcel_union[block].append(geoms.iloc[parcel_idx])
    blocks = []
    for key, idx in members.items():
        footprints = list(buildings.geometry.loc[idx])
        parts = parcel_union[key] or [unary_union(footprints).buffer(FALLBACK_BUFFER_M)]
        blocks.append(Block(key, polygonal(unary_union(parts + footprints)), idx))
    return blocks


def _street_blocks(buildings, points, streets, boundary, covered) -> list[Block]:
    faces: list[BaseGeometry] = []
    if streets is not None and not streets.empty:
        lines = list(streets.geometry)
        if boundary is not None:
            lines.append(boundary.boundary)
        faces = [f for f in polygonize(unary_union(lines)) if f.area > 0]
        if boundary is not None:
            faces = [f.intersection(boundary) for f in faces]
        if covered is not None:
            faces = [f.difference(covered) for f in faces]
        faces = [polygonal(f) for f in faces if not f.is_empty and f.area > 0]
    # stable numbering: west to east, south to north
    faces.sort(key=lambda f: (round(f.representative_point().x, 1), round(f.representative_point().y, 1)))
    assigned: dict[int, list] = {}
    if faces:
        tree = STRtree(faces)
        for label, pt in zip(points.index, points.values):
            hits = [i for i in tree.query(pt, predicate="within")]
            if hits:
                assigned.setdefault(int(min(hits)), []).append(label)
    blocks = [Block(f"S{i + 1:05d}", faces[i], idx) for i, idx in sorted(assigned.items())]
    placed = {label for b in blocks for label in b.members}
    left = [label for label in points.index if label not in placed]
    if left:
        # buildings outside every face (open street ends): one block around them
        area = unary_union(list(buildings.geometry.loc[left])).buffer(FALLBACK_BUFFER_M)
        if boundary is not None:
            area = area.intersection(boundary)
        taken = unary_union([b.geometry for b in blocks] + ([covered] if covered is not None else []))
        if not taken.is_empty:
            remainder = area.difference(taken)
            area = remainder if not remainder.is_empty else area
        blocks.append(Block(f"S{len(faces) + 1:05d}", polygonal(area), left))
    return blocks


def merge_small_blocks(blocks: list[Block], min_buildings: int) -> tuple[list[Block], list[Block]]:
    """Merge blocks below ``min_buildings`` into their nearest neighbour.

    Returns the merged blocks and the blocks that stay below the threshold
    because there is nothing to merge them with (they must not be published).
    A merged block keeps the key of its largest part.
    """
    if not blocks:
        return [], []
    geoms = [b.geometry for b in blocks]
    tree = STRtree(geoms)
    parent = list(range(len(blocks)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    groups: dict[int, list[int]] = {i: [i] for i in range(len(blocks))}
    count = {i: blocks[i].n for i in range(len(blocks))}
    dropped: set[int] = set()
    while True:
        small = sorted((count[r], blocks[r].key, r) for r in groups if count[r] < min_buildings and r not in dropped)
        if not small:
            break
        _, _, root = small[0]
        target = _nearest_group(root, groups, geoms, tree, find)
        if target is None:
            dropped.add(root)
            continue
        big, little = (target, root) if count[target] >= count[root] else (root, target)
        parent[little] = big
        groups[big] += groups.pop(little)
        count[big] += count.pop(little)
    merged, too_small = [], []
    for root, idx in sorted(groups.items()):
        largest = max(idx, key=lambda i: (blocks[i].n, blocks[i].key))
        block = Block(
            blocks[largest].key,
            polygonal(unary_union([geoms[i] for i in idx])),
            [m for i in sorted(idx) for m in blocks[i].members],
        )
        (too_small if root in dropped else merged).append(block)
    return merged, too_small


def _nearest_group(root, groups, geoms, tree, find) -> int | None:
    own = unary_union([geoms[i] for i in groups[root]])
    for radius in (1.0, 25.0, 100.0, 500.0, 2500.0, np.inf):
        if np.isinf(radius):
            candidates = range(len(geoms))
        else:
            candidates = tree.query(own.buffer(radius))
        best = None
        for i in candidates:
            other = find(int(i))
            if other == root:
                continue
            d = own.distance(geoms[int(i)])
            shared = own.boundary.intersection(geoms[int(i)].boundary).length if d == 0 else 0.0
            key = (round(d, 6), -shared, other)
            if best is None or key < best[0]:
                best = (key, other)
        if best is not None:
            return best[1]
    return None


def polygonal(geom: BaseGeometry) -> BaseGeometry:
    """Polygonal part of a geometry, valid, as Polygon or MultiPolygon."""
    geom = make_valid(geom) if not geom.is_valid else geom
    if isinstance(geom, (Polygon, MultiPolygon)):
        return geom
    polys = [g for g in getattr(geom, "geoms", []) if isinstance(g, (Polygon, MultiPolygon))]
    parts = [p for g in polys for p in (g.geoms if isinstance(g, MultiPolygon) else [g])]
    return MultiPolygon(parts) if len(parts) > 1 else (parts[0] if parts else Polygon())
