"""Generate the XWaermeplan model module from the XSD.

    python scripts/gen_xwp_model.py            # writes src/fheat_core/xwp/model/v0_9_6.py
    python scripts/gen_xwp_model.py --check    # exit 1 if the checked-in module is out of date

Structure (classes, inheritance, attributes, their order, multiplicities,
reference targets, enumeration codes and labels) comes from the XSD. The XSD
types every measure as gml:MeasureType without a unit, so units come from the
UML model export ``docs/xwaermeplan/xwp_0.9.6_modell.json``; it also supplies
the Python names of the enum members. The generator stops if XSD and model
export disagree on anything else (see docs/xwaermeplan/abgleich.md).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VERSION = "0.9.6"
XS = "{http://www.w3.org/2001/XMLSchema}"
GML = "{http://www.opengis.net/gml/3.2}"

SIMPLE_TYPES = {"string": "string", "integer": "integer", "boolean": "boolean", "date": "date", "anyURI": "uri"}
GEOMETRY_PROPERTY_TYPES = {
    "gml:MultiSurfacePropertyType": "MultiSurface",
    "gml:MultiCurvePropertyType": "MultiCurve",
    "gml:GeometryPropertyType": "Geometry",
}
PY_TYPES = {
    "string": "str", "uri": "str", "integer": "int", "boolean": "bool", "date": "datetime.date",
    "measure": "float | Measure", "geometry": "BaseGeometry",
}
# in the model export but not in the XSD; the UUID is gml:id / JSON-FG id instead
IGNORED_MODEL_ATTRS = {("WP_Objekt", "uuid")}


@dataclass
class Attr:
    name: str
    kind: str
    type: str
    min: int
    max: int | None
    owner: str
    uom: str | None = None
    reverse: str | None = None
    doc: str = ""


@dataclass
class Cls:
    name: str
    stereotype: str
    abstract: bool
    base: str | None
    doc: str
    attrs: list[Attr] = field(default_factory=list)


@dataclass
class Enum:
    name: str
    doc: str
    values: list[tuple[str, str, str]]  # (member name, code, label)


def _doc(el) -> str:
    d = el.find(f"{XS}annotation/{XS}documentation")
    if d is None or d.text is None:
        return ""
    text = d.text.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.strip() for line in text.strip().split("\n"))


def _member_name(name: str, code: str, taken: set[str]) -> str:
    ident = re.sub(r"\W", "_", name)
    if not ident or ident[0].isdigit():
        ident = "J" + ident  # years and age classes: J2030, J1990_1999
    if not ident.isidentifier() or ident in taken:
        ident = f"C{code}"
    return ident


def parse(xsd_path: Path, model_path: Path) -> tuple[str, str, list[Enum], list[Cls]]:
    root = etree.parse(str(xsd_path)).getroot()
    namespace, version = root.get("targetNamespace"), root.get("version")
    model = json.loads(model_path.read_text(encoding="utf-8"))

    # --- enumerations
    enums: dict[str, Enum] = {}
    for st in root.findall(f"{XS}simpleType"):
        name = st.get("name").removesuffix("Type")
        model_values = {v["code"]: v["name"] for v in model["enums"][name]["values"]}
        codes = [e.get("value") for e in st.iter(f"{XS}enumeration")]
        if codes != list(model_values):
            raise SystemExit(f"{name}: codes differ between XSD {codes} and model {list(model_values)}")
        taken: set[str] = set()
        vals = []
        for e in st.iter(f"{XS}enumeration"):
            code = e.get("value")
            member = _member_name(model_values[code], code, taken)
            taken.add(member)
            vals.append((member, code, _doc(e)))
        enums[name] = Enum(name, _doc(st), vals)

    # --- classes
    types = {ct.get("name"): ct for ct in root.findall(f"{XS}complexType")}
    elements = {el.get("name"): el for el in root.findall(f"{XS}element")}

    def property_target(type_name: str) -> str:
        """xwp:WP_GemeindePropertyType -> WP_Gemeinde"""
        ct = types[type_name.removeprefix("xwp:")]
        return ct.find(f"{XS}sequence/{XS}element").get("ref").removeprefix("xwp:")

    classes: dict[str, Cls] = {}
    for name, el in elements.items():
        ct = types[el.get("type").removeprefix("xwp:")]
        ext = ct.find(f"{XS}complexContent/{XS}extension")
        if ext is not None:
            stereotype = "FeatureType"
            base = ext.get("base")
            base = None if base == "gml:AbstractFeatureType" else base.removeprefix("xwp:").removesuffix("Type")
            seq = ext.find(f"{XS}sequence")
        else:
            stereotype, base, seq = "DataType", None, ct.find(f"{XS}sequence")
        cls = Cls(name, stereotype, el.get("abstract") == "true", base, _doc(el))
        model_cls = model["classes"][name]
        model_attrs = {a["name"]: a for a in model_cls["attrs"]}
        if model_cls["stereotype"] != stereotype or model_cls["abstract"] != cls.abstract:
            raise SystemExit(f"{name}: stereotype/abstract differ between XSD and model")
        for a in seq.findall(f"{XS}element") if seq is not None else []:
            aname, atype = a.get("name"), a.get("type")
            mx = a.get("maxOccurs", "1")
            attr = Attr(aname, "", "", int(a.get("minOccurs", "1")), None if mx == "unbounded" else int(mx), name, doc=_doc(a))
            if atype in SIMPLE_TYPES:
                attr.kind = attr.type = SIMPLE_TYPES[atype]
            elif atype == "gml:MeasureType":
                attr.kind, attr.type = "measure", "measure"
                attr.uom = model_attrs[aname]["uom"]
                if not attr.uom:
                    raise SystemExit(f"{name}.{aname}: no unit in the model export")
            elif atype == "gml:ReferenceType":
                info = a.find(f"{XS}annotation/{XS}appinfo")
                attr.kind = "ref"
                attr.type = info.find(f"{GML}targetElement").text.removeprefix("xwp:")
                rev = info.find(f"{GML}reversePropertyName")
                attr.reverse = rev.text.removeprefix("xwp:") if rev is not None else None
            elif atype in GEOMETRY_PROPERTY_TYPES:
                attr.kind, attr.type = "geometry", GEOMETRY_PROPERTY_TYPES[atype]
            elif atype.endswith("PropertyType"):
                attr.kind, attr.type = "datatype", property_target(atype)
            elif atype.removeprefix("xwp:").removesuffix("Type") in enums:
                attr.kind, attr.type = "enum", atype.removeprefix("xwp:").removesuffix("Type")
            else:
                raise SystemExit(f"{name}.{aname}: unknown type {atype}")
            # cross-check with the model export
            m = model_attrs.get(aname)
            if m is None:
                raise SystemExit(f"{name}.{aname}: missing in the model export")
            if m["mult"] != _mult(attr):
                raise SystemExit(f"{name}.{aname}: multiplicity XSD {_mult(attr)} vs model {m['mult']}")
            cls.attrs.append(attr)
        xsd_names = [a.name for a in cls.attrs]
        model_names = [n for n in model_attrs if n != "id" and (name, n) not in IGNORED_MODEL_ATTRS]
        if xsd_names != model_names:
            raise SystemExit(f"{name}: attributes XSD {xsd_names} vs model {model_names}")
        classes[name] = cls

    if set(classes) != set(model["classes"]) or set(enums) != set(model["enums"]):
        raise SystemExit("class or enum sets differ between XSD and model export")

    # bases before subclasses, otherwise alphabetical
    def depth(c: Cls) -> int:
        return 0 if c.base is None else 1 + depth(classes[c.base])

    ordered = sorted(classes.values(), key=lambda c: (depth(c), c.name))
    return namespace, version, sorted(enums.values(), key=lambda e: e.name), ordered


def _mult(a: Attr) -> str:
    hi = "*" if a.max is None else str(a.max)
    return str(a.min) if str(a.min) == hi else f"{a.min}..{hi}"


def _docstring(doc: str, indent: str) -> str:
    doc = doc.replace("\\", "\\\\").replace('"""', '\\"\\"\\"') or "(ohne Beschreibung)"
    lines: list[str] = []
    for para in doc.split("\n"):
        lines.extend(textwrap.wrap(para, 88 - len(indent)) or [""])
    if len(lines) == 1:
        return f'{indent}"""{lines[0]}"""\n'
    return f'{indent}"""' + lines[0] + "\n" + "".join(f"{indent}{ln}\n" if ln else "\n" for ln in lines[1:]) + f'{indent}"""\n'


