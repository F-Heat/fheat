"""House connections under other buildings (fheat_core.algorithms.under_buildings)."""
from __future__ import annotations

import geopandas as gpd
from shapely.geometry import LineString, box

from fheat_core import columns as cols
from fheat_core.algorithms.under_buildings import mark_length_under_buildings
from tests.conftest import CRS

FRONT = box(-5, 5, 5, 15)
REAR = box(-3, 20, 3, 26)  # centroid (0, 23)
FAR = box(28, 48, 32, 52)  # centroid (30, 50)


def _net(*rows):
    return gpd.GeoDataFrame({cols.TYPE: [row[0] for row in rows]}, geometry=[row[1] for row in rows], crs=CRS)


def _frame(*polys):
    return gpd.GeoDataFrame(geometry=list(polys), crs=CRS)


def test_a_house_connection_under_another_building_gets_its_length():
    net = _net(
        (cols.EDGE_TYPE_HOUSE_CONNECTION, LineString([(0, 0), (0, 23)])),   # rear house, 10 m under FRONT
        (cols.EDGE_TYPE_HOUSE_CONNECTION, LineString([(0, 0), (0, 10)])),   # front house: only its own
        (cols.EDGE_TYPE_HOUSE_CONNECTION, LineString([(30, 50), (30, 0)])),  # far away: free
        ("Straßenleitung", LineString([(-10, 10), (10, 10)])),               # a street pipe is never marked
    )
    out = mark_length_under_buildings(net, _frame(REAR, FRONT, FAR), _frame(FRONT, REAR, FAR))
    assert out[cols.LENGTH_UNDER_BUILDINGS].tolist() == [10.0, 0.0, 0.0, 0.0]


def test_without_obstacles_nothing_is_marked():
    net = _net((cols.EDGE_TYPE_HOUSE_CONNECTION, LineString([(0, 0), (0, 23)])))
    out = mark_length_under_buildings(net, _frame(REAR), None)
    assert out[cols.LENGTH_UNDER_BUILDINGS].tolist() == [0.0]


def test_the_own_building_is_the_one_an_end_lies_in():
    # the planner moved the building end of the rear house from its centroid to its back
    net = _net((cols.EDGE_TYPE_HOUSE_CONNECTION, LineString([(0, 0), (0, 25)])))
    out = mark_length_under_buildings(net, _frame(REAR, FRONT), _frame(FRONT, REAR))
    assert out[cols.LENGTH_UNDER_BUILDINGS].tolist() == [10.0]


def test_an_end_millimetres_beside_the_centroid_still_finds_its_building():
    # a U-shaped house: its centroid lies in the courtyard, outside the outline;
    # a web map moved the untouched end there by its coordinate round trip
    u_shape = box(-5, 20, -3, 30).union(box(3, 20, 5, 30)).union(box(-5, 28, 5, 30))
    centroid = u_shape.centroid
    net = _net((cols.EDGE_TYPE_HOUSE_CONNECTION, LineString([(0, 40), (centroid.x + 0.0017, centroid.y)])))
    out = mark_length_under_buildings(net, _frame(u_shape), _frame(u_shape))
    assert out[cols.LENGTH_UNDER_BUILDINGS].tolist() == [0.0]
