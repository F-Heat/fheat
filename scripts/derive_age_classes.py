"""Derive the EFH/MFH demands and LANUV factors of ``building_age_classes.json`` from the IWU type buildings.

Source: Loga, Stein (2026), Tabellenwerte des Typgebäude-Modells zur
energetischen Bewertung des Wohngebäudebestands, v1.2, Institut Wohnen und
Umwelt, https://doi.org/10.5281/zenodo.18166030 (CC BY 4.0), the file
``Typgebaeude-Tabellenwerte_v1.2.xlsx`` of https://zenodo.org/records/18166030.
The steps are described in ``docs/age_class_values.md``.

    python scripts/derive_age_classes.py <Typgebaeude-Tabellenwerte_v1.2.xlsx>
    python scripts/derive_age_classes.py <xlsx> --write

Without ``--write`` it prints the derived values next to those in the JSON
and exits with 1 if they differ; with ``--write`` it writes them into the
JSON (only the two demands and the two factors, keys and ``baujahre`` stay). Needs openpyxl
(``pip install -e ".[excel]"``).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from openpyxl import load_workbook

JSON = Path(__file__).resolve().parents[1] / "src" / "fheat_de" / "data" / "building_age_classes.json"

#: IWU age classes of the "Differenziertes Modell 2025", in sheet order.
IWU_CLASSES = ["bis 1918", "1919 – 1948", "1949 – 1978", "1979 – 1994", "1995 – 2001",
               "2002 – 2009", "2010 – 2015", "2016 – 2020", "2021 – 2025"]

#: The six building variants: first row in "Tabellen Anhang C" (energy figures)
#: and "Tabellen Anhang A" (stock), and the start of their label. Each block
#: has one row per IWU class.
VARIANTS = {
    "EFH": [(21, 53, "EZFH freistehend"), (30, 62, "EZFH"), (39, 71, "EZFH Reihenhaus")],
    "MFH": [(48, 80, "MFH"), (57, 89, "MFH"), (66, 98, "MFH mit 21")],
}

#: F|Heat age class -> IWU classes it takes (several: weighted by living area).
CLASS_MAP = {
    "A": ["bis 1918"], "B": ["bis 1918"], "C": ["1919 – 1948"],
    "D": ["1949 – 1978"], "E": ["1949 – 1978"], "F": ["1949 – 1978"],
    "G": ["1979 – 1994"], "H": ["1979 – 1994"], "I": ["1995 – 2001"],
    "J": ["2002 – 2009"], "K": ["2010 – 2015"], "L": ["2016 – 2020", "2021 – 2025"],
}

SHEET_C, SHEET_A = "Tabellen Anhang C", "Tabellen Anhang A"
#: Anhang C, block "Niedertemperaturkessel / Heizöl und Fernwärme, TABULA-Berechnung
#: mit Standardrandbedingungen": block label, supply system, column title, type
#: label, age class, final energy district heating for heating + hot water.
C_BLOCK, C_SYSTEM, C_TITLE, C_TYPE, C_CLASS, C_VALUE = "W5", "AF8", "AH10", "X", "Y", "AH"
#: Anhang C, block "Brennwert-Kessel / Erdgas, TABULA-Berechnung mit
#: Standardrandbedingungen": block label, column titles, type label, useful
#: heat for heating and for hot water (the denominator of the LANUV factor).
U_BLOCK, U_TITLE_HEATING, U_TITLE_WATER, U_TYPE, U_HEATING, U_WATER = "E5", "L10", "M10", "F", "L", "M"
#: Anhang A: type label, age class, living area of the stock [Mio. m²].
A_TYPE, A_CLASS, A_AREA = "D", "E", "H"


def _text(value) -> str:
    return " ".join(str(value or "").split())


def read_source(path: Path) -> dict[str, dict[str, list[tuple[float, float, float]]]]:
    """Per building type and IWU class, one entry per variant: (final energy district heating, heating +
    hot water [kWh/m²a], living area [Mio. m²], useful heat, heating + hot water [kWh/m²a])."""
    book = load_workbook(path, read_only=True, data_only=True)
    c, a = book[SHEET_C], book[SHEET_A]
    checks = [
        (C_BLOCK, lambda t: "Fernwärme" in t and "Standardrandbedingungen" in t, "the district heating block "
         "with standard boundary conditions"),
        (C_SYSTEM, lambda t: t == "Fernwärme", "'Fernwärme'"),
        (C_TITLE, lambda t: t.replace("-", "") == "Heizung + Warmwasser", "'Heizung + Warmwasser'"),
        (U_BLOCK, lambda t: "Brennwert-Kessel / Erdgas" in t and "Standardrandbedingungen" in t, "the gas "
         "condensing boiler block with standard boundary conditions"),
        (U_TITLE_HEATING, lambda t: t == "Heizung", "'Heizung'"),
        (U_TITLE_WATER, lambda t: t.replace("- ", "").replace("-", "") == "Warmwasser", "'Warmwasser'"),
    ]
    for coordinate, ok, expected in checks:
        if not ok(_text(c[coordinate].value)):
            raise ValueError(f"{SHEET_C}!{coordinate} is {c[coordinate].value!r}, expected {expected}")
    data: dict[str, dict[str, list[tuple[float, float, float]]]] = {}
    for building_type, variants in VARIANTS.items():
        per_class = data.setdefault(building_type, {k: [] for k in IWU_CLASSES})
        for row_c, row_a, label in variants:
            for name, cell in ((SHEET_C, c[f"{C_TYPE}{row_c}"]), (SHEET_C, c[f"{U_TYPE}{row_c}"]),
                               (SHEET_A, a[f"{A_TYPE}{row_a}"])):
                if not _text(cell.value).startswith(label):
                    raise ValueError(f"{name}!{cell.coordinate} is {cell.value!r}, expected {label!r}")
            for i, iwu_class in enumerate(IWU_CLASSES):
                rc, ra = row_c + i, row_a + i
                for name, cell in ((SHEET_C, c[f"{C_CLASS}{rc}"]), (SHEET_A, a[f"{A_CLASS}{ra}"])):
                    if _text(cell.value) != iwu_class:
                        raise ValueError(f"{name}!{cell.coordinate} is {cell.value!r}, expected {iwu_class!r}")
                useful = float(c[f"{U_HEATING}{rc}"].value) + float(c[f"{U_WATER}{rc}"].value)
                per_class[iwu_class].append(
                    (float(c[f"{C_VALUE}{rc}"].value), float(a[f"{A_AREA}{ra}"].value), useful))
    return data


def derive(data) -> dict[str, dict[str, float]]:
    """F|Heat class -> {"waerme_efh_kwh_m2a", "waerme_mfh_kwh_m2a", "faktor_lanuv_efh", "faktor_lanuv_mfh"}.

    Demands: living-area weighted means, one decimal. Factors: final energy
    district heating / useful heat of each variant and IWU class, their plain
    mean (not weighted), three decimals.
    """
    out = {}
    for fheat_class, iwu_classes in CLASS_MAP.items():
        out[fheat_class] = {}
        for building_type in VARIANTS:
            rows = [r for c in iwu_classes for r in data[building_type][c]]
            mean = sum(f * w for f, w, _ in rows) / sum(w for _, w, _ in rows)
            factor = sum(f / u for f, _, u in rows) / len(rows)
            out[fheat_class][f"waerme_{building_type.lower()}_kwh_m2a"] = round(mean, 1)
            out[fheat_class][f"faktor_lanuv_{building_type.lower()}"] = round(factor, 3)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("xlsx", type=Path, help="Typgebaeude-Tabellenwerte_v1.2.xlsx")
    parser.add_argument("--write", action="store_true", help="write the values into building_age_classes.json")
    args = parser.parse_args()

    derived = derive(read_source(args.xlsx))
    table = json.loads(JSON.read_text(encoding="utf-8"))
    differs = False
    for fheat_class, values in derived.items():
        current = {k: table[fheat_class].get(k) for k in values}
        mark = "" if current == values else "  <- differs"
        differs |= bool(mark)
        print(f"{fheat_class}: EFH {values['waerme_efh_kwh_m2a']:6.1f} x{values['faktor_lanuv_efh']:.3f}"
              f"  MFH {values['waerme_mfh_kwh_m2a']:6.1f} x{values['faktor_lanuv_mfh']:.3f}"
              f"  (JSON {current['waerme_efh_kwh_m2a']} x{current['faktor_lanuv_efh']},"
              f" {current['waerme_mfh_kwh_m2a']} x{current['faktor_lanuv_mfh']}){mark}")
        table[fheat_class].update(values)
    if args.write:
        JSON.write_text(json.dumps(table, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(f"written: {JSON}")
        return 0
    return 1 if differs else 0


if __name__ == "__main__":
    sys.exit(main())
