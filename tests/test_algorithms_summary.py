"""Tests for fheat_core.algorithms.summary.

Covers:
- summarize_pipes: totals per DN, kWh → MWh, zero rows in catalogue order,
  unknown DN appended, edges without DN ignored, empty net, missing columns.
- summarize_buildings: fixed profile order, zero rows, unknown profile
  appended, NA row, counts add up.
- network_length_split: house connection + route = total length.
"""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, Polygon

from fheat_core import columns as cols
from fheat_core.algorithms.summary import (
    LOAD_PROFILE_ORDER,
    network_length_split,
    summarize_buildings,
    summarize_pipes,
)

CRS = "EPSG:25832"


@pytest.fixture
def catalogue():
    return pd.DataFrame({"DN": ["PEX 20", "PEX 25", "PEX 32", "KMR 100"]})


def _net(rows):
    """rows: (type, DN, length, loss kWh/a, loss extra kWh/a)"""
    return gpd.GeoDataFrame(
        {
            cols.TYPE: [r[0] for r in rows],
            cols.NOMINAL_DIAMETER: [r[1] for r in rows],
            cols.LENGTH: [r[2] for r in rows],
            cols.HEAT_LOSS: [r[3] for r in rows],
            cols.HEAT_LOSS_EXTRA_INSULATION: [r[4] for r in rows],
            "geometry": [LineString([(0, i), (r[2], i)]) for i, r in enumerate(rows)],
        },
        crs=CRS,
    )


@pytest.fixture
def net():
    return _net(
        [
            ("Hausanschluss", "PEX 20", 10.0, 1000.0, 800.0),
            ("Hausanschluss", "PEX 20", 15.0, 1500.0, 1200.0),
            ("Hausanschluss", "PEX 25", 20.0, 2000.0, 1600.0),
            ("Straßenleitung", "KMR 100", 100.0, 20000.0, 15000.0),
            ("Straßenleitung", "PEX 25", 50.0, 6000.0, 5000.0),
            ("Quellenanschluss", "KMR 100", 5.0, 1000.0, 750.0),
        ]
    )


def _row(df, dn):
    return df[df[cols.NOMINAL_DIAMETER] == dn].iloc[0]


class TestSummarizePipes:
    def test_one_row_per_catalogue_dn_in_order(self, net, catalogue):
        df = summarize_pipes(net, catalogue)
        assert list(df[cols.NOMINAL_DIAMETER]) == ["PEX 20", "PEX 25", "PEX 32", "KMR 100"]

    def test_totals_per_dn(self, net, catalogue):
        df = summarize_pipes(net, catalogue)

        pex20 = _row(df, "PEX 20")
        assert pex20[cols.N_HOUSE_CONNECTIONS] == 2
        assert pex20[cols.HOUSE_CONNECTION_LENGTH] == pytest.approx(25.0)
        assert pex20[cols.ROUTE_LENGTH] == pytest.approx(0.0)
        assert pex20[cols.HEAT_LOSS_MWH] == pytest.approx(2.5)
        assert pex20[cols.HEAT_LOSS_EXTRA_INSULATION_MWH] == pytest.approx(2.0)

        pex25 = _row(df, "PEX 25")
        assert pex25[cols.N_HOUSE_CONNECTIONS] == 1
        assert pex25[cols.HOUSE_CONNECTION_LENGTH] == pytest.approx(20.0)
        assert pex25[cols.ROUTE_LENGTH] == pytest.approx(50.0)
        assert pex25[cols.HEAT_LOSS_MWH] == pytest.approx(8.0)

    def test_source_connection_counts_as_route(self, net, catalogue):
        kmr = _row(summarize_pipes(net, catalogue), "KMR 100")
        assert kmr[cols.N_HOUSE_CONNECTIONS] == 0
        assert kmr[cols.ROUTE_LENGTH] == pytest.approx(105.0)
        assert kmr[cols.HEAT_LOSS_MWH] == pytest.approx(21.0)

    def test_unused_dn_is_zero(self, net, catalogue):
        pex32 = _row(summarize_pipes(net, catalogue), "PEX 32")
        assert pex32[cols.N_HOUSE_CONNECTIONS] == 0
        assert pex32[cols.HOUSE_CONNECTION_LENGTH] == 0.0
        assert pex32[cols.ROUTE_LENGTH] == 0.0
        assert pex32[cols.HEAT_LOSS_MWH] == 0.0

    def test_sums_match_the_net(self, net, catalogue):
        df = summarize_pipes(net, catalogue)
        total_length = df[cols.HOUSE_CONNECTION_LENGTH].sum() + df[cols.ROUTE_LENGTH].sum()
        assert total_length == pytest.approx(net[cols.LENGTH].sum())
        assert df[cols.HEAT_LOSS_MWH].sum() == pytest.approx(net[cols.HEAT_LOSS].sum() / 1000)

    def test_dn_missing_from_catalogue_is_appended(self, net):
        df = summarize_pipes(net, pd.DataFrame({"DN": ["PEX 32", "PEX 20"]}))
        assert list(df[cols.NOMINAL_DIAMETER]) == ["PEX 32", "PEX 20", "PEX 25", "KMR 100"]

    def test_numeric_catalogue_labels(self):
        net = _net([("Hausanschluss", 20, 10.0, 100.0, 80.0)])
        df = summarize_pipes(net, pd.DataFrame({"DN": [20, 25]}))
        assert list(df[cols.NOMINAL_DIAMETER]) == [20, 25]
        assert _row(df, 20)[cols.N_HOUSE_CONNECTIONS] == 1

    def test_edges_without_dn_are_ignored(self, catalogue):
        net = _net(
            [
                ("Hausanschluss", "PEX 20", 10.0, 100.0, 80.0),
                ("Straßenleitung", np.nan, 99.0, 999.0, 999.0),
            ]
        )
        df = summarize_pipes(net, catalogue)
        assert len(df) == len(catalogue)
        assert df[cols.ROUTE_LENGTH].sum() == 0.0

    def test_empty_net_gives_zero_catalogue_rows(self, catalogue):
        empty = gpd.GeoDataFrame({"geometry": []}, geometry="geometry", crs=CRS)
        df = summarize_pipes(empty, catalogue)
        assert list(df[cols.NOMINAL_DIAMETER]) == list(catalogue["DN"])
        assert (df[cols.N_HOUSE_CONNECTIONS] == 0).all()
        assert df[cols.HEAT_LOSS_MWH].sum() == 0.0

    def test_missing_loss_column_counts_as_zero(self, net, catalogue):
        df = summarize_pipes(net.drop(columns=[cols.HEAT_LOSS_EXTRA_INSULATION]), catalogue)
        assert df[cols.HEAT_LOSS_EXTRA_INSULATION_MWH].sum() == 0.0
        assert df[cols.HEAT_LOSS_MWH].sum() > 0

    def test_column_dtypes(self, net, catalogue):
        df = summarize_pipes(net, catalogue)
        assert pd.api.types.is_integer_dtype(df[cols.N_HOUSE_CONNECTIONS])
        for column in (
            cols.HOUSE_CONNECTION_LENGTH,
            cols.ROUTE_LENGTH,
            cols.HEAT_LOSS_MWH,
            cols.HEAT_LOSS_EXTRA_INSULATION_MWH,
        ):
            assert pd.api.types.is_float_dtype(df[column]), column


