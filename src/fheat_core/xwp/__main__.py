"""Command line for the XWaermeplan export.

    python -m fheat_core.xwp validate xwaermeplan.gml
    python -m fheat_core.xwp template --plan plan.json --buildings buildings.gpkg --wld wld.gpkg --out ergebnis
    python -m fheat_core.xwp build    --plan plan.json --buildings buildings.gpkg --wld wld.gpkg --out ergebnis \\
        --streets streets.gpkg --parcels parcels.gpkg --network netz.gpkg,planungsgebiet.gpkg,source.gpkg \\
        --supplement ergebnis/xwp_ergaenzung.gpkg

Inputs of ``template`` and ``build`` are files written by
``FHeatOrchestrator.save_outputs`` (German or canonical column names) and a
JSON file with the plan metadata (``XwpConfig.from_dict``, see
docs/xwaermeplan). Exit code 1 when ``validate`` finds errors.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _read(path: str | None):
    if not path:
        return None
    import geopandas as gpd

    from fheat_core import columns as cols

    frame = gpd.read_file(path)
    if frame.crs is not None and frame.crs.to_epsg() != 25832:
        frame = frame.to_crs(25832)
    return cols.from_display(frame)


def _networks(specs: list[str], buildings, supply_temperature):
    from fheat_core.state import PipelineState
    from fheat_core.xwp.mapping import NetworkInput

    out = []
    for i, spec in enumerate(specs or [], start=1):
        parts = (spec.split(",") + [None, None])[:3]
        net, area, source = (_read(p) for p in parts)
        state = PipelineState(buildings_gdf=buildings, net_gdf=net, planning_area_gdf=area, source_gdf=source)
        out.append(NetworkInput(state, name=Path(parts[0]).stem, supply_temperature=supply_temperature))
    return out


def _inputs(args) -> dict:
    from fheat_core.config import XwpConfig

    config = XwpConfig.from_dict(json.loads(Path(args.plan).read_text(encoding="utf-8")))
    buildings = _read(args.buildings)
    return dict(
        buildings=buildings,
        wld=_read(args.wld),
        config=config,
        parcels=_read(args.parcels),
        streets=_read(args.streets),
        boundary=_read(args.boundary),
        data_year=args.year,
        networks=_networks(args.network, buildings, args.supply_temperature),
    )


def _validate(path: Path) -> int:
    findings: list[str] = []
    suffix = path.suffix.lower()
    if suffix in (".gml", ".xml"):
        from fheat_core.xwp.decode.gml import read_gml
        from fheat_core.xwp.encode.gml import validate_gml

        findings += [f"XSD: {f}" for f in validate_gml(path)]
        doc, issues = read_gml(path)
        findings += [f"Lesen: {i.message}" for i in issues]
        findings += [f"Modell: {i.path}: {i.message}" for i in doc.errors()]
    elif suffix == ".json":
        from fheat_core.xwp.encode.jsonfg import validate_jsonfg

        findings += [f"JSON-Schema: {f}" for f in validate_jsonfg(path)]
    elif suffix == ".gpkg":
        from fheat_core.xwp.decode.gpkg import read_gpkg
        from fheat_core.xwp.document import XwpPlanDocument

        features, issues = read_gpkg(path)
        doc = XwpPlanDocument(features=features)
        doc.link_reverse()
        findings += [f"Lesen: {i.message}" for i in issues]
        findings += [f"Modell: {i.path}: {i.message}" for i in doc.errors()]
    else:
        print(f"{path}: unbekanntes Format (erwartet .gml, .json oder .gpkg)", file=sys.stderr)
        return 2
    for line in findings:
        print(line)
    print(f"{path.name}: {'gültig' if not findings else f'{len(findings)} Befunde'}")
    return 1 if findings else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m fheat_core.xwp", description="XWärmeplan-Export von F|Heat")
    sub = ap.add_subparsers(dest="command", required=True)
    v = sub.add_parser("validate", help="GML, JSON-FG oder GeoPackage prüfen")
    v.add_argument("file", type=Path)
    for name, text in (("template", "Ergänzungsvorlage schreiben"), ("build", "XWärmeplan schreiben")):
        p = sub.add_parser(name, help=text)
        p.add_argument("--plan", required=True, help="JSON mit den Plan-Metadaten (XwpConfig)")
        p.add_argument("--buildings", required=True)
        p.add_argument("--wld", required=True)
        p.add_argument("--streets")
        p.add_argument("--parcels")
        p.add_argument("--boundary", help="Analysegebiet (Gemeinde); sonst Hülle der Gebäude")
        p.add_argument("--network", action="append", help="netz.gpkg[,planungsgebiet.gpkg[,quelle.gpkg]]; mehrfach möglich")
        p.add_argument("--supply-temperature", type=float, help="Vorlauftemperatur der Netze [°C]")
        p.add_argument("--year", type=int, help="Jahr der Daten (Basisjahr, wenn plan.json keins nennt)")
        p.add_argument("--out", required=True, type=Path)
        if name == "build":
            p.add_argument("--supplement", action="append", help="Ergänzungsdatei .gpkg oder .xlsx; mehrfach möglich")
    args = ap.parse_args(argv)

    if args.command == "validate":
        return _validate(args.file)
    if args.command == "template":
        from fheat_core.xwp.export import export_template

        files = export_template(args.out, **_inputs(args))
    else:
        from fheat_core.xwp.export import export_xwp

        files = export_xwp(args.out, supplement=args.supplement, **_inputs(args))
        report = json.loads(files["xwp_report"].read_text(encoding="utf-8"))
        print(f"gültig: {'ja' if report['gueltig'] else 'nein'}, {len(report['befunde'])} Befunde")
    for key, path in files.items():
        print(f"{key}: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
