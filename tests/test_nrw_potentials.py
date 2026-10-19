"""Tests for the potential layers of the NRW adapter (no network).

Covers:
- download.get_geothermal_from_wfs / check_geothermal_unit (WFS mocked)
- potentials.borehole_extraction: VDI 4640 classes and their bounds
- potentials.merge_geothermal_layers: overlay, gaps stay NaN, status
- potentials.process_blocks: units, block_id from the source or the buildings
- NRWDataAdapter.fetch_geothermal_shallow / fetch_geothermal_blocks:
  bbox, local files, failure → None + one warning, switched off
"""
from __future__ import annotations

import io
import json
import zipfile

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, box

from fheat_core import columns as cols
from fheat_nrw import download as dl
from fheat_nrw import potentials as pot
from fheat_nrw.adapter.data_adapter import NRWDataAdapter

CRS = "EPSG:25832"
AREA = box(0, 0, 100, 100)


def _gt_layer(key: str, parts: list[tuple], unit: str | None = None) -> gpd.GeoDataFrame:
    """WFS-like frame: one feature per (geometry, capacity)."""
    if unit is None:
        unit = dl.GEOTHERMAL_UNIT_EWS if key.startswith("ews") else dl.GEOTHERMAL_UNIT_EWK.format(
            hours=key.removeprefix("ewk"))
    return gpd.GeoDataFrame(
        {"capacity": [c for _, c in parts], "capacity_uom": [unit] * len(parts),
         "vext_scalar": [2] * len(parts)},
        geometry=[g for g, _ in parts], crs=CRS,
    )


def _full_raw(conductivity: float = 2.1) -> dict:
    raw = {key: _gt_layer(key, [(box(-50, -50, 150, 150), conductivity)])
           for key in ("ews40", "ews60", "ews80", "ews100")}
    # the collector layers cover only the left half
    raw["ewk1800"] = _gt_layer("ewk1800", [(box(-50, -50, 50, 150), 40)])
    raw["ewk2400"] = _gt_layer("ewk2400", [(box(-50, -50, 50, 150), 32)])
    return raw


# ---------------------------------------------------------------------------
# download: WFS and unit check
# ---------------------------------------------------------------------------


class TestGeothermalWfs:
    def test_asks_for_geojson_in_25832(self, monkeypatch):
        payload = _gt_layer("ews40", [(box(0, 0, 1, 1), 2.2)]).to_json().encode("utf-8")
        calls = {}

        class FakeWFS:
            def __init__(self, url, version, timeout):
                calls["url"] = url

            def getfeature(self, typename, bbox, srsname, outputFormat):
                calls.update(typename=typename, bbox=bbox, srsname=srsname, fmt=outputFormat)
                return io.BytesIO(payload)

        monkeypatch.setattr(dl, "WebFeatureService", FakeWFS)
        out = dl.get_geothermal_from_wfs("https://fake/", (1, 2, 3, 4), "er:Geothermie_EWS40")
        assert out["capacity"].tolist() == [2.2]
        assert out.crs == CRS
        assert calls == {
            "url": "https://fake/", "typename": "er:Geothermie_EWS40",
            "bbox": (1.0, 2.0, 3.0, 4.0, dl.GEOTHERMAL_SRS), "srsname": dl.GEOTHERMAL_SRS,
            "fmt": "GEOJSON",
        }

    def test_failure_raises_runtime(self, monkeypatch):
        class FakeWFS:
            def __init__(self, *a, **kw):
                raise OSError("simulated network failure")

        monkeypatch.setattr(dl, "WebFeatureService", FakeWFS)
        with pytest.raises(RuntimeError, match="Geothermie"):
            dl.get_geothermal_from_wfs("https://fake/", (0, 0, 1, 1), "er:Geothermie_EWS40")

    @pytest.mark.parametrize("key, unit", [
        ("ews60", "W/m*K"), ("ewk1800", "W/m²@1800h/a"), ("ewk2400", "W/m²@2400h/a"),
    ])
    def test_expected_units_pass(self, key, unit):
        dl.check_geothermal_unit(_gt_layer(key, [(box(0, 0, 1, 1), 1)], unit), key)

    @pytest.mark.parametrize("key, unit", [
        ("ews40", "kWh/(m*a)"), ("ewk1800", "W/m²@2400h/a"), ("ewk2400", "W/m*K"),
    ])
    def test_other_unit_raises(self, key, unit):
        with pytest.raises(RuntimeError, match="Einheit"):
            dl.check_geothermal_unit(_gt_layer(key, [(box(0, 0, 1, 1), 1)], unit), key)


