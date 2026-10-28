"""Heat sources in the NRW and the flexible adapter (no network).

Covers:
- NRWDataAdapter.fetch_wastewater: LANUK file from its own folder, 2 km,
  local file, switched off, failure → None + warning
- NRW Fordatis layers from an own folder: distances of the paper, Hotmaps
  names, restored umlauts, study areas and table of the municipality, no
  Fordatis hydrothermal or wastewater in NRW
- FlexDataAdapter: off by default, Fordatis wastewater and hydrothermal,
  a geographic CRS gives no layer
- biogas CHP units (Marktstammdatenregister) in the area and their
  clusters in both adapters; switched off, failure → None + warning
"""
from __future__ import annotations

import zipfile

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString, MultiPoint, Point, box

from fheat_core import columns as cols
from fheat_de import mastr
from fheat_de.mastr import EEG_FIELDS, KWK_FIELDS, UNIT_FIELDS, MastrTables
from fheat_eu import download as eu
from fheat_eu import heat_sources as hs
from fheat_flex import FlexDataAdapter
from fheat_nrw import download as dl
from fheat_nrw.adapter.data_adapter import NRWDataAdapter

CRS = "EPSG:25832"
AREA_BOX = (388000.0, 5779000.0, 388100.0, 5779100.0)   # Burgsteinfurt, municipality Steinfurt
LAU_STEINFURT = "DE_05566084"


def _at(dx: float, dy: float = 0.0) -> Point:
    """Point ``dx`` m east and ``dy`` m north of the area's north-east corner, in EPSG:3035."""
    point = gpd.GeoSeries([Point(AREA_BOX[2] + dx, AREA_BOX[3] + dy)], crs=CRS).to_crs(eu.FORDATIS_CRS)
    return point.iloc[0]


def _write(folder, name: str, gdf: gpd.GeoDataFrame) -> None:
    gdf.to_file(folder / name, driver="GPKG")


@pytest.fixture
def fordatis_dir(tmp_path):
    """Own Fordatis folder with one or two features per file around the area."""
    folder = tmp_path / "fordatis"
    folder.mkdir()
    g = eu.FORDATIS_CRS
    _write(folder, eu.FILE_WASTEWATER, gpd.GeoDataFrame(
        {"x": [0.0], "y": [0.0], "Power in k": [500.0]}, geometry=[_at(1000)], crs=g))
    _write(folder, eu.FILE_INDUSTRIAL, gpd.GeoDataFrame(
        {"ID_Site": [173, 5060], "EH_55_GWh": [30.0, 1.0], "EH_95_GWh": [24.0, 0.5], "Country": ["DE", "DE"]},
        geometry=[_at(15000), _at(25000)], crs=g))
    _write(folder, eu.FILE_WASTE_INCINERATION, gpd.GeoDataFrame(
        {"City": ["Steinf�rt", "Salzbergen"], "EH100PJ": [0.36, 0.77]},
        geometry=[_at(500), _at(30000)], crs=g))
    _write(folder, eu.FILE_RIVERS, gpd.GeoDataFrame(
        {"Capa in MW": [80]}, geometry=[_at(3000).buffer(1000)], crs=g))
    for name, value in zip(eu.FILES_HYDROTHERMAL, (0.0015, 0.0036)):
        _write(folder, name, gpd.GeoDataFrame({"Energy_TWh": [value]}, geometry=[MultiPoint([_at(200)])], crs=g))
    _write(folder, eu.FILE_DH_AREAS, gpd.GeoDataFrame(
        {"Label": [298, 305], "country": ["DE", "DE"], "Dem_GWh": [6.79, 31.6]},
        geometry=[_at(-50, -50).buffer(30), _at(-60, -60).buffer(20)], crs=g))
    with pd.ExcelWriter(folder / eu.FILE_STUDY_RESULTS) as writer:
        pd.DataFrame([["fid", "Label", "country", "LAU_ID"], [1, 298, "DE", LAU_STEINFURT],
                      [2, 305, "DE", "DE_05566012"]]).to_excel(
            writer, sheet_name="DH_LAU_Mapping", header=False, index=False)
        sources = list(hs._STUDY_HEADERS)
        head = ["GISCO_ID", "Country", "Unit", "DH_demand", *sources, *sources, "DH_demand", *sources, *sources]
        row = [LAU_STEINFURT, "DE", "GWh", 7.88, *([1.0] * 16), 7.47, *([2.0] * 16)]
        pd.DataFrame([[None] * len(head), head, row]).to_excel(
            writer, sheet_name="Matching_results", header=False, index=False)
    return folder


