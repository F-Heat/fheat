"""XWaermeplan GeoPackage writer (phase 4): every class is written and reads back."""
from __future__ import annotations

import sqlite3

import pytest

pyogrio = pytest.importorskip("pyogrio")

from fheat_core.xwp.encode.gpkg import METADATA_TABLE, gpkg_schema, to_tables, write_gpkg  # noqa: E402
from fheat_core.xwp.model import v0_9_6 as m  # noqa: E402
from tests.xwp_synth import document, document_all  # noqa: E402

VARIABLE = [n for n in m.FEATURE_TYPES if m.CLASSES[n].__xwp__.geometry_attr
            and m.CLASSES[n].__xwp__.geometry_attr.type == "Geometry"]


def _read_back(path, tables):
    layers = {name for name, _ in pyogrio.list_layers(path)}
    assert layers == {t.name for t in tables}
    for t in tables:
        frame = pyogrio.read_dataframe(path, layer=t.name, read_geometry=t.geometry_type is not None)
        expected = [c.name for c in t.columns] + (["geometry"] if t.geometry_type else [])
        assert list(frame.columns) == expected, t.name
        assert len(frame) == len(t.rows), t.name
        if t.geometry_type:
            info = pyogrio.read_info(path, layer=t.name)
            assert info["geometry_type"] == t.geometry_type, t.name
            assert info["crs"] == "EPSG:25832", t.name


@pytest.fixture(scope="module", params=[False, True], ids=["minimal", "maximal"])
def written(request, tmp_path_factory):
    """All 29 feature types in one file (writing a GeoPackage costs about a second)."""
    doc, objects = document_all(m, request.param)
    path = write_gpkg(doc, tmp_path_factory.mktemp("gpkg") / "plan.gpkg")
    return request.param, path, to_tables(doc), objects


def test_every_table_reads_back(written):
    _, path, tables, _ = written
    _read_back(path, tables)


@pytest.mark.parametrize("feature_type", m.FEATURE_TYPES)
def test_every_feature_type_is_stored(written, feature_type):
    maximal, _, tables, objects = written
    obj = objects[feature_type]
    main = next(t for t in tables if t.feature_type == feature_type and any(r["uuid"] == obj.id for r in t.rows))
    if maximal:  # every attribute has a column or a child table with rows of this object
        info = type(obj).__xwp__
        stored = {c.name for c in main.columns}
        base = feature_type.lower()
        for a in info.attrs:
            if a is info.geometry_attr or (a.kind == "ref" and a.many and a.reverse):
                continue
            column = any(n in stored for n in (a.name.lower(), f"{a.name.lower()}_fkcl", f"{a.name.lower()}_fk"))
            child = any(t.name == f"{base}_{a.name.lower()}" and any(r[f"{base}_id"] == obj.id for r in t.rows)
                        for t in tables)
            assert column or child, f"{feature_type}.{a.name}"


@pytest.mark.parametrize("feature_type", VARIABLE)
def test_variable_geometry_is_split_by_type(tmp_path, feature_type):
    doc, obj, _ = document(m, feature_type, False, variable_as="point")
    path = write_gpkg(doc, tmp_path / "plan.gpkg")
    base = feature_type.lower()
    frame = pyogrio.read_dataframe(path, layer=base + "_punkt")
    assert list(frame["uuid"]) == [obj.id]
    assert base + "_flaeche" not in {n for n, _ in pyogrio.list_layers(path)}


def test_template_with_all_tables(tmp_path):
    doc, _, _ = document(m, "WP_Waermelinie", False)
    path = write_gpkg(doc, tmp_path / "vorlage.gpkg", include_empty=True)
    tables = to_tables(doc, include_empty=True)
    assert len(tables) == len(gpkg_schema(m))
    _read_back(path, tables)


def test_layout_follows_the_relational_ddl(tmp_path):
    doc, plan, _ = document(m, "WP_Plan", True)
    path = write_gpkg(doc, tmp_path / "plan.gpkg")
    bereich = doc.of_type("WP_Bereich")[0]
    frame = pyogrio.read_dataframe(path, layer="wp_bereich", read_geometry=False)
    assert frame.loc[0, "gehoertzuplan_fk"] == plan.id
    assert "bereich_fk" not in pyogrio.read_info(path, layer="wp_plan")["fields"]  # reverse side holds it
    stelle = pyogrio.read_dataframe(path, layer="wp_plan_planungsverantwortlichestelle")
    assert list(stelle["wp_plan_id"]) == [plan.id]
    plan_row = pyogrio.read_dataframe(path, layer="wp_plan", read_geometry=False)
    assert plan_row.loc[0, "verfahrensart_fkcl"] in {e.code for e in m.WP_VerfahrenArt}
    assert pyogrio.read_info(path, layer="wp_plan")["geometry_name"] == "raeumlichergeltungsbereich"
    assert bereich.id in set(pyogrio.read_dataframe(path, layer="wp_bereich", read_geometry=False)["uuid"])


def test_code_lists_metadata_and_aliases(tmp_path):
    doc, _, _ = document(m, "WP_Waermelinie", True)
    path = write_gpkg(doc, tmp_path / "plan.gpkg")
    status = pyogrio.read_dataframe(path, layer="wp_status")
    assert list(status["code"]) == [e.code for e in m.WP_Status]
    meta = dict(pyogrio.read_dataframe(path, layer=METADATA_TABLE).values.tolist())
    assert meta["xwp_version"] == "0.9.6" and "nicht normativ" in meta["hinweis"]
    con = sqlite3.connect(path)
    try:
        alias = con.execute(
            "SELECT name, description FROM gpkg_data_columns WHERE table_name='wp_waermelinie' AND column_name='waermemenge'"
        ).fetchone()
        ident = con.execute("SELECT identifier FROM gpkg_contents WHERE table_name='wp_waermelinie'").fetchone()
    finally:
        con.close()
    assert alias[0] == "waermeMenge [MWh/a]" and alias[1]
    assert ident == ("WP_Waermelinie",)


def test_existing_file_is_replaced(tmp_path):
    doc, _, _ = document(m, "WP_Waermelinie", False)
    path = tmp_path / "plan.gpkg"
    write_gpkg(doc, path)
    write_gpkg(doc, path)
    assert len(pyogrio.read_dataframe(path, layer="wp_waermelinie")) == 1
