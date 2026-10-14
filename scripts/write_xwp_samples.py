"""Write the XWaermeplan GML files the CI job reads with XPlan-Tools.

    python scripts/write_xwp_samples.py <out dir>

Writes every concrete feature type as minimal and maximal object (variable
geometry once as area, once as point) and the Burgsteinfurt example, each
checked against the XSD first. Run from the repository root.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from fheat_core.xwp.encode.gml import validate_gml, write_gml  # noqa: E402
from fheat_core.xwp.model import current as model  # noqa: E402
from tests.xwp_golden import burgsteinfurt_plan  # noqa: E402
from tests.xwp_synth import document_all  # noqa: E402


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    docs = {
        f"alle_klassen_{'maximal' if maximal else 'minimal'}_{variable}": document_all(model, maximal, variable)[0]
        for maximal in (False, True)
        for variable in ("surface", "point")
    }
    docs["burgsteinfurt"] = burgsteinfurt_plan()[0]
    failed = False
    for name, doc in docs.items():
        path = write_gml(doc, out / f"{name}.gml")
        findings = validate_gml(path)
        print(f"{path.name}: {len(doc.features)} Objekte, XSD {'gültig' if not findings else findings[:3]}")
        failed |= bool(findings)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
