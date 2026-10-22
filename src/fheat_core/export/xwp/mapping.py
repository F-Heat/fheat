"""The XWaermeplan side of the export, as data.

Everything that depends on the schema version lives here: the classes
F|Heat writes with every attribute, where its value comes from, its unit and
code list (:data:`CLASSES`), and the codes F|Heat writes or accepts in
:class:`XWPExportConfig`, with a short German label for forms. Apart from
the defaults of :class:`XWPExportConfig`, the rest of the export names no
class, attribute or code of XWaermeplan; a new schema version means updating
this module. ``tests/test_xwp_mapping.py`` checks it
against the model xplan-tools ships, ``tests/test_xwp_evidence.py`` against
the XSD and the feature catalogue of the XLeitstelle and against the F|Heat
schemas. The module needs no xplan-tools, so the configuration can be checked
without it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Optional

from fheat_core import columns as cols

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
INTERIM_YEAR_CODE = {label: code for code, label in INTERIM_YEAR.items()}

#: Lower bounds of the suitability stages 1000, 2000 and 3000 (below the last: 4000)
SUITABILITY_STAGES = ("1000", "2000", "3000", "4000")

#: WP_Eignungsstufe 5000 "Keine Aussage notwendig oder möglich (entweder vereinfachtes
#: Verfahren durchgeführt oder Versorgungsart Prüfgebiet)": the supply types and
#: procedures after which every suitability stage is 5000
NO_STATEMENT = "5000"
NO_STATEMENT_SUPPLY_TYPES = frozenset({"4000", "40001", "40002", "40003"})  # Prüfgebiet
NO_STATEMENT_PROCEDURES = frozenset({"3000"})                                # Vereinfachtes Verfahren

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


def check_code(code_list: str, code) -> str:
    """``code`` as string if it is in the code list, else ValueError (no fallback to 9999)."""
    codes = CODE_LISTS[code_list]
    code = str(code)
    if code not in codes:
        raise ValueError(f"{code!r} is not a code of {code_list} ({', '.join(codes)}).")
    return code


# ------------------------------------------------------------------
# Classes and their attributes
# ------------------------------------------------------------------

#: The classes F|Heat writes; the rest of the export names them only through these.
PLAN = "WP_Plan"
MUNICIPALITY = "WP_Gemeinde"
AREA = "WP_Bereich"
HEAT_LINE = "WP_Waermelinie"
HEAT_NETWORK = "WP_Waermenetz"
FINAL_ENERGY = "WP_EndenergieEnergietraeger"
SUPPLY_AREA_TARGET = "WP_WaermeversorgungsgebietZieljahr"
SUPPLY_AREA_INTERIM = "WP_WaermeversorgungsgebietStuetzjahr"

#: Supply area class per ``XWPExportConfig.supply_year``; the interim years
#: are one class with the attribute ``stuetzjahr``.
SUPPLY_AREA_CLASS = {
    "zieljahr": SUPPLY_AREA_TARGET,
    "2030": SUPPLY_AREA_INTERIM,
    "2035": SUPPLY_AREA_INTERIM,
    "2040": SUPPLY_AREA_INTERIM,
}

DECIMALS = 6  # of converted measures; F|Heat values carry no more


@dataclass(frozen=True)
class Attribute:
    """Where the export takes one attribute of a class from, and how it converts it.

    ``source`` says where the value comes from, ``name`` what it is called there:

    - ``"column"``: column of the F|Heat layer (a constant of :mod:`fheat_core.columns`)
    - ``"summary"``: key of the network's ``result_summary`` (a constant of :mod:`fheat_core.columns`)
    - ``"config"``: field of :class:`XWPExportConfig`
    - ``"network"``: field of the :class:`NetworkResult`
    - ``"rule"``: a value F|Heat derives, the function ``name`` in ``mappers.RULES``
    - ``"nested"``: a value of the data type ``name``, filled from its own table
    - ``"geometry"``: the geometry of the feature
    - ``"reference"``: set by the builder: ``"plan"``, ``"area"`` or ``"areas"``

    A measure carries the F|Heat ``unit``, the XWaermeplan unit ``uom`` and
    the ``factor`` between them; a code its ``code_list`` (checked in
    :class:`XWPExportConfig` and by xplan-tools, which reports a wrong code as
    a finding); ``cast`` turns a value into the type the schema asks for.
    """

    source: str
    name: str = ""
    unit: Optional[str] = None
    uom: Optional[str] = None
    factor: float = 1.0
    code_list: Optional[str] = None
    cast: Optional[type] = None

    def convert(self, value):
        """The XWaermeplan value of an F|Heat value; None for a missing or non-finite one."""
        if value is None:
            return None
        if self.uom is not None:
            value = float(value)
            if not math.isfinite(value):
                return None
            return {"value": round(value * self.factor, DECIMALS), "uom": self.uom}
        if self.code_list is not None:
            return str(value)
        return self.cast(value) if self.cast is not None else value


_HEAT = {"unit": "kWh/a", "uom": "MWh/a", "factor": 1e-3}
_METRE = {"unit": "m", "uom": "m"}
_GEOMETRY = Attribute("geometry")
_IN_AREA = Attribute("reference", "area")

#: class or data type -> attribute -> where it comes from. Exactly what the export writes.
CLASSES: dict[str, dict[str, Attribute]] = {
    PLAN: {
        "name": Attribute("config", "plan_name"),
        "planungsverantwortlicheStelle": Attribute("nested", MUNICIPALITY),
        "verfahrensart": Attribute("config", "procedure", code_list="WP_VerfahrenArt"),
        "gesetzlicheGrundlage": Attribute("config", "legal_basis", code_list="WP_GesetzlicheGrundlage"),
        "zieljahr": Attribute("config", "target_year", cast=str),
        "basisJahrDatenerfassung": Attribute("config", "base_year", cast=str),
        "beschlussDatum": Attribute("config", "decision_date"),
        "raeumlicherGeltungsbereich": _GEOMETRY,
        "bereich": Attribute("reference", "areas"),
    },
    MUNICIPALITY: {
        "name": Attribute("config", "municipality_name"),
        "regionalSchluessel12": Attribute("config", "resolved_regional_key"),
    },
    AREA: {
        "nummer": Attribute("config", "area_number"),
        "name": Attribute("config", "area_name"),
        "geltungsbereich": _GEOMETRY,
        "gehoertZuPlan": Attribute("reference", "plan"),
    },
    HEAT_LINE: {
        "position": _GEOMETRY,
        "waermeMenge": Attribute("column", cols.HEAT_DEMAND, **_HEAT),
        "waermelinienDichte": Attribute("column", cols.HEAT_LINE_DENSITY, unit="kWh/(a·m)", uom="MWh/(m*a)",
                                        factor=1e-3),
        "laenge": Attribute("column", cols.LENGTH, **_METRE),
        "gehoertZuBereich": _IN_AREA,
    },
    HEAT_NETWORK: {
        "position": _GEOMETRY,
        "netzID": Attribute("network", "key"),
        "name": Attribute("network", "name"),
        "betreiber": Attribute("network", "operator"),
        "medium": Attribute("config", "network_medium", code_list="WP_Transportmedium"),
        "laenge": Attribute("summary", cols.TOTAL_ROUTE_LENGTH, **_METRE),
        "anzahlGebaeudeAnschluss": Attribute("summary", cols.TOTAL_BUILDINGS, cast=int),
        "status": Attribute("config", "network_status", code_list="WP_Status"),
        "temperatur": Attribute("summary", cols.SUPPLY_TEMPERATURE, unit="°C", uom="°C"),
        "eeNachEnergietraeger": Attribute("nested", FINAL_ENERGY),
        "gehoertZuBereich": _IN_AREA,
    },
    FINAL_ENERGY: {
        "energietraeger": Attribute("config", "source_energy_carrier", code_list="WP_Energietraeger"),
        "endenergie": Attribute("rule", "heat_fed_in", unit="MWh/a", uom="MWh/a"),
    },
    SUPPLY_AREA_TARGET: {
        "position": _GEOMETRY,
        "versorgungsart": Attribute("config", "supply_type", code_list="WP_WaermeversorgungsgebietTyp"),
        "waermeMenge": Attribute("column", cols.HEAT_DEMAND, **_HEAT),
        "eignungDezentraleVersorgung": Attribute("rule", "no_statement", code_list="WP_Eignungsstufe"),
        "eignungWaermenetz": Attribute("rule", "suitability", code_list="WP_Eignungsstufe"),
        "eignungWasserstoffnetz": Attribute("rule", "no_statement", code_list="WP_Eignungsstufe"),
        "gehoertZuBereich": _IN_AREA,
    },
    SUPPLY_AREA_INTERIM: {
        "position": _GEOMETRY,
        "versorgungsart": Attribute("config", "supply_type", code_list="WP_WaermeversorgungsgebietTyp"),
        "waermeMenge": Attribute("column", cols.HEAT_DEMAND, **_HEAT),
        "stuetzjahr": Attribute("rule", "interim_year", code_list="WP_Stuetzjahr"),
        "gehoertZuBereich": _IN_AREA,
    },
}

#: XWPExportConfig field -> code list its codes must come from
CONFIG_CODE_LISTS = {
    attribute.name: attribute.code_list
    for attributes in CLASSES.values()
    for attribute in attributes.values()
    if attribute.source == "config" and attribute.code_list is not None
}


@dataclass(frozen=True)
class Condition:
    """A conformity condition of the schema documentation that the XSD does not enforce.

    ``attributes`` of ``class_name`` are mandatory where ``applies(config, properties)`` holds.
    """

    class_name: str
    attributes: tuple[str, ...]
    reason: str
    applies: Callable[[Any, dict], bool]


SMALL_HEAT_PLANNING = "2000"  # WP_VerfahrenArt
EXISTING = "1000"             # WP_Status

CONFORMITY = (
    Condition(SUPPLY_AREA_TARGET, ("eignungDezentraleVersorgung", "eignungWaermenetz", "eignungWasserstoffnetz"),
              "only optional in the small heat planning (verfahrensart 2000)",
              lambda config, properties: config.procedure != SMALL_HEAT_PLANNING),
    Condition(HEAT_NETWORK, ("medium", "temperatur"), "mandatory for existing networks (status 1000)",
              lambda config, properties: properties.get("status") == EXISTING),
)


def attributes() -> Iterator[tuple[str, str, Attribute]]:
    """``(class, attribute name, attribute)`` of every attribute the export writes."""
    for class_name, table in CLASSES.items():
        for name, attribute in table.items():
            yield class_name, name, attribute


def geometry_property(class_name: str) -> str:
    """The attribute that holds the geometry of ``class_name``."""
    return next(name for name, attribute in CLASSES[class_name].items() if attribute.source == "geometry")


def written_from(class_name: str, source: str, name: str) -> tuple[str, Attribute]:
    """``(attribute name, attribute)`` of ``class_name`` filled from ``source`` ``name``."""
    return next(
        (prop, attribute) for prop, attribute in CLASSES[class_name].items()
        if (attribute.source, attribute.name) == (source, name)
    )


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
