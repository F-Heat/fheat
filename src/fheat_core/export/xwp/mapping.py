"""Code lists, unit conversions and written properties of the XWaermeplan export, as data.

Everything that depends on the schema version and is not F|Heat logic lives
here: the codes F|Heat writes or accepts in :class:`XWPExportConfig`, with a
short German label for forms, the unit of every measure F|Heat converts and
the properties the mappers write. A new schema version means updating these
tables; ``tests/test_xwp_mapping.py`` checks them against the model
xplan-tools ships, ``tests/test_xwp_evidence.py`` against the XSD and the
feature catalogue of the XLeitstelle. The module needs no xplan-tools, so the
configuration can be checked without it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

#: xplan-tools application schema (prefix, major.minor) and the full version it must be
APPSCHEMA = ("xwp", "0.9")
SCHEMA_VERSION = "0.9.6"
NAMESPACE = "http://www.xwaermeplan.de/0/9/6"

# Code lists: code -> short label (from the alias in xplan-tools' model).
PROCEDURE = {  # WP_VerfahrenArt
    "1000": "Regelverfahren",
    "2000": "Kleine Wärmeplanung",
    "3000": "Vereinfachtes Verfahren",
    "4000": "Verkürzte Wärmeplanung",
}

LEGAL_BASIS = {  # WP_GesetzlicheGrundlage
    "1000": "WPG",
    "2000": "Landesverordnung",
    "3000": "Kommunalrichtlinie",
}

NETWORK_STATUS = {  # WP_Status
    "1000": "bestehend",
    "2000": "in Planung oder genehmigt",
    "3000": "potenziell",
}

TRANSPORT_MEDIUM = {  # WP_Transportmedium
    "1000": "Wasser",
    "2000": "Dampf",
    "3000": "Sole",
    "4000": "Kältemittel",
    "9999": "sonstiges",
}

ENERGY_CARRIER = {  # WP_Energietraeger
    "1100": "Kohle",
    "11001": "Braunkohle",
    "11002": "Steinkohle",
    "1200": "Fossiles Gas (OK)",
    "12001": "Erdgas",
    "12002": "Flüssiggas",
    "12003": "Grubengas",
    "1300": "Mineralölprodukte (OK)",
    "13001": "Heizöl",
    "13002": "Dieselkraftstoff",
    "2000": "Abfall (OK)",
    "20001": "nicht biogener Abfall",
    "20002": "biogener Abfall",
    "3100": "Biomasse (OK)",
    "31001": "feste Biomasse (ohne Altholz)",
    "31002": "Altholz",
    "31003": "flüssige Biomasse",
    "3200": "gasförmige Biomasse (OK)",
    "32001": "Biogas",
    "32002": "Biomethan",
    "32003": "Klärgas",
    "32004": "Deponiegas",
    "4000": "Wasserstoff (OK)",
    "40001": "grüner Wasserstoff",
    "40002": "blauer Wasserstoff",
    "40003": "orangener Wasserstoff",
    "40004": "türkiser Wasserstoff",
    "5000": "Wasserstoffderivate",
    "50001": "synthetisches Methan",
    "6000": "Strom (OK)",
    "60001": "Strom Wärmepumpe",
    "60002": "Strom Direktheizung",
    "7100": "Solarthermie (OK)",
    "71001": "Solarthermie Dachflächen",
    "71002": "Solarthermie Freiflächen",
    "7200": "Geothermie (OK)",
    "72001": "Oberflächennahe Geothermie",
    "72002": "Tiefe Geothermie",
    "7300": "Umweltwärme (OK)",
    "73001": "Grundwasser",
    "73002": "Oberflächengewässer",
    "73003": "Grubenwasser",
    "73004": "Umgebungsluft",
    "73005": "Abwasser",
    "8000": "Unvermeidbare Abwärme (OK)",
    "80001": "Abwärme < 60 °C",
    "80002": "Abwärme 60 bis 110 °C",
    "80003": "Abwärme ab 110 °C",
    "9990": "Sonstige (OK)",
    "99901": "Sonstige fossile Brennstoffe",
    "99902": "Sonstige erneuerbare Energien",
}

SUPPLY_TYPE = {  # WP_WaermeversorgungsgebietTyp
    "1000": "Wärmenetzgebiet",
    "10001": "Wärmenetzverdichtungsgebiet",
    "10002": "Wärmenetzausbaugebiet",
    "10003": "Wärmenetzneubaugebiet",
    "2000": "Wasserstoffnetzgebiet",
    "3000": "Gebiet der dezentralen Wärmeversorgung",
    "4000": "Prüfgebiet",
    "40001": "Prüfgebiet Wärmenetz",
    "40002": "Prüfgebiet Wasserstoffnetzgebiet",
    "40003": "Prüfgebiet grünes Methan",
}

SUITABILITY = {  # WP_Eignungsstufe
    "1000": "sehr wahrscheinlich geeignet",
    "2000": "wahrscheinlich geeignet",
    "3000": "wahrscheinlich ungeeignet",
    "4000": "sehr wahrscheinlich ungeeignet",
    "5000": "trifft nicht zu",
}

INTERIM_YEAR = {  # WP_Stuetzjahr
    "1000": "2030",
    "2000": "2035",
    "3000": "2040",
}

#: Supply area class per ``XWPExportConfig.supply_year``; the interim years
#: are one class with the attribute ``stuetzjahr``.
SUPPLY_AREA_CLASS = {
    "zieljahr": "WP_WaermeversorgungsgebietZieljahr",
    "2030": "WP_WaermeversorgungsgebietStuetzjahr",
    "2035": "WP_WaermeversorgungsgebietStuetzjahr",
    "2040": "WP_WaermeversorgungsgebietStuetzjahr",
}
INTERIM_YEAR_CODE = {label: code for code, label in INTERIM_YEAR.items()}

#: Lower bounds of the suitability stages 1000, 2000 and 3000 (below the last: 4000)
SUITABILITY_STAGES = ("1000", "2000", "3000", "4000")

CODE_LISTS = {
    "WP_VerfahrenArt": PROCEDURE,
    "WP_GesetzlicheGrundlage": LEGAL_BASIS,
    "WP_Status": NETWORK_STATUS,
    "WP_Transportmedium": TRANSPORT_MEDIUM,
    "WP_Energietraeger": ENERGY_CARRIER,
    "WP_WaermeversorgungsgebietTyp": SUPPLY_TYPE,
    "WP_Eignungsstufe": SUITABILITY,
    "WP_Stuetzjahr": INTERIM_YEAR,
}

#: code list -> (feature or data type, property) the export writes it to
CODE_LIST_PROPERTIES = {
    "WP_VerfahrenArt": ("WP_Plan", "verfahrensart"),
    "WP_GesetzlicheGrundlage": ("WP_Plan", "gesetzlicheGrundlage"),
    "WP_Status": ("WP_Waermenetz", "status"),
    "WP_Transportmedium": ("WP_Waermenetz", "medium"),
    "WP_Energietraeger": ("WP_EndenergieEnergietraeger", "energietraeger"),
    "WP_WaermeversorgungsgebietTyp": ("WP_WaermeversorgungsgebietZieljahr", "versorgungsart"),
    "WP_Eignungsstufe": ("WP_WaermeversorgungsgebietZieljahr", "eignungWaermenetz"),
    "WP_Stuetzjahr": ("WP_WaermeversorgungsgebietStuetzjahr", "stuetzjahr"),
}

#: Properties the mappers write, per feature or data type, geometry included.
#: The builder adds the references (WP_Plan.bereich, WP_Bereich.gehoertZuPlan
#: and gehoertZuBereich of every map feature).
WRITTEN_PROPERTIES = {
    "WP_Plan": (
        "name", "planungsverantwortlicheStelle", "verfahrensart", "gesetzlicheGrundlage",
        "zieljahr", "basisJahrDatenerfassung", "beschlussDatum", "raeumlicherGeltungsbereich",
    ),
    "WP_Gemeinde": ("name", "regionalSchluessel12"),
    "WP_Bereich": ("nummer", "name", "geltungsbereich"),
    "WP_Waermelinie": ("position", "waermeMenge", "waermelinienDichte", "laenge"),
    "WP_Waermenetz": (
        "position", "netzID", "name", "betreiber", "medium", "laenge",
        "anzahlGebaeudeAnschluss", "status", "temperatur", "eeNachEnergietraeger",
    ),
    "WP_EndenergieEnergietraeger": ("energietraeger", "endenergie"),
    "WP_WaermeversorgungsgebietZieljahr": ("position", "versorgungsart", "waermeMenge", "eignungWaermenetz"),
    "WP_WaermeversorgungsgebietStuetzjahr": ("position", "versorgungsart", "waermeMenge", "stuetzjahr"),
}

#: (feature type, property) -> data type of the nested value the mappers write
DATA_TYPES = {
    ("WP_Plan", "planungsverantwortlicheStelle"): "WP_Gemeinde",
    ("WP_Waermenetz", "eeNachEnergietraeger"): "WP_EndenergieEnergietraeger",
}


def check_code(code_list: str, code) -> str:
    """``code`` as string if it is in the code list, else ValueError (no fallback to 9999)."""
    codes = CODE_LISTS[code_list]
    code = str(code)
    if code not in codes:
        raise ValueError(f"{code!r} is not a code of {code_list} ({', '.join(codes)}).")
    return code


@dataclass(frozen=True)
class Conversion:
    """F|Heat value x ``factor`` = XWaermeplan value in ``uom``."""

    fheat_unit: str
    factor: float
    uom: str


_HEAT = Conversion("kWh/a", 1e-3, "MWh/a")

#: (feature or data type, property) -> conversion of the F|Heat value
MEASURES = {
    ("WP_Waermelinie", "waermeMenge"): _HEAT,
    ("WP_Waermelinie", "waermelinienDichte"): Conversion("kWh/(a·m)", 1e-3, "MWh/(m*a)"),
    ("WP_Waermelinie", "laenge"): Conversion("m", 1.0, "m"),
    ("WP_Waermenetz", "laenge"): Conversion("m", 1.0, "m"),
    ("WP_Waermenetz", "temperatur"): Conversion("°C", 1.0, "°C"),
    ("WP_EndenergieEnergietraeger", "endenergie"): Conversion("MWh/a", 1.0, "MWh/a"),
    ("WP_WaermeversorgungsgebietZieljahr", "waermeMenge"): _HEAT,
    ("WP_WaermeversorgungsgebietStuetzjahr", "waermeMenge"): _HEAT,
}

DECIMALS = 6  # of converted measures; F|Heat values carry no more


def measure(feature_type: str, prop: str, value) -> dict | None:
    """``{"value", "uom"}`` of an F|Heat value; None for a missing or non-finite value."""
    conversion = MEASURES[(feature_type, prop)]
    if value is None:
        return None
    value = float(value)
    if not math.isfinite(value):
        return None
    return {"value": round(value * conversion.factor, DECIMALS), "uom": conversion.uom}


def regional_key(municipality_key) -> str:
    """12-digit Regionalschlüssel (RS) of a municipality from its 8-digit AGS.

    Since 2009 a municipality outside any association (verbandsfrei) repeats
    its three-digit code after a 0 in the association part: Steinfurt
    05566084 -> 055660084084, a kreisfreie Stadt gets 0000 (05515000 ->
    055150000000). All NRW municipalities are verbandsfrei. For a member of
    an Amt, Samt- or Verbandsgemeinde the association code cannot be derived;
    pass the RS itself (``XWPExportConfig.regional_key``).
    """
    ags = str(municipality_key).strip()
    if len(ags) not in (7, 8) or not ags.isdigit():  # 7: leading zero lost in a number column
        raise ValueError(f"municipality key {municipality_key!r} is not an 8-digit AGS.")
    ags = ags.zfill(8)
    return f"{ags[:5]}0{ags[5:]}{ags[5:]}"
