"""XWaermeplan as GeoPackage: F|Heat exchange format, NOT normative.

There is no official GeoPackage schema for XWaermeplan (docs/xwaermeplan/
abgleich.md, 4.). The layout follows the relational DDL of the XLeitstelle
(``implementierung/postgres/relational``), see kodierung.md, 5.:

* one table per concrete feature type, lower case (``wp_waermelinie``);
  variable geometry (point or area) is split into ``<table>_punkt`` and
  ``<table>_flaeche`` because QGIS handles mixed geometry tables badly
* column ``uuid`` = feature id; attribute columns in lower case
* enumeration -> ``<attr>_fkcl`` with the code; one code list table per
  enumeration (``wp_status``: code, name, label)
* reference -> ``<attr>_fk`` with the UUID of the target (the DDL uses its
  serial ids); list-valued references with a reverse role (``WP_Plan.bereich``)
  are not stored, the reverse side holds them
* data types and multiple values -> child table ``<table>_<attr>`` with
  ``_id`` and ``<parent table>_id`` (UUIDs)
* dates as ISO text, measures as numbers in the model unit (unit in the alias)
* table ``xwp_metadaten`` (version, namespace, format note); field aliases and
  descriptions in ``gpkg_data_columns``

GML stays the normative format.
"""
from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from shapely.geometry import MultiLineString, MultiPoint, MultiPolygon
from shapely.geometry.base import BaseGeometry

from fheat_core.xwp.document import XwpPlanDocument
from fheat_core.xwp.model.base import (
    BOOLEAN,
    DATATYPE,
    DATE,
    ENUM,
    GEOMETRY,
    INTEGER,
    MEASURE,
    MULTI_CURVE,
    MULTI_SURFACE,
    REF,
    VARIABLE,
    AttrInfo,
    Measure,
    XwpObject,
    model_module,
    values,
)

FORMAT_NOTE = "F|Heat-Austauschformat für XWärmeplan, nicht normativ; normativ ist die GML-Kodierung."
METADATA_TABLE = "xwp_metadaten"
POINT_SUFFIX, AREA_SUFFIX = "_punkt", "_flaeche"
_DTYPES = {"str": object, "float": "float64", "int": "Int64", "bool": "boolean"}
_GEOMETRY_TYPES = {MULTI_SURFACE: "MultiPolygon", MULTI_CURVE: "MultiLineString"}


@dataclass
class Column:
    name: str
    dtype: str  # str, float, int, bool
    alias: str
    doc: str = ""


@dataclass
class TableDef:
    """One GeoPackage table; ``geometry_type`` None = table without geometry."""

    name: str
    columns: list[Column]
    identifier: str
    description: str = ""
    geometry_name: str | None = None
    geometry_type: str | None = None
    feature_type: str | None = None  # main tables: the XWaermeplan class
    parent: str | None = None  # child tables: the parent table
    attr: AttrInfo | None = None  # child tables: the attribute they hold
    rows: list[dict[str, Any]] = field(default_factory=list)


# --------------------------------------------------------------------------
# schema


def table_base(class_name: str) -> str:
    return class_name.lower()


def gpkg_schema(model) -> list[TableDef]:
    """All tables for a model version: feature tables, child tables, code lists (without rows)."""
    tables: list[TableDef] = []
    for name in model.FEATURE_TYPES:
        tables.extend(_feature_tables(model.CLASSES[name], model))
    for enum_name, enum_cls in model.ENUMS.items():
        tables.append(TableDef(
            name=table_base(enum_name),
            columns=[Column("code", "str", "Code"), Column("name", "str", "Name"), Column("label", "str", "Bezeichnung")],
            identifier=enum_name,
            description=f"Codeliste {enum_name}",
        ))
    tables.append(TableDef(
        name=METADATA_TABLE,
        columns=[Column("schluessel", "str", "Schlüssel"), Column("wert", "str", "Wert")],
        identifier="XWärmeplan-Metadaten",
        description=FORMAT_NOTE,
    ))
    names = [t.name for t in tables]
    if len(names) != len(set(names)):
        raise ValueError(f"table names collide: {sorted(n for n in names if names.count(n) > 1)}")
    return tables