def _buildings(profiles, demands):
    polys = [Polygon([(i * 20, 0), (i * 20 + 10, 0), (i * 20 + 10, 10), (i * 20, 10)]) for i in range(len(profiles))]
    return gpd.GeoDataFrame(
        {
            cols.LOAD_PROFILE: pd.array(profiles, dtype="string"),
            cols.HEAT_DEMAND: demands,
            "geometry": polys,
        },
        crs=CRS,
    )


class TestSummarizeBuildings:
    def test_fixed_order_with_zero_rows(self):
        df = summarize_buildings(_buildings(["MFH", "EFH", "EFH"], [35000.0, 15000.0, 25000.0]))
        assert list(df[cols.LOAD_PROFILE]) == list(LOAD_PROFILE_ORDER)
        efh = df[df[cols.LOAD_PROFILE] == "EFH"].iloc[0]
        assert efh[cols.N_BUILDINGS] == 2
        assert efh[cols.HEAT_DEMAND_MWH] == pytest.approx(40.0)
        gko = df[df[cols.LOAD_PROFILE] == "GKO"].iloc[0]
        assert gko[cols.N_BUILDINGS] == 0
        assert gko[cols.HEAT_DEMAND_MWH] == 0.0

    def test_unknown_profiles_appended_alphabetically(self):
        df = summarize_buildings(_buildings(["ZZZ", "EFH", "ABC"], [1000.0, 2000.0, 3000.0]))
        assert list(df[cols.LOAD_PROFILE]) == [*LOAD_PROFILE_ORDER, "ABC", "ZZZ"]

    def test_missing_profile_gets_own_row(self):
        df = summarize_buildings(_buildings(["EFH", None, None], [1000.0, 2000.0, 3000.0]))
        last = df.iloc[-1]
        assert pd.isna(last[cols.LOAD_PROFILE])
        assert last[cols.N_BUILDINGS] == 2
        assert last[cols.HEAT_DEMAND_MWH] == pytest.approx(5.0)

    def test_no_na_row_when_all_profiles_known(self):
        df = summarize_buildings(_buildings(["EFH"], [1000.0]))
        assert df[cols.LOAD_PROFILE].notna().all()

    def test_counts_add_up(self):
        profiles = ["EFH", "MFH", None, "XYZ", "GKO"]
        demands = [1000.0, 2000.0, 3000.0, 4000.0, 5000.0]
        df = summarize_buildings(_buildings(profiles, demands))
        assert df[cols.N_BUILDINGS].sum() == len(profiles)
        assert df[cols.HEAT_DEMAND_MWH].sum() == pytest.approx(sum(demands) / 1000)

    def test_empty_buildings(self):
        df = summarize_buildings(_buildings([], []))
        assert list(df[cols.LOAD_PROFILE]) == list(LOAD_PROFILE_ORDER)
        assert df[cols.N_BUILDINGS].sum() == 0


class TestNetworkLengthSplit:
    def test_split_adds_up_to_total(self, net):
        house, route = network_length_split(net)
        assert house == pytest.approx(45.0)
        assert route == pytest.approx(155.0)
        assert house + route == pytest.approx(net[cols.LENGTH].sum())

    def test_counts_edges_without_dn(self):
        net = _net([("Straßenleitung", np.nan, 30.0, 0.0, 0.0)])
        assert network_length_split(net) == (0.0, pytest.approx(30.0))

    def test_empty_or_none(self):
        assert network_length_split(None) == (0.0, 0.0)
        empty = gpd.GeoDataFrame({"geometry": []}, geometry="geometry", crs=CRS)
        assert network_length_split(empty) == (0.0, 0.0)
