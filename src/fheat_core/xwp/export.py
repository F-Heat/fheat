"""Write a complete XWaermeplan export: GML, JSON-FG, GeoPackage and a check report.

Used by :meth:`fheat_core.orchestrator.FHeatOrchestrator.save_xwp` and the
command line (``python -m fheat_core.xwp``). The files are written even
when the plan still has gaps (e.g. no decision date yet): the check report
says what is missing, so a draft can be reviewed before it is complete.
"""
from __future__ import annotations

import datetime
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Sequence

from fheat_core.config import XwpConfig
from fheat_core.xwp.document import XwpPlanDocument
from fheat_core.xwp.mapping import NetworkInput, build_plan
from fheat_core.xwp.mapping.bestand import MappingNotes
from fheat_core.xwp.model.base import ERROR, model_module
from fheat_core.xwp.supplement import Supplement, read_supplement, write_template

BASENAME = "xwaermeplan"
TEMPLATE_BASENAME = "xwp_ergaenzung"
FILE_KEYS = {"gml": "xwp_gml", "jsonfg": "xwp_jsonfg", "gpkg": "xwp_gpkg"}
SUFFIXES = {"gml": ".gml", "jsonfg": ".json", "gpkg": ".gpkg"}


def load_supplement(supplement) -> Supplement | None:
    """A Supplement from a Supplement, one path (.gpkg/.xlsx) or several paths."""
    if supplement is None or isinstance(supplement, Supplement):
        return supplement
    paths = [supplement] if isinstance(supplement, (str, Path)) else list(supplement)
    gpkg = next((Path(p) for p in paths if str(p).lower().endswith(".gpkg")), None)
    xlsx = next((Path(p) for p in paths if str(p).lower().endswith((".xlsx", ".xlsm"))), None)
    unknown = [p for p in paths if Path(p) not in (gpkg, xlsx)]
    if unknown:
        raise ValueError(f"Ergänzungsdateien müssen .gpkg oder .xlsx sein: {unknown}")
    return read_supplement(gpkg=gpkg, xlsx=xlsx)