def _feature_tables(cls, model) -> list[TableDef]:
    info = cls.__xwp__
    geom = info.geometry_attr
    base = table_base(info.name)
    children: list[TableDef] = []
    columns = [Column("uuid", "str", "id", "UUID des Objekts (gml:id / JSON-FG id)")]
    columns += _columns(info.attrs, base, children, model, skip=geom)
    variants = [(base, _GEOMETRY_TYPES.get(geom.type) if geom else None)]
    if geom is not None and geom.type == VARIABLE:
        variants = [(base + AREA_SUFFIX, "MultiPolygon"), (base + POINT_SUFFIX, "MultiPoint")]
    mains = [
        TableDef(
            name=name, columns=list(columns), identifier=info.name + (f" ({name.rsplit('_', 1)[1]})" if name != base else ""),
            description=info.doc, geometry_name=geom.name.lower() if geom else None,
            geometry_type=gtype, feature_type=info.name,
        )
        for name, gtype in variants
    ]
    return mains + children


def _columns(attrs, table: str, children: list[TableDef], model, skip: AttrInfo | None = None) -> list[Column]:
    cols: list[Column] = []
    for a in attrs:
        if a is skip:
            continue
        if a.kind == REF and a.many and a.reverse:
            continue  # stored on the reverse side
        if a.kind == GEOMETRY:
            raise NotImplementedError(f"{a.owner}.{a.name}: a second geometry has no GeoPackage column")
        if a.many or a.kind == DATATYPE:
            children.extend(_child_tables(a, table, model))
            continue
        cols.append(value_column(a))
    names = [c.name for c in cols]
    if len(names) != len(set(names)):
        raise ValueError(f"{table}: column names collide after lower-casing: {names}")
    return cols


def value_column(a: AttrInfo) -> Column:
    label = a.name + (f" [{a.uom}]" if a.uom else "")
    if a.kind == ENUM:
        return Column(f"{a.name.lower()}_fkcl", "str", f"{label} ({a.type})", a.doc)
    if a.kind == REF:
        return Column(f"{a.name.lower()}_fk", "str", f"{label} (UUID {a.type})", a.doc)
    dtype = {MEASURE: "float", INTEGER: "int", BOOLEAN: "bool"}.get(a.kind, "str")
    return Column(a.name.lower(), dtype, label, a.doc)


def _child_tables(a: AttrInfo, parent: str, model) -> list[TableDef]:
    name = f"{parent}_{a.name.lower()}"
    children: list[TableDef] = []
    columns = [Column("_id", "str", "id", "UUID der Zeile"), Column(f"{parent}_id", "str", f"{parent} (UUID)", "Übergeordnete Zeile")]
    if a.kind == DATATYPE:
        columns += _columns(model.CLASSES[a.type].__xwp__.attrs, name, children, model)
    else:
        columns.append(value_column(a))
    return [TableDef(name=name, columns=columns, identifier=f"{parent}.{a.name}", description=a.doc,
                     parent=parent, attr=a)] + children


# --------------------------------------------------------------------------
# rows


def to_tables(doc: XwpPlanDocument, *, include_empty: bool = False, check: bool = True) -> list[TableDef]:
    """The tables with rows; without ``include_empty`` only tables that have rows (code lists always)."""
    if check:
        doc.check()
    if not doc.features:
        raise ValueError("the document has no features")
    model = model_module(doc.features[0])
    tables = gpkg_schema(model)
    by_name = {t.name: t for t in tables}
    for f in doc.ordered():
        info = type(f).__xwp__
        geom_attr = info.geometry_attr
        geom = getattr(f, geom_attr.name) if geom_attr else None
        name = table_base(info.name)
        if geom_attr is not None and geom_attr.type == VARIABLE:
            name += POINT_SUFFIX if geom is not None and geom.geom_type in ("Point", "MultiPoint") else AREA_SUFFIX
        table = by_name[name]
        row: dict[str, Any] = {"uuid": f.id}
        _fill(row, f, info.attrs, table_base(info.name), f.id, by_name, skip=geom_attr)
        if geom_attr is not None:
            row["geometry"] = _multi(geom) if geom is not None else None
        table.rows.append(row)
    for enum_name, enum_cls in model.ENUMS.items():
        by_name[table_base(enum_name)].rows = [
            {"code": e.code, "name": e.name, "label": e.label} for e in enum_cls
        ]
    by_name[METADATA_TABLE].rows = [
        {"schluessel": "xwp_version", "wert": model.VERSION},
        {"schluessel": "xwp_namespace", "wert": model.NAMESPACE},
        {"schluessel": "dokument_id", "wert": doc.id},
        {"schluessel": "koordinatensystem", "wert": "EPSG:25832"},
        {"schluessel": "hinweis", "wert": FORMAT_NOTE},
    ]
    if include_empty:
        return tables
    return [t for t in tables if t.rows]


