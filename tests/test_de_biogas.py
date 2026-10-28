"""Tests for fheat_de.biogas (MaStR biogas units and their clusters).

- only biogas units in operation or planned, from 250 kW, with an HBL and
  coordinates; the HBL is split among all biogas units of the EEG plant
- heat by the P_th/P_el of the CHP plant, the flat efficiencies without
  plausible CHP data
- only units within the distance of the area
- clusters: chains of at most 3 km, sums, the one with the most heat first,
  hull + 500 m or a circle of 1.5 km
"""
from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point, box

from fheat_core import columns as cols
from fheat_de import biogas
from fheat_de.mastr import EEG_FIELDS, KWK_FIELDS, UNIT_FIELDS, MastrTables

CRS = "EPSG:25832"
# Burgsteinfurt in UTM 32N and WGS84
X, Y = 386_150.0, 5_778_800.0
LON, LAT = 7.3367, 52.1475
AREA = box(X - 20_000, Y - 20_000, X + 20_000, Y + 20_000)
FLAT = biogas.ETA_TH / biogas.ETA_EL


def _unit(nr, power="500", eeg="EEG1", kwk="", fuel=biogas.FUEL_BIOGAS, status="35", lon=LON, lat=LAT, **extra):
    row = dict.fromkeys(UNIT_FIELDS, "")
    row.update(EinheitMastrNummer=nr, Nettonennleistung=power, EegMaStRNummer=eeg, KwkMaStRNummer=kwk,
               Hauptbrennstoff=fuel, EinheitBetriebsstatus=status, Laengengrad=str(lon), Breitengrad=str(lat),
               Gemeinde="Steinfurt", **extra)
    return row


def _tables(units, eeg=(), kwk=()) -> MastrTables:
    def frame(rows, fields):
        return pd.DataFrame([{**dict.fromkeys(fields, ""), **r} for r in rows], columns=list(fields))

    return MastrTables(frame(units, UNIT_FIELDS), frame(eeg, EEG_FIELDS), frame(kwk, KWK_FIELDS), "01.10.2026")


def _eeg(nr="EEG1", hbl="400", **extra):
    return {"EegMaStRNummer": nr, "BiogasHoechstbemessungsleistung": hbl, **extra}


def _plants(tables, **kwargs):
    return biogas.process_biogas(tables, AREA, CRS, **kwargs).set_index(cols.MASTR_UNIT_ID)


class TestSelection:
    def test_filters(self):
        tables = _tables(
            [_unit("SEE1"), _unit("SEE2", status="31"), _unit("SEE3", status="38"),
             _unit("SEE4", fuel="2446"), _unit("SEE5", power="249"), _unit("SEE6", eeg="EEG2"),
             _unit("SEE7", eeg=""), _unit("SEE8", lon="", lat="")],
            eeg=[_eeg(), _eeg("EEG2", hbl="")],
        )
        plants = _plants(tables)
        assert sorted(plants.index) == ["SEE1", "SEE2"]
        assert plants.loc["SEE2", cols.OPERATING_STATUS] == "in Planung"

    def test_gross_power_without_net_power(self):
        plants = _plants(_tables([_unit("SEE1", power="", Bruttoleistung="300")], eeg=[_eeg()]))
        assert plants.loc["SEE1", cols.ELECTRIC_POWER_KW] == 300.0

    def test_only_units_near_the_area(self):
        far = _unit("SEE2", eeg="EEG2", lon=LON + 0.5)  # about 34 km east
        tables = _tables([_unit("SEE1"), far], eeg=[_eeg(), _eeg("EEG2")])
        assert list(_plants(tables).index) == ["SEE1"]
        assert list(_plants(tables, max_distance=20_000).index) == ["SEE1", "SEE2"]


