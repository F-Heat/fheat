"""Write a collection as GML (xplan-tools) and check it against the XSD.

GML is the only format: JSON-FG as xplan-tools 1.26 writes it does not
validate against the JSON schema of XWaermeplan 0.9.6, and the schema-valid
form cannot be read by xplan-tools (docs/xwp_mapping.md).
"""
from __future__ import annotations

from pathlib import Path

from fheat_core.export.xwp import mapping

SUFFIX = ".gml"

SPEC_RAW = "https://gitlab.opencode.de/xleitstelle/xwaermeplan/spezifikation/-/raw/main"
SF_NAMESPACE = "http://www.opengis.net/ogcapi-features-1/1.0/sf"
SF_XSD = "http://schemas.opengis.net/ogcapi/features/part1/1.0/xml/core-sf.xsd"


def gml_path(path) -> Path:
    """``path`` as a Path; ValueError unless it names a GML file."""
    path = Path(path)
    if path.suffix.lower() != SUFFIX:
        raise ValueError(f"{path}: the suffix must be {SUFFIX}; XWaermeplan is written as GML only.")
    return path


def write(collection, path) -> Path:
    """Write ``collection`` to the GML file ``path``."""
    from xplan_tools.interface import Datasource

    path = gml_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if any(f.get_name() == mapping.PLAN for f in collection.get_features()):
        with Datasource(str(path), format="gml", for_write=True).repo() as repo:
            repo.save_all(collection)
    else:
        _write_gml_without_plan(collection, path)
    _pin_schema_link(path)
    return path


def read_features(path) -> dict:
    """``{id: feature}`` of a written GML file, every feature validated by xplan-tools.

    xplan-tools reads a file only as a whole collection and rejects a
    fragment, whose area refers to a plan outside the file (a mandatory
    reference it cannot drop, 1.26). This reads the features the way its
    readers do, without the collection's reference check.
    """
    from lxml import etree
    from xplan_tools.util import parse_srs

    from fheat_core.export.xwp.builder import appschema

    schema = appschema()
    features = {}
    root = etree.parse(str(gml_path(path))).getroot()
    srid = parse_srs(next(e.get("srsName") for e in root.iter() if e.get("srsName")))
    for element in root.iterfind("./*/*"):
        if etree.QName(element).namespace != mapping.NAMESPACE:
            continue  # gml:boundedBy
        model = schema.model_factory(etree.QName(element).localname).model_validate(element, context={"srid": srid})
        features[model.id] = model
    return features


def _write_gml_without_plan(collection, path: Path) -> None:
    """The GML of a fragment, as xplan-tools would write it.

    xplan-tools' GML writer takes the envelope of the plan geometry and
    fails without a WP_Plan (1.26), although XWaermeplan files carry no
    envelope; so the root is built here and every feature is serialised by
    xplan-tools itself.
    """
    import uuid

    from lxml import etree

    gml = "http://www.opengis.net/gml/3.2"
    nsmap = {None: mapping.NAMESPACE, "gml": gml, "xlink": "http://www.w3.org/1999/xlink",
             "xsi": "http://www.w3.org/2001/XMLSchema-instance", "sf": SF_NAMESPACE}
    root = etree.Element(f"{{{SF_NAMESPACE}}}FeatureCollection", nsmap=nsmap, attrib={
        f"{{{nsmap['xsi']}}}schemaLocation": (
            f"{mapping.NAMESPACE} {SPEC_RAW}/xsd/waermeplan.xsd {SF_NAMESPACE} {SF_XSD} "
            f"{gml} https://schemas.opengis.net/gml/3.2.1/gml.xsd"
        ),
        f"{{{gml}}}id": f"GML_{uuid.uuid4()}",
    })
    for feature in collection.get_features():
        etree.SubElement(root, f"{{{SF_NAMESPACE}}}featureMember").append(feature.model_dump_gml(feature_srs=True))
    etree.ElementTree(root).write(str(path), pretty_print=True, xml_declaration=True, encoding="UTF-8")


def _pin_schema_link(path: Path) -> None:
    """Point the schema location at the version written.

    xplan-tools links ``xsd/waermeplan.xsd`` on ``main``, which is version
    0.9.7 since 13.10.2026; a validator would load the wrong schema.
    """
    from lxml import etree

    tree = etree.parse(str(path))
    root = tree.getroot()
    attr = "{http://www.w3.org/2001/XMLSchema-instance}schemaLocation"
    root.set(attr, root.get(attr, "").replace(
        f"{SPEC_RAW}/xsd/waermeplan.xsd", f"{SPEC_RAW}/xsd/{mapping.SCHEMA_VERSION}/waermeplan.xsd"
    ))
    tree.write(str(path), pretty_print=True, xml_declaration=True, encoding="UTF-8")


def validate_gml(path, schema_dir) -> list[str]:
    """XSD findings of a written GML file, offline.

    ``schema_dir`` holds ``waermeplan.xsd`` of the written version and a
    ``catalog.xml`` (OASIS XML catalog) that maps the imported OGC and W3C
    schemas to local copies; nothing is fetched from the network.
    """
    from lxml import etree

    schema_dir = Path(schema_dir)
    ns = "{urn:oasis:names:tc:entity:xmlns:xml:catalog}"
    catalog = etree.parse(str(schema_dir / "catalog.xml")).getroot()
    local = {u.get("name"): str(schema_dir / u.get("uri")) for u in catalog.iter(f"{ns}uri")}

    class CatalogResolver(etree.Resolver):
        def resolve(self, url, pubid, context):
            return self.resolve_filename(local[url], context) if url in local else None

    parser = etree.XMLParser(no_network=True)
    parser.resolvers.add(CatalogResolver())
    xsd = schema_dir / "waermeplan.xsd"
    namespace = etree.parse(str(xsd)).getroot().get("targetNamespace")
    # the root element is sf:FeatureCollection, so both schemas are needed
    wrapper = (
        '<schema xmlns="http://www.w3.org/2001/XMLSchema">'
        f'<import namespace="{namespace}" schemaLocation="{xsd.as_uri()}"/>'
        f'<import namespace="{SF_NAMESPACE}" schemaLocation="{SF_XSD}"/>'
        "</schema>"
    )
    schema = etree.XMLSchema(etree.fromstring(wrapper.encode(), parser))
    document = etree.parse(str(path), etree.XMLParser(no_network=True))
    if schema.validate(document):
        return []
    return [f"line {e.line}: {e.message}" for e in schema.error_log]
