"""Tests for fheat_eu.download (Fordatis, Hotmaps).

No HTTP: cache.cached_download is replaced.
- Fordatis files: bitstream URL of version 341.5, own folder first, unknown name
- read_fordatis: only the features in the EPSG:3035 box
- study workbook: mapping sheet with its header row, matching sheet raw
- Hotmaps names: the five columns, one row per SiteID
"""
from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point

from fheat_eu import download as eu


@pytest.fixture
def fake_cache(monkeypatch, tmp_path):
    """cached_download that hands out files from ``tmp_path`` and logs the URLs."""
    calls: list[tuple[str, str]] = []

    def fake(url, filename, expected_timestamp=None, cache_dir_override=None, timeout=None):
        calls.append((url, filename))
        return tmp_path / filename

    monkeypatch.setattr(eu.cache, "cached_download", fake)
    return calls


class TestFordatisFile:
    def test_bitstream_url_of_the_fixed_version(self, fake_cache, tmp_path):
        path = eu.fordatis_file("wte.gpkg")
        assert fake_cache == [("https://fordatis.fraunhofer.de/bitstream/fordatis/341.5/6/wte.gpkg",
                               "fordatis-341.5_wte.gpkg")]
        assert path == tmp_path / "fordatis-341.5_wte.gpkg"

    def test_own_folder_wins(self, fake_cache, tmp_path):
        (tmp_path / "wwtp.gpkg").write_bytes(b"x")
        assert eu.fordatis_file("wwtp.gpkg", folder=tmp_path) == tmp_path / "wwtp.gpkg"
        assert fake_cache == []

    def test_missing_in_own_folder(self, tmp_path):
        with pytest.raises(RuntimeError, match="fehlt"):
            eu.fordatis_file("wwtp.gpkg", folder=tmp_path)

    def test_unknown_file(self):
        with pytest.raises(ValueError, match="Unbekannte"):
            eu.fordatis_file("solar.gpkg")


def test_read_fordatis_reads_only_the_box(tmp_path):
    points = gpd.GeoDataFrame(
        {"Power in k": [100.0, 200.0]},
        geometry=[Point(4_100_000, 3_200_000), Point(4_300_000, 3_200_000)], crs=eu.FORDATIS_CRS,
    )
    points.to_file(tmp_path / "wwtp.gpkg", driver="GPKG")
    got = eu.read_fordatis("wwtp.gpkg", (4_050_000, 3_150_000, 4_150_000, 3_250_000), folder=tmp_path)
    assert got["Power in k"].tolist() == [100.0]


def test_read_study_results(tmp_path):
    with pd.ExcelWriter(tmp_path / eu.FILE_STUDY_RESULTS) as writer:
        pd.DataFrame([["fid", "Label", "country", "LAU_ID"], [1, 298, "DE", "DE_05566084"]]).to_excel(
            writer, sheet_name="DH_LAU_Mapping", header=False, index=False)
        pd.DataFrame([["High_temperature", None], ["GISCO_ID", "Country"], ["DE_05566084", "DE"]]).to_excel(
            writer, sheet_name="Matching_results", header=False, index=False)
    mapping, matching = eu.read_study_results(folder=tmp_path)
    assert list(mapping.columns) == ["fid", "Label", "country", "LAU_ID"]
    assert mapping["LAU_ID"].tolist() == ["DE_05566084"]
    assert matching.iloc[2, 0] == "DE_05566084"


def test_hotmaps_industry_names(fake_cache, tmp_path):
    (tmp_path / eu.FILE_HOTMAPS_INDUSTRY).write_text(
        '"SiteID";"CompanyName";"SiteName";"City";"Subsector";"geom"\n'
        '173;"Dyckerhoff GmbH";"Werk Lengerich";"Lengerich";"Cement";"SRID=4326;POINT(7.8 52.2)"\n'
        '173;"Dyckerhoff GmbH";"Werk Lengerich";"Lengerich";"Cement";"SRID=4326;POINT(7.8 52.2)"\n'
        ';"ohne Id";"";"";"";""\n',
        encoding="utf-8",
    )
    names = eu.hotmaps_industry_names()
    assert list(names.columns) == list(eu.HOTMAPS_COLUMNS)
    assert names["SiteID"].tolist() == [173]
    assert names["SiteName"].iloc[0] == "Werk Lengerich"