class TestEnergy:
    def test_hbl_split_among_all_units_of_the_plant(self):
        # the 100 kW unit is too small to be shown but keeps its share
        tables = _tables([_unit("SEE1", power="300"), _unit("SEE2", power="600"), _unit("SEE3", power="100")],
                         eeg=[_eeg(hbl="500")])
        plants = _plants(tables)
        assert sorted(plants.index) == ["SEE1", "SEE2"]
        assert plants.loc["SEE1", cols.ELECTRICITY_MWH] == pytest.approx(500 * 8760 * 0.3 / 1e3)
        assert plants.loc["SEE2", cols.ELECTRICITY_MWH] == pytest.approx(500 * 8760 * 0.6 / 1e3)
        assert plants.loc["SEE1", cols.MAX_RATED_POWER_KW] == 500.0

    def test_heat_from_the_chp_data(self):
        tables = _tables([_unit("SEE1", kwk="KWK1")], eeg=[_eeg()],
                         kwk=[{"KwkMastrNummer": "KWK1", "ElektrischeKwkLeistung": "500", "ThermischeNutzleistung": "550"}])
        row = _plants(tables).loc["SEE1"]
        assert row[cols.THERMAL_BASIS] == "kwk"
        assert row[cols.THERMAL_POWER_KW] == pytest.approx(550.0)
        assert row[cols.CHP_HEAT_MWH] == pytest.approx(400 * 8760 / 1e3 * 1.1)

    @pytest.mark.parametrize("kwk", ["", "KWK1"])
    def test_flat_efficiencies_without_plausible_chp_data(self, kwk):
        # 550 000 "kW" heat for 500 kW: entered in W
        tables = _tables([_unit("SEE1", kwk=kwk)], eeg=[_eeg()],
                         kwk=[{"KwkMastrNummer": "KWK1", "ElektrischeKwkLeistung": "500", "ThermischeNutzleistung": "550000"}])
        row = _plants(tables).loc["SEE1"]
        assert row[cols.THERMAL_BASIS] == "factor"
        assert row[cols.THERMAL_POWER_KW] == pytest.approx(500 * FLAT)
        assert row[cols.CHP_HEAT_MWH] == pytest.approx(400 * 8760 / 1e3 * FLAT)

    def test_eeg_details_and_source(self):
        tables = _tables([_unit("SEE1", Inbetriebnahmedatum="2009-12-01")],
                         eeg=[_eeg(EegInbetriebnahmedatum="2009-11-30", BiogasInanspruchnahmeFlexiPraemie="1")])
        row = _plants(tables).loc["SEE1"]
        assert row[cols.COMMISSIONING_DATE] == "2009-12-01"
        assert row[cols.EEG_COMMISSIONING_DATE] == "2009-11-30"
        assert bool(row[cols.FLEX_PREMIUM]) is True
        assert row[cols.MASTR_EEG_ID] == "EEG1"
        assert row[cols.DATA_SOURCE] == "Bundesnetzagentur, Marktstammdatenregister (Stand 01.10.2026)"
        assert row[cols.SOURCE_CANDIDATE_LAT] == pytest.approx(LAT, abs=1e-5)

    def test_columns(self):
        plants = biogas.process_biogas(_tables([_unit("SEE1")], eeg=[_eeg()]), AREA, CRS)
        assert list(plants.columns) == biogas.PLANT_ORDER + ["geometry"]
        assert plants.crs == CRS


def _plant_frame(points, heat):
    return gpd.GeoDataFrame({
        cols.MASTR_UNIT_ID: [f"SEE{i}" for i in range(len(points))],
        cols.MUNICIPALITY: pd.array(["A"] * len(points), dtype="string"),
        cols.ELECTRIC_POWER_KW: 500.0, cols.THERMAL_POWER_KW: 550.0,
        cols.ELECTRICITY_MWH: 1000.0, cols.CHP_HEAT_MWH: heat, cols.DATA_SOURCE: "MaStR",
    }, geometry=[Point(p) for p in points], crs=CRS)


class TestClusters:
    def test_chains_sums_and_order(self):
        # chain 0-2.5 km-5 km is one cluster; the single unit at 20 km has more heat
        plants = _plant_frame([(0, 0), (2500, 0), (5000, 0), (20_000, 0)], [100.0, 100.0, 100.0, 1000.0])
        out = biogas.biogas_clusters(plants)
        assert list(out.columns) == biogas.CLUSTER_ORDER + ["geometry"]
        assert out[cols.CLUSTER_ID].tolist() == [1, 2]
        assert out[cols.N_UNITS].tolist() == [1, 3]
        chain = out.iloc[1]
        assert chain[cols.CHP_HEAT_MWH] == pytest.approx(300.0)
        assert chain[cols.ELECTRIC_POWER_KW] == pytest.approx(1500.0)
        assert chain[cols.MAX_INTERNAL_DISTANCE] == pytest.approx(5000.0)
        assert chain[cols.MASTR_UNIT_IDS] == "SEE0; SEE1; SEE2"
        assert chain[cols.MUNICIPALITY] == "A"

    def test_areas(self):
        plants = _plant_frame([(0, 0), (2000, 0), (20_000, 0)], [1.0, 1.0, 5.0])
        out = biogas.biogas_clusters(plants)
        single, pair = out.geometry.iloc[0], out.geometry.iloc[1]
        assert single.contains(Point(20_000, 1400)) and not single.contains(Point(20_000, 1600))
        assert pair.contains(Point(1000, 450)) and not pair.contains(Point(1000, 550))

    def test_no_units(self):
        out = biogas.biogas_clusters(_plant_frame([], []))
        assert out.empty and list(out.columns) == biogas.CLUSTER_ORDER + ["geometry"]
