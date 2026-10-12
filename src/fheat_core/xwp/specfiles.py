"""Access to the vendored XWaermeplan schemas (``spec/<version>/``) without network.

Needs lxml (extra ``[xwp]``) for the XSD and jsonschema/referencing for the
JSON schema; both are imported only when used.
"""
from __future__ import annotations

import functools
import json
from pathlib import Path

SPEC_ROOT = Path(__file__).resolve().parent / "spec"
SF_NAMESPACE = "http://www.opengis.net/ogcapi-features-1/1.0/sf"
SF_XSD = "http://schemas.opengis.net/ogcapi/features/part1/1.0/xml/core-sf.xsd"


def spec_dir(version: str) -> Path:
    path = SPEC_ROOT / version
    if not path.is_dir():
        raise ValueError(f"no vendored XWaermeplan specification for version {version}")
    return path


@functools.lru_cache(maxsize=None)
def xsd_schema(version: str):
    """``lxml.etree.XMLSchema`` for XWaermeplan instances with ``sf:FeatureCollection`` as root."""
    from lxml import etree

    xsd_dir = spec_dir(version) / "xsd"
    ns = "{urn:oasis:names:tc:entity:xmlns:xml:catalog}"
    catalog = etree.parse(str(xsd_dir / "catalog.xml")).getroot()
    mapping = {u.get("name"): str(xsd_dir / u.get("uri")) for u in catalog.iter(f"{ns}uri")}

    class CatalogResolver(etree.Resolver):
        def resolve(self, url, pubid, context):
            if url in mapping:
                return self.resolve_filename(mapping[url], context)
            return None

    parser = etree.XMLParser(no_network=True)
    parser.resolvers.add(CatalogResolver())
    root = etree.parse(str(xsd_dir / "waermeplan.xsd")).getroot()
    # the instances' root is sf:FeatureCollection, so import both schemas
    wrapper = (
        '<schema xmlns="http://www.w3.org/2001/XMLSchema">'
        f'<import namespace="{root.get("targetNamespace")}" schemaLocation="{(xsd_dir / "waermeplan.xsd").as_uri()}"/>'
        f'<import namespace="{SF_NAMESPACE}" schemaLocation="{SF_XSD}"/>'
        "</schema>"
    )
    return etree.XMLSchema(etree.fromstring(wrapper.encode(), parser))


@functools.lru_cache(maxsize=None)
def json_registry(version: str):
    """``(referencing.Registry, base URI of features.json)`` for the XWaermeplan JSON schema."""
    from referencing import Registry, Resource

    json_dir = spec_dir(version) / "json"
    catalog = json.loads((json_dir / "catalog.json").read_text(encoding="utf-8"))
    resources = [
        (uri, Resource.from_contents(json.loads((json_dir / rel).read_text(encoding="utf-8"))))
        for uri, rel in catalog.items()
    ]
    base = next(uri for uri in catalog if uri.endswith("/features.json"))
    return Registry().with_resources(resources), base
