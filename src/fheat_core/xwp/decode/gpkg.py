"""Read a GeoPackage in the F|Heat XWaermeplan layout (own exports and supplement files)."""
from __future__ import annotations

from pathlib import Path

from fheat_core.xwp.decode.tables import from_tables
from fheat_core.xwp.model.base import Issue, XwpObject


def read_tables(path: str | Path) -> dict[str, list[dict]]:
    """All layers as rows (dicts); spatial layers carry a shapely ``geometry``."""
    import pyogrio

    tables: dict[str, list[dict]] = {}
    for name, geometry_type in pyogrio.list_layers(path):
        if str(name).startswith(("gpkg_", "rtree_")):
            continue
        frame = pyogrio.read_dataframe(path, layer=name, read_geometry=geometry_type is not None)
        if geometry_type is not None:
            crs = frame.crs
            if crs is not None and crs.to_epsg() not in (25832, None):
                frame = frame.to_crs(25832)
        rows = frame.to_dict("records")
        tables[str(name)] = rows
    return tables


def read_gpkg(path: str | Path, model=None) -> tuple[list[XwpObject], list[Issue]]:
    """Features and findings of a GeoPackage written by :func:`~fheat_core.xwp.encode.gpkg.write_gpkg`
    or filled in from the supplement template."""
    if model is None:
        from fheat_core.xwp.model import current as model
    return from_tables(read_tables(path), model)