# ---------------------------------------------------------------------------
# borehole screening value
# ---------------------------------------------------------------------------


class TestBoreholeExtraction:
    @pytest.mark.parametrize("lam, w1800, w2400", [
        (1.0, 25, 20), (1.49, 25, 20), (1.5, 60, 50), (2.2, 60, 50), (3.0, 60, 50),
        (3.01, 84, 70), (4.0, 84, 70),
    ])
    def test_vdi_classes(self, lam, w1800, w2400):
        table = pot.load_borehole_table()
        values = pd.Series([lam])
        assert pot.borehole_extraction(values, table, 1800).iloc[0] == w1800
        assert pot.borehole_extraction(values, table, 2400).iloc[0] == w2400

    def test_missing_conductivity_stays_nan(self):
        out = pot.borehole_extraction(pd.Series([np.nan, 2.0]), pot.load_borehole_table(), 1800)
        assert np.isnan(out.iloc[0]) and out.iloc[1] == 60

    def test_own_table(self, tmp_path):
        path = tmp_path / "table.json"
        path.write_text(json.dumps({"classes": [
            {"max": 2.0, "max_inclusive": True, "extraction_1800": 10, "extraction_2400": 8},
            {"max": None, "extraction_1800": 99, "extraction_2400": 77},
        ]}), encoding="utf-8")
        table = pot.load_borehole_table(path)
        assert pot.borehole_extraction(pd.Series([2.0, 2.1]), table, 2400).tolist() == [8, 77]


# ---------------------------------------------------------------------------
# merge of the GD layers
# ---------------------------------------------------------------------------


class TestMergeGeothermalLayers:
    def test_overlay_covers_the_area_and_gaps_stay_nan(self):
        out = pot.merge_geothermal_layers(_full_raw(), AREA, CRS)
        assert out.crs == CRS
        assert out.geometry.area.sum() == pytest.approx(AREA.area)
        left = out[out.geometry.representative_point().x < 50].iloc[0]
        right = out[out.geometry.representative_point().x > 50].iloc[0]
        assert left[cols.COLLECTOR_EXTRACTION_1800] == 40 and left[cols.COLLECTOR_EXTRACTION_2400] == 32
        assert left[cols.GEOTHERMAL_STATUS] == cols.STATUS_ASSESSED
        assert np.isnan(right[cols.COLLECTOR_EXTRACTION_1800])  # never 0
        assert right[cols.GEOTHERMAL_STATUS] == cols.STATUS_PARTLY_ASSESSED
        assert right[cols.GROUND_CONDUCTIVITY_100] == pytest.approx(2.1)
        assert right[cols.BOREHOLE_EXTRACTION_1800] == 60 and right[cols.BOREHOLE_EXTRACTION_2400] == 50

    def test_area_without_any_layer_is_not_assessed(self):
        raw = {key: None for key in pot.GEOTHERMAL_COLUMNS}
        raw["ews100"] = _gt_layer("ews100", [(box(0, 0, 50, 100), 3.5)])
        out = pot.merge_geothermal_layers(raw, AREA, CRS)
        empty = out[out.geometry.representative_point().x > 50].iloc[0]
        assert empty[cols.GEOTHERMAL_STATUS] == cols.STATUS_NOT_ASSESSED
        assert np.isnan(empty[cols.BOREHOLE_EXTRACTION_1800])
        assessed = out[out.geometry.representative_point().x < 50].iloc[0]
        assert assessed[cols.BOREHOLE_EXTRACTION_1800] == 84

    def test_borehole_value_falls_back_to_a_shorter_probe(self):
        raw = {key: None for key in pot.GEOTHERMAL_COLUMNS}
        raw["ews40"] = _gt_layer("ews40", [(box(0, 0, 100, 100), 1.2)])
        out = pot.merge_geothermal_layers(raw, AREA, CRS)
        assert out[cols.BOREHOLE_EXTRACTION_1800].tolist() == [25]

    def test_polygons_are_cut_at_the_area(self):
        out = pot.merge_geothermal_layers(_full_raw(), AREA, CRS)
        minx, miny, maxx, maxy = out.total_bounds
        assert (minx, miny, maxx, maxy) == pytest.approx((0, 0, 100, 100))