def export_xwp(
    out_dir: str | Path,
    *,
    buildings,
    wld,
    config: XwpConfig,
    parcels=None,
    streets=None,
    boundary=None,
    data_year: int | None = None,
    networks: Sequence[NetworkInput] = (),
    supplement=None,
    basename: str = BASENAME,
) -> dict[str, Path]:
    """Build the plan and write the formats of ``config.formats`` plus ``<basename>_pruefbericht.json``."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    doc, notes = build_plan(buildings, wld, config, networks=networks, parcels=parcels, streets=streets,
                            boundary=boundary, data_year=data_year, supplement=load_supplement(supplement))
    files: dict[str, Path] = {}
    schema_findings: dict[str, list[str]] = {}
    for fmt in config.formats:
        path = out_dir / f"{basename}{SUFFIXES[fmt]}"
        if fmt == "gml":
            from fheat_core.xwp.encode.gml import validate_gml, write_gml

            write_gml(doc, path, precision=config.precision, check=False)
            schema_findings["xsd"] = validate_gml(path)
        elif fmt == "jsonfg":
            from fheat_core.xwp.encode.jsonfg import write_jsonfg

            write_jsonfg(doc, path, precision=config.precision, check=False)
            schema_findings["json_schema"] = _validate_jsonfg_if_possible(path)
        else:
            from fheat_core.xwp.encode.gpkg import write_gpkg

            write_gpkg(doc, path, check=False)
        files[FILE_KEYS[fmt]] = path
    report = build_report(doc, notes, files, schema_findings)
    report_path = out_dir / f"{basename}_pruefbericht.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    files["xwp_report"] = report_path
    return files


def export_template(
    out_dir: str | Path,
    *,
    buildings,
    wld,
    config: XwpConfig,
    parcels=None,
    streets=None,
    boundary=None,
    data_year: int | None = None,
    networks: Sequence[NetworkInput] = (),
    basename: str = TEMPLATE_BASENAME,
) -> dict[str, Path]:
    """Write the supplement template (GeoPackage, and Excel when openpyxl is installed)."""
    import importlib.util

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    doc, notes = build_plan(buildings, wld, config, networks=networks, parcels=parcels, streets=streets,
                            boundary=boundary, data_year=data_year)
    xlsx = out_dir / f"{basename}.xlsx" if importlib.util.find_spec("openpyxl") else None
    written = write_template(doc, out_dir / f"{basename}.gpkg", xlsx, notes.placeholders)
    return {f"xwp_template_{fmt}": path for fmt, path in written.items()}


def _validate_jsonfg_if_possible(path: Path) -> list[str]:
    import importlib.util

    if importlib.util.find_spec("jsonschema") is None:
        return ["nicht geprüft: jsonschema ist nicht installiert"]
    from fheat_core.xwp.encode.jsonfg import validate_jsonfg

    return validate_jsonfg(path)


# --------------------------------------------------------------------------
# check report


def coverage(doc: XwpPlanDocument, notes: MappingNotes, model=None) -> dict[str, dict]:
    """Per concrete feature type: number of objects, where they come from, missing mandatory attributes."""
    if model is None:
        model = model_module(doc.features[0]) if doc.features else None
        if model is None:
            from fheat_core.xwp.model import current as model
    issues = doc.validate()
    missing: dict[str, Counter] = defaultdict(Counter)
    for issue in issues:
        if issue.code == "missing" and "[" in issue.path:
            cls = issue.path.split("[", 1)[0]
            missing[cls][issue.path.split("]", 1)[1].lstrip(".")] += 1
    out = {}
    for name in model.FEATURE_TYPES:
        objects = [f for f in doc.features if type(f).__xwp__.name == name]
        origins = Counter(
            "ergänzt" if f.id in notes.supplement_ids else "Vorschlag" if f.id in notes.proposal_ids else "automatisch"
            for f in objects
        )
        origin = "leer" if not objects else ", ".join(sorted(origins)) if len(origins) > 1 else next(iter(origins))
        out[name] = {
            "anzahl": len(objects),
            "herkunft": origin,
            "fehlende_pflichtangaben": dict(missing.get(name, {})),
        }
    return out


def build_report(doc: XwpPlanDocument, notes: MappingNotes, files: dict[str, Path],
                 schema_findings: dict[str, Iterable[str]]) -> dict:
    """The check report: validity, findings, coverage per class, notes of the mapping."""
    model = model_module(doc.features[0]) if doc.features else None
    issues = doc.validate()
    errors = [i for i in issues if i.severity == ERROR]
    schema_errors = {k: list(v) for k, v in schema_findings.items()}
    valid = not errors and not any(v for k, v in schema_errors.items() if not (v and v[0].startswith("nicht geprüft")))
    return {
        "xwaermeplan_version": getattr(model, "VERSION", None),
        "erstellt": datetime.datetime.now().isoformat(timespec="seconds"),
        "gueltig": valid,
        "dateien": {k: Path(v).name for k, v in files.items()},
        "schema": schema_errors,
        "befunde": [
            {"pfad": i.path, "code": i.code, "meldung": i.message, "schwere": i.severity} for i in issues
        ],
        "ergaenzung": {
            "ueberschrieben": notes.supplement_overridden,
            "hinzugefuegt": notes.supplement_added,
            "nicht_uebernommen": notes.supplement_skipped,
            "offene_platzhalter": notes.supplement_open_placeholders,
            "befunde": [{"pfad": i.path, "code": i.code, "meldung": i.message} for i in notes.supplement_issues],
        },
        "abdeckung": coverage(doc, notes, model),
        "hinweise": list(notes.messages),
        "datenschutz": {
            "baubloecke_nicht_ausgegeben": notes.blocks_dropped,
            "gebaeude_darin": notes.buildings_in_dropped_blocks,
            "rasterzellen_nicht_ausgegeben": notes.raster_cells_dropped,
        },
    }


__all__ = ["build_report", "coverage", "export_template", "export_xwp", "load_supplement"]