def _fill(row: dict, obj: XwpObject, attrs, table: str, row_id: str, by_name: dict[str, TableDef],
          skip: AttrInfo | None = None) -> None:
    for a in attrs:
        if a is skip or (a.kind == REF and a.many and a.reverse):
            continue
        vals = values(obj, a)
        if a.many or a.kind == DATATYPE:
            child = by_name[f"{table}_{a.name.lower()}"]
            for i, v in enumerate(vals):
                child_id = str(uuid.uuid5(uuid.UUID(row_id), f"{a.name}[{i}]"))
                crow: dict[str, Any] = {"_id": child_id, f"{table}_id": row_id}
                if a.kind == DATATYPE:
                    _fill(crow, v, type(v).__xwp__.attrs, child.name, child_id, by_name)
                else:
                    crow[value_column(a).name] = _scalar(a, v)
                child.rows.append(crow)
            continue
        row[value_column(a).name] = _scalar(a, vals[0]) if vals else None


def _scalar(a: AttrInfo, v) -> Any:
    if a.kind == MEASURE:
        return float(v.value if isinstance(v, Measure) else v)
    if a.kind == ENUM:
        return v.code
    if a.kind == REF:
        return v.id
    if a.kind == DATE:
        return v.isoformat()
    if a.kind == INTEGER:
        return int(v)
    if a.kind == BOOLEAN:
        return bool(v)
    return v


def _multi(geom: BaseGeometry) -> BaseGeometry:
    t = geom.geom_type
    if t == "Polygon":
        return MultiPolygon([geom])
    if t == "LineString":
        return MultiLineString([geom])
    if t == "Point":
        return MultiPoint([geom])
    return geom


# --------------------------------------------------------------------------
# writing


def write_gpkg(doc: XwpPlanDocument, path: str | Path, *, include_empty: bool = False, check: bool = True) -> Path:
    """Write the plan as GeoPackage (an existing file is replaced)."""
    import geopandas as gpd
    import pandas as pd
    import pyogrio

    path = Path(path)
    tables = to_tables(doc, include_empty=include_empty, check=check)
    if path.exists():
        path.unlink()
    for t in tables:
        frame = pd.DataFrame(
            {c.name: pd.Series([r.get(c.name) for r in t.rows], dtype=_DTYPES[c.dtype]) for c in t.columns}
        )
        options = {"IDENTIFIER": t.identifier, "DESCRIPTION": (t.description or "")[:1000]}
        if t.geometry_type:
            frame = gpd.GeoDataFrame(frame, geometry=gpd.GeoSeries([r.get("geometry") for r in t.rows], crs=25832))
            options["GEOMETRY_NAME"] = t.geometry_name
            pyogrio.write_dataframe(frame, path, layer=t.name, driver="GPKG", geometry_type=t.geometry_type,
                                    layer_options=options, append=path.exists())
        else:
            pyogrio.write_dataframe(frame, path, layer=t.name, driver="GPKG", layer_options=options,
                                    append=path.exists())
    _write_aliases(path, tables)
    return path


def _write_aliases(path: Path, tables: list[TableDef]) -> None:
    """Field aliases and descriptions via the GeoPackage schema extension (read by GDAL and QGIS)."""
    con = sqlite3.connect(path)
    try:
        con.execute(
            "CREATE TABLE IF NOT EXISTS gpkg_data_columns (table_name TEXT NOT NULL, column_name TEXT NOT NULL,"
            " name TEXT, title TEXT, description TEXT, mime_type TEXT, constraint_name TEXT,"
            " CONSTRAINT pk_gdc PRIMARY KEY (table_name, column_name), CONSTRAINT gdc_tn UNIQUE (table_name, name))"
        )
        con.execute(
            "CREATE TABLE IF NOT EXISTS gpkg_extensions (table_name TEXT, column_name TEXT, extension_name TEXT NOT NULL,"
            " definition TEXT NOT NULL, scope TEXT NOT NULL,"
            " CONSTRAINT ge_tce UNIQUE (table_name, column_name, extension_name))"
        )
        con.execute(
            "INSERT OR IGNORE INTO gpkg_extensions VALUES ('gpkg_data_columns', NULL, 'gpkg_schema',"
            " 'http://www.geopackage.org/spec/#extension_schema', 'read-write')"
        )
        con.executemany(
            "INSERT OR REPLACE INTO gpkg_data_columns (table_name, column_name, name, title, description)"
            " VALUES (?, ?, ?, ?, ?)",
            [(t.name, c.name, c.alias, c.alias, c.doc) for t in tables for c in t.columns],
        )
        con.commit()
    finally:
        con.close()


__all__ = ["Column", "TableDef", "gpkg_schema", "to_tables", "write_gpkg"]