# ---------------------------------------------------------------------------
# LANUK building blocks
# ---------------------------------------------------------------------------


def _raw_blocks(with_id: bool = True) -> gpd.GeoDataFrame:
    data = {
        "AGS": ["05566084"] * 3, "Gemeinde": ["Steinfurt"] * 3,
        "ON_kWh_ist": [165738.7, 0.0, np.nan], "ON_kWh_45": [136436.5, 0.0, np.nan],
        "MT_kWh_ist": [0.0, 0.0, np.nan], "MT_kWh_45": [0.0, 0.0, np.nan],
        "Heizlast": [87.2, 10.0, np.nan], "Heizlast45": [71.8, 9.0, np.nan],
        "Stand": ["20240901"] * 3,
    }
    if with_id:
        data["block_id"] = ["u1", "u2", "u3"]
    return gpd.GeoDataFrame(
        data, geometry=[box(0, 0, 40, 40), box(50, 0, 90, 40), box(0, 50, 40, 90)], crs=CRS
    )


def _buildings_with_blocks() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {cols.BLOCK_ID: pd.array(["u1", "u1", "u2", None], dtype="string")},
        geometry=[box(1, 1, 5, 5), box(10, 10, 15, 15), box(60, 10, 65, 15), box(5, 60, 9, 65)],
        crs=CRS,
    )


class TestProcessBlocks:
    def test_units_and_status(self):
        out = pot.process_blocks(_raw_blocks())
        assert out[cols.BLOCK_ID].tolist() == ["u1", "u2", "u3"]
        assert out[cols.ONG_POTENTIAL_MWH].iloc[0] == pytest.approx(165.7387)
        assert out[cols.BLOCK_HEATING_LOAD].iloc[0] == pytest.approx(87.2)
        assert out[cols.ONG_POTENTIAL_MWH].iloc[1] == 0.0       # 0 stays 0
        assert np.isnan(out[cols.ONG_POTENTIAL_MWH].iloc[2])    # missing stays NaN
        assert out[cols.BLOCK_POTENTIAL_STATUS].tolist() == [
            cols.STATUS_ASSESSED, cols.STATUS_ASSESSED, cols.STATUS_NOT_ASSESSED]

    def test_block_id_from_the_buildings_inside(self):
        out = pot.process_blocks(_raw_blocks(with_id=False), _buildings_with_blocks())
        assert out[cols.BLOCK_ID].iloc[0] == "u1"
        assert out[cols.BLOCK_ID].iloc[1] == "u2"
        assert pd.isna(out[cols.BLOCK_ID].iloc[2])              # only a building without id

    def test_without_buildings_no_id(self):
        out = pot.process_blocks(_raw_blocks(with_id=False))
        assert out[cols.BLOCK_ID].isna().all()

    def test_changed_field_names_raise(self):
        with pytest.raises(RuntimeError, match="Feldnamen"):
            pot.process_blocks(_raw_blocks().rename(columns={"ON_kWh_ist": "ON_ist"}))


# ---------------------------------------------------------------------------
# NRWDataAdapter
# ---------------------------------------------------------------------------

AREA_BOX = (388000.0, 5779000.0, 388100.0, 5779100.0)