@pytest.fixture
def hotmaps(monkeypatch):
    names = pd.DataFrame({"SiteID": pd.array([173], dtype="Int64"), "CompanyName": ["Dyckerhoff GmbH"],
                          "SiteName": ["Werk Lengerich"], "City": ["Lengerich"], "Subsector": ["Cement"]})
    monkeypatch.setattr(eu, "hotmaps_industry_names", lambda cache_dir=None: names)


def _loaded_adapter(**kwargs) -> NRWDataAdapter:
    adapter = NRWDataAdapter(municipality_name="Steinfurt", **kwargs)
    adapter._buildings = gpd.GeoDataFrame({cols.HEAT_DEMAND: [1000.0]},
                                          geometry=[box(388010, 5779010, 388020, 5779020)], crs=CRS)
    adapter._streets = gpd.GeoDataFrame({"geometry": [LineString([(388000, 5779000), (388100, 5779100)])]}, crs=CRS)
    adapter._boundary = gpd.GeoDataFrame(geometry=[box(*AREA_BOX)], crs=CRS)
    return adapter


def _plants_zip(tmp_path):
    plants = gpd.GeoDataFrame(
        {"standortnr": ["1", "2"], "name": ["Steinfurt-Burgsteinfurt", "Ochtrup"], "ew_bemess": ["38000", "30000"],
         "ew": ["30000", "20000"], "jabw_menge": ["1000000", "800000"]},
        geometry=[Point(388150, 5779050), Point(392000, 5779050)], crs=CRS,
    )
    gpkg = tmp_path / "KomKlaeranlagen.gpkg"
    plants.to_file(gpkg, layer=dl.LAYER_WASTEWATER, driver="GPKG")
    path = tmp_path / dl.FILE_WASTEWATER
    with zipfile.ZipFile(path, "w") as zf:
        zf.write(gpkg, arcname=gpkg.name)
    return path, gpkg


class TestNRWWastewater:
    def test_lanuk_plants_within_2_km(self, monkeypatch, tmp_path):
        path, _ = _plants_zip(tmp_path)
        seen = {}

        def fake_cached_file(url, name, cache_dir=None, files=None):
            seen.update(url=url, name=name)
            return path

        monkeypatch.setattr(dl, "cached_file", fake_cached_file)
        out = _loaded_adapter().fetch_wastewater()
        assert seen == {"url": dl.URL_WASTEWATER, "name": dl.FILE_WASTEWATER}
        assert out[cols.SOURCE_NAME].tolist() == ["Steinfurt-Burgsteinfurt"]   # Ochtrup is 3.9 km away
        assert out[cols.HEAT_EXTRACTION_MWH].iloc[0] == pytest.approx(5815.0)
        assert out.crs == CRS

    def test_local_file_and_switch(self, monkeypatch, tmp_path):
        _, gpkg = _plants_zip(tmp_path)
        monkeypatch.setattr(dl, "cached_file", lambda *a, **kw: pytest.fail("no download"))
        assert len(_loaded_adapter(wastewater_path=gpkg).fetch_wastewater()) == 1
        assert _loaded_adapter(download_heat_sources=False).fetch_wastewater() is None

    def test_failure_gives_none_and_a_warning(self, monkeypatch, caplog):
        def failing(*a, **kw):
            raise RuntimeError("Download fehlgeschlagen")

        monkeypatch.setattr(dl, "cached_file", failing)
        with caplog.at_level("WARNING"):
            assert _loaded_adapter().fetch_wastewater() is None
        assert "Kläranlagen" in caplog.records[-1].getMessage()


