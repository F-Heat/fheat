"""Tests for fheat_nds.processing: ALKIS buildings + LoD2 + Zensus → BuildingsSchema."""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

from fheat_core import columns as cols
from fheat_core.schemas import BuildingsSchema
from fheat_de import heat_demand as hd
from fheat_de.lod2 import lod2_frame
from fheat_nds import processing as proc

CRS = "EPSG:25832"


@pytest.fixture(scope="module")
def tables():
    return hd.load_building_functions(), hd.load_age_classes()


def _alkis(rows):
    """rows: (function code, address, x, footprint edge)."""
    return gpd.GeoDataFrame(
        {
            "gfkzshh": [f"31001_{f}" for f, *_ in rows],
            "funktion": ["Wohngebäude" if 1000 <= f <= 1299 else "Gebäude" for f, *_ in rows],
            "lagebeztxt": [a for _, a, *_ in rows],
        },
        geometry=[box(x, 0, x + e, e) for *_, x, e in rows],
        crs=CRS,
    )


def _lod2(eaves_by_x):
    rows = [{"lod2_id": f"L{x}", "height": h + 3, "eaves_height": h, "geometry": box(x - 1, -1, x + 30, 30)}
            for x, h in eaves_by_x.items()]
    return lod2_frame(rows)


def _run(alkis, lod2, ages, tables, **kw):
    functions, age_table = tables
    return proc.process_buildings(alkis, lod2, pd.Series(ages, index=alkis.index), functions, age_table, **kw)


class TestProcessBuildings:
    def test_schema_and_heat_demand_of_a_house(self, tables):
        alkis = _alkis([(1000, "Hauptstr. 1", 0, 10.0)])
        out = _run(alkis, _lod2({0: 6.1}), ["F"], tables)
        BuildingsSchema.validate(out)
        row = out.iloc[0]
        assert row[cols.FLOOR_AREA] == pytest.approx(0.7 * 100 * 2)    # two storeys below 6.1 m eaves
        specific = tables[1].set_index("Baualtersklasse").loc["F", "waerme_efh_kwh_m2a"]
        assert row[cols.HEAT_DEMAND] == pytest.approx(140 * specific)
        assert row[cols.HEAT_DEMAND_CALCULATED] == row[cols.HEAT_DEMAND]
        assert row[cols.THERMAL_POWER] == pytest.approx(row[cols.HEAT_DEMAND] / row[cols.FULL_LOAD_HOURS])
        assert (row[cols.BUILDING_TYPE], row[cols.LOAD_PROFILE]) == ("EFH", "EFH")
        assert row[cols.DATA_SOURCE] == proc.SOURCE_LOD2
        assert row[cols.ADDRESS] == "Hauptstr. 1"
        assert cols.HEAT_DEMAND_DATASET not in out.columns

    def test_a_large_house_is_an_mfh(self, tables):
        out = _run(_alkis([(1000, "A 1", 0, 20.0)]), _lod2({0: 9.0}), ["F"], tables)   # 0.7 × 400 × 3 = 840 m²
        assert (out[cols.BUILDING_TYPE].iloc[0], out[cols.LOAD_PROFILE].iloc[0]) == ("MFH", "MFH")

    def test_without_lod2_the_median_storeys_of_the_houses(self, tables):
        alkis = _alkis([(1000, "A 1", 0, 10.0), (1000, "A 2", 100, 10.0), (1000, "A 3", 200, 10.0)])
        out = _run(alkis, _lod2({0: 9.0, 100: 9.2}), ["F"] * 3, tables)
        assert out[cols.DATA_SOURCE].tolist() == [proc.SOURCE_LOD2] * 2 + [proc.SOURCE_ASSUMED]
        assert out[cols.FLOOR_AREA].tolist() == pytest.approx([210.0, 210.0, 210.0])

    def test_without_any_lod2_two_storeys(self, tables):
        out = _run(_alkis([(1000, "A 1", 0, 10.0)]), None, ["F"], tables)
        assert out[cols.FLOOR_AREA].iloc[0] == pytest.approx(0.7 * 100 * proc.DEFAULT_STOREYS)

    def test_missing_age_classes_take_the_most_frequent_one(self, tables):
        alkis = _alkis([(1000, "A 1", 0, 10.0), (1000, "A 2", 100, 10.0), (1000, "A 3", 200, 10.0)])
        out = _run(alkis, None, ["J", "J", np.nan], tables)
        assert out[cols.CONSTRUCTION_CLASS].tolist() == ["J", "J", "J"]
        none = _run(alkis, None, [np.nan] * 3, tables)
        assert set(none[cols.CONSTRUCTION_CLASS]) == {proc.DEFAULT_AGE_CLASS}

    def test_annexes_without_address_are_left_out(self, tables):
        alkis = _alkis([
            (1000, "A 1", 0, 10.0),      # house
            (1000, "", 100, 10.0),       # residential without address
            (2000, "", 200, 20.0),       # shed of 400 m² footprint, generic function
            (3100, "", 300, 5.0),        # small building of another function without address
            (3100, "", 400, 30.0),       # hall without address: stays
        ])
        out = _run(alkis, None, ["F"] * 5, tables)
        assert out.geometry.bounds["minx"].tolist() == [0.0, 400.0]

    def test_not_energetically_relevant_functions_are_left_out(self, tables):
        functions, _ = tables
        irrelevant = functions.loc[pd.to_numeric(functions["energetisch_relevant"], errors="coerce") == 0, "Funktion"]
        alkis = _alkis([(1000, "A 1", 0, 10.0), (int(irrelevant.iloc[0]), "B 1", 100, 10.0)])
        assert len(_run(alkis, None, ["F", "F"], tables)) == 1

    def test_no_relevant_building_raises(self, tables):
        with pytest.raises(ValueError, match="energetisch relevanter"):
            _run(_alkis([(1000, "", 0, 5.0)]), None, ["F"], tables)
