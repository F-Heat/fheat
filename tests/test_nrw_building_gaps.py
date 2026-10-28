"""Tests for fheat_nrw.building_gaps: residential ALKIS buildings missing in WBM-NRW."""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

from fheat_core import columns as cols
from fheat_core.schemas import BuildingsSchema
from fheat_nrw import building_gaps as gaps_mod
from fheat_nrw.adapter.data_adapter import NRWDataAdapter
from fheat_nrw.processing import DATA_SOURCE, SOURCE_DATASET, process_buildings

CRS = "EPSG:25832"
KEY = "05554068"


def _alkis(rows):
    """ALKIS buildings: (oid, function code, municipality key, geometry)."""
    return gpd.GeoDataFrame(
        {
            "lagebeztxt": [f"Weg {i}" for i in range(len(rows))],
            "oid": [r[0] for r in rows],
            "gfkzshh": [r[1] for r in rows],
            "funktion": ["Wohngebäude"] * len(rows),
            "gmdschl": [r[2] for r in rows],
        },
        geometry=[r[3] for r in rows],
        crs=CRS,
    )


def _homes(n_per_class=40):
    """WBM-NRW residential buildings: EFH of 1970, new EFH and GMFH (2 storeys), new MFH (3 storeys)."""
    rows = []
    for i in range(n_per_class):
        x = i * 20.0
        rows.append(("EFH_1970", 1, 4.5, 70.0, 140.0, box(x, 0, x + 10, 10)))
        rows.append(("EFH_2022", 2, 8.5, 140.0, 60.0, box(x, 100, x + 10, 110)))
        rows.append(("MFH_2022", 3, 11.5, 420.0, 50.0, box(x, 200, x + 15, 215)))
        rows.append(("GMFH_2022", 2, 8.5, 900.0, 45.0, box(x, 300, x + 18, 318)))
    return gpd.GeoDataFrame(
        {
            "GEBAEUDETY": [r[0] for r in rows],
            "WG_NWG": "WG",
            "STKW": [r[1] for r in rows],
            "NF": [r[3] for r in rows],
            "RW_WW_spez": [r[4] for r in rows],
            "RW_WW": [r[3] * r[4] for r in rows],
        },
        geometry=[r[5] for r in rows],
        crs=CRS,
    )


def _lod2_for(homes):
    """LoD2 footprints of the WBM-NRW buildings, 1 m above their storey heights."""
    height = homes["GEBAEUDETY"].map({"EFH_1970": 4.5, "EFH_2022": 8.5, "MFH_2022": 11.5, "GMFH_2022": 8.5})
    return gpd.GeoDataFrame(
        {"lod2_id": [f"WBM{i:013d}" for i in range(len(homes))], "height": height.to_numpy()},
        geometry=homes.geometry.to_numpy(),
        crs=CRS,
    )


class TestResidentialGaps:
    def test_only_residential_buildings_of_the_municipality_without_wbm_building(self):
        raw = gpd.GeoDataFrame({"RW_WW": [1.0]}, geometry=[box(0, 0, 10, 10)], crs=CRS)
        alkis = _alkis([
            ("DENW_in_wbm_000BL", "31001_1000", KEY, box(1, 1, 9, 9)),
            ("DENW_new_house0BL", "31001_1000", KEY, box(50, 0, 60, 10)),
            ("DENW_mixed_use0BL", "31001_1100", KEY, box(70, 0, 80, 10)),
            ("DENW_garden_hs0BL", "31001_1310", KEY, box(90, 0, 95, 5)),
            ("DENW_garage_000BL", "31001_2460", KEY, box(100, 0, 105, 5)),
            ("DENW_carport_00BL", "51009_1611", KEY, box(110, 0, 115, 5)),
            ("DENW_neighbour0BL", "31001_1000", "05554064", box(130, 0, 140, 10)),
        ])
        out = gaps_mod.residential_gaps(alkis, raw, KEY.lstrip("0"), "RW_WW")
        assert out["oid"].tolist() == ["DENW_new_house0BL", "DENW_mixed_use0BL"]

    def test_annexes_of_houses_in_wbm_are_not_added(self):
        # a house and a garage (no heat demand) in WBM-NRW
        raw = gpd.GeoDataFrame({"RW_WW": [9000.0, 0.0]}, geometry=[box(0, 0, 10, 10), box(40, 0, 45, 5)], crs=CRS)
        alkis = _alkis([
            ("DENW_annex_0000BL", "31001_1000", KEY, box(10, 2, 14, 8)),     # touches the house
            ("DENW_next_door0BL", "31001_1000", KEY, box(10, -10, 20, 0)),  # touches it too, own address
            ("DENW_by_garage0BL", "31001_1000", KEY, box(45, 0, 55, 10)),   # touches the garage only
            ("DENW_no_number0BL", "31001_1000", KEY, box(70, 0, 80, 10)),   # free-standing
        ])
        alkis.loc[[0, 2, 3], "lagebeztxt"] = [None, "", " "]
        out = gaps_mod.residential_gaps(alkis, raw, KEY, "RW_WW")
        assert out["oid"].tolist() == ["DENW_next_door0BL", "DENW_by_garage0BL", "DENW_no_number0BL"]


