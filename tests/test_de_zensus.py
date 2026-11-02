"""Tests for fheat_de.zensus: age class of the Zensus 2022 cell a building lies in."""
from __future__ import annotations

import zipfile

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Point

from fheat_de import zensus

HEADER = ["x_mp", "y_mp", "Insgesamt_Gebaeude", *zensus.DECADE_CLASSES]


def _csv(rows, size):
    """Rows (x_mp, y_mp, decade counts by name)."""
    lines = [";".join([f"GITTER_ID_{size}", *HEADER])]
    for x, y, counts in rows:
        values = [str(counts.get(d, "–")) for d in zensus.DECADE_CLASSES]
        lines.append(";".join([f"CRS3035RES{size}N{y}E{x}", str(x), str(y), "3", *values]))
    return "\n".join(lines) + "\n"


@pytest.fixture
def grid(tmp_path, monkeypatch):
    path = tmp_path / "zensus.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(zensus.CSV_100M, _csv([
            (4100050, 3200050, {"a1970bis1979": 5, "a1950bis1959": 2}),
            (4100150, 3200050, {}),                                    # all "–": no count
        ], "100m"))
        z.writestr(zensus.CSV_1KM, _csv([(4100500, 3200500, {"a2000bis2009": 9, "Vor1919": 1})], "1km"))
    monkeypatch.setattr(zensus.cache, "cached_download", lambda url, name, ts, cache_dir: path)
    return path


def _points(*xy):
    return gpd.GeoSeries([Point(x, y) for x, y in xy], crs=zensus.GRID_CRS)


def test_class_of_the_100m_cell_else_the_1km_cell(grid):
    out = zensus.construction_classes(_points((4100020, 3200080), (4100120, 3200010), (4108000, 3208000)))
    # most frequent decade 1970s; the second cell has no count, its 1 km cell 2000s; no cell at all
    assert out.iloc[0] == "F" and out.iloc[1] == "J" and pd.isna(out.iloc[2])


def test_points_in_another_crs(grid):
    pts = _points((4100020, 3200080)).to_crs("EPSG:25832")
    assert zensus.construction_classes(pts).tolist() == ["F"]


def test_no_points_no_download(monkeypatch):
    monkeypatch.setattr(zensus.cache, "cached_download", lambda *a: pytest.fail("no download"))
    assert zensus.construction_classes(gpd.GeoSeries([], crs="EPSG:25832")).empty


def test_every_decade_has_an_age_class_of_the_table():
    from fheat_de.heat_demand import load_age_classes

    assert set(zensus.DECADE_CLASSES.values()) <= set(load_age_classes()["Baualtersklasse"])


def test_dominant_class_ignores_cells_without_count():
    cells = pd.DataFrame({"_x": [1, 2], "_y": [1, 2], "a1990bis1999": ["4", "–"], "a2016undspaeter": ["7", "–"]})
    out = zensus.dominant_classes(cells)
    assert out.to_dict() == {(1, 1): "L"}
    assert np.issubdtype(np.array(out.index.get_level_values(0)).dtype, np.integer)
