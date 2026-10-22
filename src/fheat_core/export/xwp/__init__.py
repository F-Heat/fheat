"""XWaermeplan export of the F|Heat results (optional extra ``[xwp]``).

A one-way adapter on xplan-tools, the library of the XLeitstelle: the
mappers turn heat lines, networks, suitability polygons and the heated
buildings into feature records, xplan-tools builds and checks the models
and writes GML and JSON-FG. Importing this package needs no xplan-tools;
only :func:`export_xwaermeplan` does.

    from fheat_core.export.xwp import XWPExportConfig, export_xwaermeplan

    report = export_xwaermeplan(orch.state, XWPExportConfig(...), "output/waermeplan.gml")

Mapping, decisions and limits: ``docs/xwp_mapping.md``.
"""
from fheat_core.export.xwp.config import XWPExportConfig
from fheat_core.export.xwp.export import export_xwaermeplan
from fheat_core.export.xwp.mappers import NetworkResult
from fheat_core.export.xwp.mapping import SCHEMA_VERSION, regional_key
from fheat_core.export.xwp.report import ExportReport, Issue

__all__ = [
    "SCHEMA_VERSION",
    "ExportReport",
    "Issue",
    "NetworkResult",
    "XWPExportConfig",
    "export_xwaermeplan",
    "regional_key",
]