class TestLod2:
    def test_tiles_of_the_points(self):
        geoms = gpd.GeoSeries([box(349800, 5766300, 349810, 5766310), box(350500, 5766100, 350510, 5766110)], crs=CRS)
        assert gaps_mod.lod2_tiles(geoms) == ["LoD2_32_349_5766_1_NW.gml", "LoD2_32_350_5766_1_NW.gml"]

    def test_reads_id_highest_height_and_footprint(self, tmp_path):
        ring = "0 0 30 10 0 30 10 8 30 0 8 30 0 0 30"
        path = tmp_path / "tile.gml"
        path.write_text(
            '<core:CityModel xmlns:core="http://www.opengis.net/citygml/1.0" '
            'xmlns:bldg="http://www.opengis.net/citygml/building/1.0" xmlns:gml="http://www.opengis.net/gml">'
            '<core:cityObjectMember><bldg:Building gml:id="DENW50AL0001ABCD">'
            "<bldg:measuredHeight>7.5</bldg:measuredHeight>"
            "<bldg:consistsOfBuildingPart><bldg:BuildingPart><bldg:measuredHeight>9.25</bldg:measuredHeight>"
            "</bldg:BuildingPart></bldg:consistsOfBuildingPart>"
            "<bldg:boundedBy><bldg:GroundSurface><bldg:lod2MultiSurface><gml:MultiSurface><gml:surfaceMember>"
            f"<gml:Polygon><gml:exterior><gml:LinearRing><gml:posList>{ring}</gml:posList>"
            "</gml:LinearRing></gml:exterior></gml:Polygon>"
            "</gml:surfaceMember></gml:MultiSurface></bldg:lod2MultiSurface></bldg:GroundSurface></bldg:boundedBy>"
            "</bldg:Building></core:cityObjectMember></core:CityModel>",
            encoding="utf-8",
        )
        out = gaps_mod.read_lod2(path)
        assert out["lod2_id"].tolist() == ["DENW50AL0001ABCD"]
        assert out["height"].iloc[0] == 9.25
        assert out.geometry.iloc[0].area == pytest.approx(80.0)

    def test_storeys_learned_per_metre_and_nearest_metre_used(self):
        homes = _homes()
        table = gaps_mod.storeys_per_height(homes, _lod2_for(homes))
        assert table.to_dict() == {4: 1, 8: 2, 11: 3}
        heights = pd.Series([4.9, 9.4, 30.0, np.nan])
        out = gaps_mod._storeys(heights, table)
        assert out.iloc[:3].tolist() == [1.0, 2.0, 3.0]
        assert np.isnan(out.iloc[3])

    def test_too_few_buildings_in_lod2_learn_nothing(self):
        homes = _homes(n_per_class=5)
        assert gaps_mod.storeys_per_height(homes, _lod2_for(homes)) is None


