"""Vendor the XWaermeplan specification for offline validation.

Copies the XWaermeplan XSD and JSON schemas of one version into
``src/fheat_core/xwp/spec/<version>/`` and mirrors everything they import:

* ``xsd/``     waermeplan.xsd plus GML 3.2.1, ISO 19139, XLink, xml.xsd and the
               OGC API Features "core-sf" schema used as FeatureCollection root,
               each under ``xsd/<host>/<path>``, and an OASIS XML catalog
               (``xsd/catalog.xml``) that maps every remote URL to its copy.
* ``json/``    featurecollection.json and features.json of XWaermeplan and the
               JSON-FG schemas they reference (JSON-FG 0.2.2, see kodierung.md),
               plus ``json/catalog.json`` (URL -> relative file).

Run it again only to move to a new XWaermeplan version:

    python scripts/fetch_xwp_spec.py --version 0.9.6 --spec-repo ..\\xwp-spec\\spezifikation

The script needs network access for the imported OGC/ISO schemas.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import urllib.request
from pathlib import Path
from urllib.parse import urljoin, urlparse

from lxml import etree

XS = "{http://www.w3.org/2001/XMLSchema}"

# Remote locations the XSD imports without a schemaLocation that resolves
# (or that GML refers to by namespace only).
EXTRA_XSD = [
    # FeatureCollection root of the reference plans (XPlan-Tools and ldproxy)
    "http://schemas.opengis.net/ogcapi/features/part1/1.0/xml/core-sf.xsd",
]

# JSON-FG 0.2.2 is the version the XWaermeplan JSON schema was generated
# against: it references geometry-objects.json, which JSON-FG 0.3 removed.
# beta.schemas.opengis.net now serves 0.3.x, so the files come from the tag.
JSONFG_TAG_URL = "https://raw.githubusercontent.com/opengeospatial/ogc-feat-geo-json/v0.2.2/core/schemas/"
JSONFG_ID_BASE = "https://beta.schemas.opengis.net/json-fg/"
JSONFG_FILES = [
    "conformsto.json", "coordrefsys.json", "feature.json", "featurecollection.json",
    "featureschema.json", "featuretype.json", "geometry-objects.json", "geometry.json",
    "place.json", "time.json",
]
# Dropped from JSON-FG in 0.2 but still referenced by XWaermeplan 0.9.6 and
# still published (informative) on the beta server.
JSONFG_LEGACY = ["link.json"]


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "fheat-fetch-xwp-spec"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def local_path(url: str) -> Path:
    u = urlparse(url)
    return Path(u.netloc) / u.path.lstrip("/")


def mirror_xsd(start_urls: list[str], root: Path) -> dict[str, str]:
    """Download XSDs and everything they include/import; return URL -> relative path."""
    done: dict[str, str] = {}
    queue = list(start_urls)
    while queue:
        url = queue.pop()
        url = url.replace("https://schemas.opengis.net", "http://schemas.opengis.net")
        if url in done:
            continue
        data = fetch(url)
        rel = local_path(url)
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(data)
        done[url] = rel.as_posix()
        doc = etree.fromstring(data)
        for tag in ("include", "import", "redefine"):
            for el in doc.iter(f"{XS}{tag}"):
                loc = el.get("schemaLocation")
                if loc:
                    queue.append(urljoin(url, loc))
    return done


def write_catalog(mapping: dict[str, str], path: Path) -> None:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">',
    ]
    for url, rel in sorted(mapping.items()):
        lines.append(f'  <uri name="{url}" uri="{rel}"/>')
        if url.startswith("http://schemas.opengis.net"):
            https = "https" + url[4:]
            lines.append(f'  <uri name="{https}" uri="{rel}"/>')
    lines.append("</catalog>")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="0.9.6")
    ap.add_argument("--spec-repo", required=True, type=Path,
                    help="local clone of gitlab.opencode.de/xleitstelle/xwaermeplan/spezifikation")
    ap.add_argument("--out", type=Path,
                    default=Path(__file__).resolve().parents[1] / "src" / "fheat_core" / "xwp" / "spec")
    args = ap.parse_args()

    target = args.out / args.version
    if target.exists():
        shutil.rmtree(target)
    xsd_dir, json_dir = target / "xsd", target / "json"
    xsd_dir.mkdir(parents=True)
    json_dir.mkdir(parents=True)

    # --- XSD
    xsd_src = args.spec_repo / "xsd" / "waermeplan.xsd"
    shutil.copyfile(xsd_src, xsd_dir / "waermeplan.xsd")
    doc = etree.parse(str(xsd_src)).getroot()
    ns = doc.get("targetNamespace")
    if not ns.endswith("/" + args.version.replace(".", "/")):
        raise SystemExit(f"XSD namespace {ns} does not match version {args.version}")
    imports = [el.get("schemaLocation") for el in doc.iter(f"{XS}import")]
    mapping = mirror_xsd([u for u in imports if u] + EXTRA_XSD, xsd_dir)
    mapping["https://gitlab.opencode.de/xleitstelle/xwaermeplan/spezifikation/-/raw/main/xsd/waermeplan.xsd"] = "waermeplan.xsd"
    write_catalog(mapping, xsd_dir / "catalog.xml")

    # --- JSON
    jcat: dict[str, str] = {}
    xwp_base = f"https://gitlab.opencode.de/xleitstelle/xwaermeplan/spezifikation/-/raw/main/json/{args.version}/"
    for name in ("featurecollection.json", "features.json"):
        shutil.copyfile(args.spec_repo / "json" / args.version / name, json_dir / name)
        jcat[xwp_base + name] = name
    (json_dir / "json-fg").mkdir()
    for name in JSONFG_FILES:
        (json_dir / "json-fg" / name).write_bytes(fetch(JSONFG_TAG_URL + name))
        jcat[JSONFG_ID_BASE + name] = "json-fg/" + name
    for name in JSONFG_LEGACY:
        (json_dir / "json-fg" / name).write_bytes(fetch(JSONFG_ID_BASE + name))
        jcat[JSONFG_ID_BASE + name] = "json-fg/" + name
    (json_dir / "catalog.json").write_text(
        json.dumps(jcat, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")

    # line endings: keep the vendored files byte-identical except CRLF -> LF
    for p in target.rglob("*"):
        if p.is_file() and p.suffix in (".xsd", ".json", ".xml"):
            raw = p.read_bytes()
            if b"\r\n" in raw:
                p.write_bytes(re.sub(rb"\r\n", b"\n", raw))
    print(f"{len(mapping)} XSD files, {len(jcat)} JSON schemas -> {target}")


if __name__ == "__main__":
    main()
