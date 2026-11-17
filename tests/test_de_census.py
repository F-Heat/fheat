"""Census 2022 cells (fheat_de.census) and the adapters (no network).

Covers:
- read_census: both tables joined per cell, "–" → 0, only cells touching
  the area, 100 m squares in the CRS of the area, an unknown value raises
- NRWDataAdapter.fetch_census: loaded once, switched off, failure → None + warning
- FlexDataAdapter.fetch_census: only when switched on
"""
from __future__ import annotations

import json
import math
import zipfile

import geopandas as gpd
import pytest
from shapely.geometry import LineString, Point, box

from fheat_core import columns as cols
from fheat_core.schemas import CensusSchema
from fheat_de import census
from fheat_flex import FlexDataAdapter
from fheat_nrw.adapter.data_adapter import NRWDataAdapter

CRS = "EPSG:25832"
AREA_BOX = (388000.0, 5779000.0, 388100.0, 5779100.0)   # Burgsteinfurt
DASH = "\x96"


def _cell_of(x: float, y: float) -> tuple[int, int]:
    """Midpoint (EPSG:3035) of the census cell that holds the EPSG:25832 point."""
    p = gpd.GeoSeries([Point(x, y)], crs=CRS).to_crs(census.CENSUS_CRS).iloc[0]
    return math.floor(p.x / 100) * 100 + 50, math.floor(p.y / 100) * 100 + 50


def _write_tables(folder, heating_value: str = "3") -> None:
    inside = _cell_of(388050, 5779050)
    far = (inside[0] + 5000, inside[1])
    rows = {"inside": inside, "far": far}
    headers = {
        "Zensus2022_Heizungsart.zip": "Insgesamt_Heizungsart;Fernheizung;Etagenheizung;Blockheizung;Zentralheizung;"
                                      "Einzel_Mehrraumoefen;keine_Heizung",
        "Zensus2022_Energietraeger.zip": "Insgesamt_Energietraeger;Gas;Heizoel;Holz_Holzpellets;Biomasse_Biogas;"
                                         "Solar_Geothermie_Waermepumpen;Strom;Kohle;Fernwaerme;kein_Energietraeger",
    }
    for zip_name, csv_name, columns in census.TABLES:
        values = [f"1{len(columns)}"] + [DASH] * (len(columns) - 2) + [heating_value]
        lines = [f"GITTER_ID_100m;x_mp_100m;y_mp_100m;{headers[zip_name]}"]
        lines += [f"ID{name};{x};{y};" + ";".join(values) for name, (x, y) in rows.items()]
        with zipfile.ZipFile(folder / zip_name, "w") as archive:
            archive.writestr(csv_name, ("\n".join(lines) + "\n").encode("latin1"))
        (folder / f"{zip_name}.json").write_text(json.dumps({"url": census.CENSUS_URL + zip_name}), encoding="utf-8")


def test_cells_in_the_area(tmp_path):
    _write_tables(tmp_path)
    cells = census.read_census(box(*AREA_BOX), CRS, tmp_path)
    CensusSchema.validate(cells)
    assert cells[cols.CENSUS_CELL_ID].tolist() == ["IDinside"]
    row = cells.iloc[0]
    assert row[cols.HEATING_TOTAL] == 17 and row[cols.HEATING_DISTRICT] == 0 and row[cols.HEATING_NONE] == 3
    assert row[cols.CARRIER_TOTAL] == 110 and row[cols.CARRIER_GAS] == 0 and row[cols.CARRIER_NONE] == 3
    assert cells.crs == CRS
    assert cells.geometry.iloc[0].area == pytest.approx(10000, rel=0.01)


def test_unknown_value_raises(tmp_path):
    _write_tables(tmp_path, heating_value="/")
    with pytest.raises(ValueError):
        census.read_census(box(*AREA_BOX), CRS, tmp_path)


def _loaded_adapter(**kwargs) -> NRWDataAdapter:
    adapter = NRWDataAdapter(municipality_name="Steinfurt", **kwargs)
    adapter._buildings = gpd.GeoDataFrame({cols.HEAT_DEMAND: [1000.0]},
                                          geometry=[box(388010, 5779010, 388020, 5779020)], crs=CRS)
    adapter._streets = gpd.GeoDataFrame({"geometry": [LineString([(388000, 5779000), (388100, 5779100)])]}, crs=CRS)
    adapter._boundary = gpd.GeoDataFrame(geometry=[box(*AREA_BOX)], crs=CRS)
    return adapter


class TestAdapters:
    def test_nrw_loads_once(self, tmp_path, monkeypatch):
        _write_tables(tmp_path)
        calls = []
        read = census.read_census
        monkeypatch.setattr(census, "read_census", lambda *a: calls.append(a) or read(*a))
        adapter = _loaded_adapter(cache_dir=tmp_path)
        assert adapter.fetch_census()[cols.CENSUS_CELL_ID].tolist() == ["IDinside"]
        adapter.fetch_census()
        assert len(calls) == 1

    def test_nrw_switched_off(self, monkeypatch):
        monkeypatch.setattr(census, "read_census", lambda *a: pytest.fail("no download"))
        assert _loaded_adapter(download_census=False).fetch_census() is None

    def test_nrw_failure_gives_none_and_a_warning(self, monkeypatch, caplog):
        def failing(*a):
            raise RuntimeError("destatis nicht erreichbar")

        monkeypatch.setattr(census, "read_census", failing)
        with caplog.at_level("WARNING"):
            assert _loaded_adapter().fetch_census() is None
        assert "Zensus 2022" in caplog.records[-1].getMessage()

    def test_flex_only_when_switched_on(self, tmp_path):
        _write_tables(tmp_path)
        paths = {}
        for name, gdf in (("buildings", gpd.GeoDataFrame({"heat_demand": [1000.0]}, geometry=[box(*AREA_BOX)], crs=CRS)),
                          ("streets", gpd.GeoDataFrame(geometry=[LineString([(388000, 5779000), (388100, 5779100)])], crs=CRS)),
                          ("parcels", gpd.GeoDataFrame(geometry=[box(*AREA_BOX)], crs=CRS))):
            paths[name] = tmp_path / f"{name}.gpkg"
            gdf.to_file(paths[name], driver="GPKG")
        off = FlexDataAdapter(paths["buildings"], paths["streets"], paths["parcels"], cache_dir=tmp_path)
        assert off.fetch_census() is None
        on = FlexDataAdapter(paths["buildings"], paths["streets"], paths["parcels"], cache_dir=tmp_path,
                             download_census=True)
        assert on.fetch_census()[cols.CENSUS_CELL_ID].tolist() == ["IDinside"]