def _py_type(a: Attr) -> str:
    if a.kind in PY_TYPES:
        t = PY_TYPES[a.kind]
    elif a.kind == "ref":
        t = f"Ref | {a.type}"
    else:
        t = a.type
    if a.max is None or a.max > 1:
        return f"list[{t}] = field(default_factory=list)"
    return f"{t} | None = None"


def render(namespace: str, version: str, enums: list[Enum], classes: list[Cls]) -> str:
    out = [
        f'"""XWaermeplan {version} model (namespace {namespace}).\n\n'
        "GENERATED by scripts/gen_xwp_model.py from the XSD in fheat_core/xwp/spec and\n"
        "docs/xwaermeplan/xwp_0.9.6_modell.json. Do not edit; run the generator.\n"
        '"""\n',
        "from __future__ import annotations\n\n",
        "import datetime\n",
        "from dataclasses import dataclass, field\n",
        "from typing import ClassVar\n\n",
        "from shapely.geometry.base import BaseGeometry\n\n",
        "from fheat_core.xwp.model.base import (\n",
        "    AttrInfo,\n    ClassInfo,\n    Measure,\n    Ref,\n    XwpDataType,\n",
        "    XwpEnum,\n    XwpFeature,\n    XwpObject,\n    make_register,\n)\n\n",
        f'VERSION = "{version}"\n',
        f'NAMESPACE = "{namespace}"\n\n',
        "CLASSES: dict[str, type[XwpObject]] = {}\n",
        "ENUMS: dict[str, type[XwpEnum]] = {}\n",
        "_register = make_register(CLASSES, ENUMS)\n",
    ]
    for e in enums:
        out.append(f"\n\nclass {e.name}(XwpEnum):\n")
        out.append(_docstring(e.doc, "    "))
        out.append("\n")
        for member, code, label in e.values:
            out.append(f"    {member} = ({code!r}, {label!r})\n")
        out.append(f"\n\nENUMS[{e.name!r}] = {e.name}\n")
    for c in classes:
        if c.base:
            parent = c.base
        else:
            parent = "XwpFeature" if c.stereotype == "FeatureType" else "XwpDataType"
        out.append(f"\n\n@_register\n@dataclass(kw_only=True)\nclass {c.name}({parent}):\n")
        out.append(_docstring(c.doc, "    "))
        out.append("\n")
        for a in c.attrs:
            out.append(f"    {a.name}: {_py_type(a)}\n")
        if c.attrs:
            out.append("\n")
        out.append("    __xwp__: ClassVar[ClassInfo] = ClassInfo(\n")
        out.append(f"        name={c.name!r},\n        stereotype={c.stereotype!r},\n")
        out.append(f"        abstract={c.abstract!r},\n        base={c.base!r},\n")
        out.append(f"        doc={c.doc!r},\n")
        out.append("        own_attrs=(\n" if c.attrs else "        own_attrs=(),\n")
        for a in c.attrs:
            out.append("            AttrInfo(\n")
            out.append(f"                name={a.name!r}, kind={a.kind!r}, type={a.type!r},\n")
            out.append(f"                min={a.min!r}, max={a.max!r}, owner={a.owner!r},\n")
            if a.uom is not None:
                out.append(f"                uom={a.uom!r},\n")
            if a.reverse is not None:
                out.append(f"                reverse={a.reverse!r},\n")
            out.append(f"                doc={a.doc!r},\n")
            out.append("            ),\n")
        if c.attrs:
            out.append("        ),\n")
        out.append("    )\n")
    concrete = [c.name for c in classes if not c.abstract and c.stereotype == "FeatureType"]
    out.append("\n\n# concrete feature types, i.e. what can appear in a plan document\n")
    out.append("FEATURE_TYPES: tuple[str, ...] = (\n")
    out.extend(f"    {n!r},\n" for n in sorted(concrete))
    out.append(")\n")
    return "".join(out)


def generate(version: str = DEFAULT_VERSION, xsd: Path | None = None, model: Path | None = None) -> str:
    xsd = xsd or ROOT / "src" / "fheat_core" / "xwp" / "spec" / version / "xsd" / "waermeplan.xsd"
    model = model or ROOT / "docs" / "xwaermeplan" / f"xwp_{version}_modell.json"
    return render(*parse(xsd, model))


def module_path(version: str = DEFAULT_VERSION) -> Path:
    return ROOT / "src" / "fheat_core" / "xwp" / "model" / f"v{version.replace('.', '_')}.py"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default=DEFAULT_VERSION)
    ap.add_argument("--check", action="store_true", help="only compare with the checked-in module")
    args = ap.parse_args()
    code = generate(args.version)
    path = module_path(args.version)
    if args.check:
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if current != code:
            sys.exit(f"{path} is out of date; run scripts/gen_xwp_model.py")
        print(f"{path} is up to date")
        return
    path.write_text(code, encoding="utf-8", newline="\n")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