def _loaded_adapter(**kwargs) -> NRWDataAdapter:
    adapter = NRWDataAdapter(municipality_name="Steinfurt", **kwargs)
    adapter._buildings = gpd.GeoDataFrame(
        {cols.BLOCK_ID: pd.array(["u1"], dtype="string")},
        geometry=[box(388010, 5779010, 388020, 5779020)], crs=CRS,
    )
    adapter._streets = gpd.GeoDataFrame(
        {"geometry": [LineString([(388000, 5779000), (388100, 5779100)])]}, crs=CRS
    )
    adapter._boundary = gpd.GeoDataFrame(geometry=[box(*AREA_BOX)], crs=CRS)
    return adapter


def _wfs_answers() -> dict:
    area = box(387000, 5778000, 389000, 5780000)
    return {layer: _gt_layer(key, [(area, 2.0 if key.startswith("ews") else 25)])
            for key, layer in dl.LAYERS_GEOTHERMAL.items()}


class TestAdapterGeothermalShallow:
    def test_downloads_all_layers_for_the_area(self, monkeypatch):
        answers, seen = _wfs_answers(), []

        def fake_wfs(url, bbox, layer, **kw):
            seen.append((url, bbox, layer))
            return answers[layer]

        monkeypatch.setattr(dl, "get_geothermal_from_wfs", fake_wfs)
        out = _loaded_adapter().fetch_geothermal_shallow()
        assert [s[2] for s in seen] == list(dl.LAYERS_GEOTHERMAL.values())
        assert {s[0] for s in seen} == {dl.URL_GEOTHERMAL}
        assert seen[0][1] == pytest.approx(AREA_BOX)
        assert out.crs == CRS
        assert out[cols.GEOTHERMAL_STATUS].tolist() == [cols.STATUS_ASSESSED]
        assert out[cols.BOREHOLE_EXTRACTION_2400].tolist() == [50]

    def test_wrong_unit_gives_none_and_a_warning(self, monkeypatch, caplog):
        answers = _wfs_answers()
        answers["er:Geothermie_EWS40"]["capacity_uom"] = "kWh/(m*a)"
        monkeypatch.setattr(dl, "get_geothermal_from_wfs", lambda url, bbox, layer, **kw: answers[layer])
        with caplog.at_level("WARNING"):
            assert _loaded_adapter().fetch_geothermal_shallow() is None
        assert "Einheit" in caplog.records[-1].getMessage()

    def test_failure_once_gives_none_and_one_warning(self, monkeypatch, caplog):
        calls = []

        def failing(*a, **kw):
            calls.append(1)
            raise RuntimeError("WFS-Anfrage fehlgeschlagen")

        monkeypatch.setattr(dl, "get_geothermal_from_wfs", failing)
        adapter = _loaded_adapter(geothermal_wfs="https://mirror/")
        with caplog.at_level("WARNING"):
            assert adapter.fetch_geothermal_shallow() is None
            assert adapter.fetch_geothermal_shallow() is None
        assert len(calls) == 1
        assert len([r for r in caplog.records if r.levelname == "WARNING"]) == 1

    def test_switched_off(self, monkeypatch):
        monkeypatch.setattr(dl, "get_geothermal_from_wfs", lambda *a, **kw: pytest.fail("no download"))
        assert _loaded_adapter(download_geothermal_shallow=False).fetch_geothermal_shallow() is None

    def test_local_geopackage_wins(self, monkeypatch, tmp_path):
        monkeypatch.setattr(dl, "get_geothermal_from_wfs", lambda *a, **kw: pytest.fail("no download"))
        path = tmp_path / "gt.gpkg"
        for key, layer in dl.LAYERS_GEOTHERMAL.items():
            if key != "ewk2400":   # a missing layer is no error
                _wfs_answers()[layer].to_crs("EPSG:4326").to_file(path, layer=key, driver="GPKG")
        out = _loaded_adapter(geothermal_shallow_path=path).fetch_geothermal_shallow()
        assert out[cols.COLLECTOR_EXTRACTION_1800].tolist() == [25]
        assert np.isnan(out[cols.COLLECTOR_EXTRACTION_2400].iloc[0])
        assert out[cols.GEOTHERMAL_STATUS].tolist() == [cols.STATUS_PARTLY_ASSESSED]


