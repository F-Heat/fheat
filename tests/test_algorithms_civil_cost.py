"""Tests for fheat_core.algorithms.civil_cost (civil works factors per line)."""
from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString, Polygon

from fheat_core import columns as cols
from fheat_core.algorithms.civil_cost import (
    CIVIL_FACTOR_COLUMN,
    apply_cost_table,
    civil_factors_for_lines,
)

CRS = "EPSG:25832"

LEFT = Polygon([(0, -10), (50, -10), (50, 10), (0, 10)])
RIGHT = Polygon([(50, -10), (100, -10), (100, 10), (50, 10)])


def _landuse():
    # left half (x < 50): road (factor 1.4); right half (x >= 50): green (factor 0.5)
    return gpd.GeoDataFrame(
        {
            "klasse": ["AX_Strassenverkehr", "AX_SportFreizeitUndErholungsflaeche"],
            "geometry": [LEFT, RIGHT],
        },
        crs=CRS,
        geometry="geometry",
    )


def _factored_landuse():
    return apply_cost_table(
        _landuse(),
        class_column="klasse",
        cost_table={"AX_Strassenverkehr": 1.4, "AX_SportFreizeitUndErholungsflaeche": 0.5},
    )


def _layer(factor, poly=LEFT, civil_class=None):
    data = {CIVIL_FACTOR_COLUMN: [factor], "geometry": [poly]}
    if civil_class is not None:
        data["civil_class"] = [civil_class]
    return gpd.GeoDataFrame(data, crs=CRS, geometry="geometry")


def _lines(*coords, index=None):
    return gpd.GeoSeries([LineString(c) for c in coords], crs=CRS, index=index)


def _factors(lines, layers, **kwargs):
    kwargs.setdefault("buffer_m", 1.0)
    return civil_factors_for_lines(lines, layers, crs=CRS, **kwargs)[cols.CIVIL_COST_FACTOR].tolist()


# ---------------------------------------------------------------------------
# apply_cost_table
# ---------------------------------------------------------------------------


def test_apply_cost_table_exact_and_default():
    lu = _factored_landuse()
    assert list(lu[CIVIL_FACTOR_COLUMN]) == [1.4, 0.5]

    lu2 = apply_cost_table(
        _landuse(), class_column="klasse",
        cost_table={"AX_Strassenverkehr": 2.0}, default_factor=1.1,
    )
    assert list(lu2[CIVIL_FACTOR_COLUMN]) == [2.0, 1.1]


def test_apply_cost_table_contains_match():
    lu = gpd.GeoDataFrame(
        {"objektart_txt": ["AX_Strassenverkehr (42001)", "Wohnbauflaeche"],
         "geometry": [Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
                      Polygon([(2, 2), (3, 2), (3, 3), (2, 3)])]},
        crs=CRS, geometry="geometry",
    )
    out = apply_cost_table(lu, class_column="objektart_txt",
                           cost_table={"Strassenverkehr": 1.4, "Wohnbauflaeche": 0.9},
                           match="contains")
    assert list(out[CIVIL_FACTOR_COLUMN]) == [1.4, 0.9]


def test_contains_match_handles_umlauts_and_spaces():
    # WFS plain text (umlauts, spaces, slashes) against ASCII CamelCase keys
    lu = gpd.GeoDataFrame(
        {"nutzart": ["Wohnbaufläche", "Straßenverkehr", "Fläche gemischter Nutzung",
                     "Unland/Vegetationslose Fläche", "Unbekannt"],
         "geometry": [Polygon([(i, 0), (i + 1, 0), (i + 1, 1), (i, 1)]) for i in range(5)]},
        crs=CRS, geometry="geometry",
    )
    out = apply_cost_table(
        lu, class_column="nutzart",
        cost_table={"Strassenverkehr": 1.4, "Wohnbauflaeche": 0.9, "FlaecheGemischterNutzung": 1.0,
                    "UnlandVegetationsloseFlaeche": 1.1},
        match="contains", default_factor=1.0,
    )
    assert list(out[CIVIL_FACTOR_COLUMN]) == [0.9, 1.4, 1.0, 1.1, 1.0]


def test_apply_cost_table_without_class_column_uses_default():
    out = apply_cost_table(_landuse(), class_column="missing", cost_table={"x": 2.0}, default_factor=1.2)
    assert list(out[CIVIL_FACTOR_COLUMN]) == [1.2, 1.2]


# ---------------------------------------------------------------------------
# civil_factors_for_lines
# ---------------------------------------------------------------------------


def test_line_inside_single_polygon():
    lines = _lines([(10, 0), (30, 0)], [(60, 0), (90, 0)])
    assert _factors(lines, [_factored_landuse()]) == pytest.approx([1.4, 0.5])