class TestNRWFordatisLayers:
    def test_layers_within_the_distances_of_the_paper(self, fordatis_dir, hotmaps):
        adapter = _loaded_adapter(fordatis_path=fordatis_dir, download_heat_sources=False)
        industrial = adapter.fetch_industrial_heat()
        assert industrial[cols.SITE_ID].tolist() == [173]                 # 25 km site is out
        assert industrial[cols.SOURCE_NAME].iloc[0] == "Werk Lengerich"
        incineration = adapter.fetch_waste_incineration()
        assert incineration[cols.SOURCE_NAME].tolist() == ["Steinfurt"]  # umlaut restored from cities.csv
        assert adapter.fetch_river_heat()[cols.HEAT_MWH].tolist() == [240000.0]
        assert all(gdf.crs == CRS for gdf in (industrial, incineration))

    def test_study_values_of_the_municipality(self, fordatis_dir, hotmaps):
        adapter = _loaded_adapter(fordatis_path=fordatis_dir, download_heat_sources=False)
        assert adapter.fetch_study_dh_areas()[cols.DH_AREA_ID].tolist() == [298]
        table = adapter.fetch_study_potentials()
        assert table[cols.STUDY_SUPPLY_HT_MWH].iloc[0] == pytest.approx(7880.0)

    def test_nrw_keeps_its_own_hydrothermal_and_wastewater(self, fordatis_dir, hotmaps, monkeypatch):
        monkeypatch.setattr(dl, "cached_file", lambda *a, **kw: pytest.fail("no LANUK download"))
        adapter = _loaded_adapter(fordatis_path=fordatis_dir, download_heat_sources=False)
        assert adapter.fetch_geothermal_hydrothermal() is None
        assert adapter.fetch_wastewater() is None   # LANUK, switched off — not the Fordatis file

    def test_buffers_are_a_parameter(self, fordatis_dir, hotmaps):
        adapter = _loaded_adapter(fordatis_path=fordatis_dir, download_heat_sources=False,
                                  heat_source_buffers={"industrial_heat": 30000})
        assert len(adapter.fetch_industrial_heat()) == 2

    def test_switched_off(self, monkeypatch):
        monkeypatch.setattr(eu, "read_fordatis", lambda *a, **kw: pytest.fail("no read"))
        adapter = _loaded_adapter(download_heat_sources=False)
        assert adapter.fetch_industrial_heat() is None and adapter.fetch_study_potentials() is None

    def test_failure_gives_none_and_a_warning(self, monkeypatch, caplog):
        def failing(*a, **kw):
            raise RuntimeError("Fordatis nicht erreichbar")

        monkeypatch.setattr(eu.cache, "cached_download", failing)
        with caplog.at_level("WARNING"):
            assert _loaded_adapter().fetch_waste_incineration() is None
        assert "Müllverbrennung" in caplog.records[-1].getMessage()


class TestFlexAdapter:
    @staticmethod
    def _files(tmp_path, crs=CRS):
        buildings = gpd.GeoDataFrame({"heat_demand": [1000.0]}, geometry=[box(*AREA_BOX)], crs=CRS).to_crs(crs)
        streets = gpd.GeoDataFrame(geometry=[LineString([(388000, 5779000), (388100, 5779100)])], crs=CRS)
        parcels = gpd.GeoDataFrame(geometry=[box(*AREA_BOX)], crs=CRS)
        paths = {}
        for name, gdf in (("buildings", buildings), ("streets", streets), ("parcels", parcels)):
            paths[name] = tmp_path / f"{name}.gpkg"
            gdf.to_file(paths[name], driver="GPKG")
        return paths

    def test_off_by_default(self, tmp_path):
        paths = self._files(tmp_path)
        adapter = FlexDataAdapter(paths["buildings"], paths["streets"], paths["parcels"])
        assert adapter.fetch_wastewater() is None and adapter.fetch_geothermal_hydrothermal() is None

    def test_fordatis_wastewater_and_hydrothermal(self, tmp_path, fordatis_dir, hotmaps):
        paths = self._files(tmp_path)
        adapter = FlexDataAdapter(paths["buildings"], paths["streets"], paths["parcels"],
                                  fordatis_path=fordatis_dir, lau_id=LAU_STEINFURT)
        wastewater = adapter.fetch_wastewater()
        assert wastewater[cols.HEAT_EXTRACTION_KW].tolist() == [500.0]
        assert wastewater[cols.DATA_SOURCE].iloc[0] == hs.SOURCE_ISI_HOTMAPS
        hydro = adapter.fetch_geothermal_hydrothermal()
        assert hydro[cols.HEAT_LT_MWH].iloc[0] == pytest.approx(3600.0)
        assert adapter.fetch_study_dh_areas()[cols.DH_AREA_ID].tolist() == [298]

    def test_geographic_crs_gives_no_layer(self, tmp_path, fordatis_dir, caplog):
        paths = self._files(tmp_path, crs="EPSG:4326")
        adapter = FlexDataAdapter(paths["buildings"], paths["streets"], paths["parcels"],
                                  fordatis_path=fordatis_dir)
        with caplog.at_level("WARNING"):
            assert adapter.fetch_wastewater() is None
        assert "metrischen" in caplog.records[-1].getMessage()


