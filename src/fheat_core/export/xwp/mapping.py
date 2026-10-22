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

BUILDING_TYPE = {  # WP_GebaeudeTyp
    "1000": "Wohngebäude",
    "10001": "Einfamilienhaus",
    "10002": "Reihenhaus",
    "10003": "Mehrfamilienhaus (3-12 WE)",
    "10004": "Großes Mehrfamilienhaus (>=13 WE)",
    "2000": "Nichtwohngebäude",
    "20001": "Bürogebäude",
    "20002": "Handel",
    "20003": "Beherbergung/Gaststätten",
    "20004": "Krankenhäuser",
    "20005": "Kultureinrichtungen",
    "20006": "Bildungseinrichtungen",
    "20007": "Sporteinrichtungen",
    "20008": "Schwimmbäder",
    "20009": "Lagergebäude",
    "20010": "Industrie",
    "9999": "unbekannt",
}

CONSTRUCTION_PERIOD = {  # WP_Baualtersklasse
    "1000": "bis 1949 (OK)",
    "10001": "vor 1919",
    "10002": "1919 - 1949",
    "2000": "1950 - 1969 (OK)",
    "20001": "1950 - 1959",
    "20002": "1960 - 1969",
    "3000": "1970 - 1989 (OK)",
    "30001": "1970 - 1979",
    "30002": "1980 - 1989",
    "4000": "1990 - 2015 (OK)",
    "40001": "1990 - 1999",
    "40002": "2000 - 2009",
    "40003": "2010 - 2015",
    "5000": "ab 2016",
    "9999": "unbekannt",
}

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
    "WP_GebaeudeTyp": BUILDING_TYPE,
    "WP_Baualtersklasse": CONSTRUCTION_PERIOD,
}


def check_code(code_list: str, code) -> str:
    """``code`` as string if it is in the code list, else ValueError (no fallback to 9999)."""
    codes = CODE_LISTS[code_list]
    code = str(code)
    if code not in codes:
        raise ValueError(f"{code!r} is not a code of {code_list} ({', '.join(codes)}).")
    return code


# ------------------------------------------------------------------
# Building type and construction period of a building (E14, E15)
# ------------------------------------------------------------------

UNKNOWN = "9999"  # WP_GebaeudeTyp and WP_Baualtersklasse: "unbekannt"

#: ALKIS Gebäudefunktion (AX_Gebaeudefunktion, four digits) -> WP_GebaeudeTyp, by the meaning
#: of the function; a residential building with another use (Wohngebäude mit Handel …) gets
#: the code of that use. Every function the NRW adapter knows; the rows in docs/xwp_mapping.md.
FUNCTION_TYPES: dict[str, str] = {
    function: code
    for code, functions in {
        "1000": "1000 1010 1020 1021 1022 1023 1024 1025 1110 1210 1311 1312 3064 3066",
        "10001": "1221 1223",
        "10004": "1100 3052",
        "9999": "9998",
        "2000": (
            "1310 1313 2000 2010 2050 2060 2074 2090 2091 2093 2094 2130 2131 2180 2220 2400 2410 "
            "2411 2412 2420 2421 2422 2423 2424 2430 2431 2440 2441 2442 2443 2444 2450 2451 2460 "
            "2461 2462 2463 2464 2465 2500 2501 2510 2511 2512 2513 2520 2521 2522 2523 2527 2528 "
            "2529 2540 2560 2570 2571 2580 2590 2591 2600 2610 2611 2612 2620 2621 2622 2623 2700 "
            "2720 2721 2723 2724 2726 2727 2728 2729 2732 2735 2740 2741 2742 3000 3040 3041 3042 "
            "3043 3044 3045 3046 3047 3048 3050 3053 3060 3061 3062 3063 3070 3071 3072 3073 3074 "
            "3075 3080 3081 3082 3090 3091 3092 3094 3095 3097 3098 3200 3240 3260 3261 3262 3263 "
            "3264 3270 3271 3272 3273 3280 3281 3290"
        ),
        "20001": "1121 1122 2020 2030 2040 2310 3010 3011 3012 3013 3014 3015 3016 3017 3018 3019",
        "20002": "1120 1123 1222 2051 2052 2053 2054 2055 2056",
        "20003": "2070 2071 2072 2073 2080 2081 2082 2083",
        "20004": "3051 3242",
        "20005": "2092 3030 3031 3032 3033 3034 3035 3036 3037 3038 3100",
        "20006": "2160 3020 3021 3022 3023 3024 3065",
        "20007": "3210 3211 3212 3230",
        "20008": "3220 3221 3222 3241",
        "20009": "2140 2141 2142 2143 2150",
        "20010": (
            "1130 1131 1220 2100 2110 2111 2112 2113 2114 2120 2121 2170 2171 2172 2200 2210 2211 2212 2213 "
            "2320"
        ),
    }.items()
    for function in functions.split()
}

