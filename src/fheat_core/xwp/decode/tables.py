"""Rows of the F|Heat table layout (GeoPackage, Excel) -> XWaermeplan objects.

The inverse of :mod:`fheat_core.xwp.encode.gpkg`: it reads the table
definitions of :func:`~fheat_core.xwp.encode.gpkg.gpkg_schema`, so writer and
reader cannot drift apart. Problems are reported per table and row as
:class:`~fheat_core.xwp.model.base.Issue` (German messages for the planner);
a row with an error in one cell still yields its object without that value.
"""
from __future__ import annotations

import datetime
import math
import uuid
from typing import Any, Iterable

from fheat_core.xwp.encode.gpkg import TableDef, gpkg_schema, table_base, value_column
from fheat_core.xwp.model.base import (
    BOOLEAN,
    DATATYPE,
    DATE,
    ENUM,
    INTEGER,
    MEASURE,
    REF,
    AttrInfo,
    Issue,
    Ref,
    XwpObject,
)


def is_empty(v: Any) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v)) or (isinstance(v, str) and not v.strip()) \
        or str(v) in ("<NA>", "NaT", "nan")


def from_tables(
    tables: dict[str, list[dict]],
    model,
    *,
    new_id=lambda: str(uuid.uuid4()),
) -> tuple[list[XwpObject], list[Issue]]:
    """Features from rows by table name; unknown tables and columns are reported, not fatal."""
    schema = {t.name: t for t in gpkg_schema(model)}
    issues: list[Issue] = []
    features: list[XwpObject] = []
    by_row_id: dict[tuple[str, str], XwpObject] = {}  # (table base, row id) -> object the child rows attach to
    for name in tables:
        if name not in schema:
            issues.append(Issue(name, "table", f"Tabelle {name} gehört nicht zum XWärmeplan-Schema {model.VERSION}."))
    for table in schema.values():  # schema order: a parent table comes before its children
        rows = tables.get(table.name) or []
        if not rows or table.feature_type is None and table.parent is None:
            continue  # code lists and metadata are not read
        known = {c.name for c in table.columns} | {"geometry", "fid"}
        unknown = sorted({k for r in rows for k in r} - known)
        if unknown:
            issues.append(Issue(table.name, "column", f"Unbekannte Spalten in {table.name}: {', '.join(unknown)}."))
        for i, row in enumerate(rows, start=1):
            where = f"{table.name} Zeile {i}"
            if table.feature_type is not None:
                obj = _feature(table, row, model, where, issues, new_id)
                if obj is not None:
                    features.append(obj)
                    by_row_id[(table_base(table.feature_type), obj.id)] = obj
            else:
                _child(table, row, model, where, issues, by_row_id)
    return features, issues


def _feature(table: TableDef, row: dict, model, where: str, issues: list[Issue], new_id) -> XwpObject | None:
    cls = model.CLASSES[table.feature_type]
    info = cls.__xwp__
    raw_id = row.get("uuid")
    obj = cls(id=str(raw_id).strip().lower() if not is_empty(raw_id) else new_id())
    _fill(obj, info.attrs, table, row, model, where, issues, skip=info.geometry_attr)
    geom_attr = info.geometry_attr
    if geom_attr is not None and not is_empty(row.get("geometry")):
        setattr(obj, geom_attr.name, row["geometry"])
    return obj


def _child(table: TableDef, row: dict, model, where: str, issues: list[Issue], by_row_id: dict) -> None:
    parent_id = row.get(f"{table.parent}_id")
    parent = by_row_id.get((table.parent, str(parent_id).strip().lower())) if not is_empty(parent_id) else None
    if parent is None:
        issues.append(Issue(where, "ref", f"{where}: Zeile verweist auf keine Zeile in {table.parent} ({parent_id})."))
        return
    attr: AttrInfo = table.attr
    if attr.kind == DATATYPE:
        value = model.CLASSES[attr.type]()
        _fill(value, value.__xwp__.attrs, table, row, model, where, issues)
        row_id = row.get("_id")
        if not is_empty(row_id):
            by_row_id[(table.name, str(row_id).strip().lower())] = value
    else:
        value = _convert(attr, row.get(value_column(attr).name), model, where, issues)
        if value is None:
            return
    if attr.many:
        current = getattr(parent, attr.name)
        if current is None:
            setattr(parent, attr.name, [value])
        else:
            current.append(value)
    else:
        if getattr(parent, attr.name) is not None:
            issues.append(Issue(where, "multiplicity", f"{where}: {attr.name} erlaubt nur einen Wert; weitere Zeile ignoriert."))
            return
        setattr(parent, attr.name, value)


def _fill(obj, attrs: Iterable[AttrInfo], table: TableDef, row: dict, model, where, issues, skip=None) -> None:
    for attr in attrs:
        if attr is skip or attr.many or attr.kind == DATATYPE or (attr.kind == REF and attr.many and attr.reverse):
            continue  # child tables / reverse side
        column = value_column(attr).name
        if column not in row:
            continue
        value = _convert(attr, row[column], model, where, issues)
        if value is not None:
            setattr(obj, attr.name, value)


def _convert(attr: AttrInfo, v: Any, model, where: str, issues: list[Issue]):
    if is_empty(v):
        return None
    try:
        if attr.kind == ENUM:
            code = str(v).strip()
            if code.endswith(".0"):  # a code column read as number
                code = code[:-2]
            return model.ENUMS[attr.type](code)
        if attr.kind == REF:
            return Ref(str(v).strip().lower(), None)
        if attr.kind == MEASURE:
            return float(v)
        if attr.kind == INTEGER:
            f = float(v)
            if not f.is_integer():
                raise ValueError(v)
            return int(f)
        if attr.kind == BOOLEAN:
            if isinstance(v, str):
                text = v.strip().lower()
                if text in ("true", "wahr", "ja", "1", "x"):
                    return True
                if text in ("false", "falsch", "nein", "0"):
                    return False
                raise ValueError(v)
            return bool(v)
        if attr.kind == DATE:
            if isinstance(v, datetime.datetime):
                return v.date()
            if isinstance(v, datetime.date):
                return v
            return datetime.date.fromisoformat(str(v).strip()[:10])
        return str(v).strip() if not isinstance(v, str) else v
    except (ValueError, KeyError, TypeError):
        expected = {ENUM: f"einen Code aus {attr.type}", REF: "eine UUID", MEASURE: "eine Zahl", INTEGER: "eine ganze Zahl",
                    BOOLEAN: "wahr/falsch", DATE: "ein Datum JJJJ-MM-TT"}.get(attr.kind, "Text")
        issues.append(Issue(f"{where}.{attr.name}", "type", f"{where}: {attr.name} erwartet {expected}, nicht {v!r}."))
        return None