def _mastr_tables() -> MastrTables:
    """Two biogas units: one in the area, one 2 km east of it."""
    points = gpd.GeoSeries([Point(388050, 5779050), Point(390100, 5779050)], crs=CRS).to_crs("EPSG:4326")
    units = pd.DataFrame([{**dict.fromkeys(UNIT_FIELDS, ""), "EinheitMastrNummer": nr, "Hauptbrennstoff": "2445",
                           "EinheitBetriebsstatus": "35", "Nettonennleistung": "500", "EegMaStRNummer": f"EEG{nr}",
                           "Laengengrad": str(p.x), "Breitengrad": str(p.y)}
                          for nr, p in zip(("SEE1", "SEE2"), points)])
    eeg = pd.DataFrame([{**dict.fromkeys(EEG_FIELDS, ""), "EegMaStRNummer": f"EEG{nr}",
                         "BiogasHoechstbemessungsleistung": "400"} for nr in ("SEE1", "SEE2")])
    return MastrTables(units, eeg, pd.DataFrame(columns=list(KWK_FIELDS)), "01.10.2026")


@pytest.fixture
def mastr_tables(monkeypatch):
    calls = []

    def read(cache_dir=None, export=mastr.MASTR_EXPORT_URL):
        calls.append(cache_dir)
        return _mastr_tables()

    monkeypatch.setattr(mastr, "read_biomass_tables", read)
    return calls


class TestBiogas:
    def test_nrw_units_in_the_area_and_clusters(self, mastr_tables):
        adapter = _loaded_adapter()
        units = adapter.fetch_biogas()
        assert units[cols.MASTR_UNIT_ID].tolist() == ["SEE1"]
        assert units.crs == CRS
        clusters = adapter.fetch_biogas_clusters()
        assert clusters[cols.N_UNITS].tolist() == [1]
        assert len(mastr_tables) == 1  # read once for both

    def test_nrw_switched_off(self, mastr_tables):
        adapter = _loaded_adapter(download_heat_sources=False)
        assert adapter.fetch_biogas() is None and adapter.fetch_biogas_clusters() is None
        assert mastr_tables == []

    def test_nrw_failure_gives_none_and_a_warning(self, monkeypatch, caplog):
        def failing(*a, **kw):
            raise RuntimeError("MaStR nicht erreichbar")

        monkeypatch.setattr(mastr, "read_biomass_tables", failing)
        with caplog.at_level("WARNING"):
            assert _loaded_adapter().fetch_biogas() is None
        assert "Marktstammdatenregister" in caplog.records[-1].getMessage()

    def test_flex_only_when_switched_on(self, tmp_path, mastr_tables):
        paths = TestFlexAdapter._files(tmp_path)
        off = FlexDataAdapter(paths["buildings"], paths["streets"], paths["parcels"])
        assert off.fetch_biogas() is None and mastr_tables == []
        on = FlexDataAdapter(paths["buildings"], paths["streets"], paths["parcels"], download_heat_sources=True)
        assert on.fetch_biogas()[cols.MASTR_UNIT_ID].tolist() == ["SEE1"]
        assert on.fetch_biogas_clusters()[cols.CLUSTER_ID].tolist() == [1]