#: Building type of F|Heat (LANUV WG_Typ, or NWG) -> WP_GebaeudeTyp, where the function is not
#: known. LANUV tells EFH, RH, MFH and GMFH apart by touching buildings and floor area, the
#: subtypes 10001-10004 count dwellings, so only the main category is verifiable.
BUILDING_TYPE_CODES = {"EFH": "1000", "RH": "1000", "MFH": "1000", "GMFH": "1000", "NWG": "2000"}

#: The main categories of WP_Baualtersklasse: code -> (first year, last year), None = open
PERIOD_YEARS = {
    "1000": (None, 1949),
    "2000": (1950, 1969),
    "3000": (1970, 1989),
    "4000": (1990, 2015),
    "5000": (2016, None),
}

#: LANUV Baualtersklasse (the year after the type in GEBAEUDETY, F|Heat's age) -> its years
#: (Kurzdokumentation Raumwärmebedarfsmodell NRW, version 2 of 17.12.2024, "Gebäudemerkmale" 3)
AGE_CLASS_YEARS = {
    "1900": (None, 1899),
    "1945": (1900, 1945),
    "1960": (1946, 1960),
    "1970": (1961, 1970),
    "1980": (1971, 1980),
    "1985": (1981, 1985),
    "1995": (1986, 1995),
    "2000": (1996, 2000),
    "2005": (2001, 2005),
    "2010": (2006, 2010),
    "2015": (2011, 2015),
    "2022": (2016, None),
}


def construction_period(first: Optional[int], last: Optional[int]) -> str:
    """The main category of WP_Baualtersklasse that holds most of the years ``first`` to ``last``.

    None is an open end. A class that spans two categories gets the one with
    the larger part of its years (E15); an even split is unknown.
    """
    def span(start, end):
        return (-math.inf if start is None else start, math.inf if end is None else end)

    start, end = span(first, last)
    shares = {}
    for code, period in PERIOD_YEARS.items():
        period_start, period_end = span(*period)
        shares[code] = min(end, period_end) - max(start, period_start) + 1
    best = max(shares.values())
    codes = [code for code, share in shares.items() if share == best]
    return codes[0] if best > 0 and len(codes) == 1 else UNKNOWN


#: LANUV age class -> main category of WP_Baualtersklasse
AGE_PERIODS = {label: construction_period(*years) for label, years in AGE_CLASS_YEARS.items()}


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
BUILDING_BLOCK = "WP_GebaeudeBaublock"

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
            try:
                value = float(value)
            except TypeError:  # pandas' NA
                return None
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
    BUILDING_BLOCK: {
        "position": _GEOMETRY,
        "baublockId": Attribute("rule", "block_id"),
        "gebaeudetyp": Attribute("rule", "building_type", code_list="WP_GebaeudeTyp"),
        "ueberwiegendBaujahr": Attribute("rule", "construction_period", code_list="WP_Baualtersklasse"),
        "nutzflaeche": Attribute("column", cols.FLOOR_AREA, unit="m²", uom="ha", factor=1e-4),
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