def test_line_over_two_polygons_is_area_weighted():
    # 20 m in the road (1.4), 20 m in the green (0.5) → mean 0.95
    lines = _lines([(30, 0), (70, 0)])
    assert _factors(lines, [_factored_landuse()]) == pytest.approx([0.95], rel=1e-3)


def test_unequal_split_is_weighted_by_area():
    # 10 m in the road (1.4), 30 m in the green (0.5) → (10·1.4 + 30·0.5) / 40
    lines = _lines([(40, 0), (80, 0)])
    assert _factors(lines, [_factored_landuse()]) == pytest.approx([(14 + 15) / 40], rel=1e-3)


def test_two_layers_multiply():
    lines = _lines([(10, 0), (30, 0)])
    assert _factors(lines, [_layer(1.5), _layer(0.8)]) == pytest.approx([1.2])


def test_three_layers_combine():
    lines = _lines([(10, 0), (30, 0)])
    assert _factors(lines, [_layer(1.25), _layer(1.15), _layer(0.95)]) == pytest.approx(
        [1.25 * 1.15 * 0.95]
    )


def test_no_layers_gives_default():
    lines = _lines([(0, 0), (1, 0)])
    assert _factors(lines, None) == [1.0]
    assert _factors(lines, []) == [1.0]
    assert _factors(lines, [None, None]) == [1.0]
    assert _factors(lines, [gpd.GeoDataFrame(geometry=[], crs=CRS)]) == [1.0]


def test_line_outside_coverage_gets_default():
    lines = _lines([(200, 200), (210, 200)])
    assert _factors(lines, [_factored_landuse()]) == [1.0]
    assert _factors(lines, [_factored_landuse()], default_factor=1.3) == [1.3]


def test_layer_without_hit_contributes_one():
    far = _layer(0.5, Polygon([(500, -10), (550, -10), (550, 10), (500, 10)]))
    lines = _lines([(10, 0), (30, 0)])
    assert _factors(lines, [_layer(1.4), far]) == pytest.approx([1.4])


def test_none_and_empty_layers_are_skipped():
    lines = _lines([(10, 0), (30, 0)])
    layers = [None, gpd.GeoDataFrame(geometry=[], crs=CRS), _layer(1.4)]
    assert _factors(lines, layers) == pytest.approx([1.4])


def test_result_keeps_the_index_of_the_lines():
    lines = _lines([(10, 0), (30, 0)], [(60, 0), (90, 0)], index=[7, 3])
    out = civil_factors_for_lines(lines, [_factored_landuse()], crs=CRS, buffer_m=1.0)
    assert list(out.index) == [7, 3]
    assert out.loc[3, cols.CIVIL_COST_FACTOR] == pytest.approx(0.5)


def test_layer_in_other_crs_is_reprojected():
    layer = _layer(1.4).to_crs("EPSG:4326")
    lines = _lines([(10, 0), (30, 0)])
    assert _factors(lines, [layer]) == pytest.approx([1.4], rel=1e-3)


def test_road_surface_is_the_class_with_the_largest_area():
    asphalt = _layer(1.15, LEFT, "asphalt")
    paving = _layer(0.95, RIGHT, "paving_stones")
    osm = gpd.GeoDataFrame(pd.concat([asphalt, paving], ignore_index=True), crs=CRS)
    lines = _lines([(10, 0), (70, 0)], [(40, 0), (90, 0)], [(200, 200), (210, 200)])
    out = civil_factors_for_lines(lines, [_layer(1.25), osm], crs=CRS, buffer_m=1.0)
    # 40 m asphalt vs 20 m paving; 10 m asphalt vs 40 m paving; no hit
    assert out[cols.ROAD_SURFACE].tolist()[:2] == ["asphalt", "paving_stones"]
    assert pd.isna(out[cols.ROAD_SURFACE].iloc[2])


def test_road_surface_comes_only_from_the_surface_layer():
    landuse = _layer(1.25, LEFT, "Strassenverkehr")
    lines = _lines([(10, 0), (30, 0)])
    out = civil_factors_for_lines(lines, [landuse, None], crs=CRS, buffer_m=1.0)
    assert out[cols.ROAD_SURFACE].tolist() == [None]
    assert out[cols.CIVIL_COST_FACTOR].tolist() == pytest.approx([1.25])


def test_empty_lines_give_an_empty_frame():
    out = civil_factors_for_lines(gpd.GeoSeries([], crs=CRS), [_layer(1.4)], crs=CRS)
    assert out.empty
    assert list(out.columns) == [cols.CIVIL_COST_FACTOR, cols.ROAD_SURFACE]