class TestEstimateGaps:
    def _gaps(self):
        return _alkis([
            ("DENW50AL0001LOD2BL", "31001_1000", KEY, box(0, 500, 10, 510)),   # 100 m², LoD2 8.7 m
            ("DENW50AL0001NONEBL", "31001_1000", KEY, box(20, 500, 30, 510)),  # 100 m², no height
            ("DENW50AL0001HUGEBL", "31001_1000", KEY, box(40, 500, 70, 530)),  # 900 m², no height
            ("DENW50AL0001MIDDBL", "31001_1000", KEY, box(80, 500, 95, 515)),  # 225 m², no height
        ])

    def test_floor_area_type_heat_and_source_like_wbm(self):
        homes = _homes()
        lod2 = pd.concat([
            _lod2_for(homes),
            gpd.GeoDataFrame({"lod2_id": ["DENW50AL0001LOD2"], "height": [8.7]}, geometry=[box(0, 500, 10, 510)], crs=CRS),
        ], ignore_index=True)
        out = gaps_mod.estimate_gaps(self._gaps(), homes, "RW_WW", gpd.GeoDataFrame(lod2, crs=CRS))

        # storeys: 8.7 m → 2 (learned); without height the median of the new buildings (2, 3 and 2 → 2)
        assert out["STKW"].tolist() == [2.0, 2.0, 2.0, 2.0]
        assert out[DATA_SOURCE].tolist() == [gaps_mod.SOURCE_LOD2] + [gaps_mod.SOURCE_ASSUMED] * 3
        assert out["NF"].tolist() == pytest.approx([140.0, 140.0, 1260.0, 315.0])
        # EFH up to the largest EFH floor area (140 m²), MFH up to the largest MFH one (420 m²), above GMFH
        assert out["GEBAEUDETY"].tolist() == ["EFH_2022", "EFH_2022", "GMFH_2022", "MFH_2022"]
        assert out["RW_WW"].tolist() == pytest.approx([140.0 * 60.0, 140.0 * 60.0, 1260.0 * 45.0, 315.0 * 50.0])
        assert out["Flurstueck"].tolist() == self._gaps()["oid"].tolist()

    def test_without_lod2_all_storeys_are_assumed(self):
        out = gaps_mod.estimate_gaps(self._gaps(), _homes(), "RW_WW", None)
        assert (out[DATA_SOURCE] == gaps_mod.SOURCE_ASSUMED).all()
        assert out["Hoehe"].isna().all()

    def test_without_age_classes_nothing_is_estimated(self):
        homes = _homes().assign(GEBAEUDETY="0")
        assert gaps_mod.estimate_gaps(self._gaps(), homes, "RW_WW", None).empty


class TestProcessing:
    def test_added_building_is_new_kept_apart_and_marked(self):
        db, wg = NRWDataAdapter(municipality_name="Vreden")._load_building_info()
        common = {"citygml_fu": "31001_1010", "WG_NWG": "WG", "Fortschrei": "1"}
        wbm = gpd.GeoDataFrame(
            {**common, "GEBAEUDETY": ["EFH_1970"], "Flurstueck": ["1"], "NF": [100.0], "RW_WW": [14000.0]},
            geometry=[box(0, 0, 10, 10)], crs=CRS,
        )
        homes = _homes()
        added = gaps_mod.estimate_gaps(
            _alkis([("DENW50AL0001NEWHBL", "31001_1000", KEY, box(10, 0, 20, 10))]), homes, "RW_WW", None
        )
        raw = gpd.GeoDataFrame(pd.concat([wbm, added], ignore_index=True), crs=CRS)
        parcels = gpd.GeoDataFrame(
            {"nationalCadastralReference": ["055540001"], "validFrom": ["1970-01-01"]},
            geometry=[box(-5, -5, 25, 15)], crs=CRS,
        )
        out = process_buildings(raw, parcels, db, wg, "RW_WW")
        BuildingsSchema.validate(out)

        # touching, but the added building has its own key and stays apart
        assert len(out) == 2
        by_source = out.set_index(cols.DATA_SOURCE)
        assert by_source.loc[SOURCE_DATASET, cols.CONSTRUCTION_CLASS] == "F"
        new = by_source.loc[gaps_mod.SOURCE_ASSUMED]
        # the parcel is of 1970, the added building gets the newest class
        assert new[cols.CONSTRUCTION_CLASS] == "L"
        expected = 140.0 * wg.loc[wg["Baualtersklasse"] == "L", "waerme_efh_kwh_m2a"].iloc[0]
        assert new[cols.HEAT_DEMAND_CALCULATED] == pytest.approx(expected)
        assert new[cols.HEAT_DEMAND_DATASET] == pytest.approx(140.0 * 60.0)