def _municipality_zip(tmp_path) -> "Path":
    folder = tmp_path / "zip"
    folder.mkdir()
    blocks = _raw_blocks(with_id=False)
    blocks["geometry"] = [box(388000, 5779000, 388040, 5779040), box(388050, 5779000, 388090, 5779040),
                          box(389000, 5779000, 389040, 5779040)]  # the last one outside the area
    blocks.to_file(folder / "Potenzial-ONG-MTG-Baublock_05566084_Steinfurt.shp")
    gpd.GeoDataFrame(
        {"Block_ID": ["u1", "u2"]},
        geometry=[box(388010, 5779010, 388020, 5779020), box(388060, 5779010, 388070, 5779020)], crs=CRS,
    ).to_file(folder / "WBM-NRW_05566084_Steinfurt.shp")
    path = tmp_path / "KWP-NRW_05566084_Steinfurt_EPSG25832_Shape.zip"
    with zipfile.ZipFile(path, "w") as zf:
        for f in folder.iterdir():
            zf.write(f, arcname=f.name)
    return path


class TestAdapterGeothermalBlocks:
    def _serve_zip(self, monkeypatch, path):
        seen = {}
        monkeypatch.setattr(dl, "file_list_from_url", lambda url: [{"name": path.name, "timestamp": "t"}])

        def fake_cached_file(url, name, cache_dir=None, files=None):
            seen.update(url=url, name=name, cache_dir=cache_dir)
            return path

        monkeypatch.setattr(dl, "cached_file", fake_cached_file)
        return seen

    def test_blocks_of_the_loaded_area_with_the_buildings_block_id(self, monkeypatch, tmp_path):
        seen = self._serve_zip(monkeypatch, _municipality_zip(tmp_path))
        out = _loaded_adapter(cache_dir=tmp_path / "cache").fetch_geothermal_blocks()
        assert seen == {"url": dl.URL_BUILDINGS, "name": "KWP-NRW_05566084_Steinfurt_EPSG25832_Shape.zip",
                        "cache_dir": tmp_path / "cache"}
        # second block lies in the area but only the loaded building (u1) knows an id
        assert out[cols.BLOCK_ID].tolist()[0] == "u1"
        assert len(out) == 2
        assert out[cols.ONG_POTENTIAL_MWH].iloc[0] == pytest.approx(165.7387)

    def test_area_bbox_takes_the_block_id_from_the_zip_buildings(self, monkeypatch, tmp_path):
        self._serve_zip(monkeypatch, _municipality_zip(tmp_path))
        adapter = NRWDataAdapter(municipality_name="Steinfurt", area_bbox=AREA_BOX)
        monkeypatch.setattr(adapter, "_ensure_loaded", lambda: pytest.fail("buildings must not be loaded"))
        out = adapter.fetch_geothermal_blocks()
        assert out[cols.BLOCK_ID].tolist() == ["u1", "u2"]
        assert out.crs == CRS

    def test_local_file_wins(self, monkeypatch, tmp_path):
        monkeypatch.setattr(dl, "cached_file", lambda *a, **kw: pytest.fail("no download"))
        path = tmp_path / "ong.gpkg"
        blocks = _raw_blocks()
        blocks["geometry"] = [box(388000, 5779000, 388040, 5779040)] * 3
        blocks.to_file(path, driver="GPKG")
        out = _loaded_adapter(geothermal_blocks_path=path).fetch_geothermal_blocks()
        assert out[cols.BLOCK_ID].tolist() == ["u1", "u2", "u3"]

    def test_switched_off_and_failure(self, monkeypatch, caplog):
        monkeypatch.setattr(dl, "file_list_from_url", lambda url: pytest.fail("no download"))
        assert _loaded_adapter(download_geothermal_blocks=False).fetch_geothermal_blocks() is None

        def unreachable(url):
            raise RuntimeError("Index nicht erreichbar")

        monkeypatch.setattr(dl, "file_list_from_url", unreachable)
        with caplog.at_level("WARNING"):
            assert _loaded_adapter().fetch_geothermal_blocks() is None
        assert "Baublock" in caplog.records[-1].getMessage()
