# XWärmeplan mapping

F|Heat → XWärmeplan 0.9.6, as implemented in [`fheat_core/export/xwp/`](../src/fheat_core/export/xwp/). Status 22.10.2026.

Every exported class has a table of its attributes in `mapping.py` (`CLASSES`): for each attribute the source (a column of an F|Heat layer or a key of the network summary, both as constants of `fheat_core/columns.py`, a field of `XWPExportConfig`, a field of the network, a rule F|Heat derives, a nested data type, the geometry or a reference set by the builder), the F|Heat unit, the XWärmeplan unit with the factor between them and the code list. `mappers.py` picks the F|Heat objects and fills each class from its table; the few values F|Heat derives (suitability stage, interim year, heat fed into a network; id, building type and construction period of a building block) are the `RULES` there. The rest of the export names no class, attribute or code of XWärmeplan, so a change of the standard touches `mapping.py` and the test data.

Three tests keep the table honest: `tests/test_xwp_mapping.py` against the model of xplan-tools 1.26; `tests/test_xwp_evidence.py` against the original of the XLeitstelle (XSD and feature catalogue, without xplan-tools) and against F|Heat, every source has to exist in the F|Heat schemas (`schemas.py`), so a renamed column fails a test before an export; `tests/test_xwp_mappers.py` that the records hold exactly the attributes of the table and that the export reads no column or summary key as text.

Version 1 writes `WP_Plan` with one `WP_Bereich` (mode `plan`) or only the `WP_Bereich` (mode `fragment`), plus `WP_Waermelinie`, `WP_Waermenetz`, one class of supply areas and the heated buildings as `WP_GebaeudeBaublock` (E12). GML is checked against the XSD. JSON-FG is written as xplan-tools writes it (measures as `{value, uom}`, references as bare UUIDs); that does not validate against the official JSON schema yet.

## Guiding rule

F|Heat writes what it computes in the XWärmeplan standard; it is not a tool for the heat planning itself. The technical plan (Philipp Sommer, 19.10.2026) sets the scope: what F|Heat does not compute comes from `XWPExportConfig` with that plan's defaults. Nothing beyond it except the building blocks (E12): no further object types, no decisions per area, no editing of plan content. Where the technical plan and the standard disagree, the technical plan applies unless the output would not conform; then the standard applies (decisions E1–E4 below).

## Sources

Every row names its source in the column **Source**:

| Short | Source |
| --- | --- |
| XSD | `waermeplan.xsd` 0.9.6, element and multiplicity (`tests/fixtures/xwp/xsd-0.9.6/`, Git blob `7898e8b`) |
| OAK | feature catalogue 0.9.6, unit of a measure (`objektartenkatalog/XWaermeplan096.zip`, extract in `tests/fixtures/xwp/oak-0.9.6-einheiten.json`) |
| TP | technical plan, section "Mapping matrix" unless named otherwise |
| LANUV | the building data of the LANUV NRW, `KWP-NRW_meta.zip` in [opengeodata.nrw.de/produkte/umwelt_klima/energie/kwp/](https://www.opengeodata.nrw.de/produkte/umwelt_klima/energie/kwp/): "Kurzdokumentation Raumwärmebedarfsmodell NRW" (version 2, 17.12.2024) and the column documentation `Dokumentation_Spalten_Raumwaerme.xlsx` |
| ALKIS | ALKIS object catalogue, attribute `gebaeudefunktion` of `AX_Gebaeude` ([ALKIS-OK des Freistaates Sachsen](https://www.landesvermessung.sachsen.de/content/Anlage_01_ALKIS-OK_SN.html), on the AFIS-ALKIS-ATKIS application schema) |
| Interpretation | neither says it; reason in the section below |

## Plan and area

| XWärmeplan | Source | Transformation | Source |
| --- | --- | --- | --- |
| `WP_Plan.name` | `XWPExportConfig.plan_name` | | XSD `WP_Plan/name` 1..1; TP |
| `WP_Plan.planungsverantwortlicheStelle` | `municipality_name`, `municipality_key` | `WP_Gemeinde` with `name` and `regionalSchluessel12` = RS (rule below) or `regional_key` | XSD `WP_Plan/planungsverantwortlicheStelle` 1..1, `WP_Gemeinde/name` 1..1; TP |
| `WP_Plan.verfahrensart` | `procedure` | default 1000 Regelverfahren | XSD `WP_VerfahrenArtType`; TP |
| `WP_Plan.gesetzlicheGrundlage` | `legal_basis` | default 1000 WPG | XSD `WP_GesetzlicheGrundlageType`; TP |
| `WP_Plan.zieljahr` | `target_year` | default 2045, as text | XSD `WP_Plan/zieljahr` 1..1 (string); TP |
| `WP_Plan.basisJahrDatenerfassung` | `base_year` | as text | XSD 1..1 (string); TP |
| `WP_Plan.beschlussDatum` | `decision_date` | mandatory in 0.9.6; a draft without it uses `mode="fragment"` | XSD `WP_Plan/beschlussDatum` 1..1; TP "Risks" |
| `WP_Plan.raeumlicherGeltungsbereich` | `boundary=` of the export, else union of `parcels_gdf` | MultiPolygon | XSD 1..1 MultiSurface; TP |
| `WP_Bereich.nummer`, `.name` | `area_number` (0), `area_name` ("F\|Heat") | | XSD `WP_Bereich/nummer`, `/name` 1..1; Interpretation (values) |
| `WP_Bereich.geltungsbereich` | plan boundary | | XSD 0..1 MultiSurface |
| `WP_Bereich.gehoertZuPlan` | the `WP_Plan`; in mode fragment `plan_id`, without one `uuid5` of the RS | the municipality's plan, not in the file; a derived id is named in the report's notes | XSD `WP_Bereich/gehoertZuPlan` 1..1; decision 21.10.2026 |

**Regionalschlüssel.** Since 2009 a municipality outside any association repeats its three-digit code after a 0: RS = AGS[0:5] + "0" + AGS[5:8] + AGS[5:8]. Steinfurt 05566084 → 055660084084, Münster (kreisfrei) 05515000 → 055150000000. Every NRW municipality is outside any association; the NRW adapter gives the AGS as `NRWDataAdapter.municipality_key`. For a member of an Amt, Samt- or Verbandsgemeinde the RS has to be passed as `regional_key`. Source: Destatis (Krajzar, "Methoden – Verfahren – Entwicklungen" 1/2009), not XWärmeplan; the technical plan's form `ss r kk 0000 ggg` is the one before 2009 and gives the same key only for kreisfreie Städte.

## WP_Waermelinie (WPG Anlage 2 I.2.2)

| XWärmeplan | Source (`wld_gdf`) | Transformation | Source |
| --- | --- | --- | --- |
| `position` | geometry | LineString → MultiLineString | XSD 1..1 MultiCurve; TP |
| `waermeMenge` | `heat_demand` (kWh/a) | ÷ 1000 → MWh/a | XSD 0..1; OAK MWh/a; TP |
| `waermelinienDichte` | `heat_line_density` (kWh/(a·m)) | ÷ 1000 → MWh/(m·a) | XSD 0..1; OAK MWh/(m*a); TP |
| `laenge` | `length` (m) | unchanged | XSD 0..1; OAK m; TP |

Segments without heat demand or length are left out. A segment that leaves the plan boundary is cut to it (TP "Consistency": geometries inside the area): `laenge` is the length inside, `waermelinienDichte` stays, `waermeMenge` = density × that length; a part shorter than 0.5 m is left out. The report's notes name how many segments were cut and how much heat demand lies outside. The density rule spreads a segment's heat demand evenly along the street, so the part outside takes its share even when the buildings it serves lie inside.

## WP_Waermenetz (WPG Anlage 2 I.2.8 a)

One per `NetworkResult` (a pipeline state in phase RESULTS).

| XWärmeplan | Source | Transformation | Source |
| --- | --- | --- | --- |
| `position` | every edge of `net_gdf` (route, house and source connections) | buffered by `network_buffer`, default `buffer_distance` of `FHeatConfig` (50 m), dissolved; cut to the plan boundary | XSD 1..1 MultiSurface (via `WP_Flaechenobjekt`); TP; E4 |
| `laenge` | `result_summary.total_route_length_m` | m, route without house connections | XSD `WP_ThermischeNetze/laenge` 1..1; OAK m; TP |
| `anzahlGebaeudeAnschluss` | `result_summary.total_buildings` | connected buildings, not house-connection edges | XSD 1..1 "Anzahl der Gebäude mit Anschluss an das Netz"; TP |
| `status` | `network_status`, the same for every network | default 3000 potenziell | XSD `WP_StatusType`, 1..1; TP |
| `medium` | `network_medium` | default 1000 Wasser | XSD `WP_TransportmediumType`, 0..1 (mandatory for existing networks); TP |
| `temperatur` | `result_summary.supply_temperature_c` | °C | XSD 0..1; OAK °C; TP |
| `name`, `netzID`, `betreiber` | `NetworkResult.name`, `.key`, `.operator` | | XSD 0..1 each |
| `eeNachEnergietraeger` | `source_energy_carrier` + `total_heat_demand_mwh_a + total_loss_mwh_a` | only when the carrier is set | XSD 0..1, `WP_EndenergieEnergietraeger` with `energietraeger` and `endenergie` 1..1; OAK MWh/a; TP; E3 |

## Supply areas

`supply_year` picks the class: `"zieljahr"` → `WP_WaermeversorgungsgebietZieljahr`, `"2030"`/`"2035"`/`"2040"` → `WP_WaermeversorgungsgebietStuetzjahr` with `stuetzjahr` 1000/2000/3000 (XSD `WP_StuetzjahrType`; TP). One area per suitability polygon (`polygons_gdf`).

| XWärmeplan | Source | Transformation | Source |
| --- | --- | --- | --- |
| `position` | geometry | cut to the plan boundary: the polygons are parcels buffered by `buffer_distance` | XSD 1..1 MultiSurface; TP "Consistency" |
| `versorgungsart` | `supply_type`, the same for every area | default 40001 Prüfgebiet Wärmenetz; F\|Heat makes no decision per area | XSD `WP_WaermeversorgungsgebietTypType`, 1..1; TP |
| `waermeMenge` | `heat_demand` (kWh/a) | ÷ 1000 → MWh/a | XSD 0..1; OAK MWh/a; TP |
| `eignungDezentraleVersorgung`, `eignungWasserstoffnetz` (target year only) | rule "no_statement" | 5000 for a Prüfgebiet or the simplified procedure (E2), else not written: F\|Heat does not assess decentral or hydrogen supply | XSD `WP_EignungsstufeType`, 0..1, conformity condition "only optional in the small heat planning"; E2 |
| `eignungWaermenetz` (target year only) | rule "suitability": `heat_demand_density` with `suitability_thresholds` | 5000 for a Prüfgebiet or the simplified procedure (E2); otherwise the stage from the thresholds, not written without them, see below | XSD `WP_EignungsstufeType`, 0..1, same condition; TP; E2 |

**Why no suitability from the density by default.** The suitability polygons are dissolved, buffered parcels, so their heat demand density is far below the block density the guideline thresholds refer to. In the Burgsteinfurt example one polygon covers 119 of 151 ha with 132 MWh/(ha·a); with the KEA-BW thresholds (415/175/70) the area of the 5.2 km network would be "wahrscheinlich ungeeignet".

## WP_GebaeudeBaublock (WPG Anlage 2 I.2.5, I.2.6)

WPG § 3, quoted by the XSD at `WP_Baublock`: a "Baublock" is "ein Gebäude oder mehrere Gebäude oder Liegenschaften", bounded on several or all sides by streets or other borders. F\|Heat writes every heated building (`heat_demand` > 0) as a block of its own, with its footprint (E13): "ein Gebäude" in the definition. A building counts when its representative point lies inside the plan boundary; its footprint is cut to it. Unheated buildings and buildings outside the plan boundary belong to no block; the notes count the heated ones outside.

| XWärmeplan | Source (`buildings_gdf`) | Transformation | Source |
| --- | --- | --- | --- |
| `position` | the footprint | cut to the plan boundary, MultiPolygon | XSD 1..1 MultiSurface (via `WP_Flaechenobjekt`); E13 |
| `baublockId` | key of the block | hash of its area (as the feature id) | XSD `WP_Baublock/baublockId` 0..1; S8 |
| `gebaeudetyp` | `function`, else `building_type` | see below | XSD 1..1 `WP_GebaeudeTypType`; E14 |
| `ueberwiegendBaujahr` | `construction_year`, else `age` | the main category, see below | XSD 1..1 `WP_BaualtersklasseType`; E15 |
| `nutzflaeche` | `floor_area` (m²) | ÷ 10 000 → ha, the building's also when its footprint is cut; not written without | XSD 0..1 "Gesamtnutzfläche der Gebäude im Baublock in Hektar"; OAK ha; LANUV `NF` "Nutzfläche (Energiebezugsfläche)" |

**Building type of a building (E14).** First the ALKIS building function (`function`, four digits, also in the CityGML form `31001_1010`), in `mapping.FUNCTION_TYPES` for every one of the 232 functions the NRW adapter knows (`tests/test_xwp_evidence.py`). ALKIS records the predominant use ("Gebäudefunktion ist die zum Zeitpunkt der Erhebung vorherrschend funktionale Bedeutung des Gebäudes (Dominanzprinzip)"); `WP_GebaeudeTyp` 1000 is the Wohngebäude of GEG § 3, "überwiegend dem Wohnen", including homes.

| WP_GebaeudeTyp | ALKIS function | Reason |
| --- | --- | --- |
| 1000 | 1000 Wohngebäude, 1010 Wohnhaus, 1020–1025 Wohnheime (Kinder-, Senioren-, Schwestern-, Studenten-, Schullandheim), 1110 Wohngebäude mit Gemeinbedarf, 1210 Land- und forstwirtschaftliches Wohngebäude, 1311 Ferienhaus, 1312 Wochenendhaus, 3064 Obdachlosenheim, 3066 Asylbewerberheim | a Wohngebäude, or a home, which GEG § 3 counts with them. 1110: the subtype would follow the number of dwellings, which F\|Heat does not know (decision 22.10.2026) |
| 10001 | 1221 Bauernhaus, 1223 Forsthaus | decision 22.10.2026 |
| 10004 | 1100 Gemischt genutztes Gebäude mit Wohnen, 3052 Heilanstalt, Pflegeanstalt, Pflegestation | decision 22.10.2026 |
| 9999 | 9998 nach Quellenlage nicht zu spezifizieren | the source does not know the use |
| 20001 | 1121 Wohn- und Verwaltungsgebäude, 1122 Wohn- und Bürogebäude, 2020 Bürogebäude, 2030 Kreditinstitut, 2040 Versicherung, 2310 Gebäude für Handel und Dienstleistung mit Wohnen, 3010–3019 (Verwaltung, Parlament, Rathaus, Post(amt), Zollamt, Gericht, Botschaft, Kreisverwaltung, Bezirksregierung, Finanzamt) | "Büro-, Verwaltungs-, Amtsgebäude"; 1121, 1122, 2310: decision 22.10.2026 |
| 20002 | 1120 Wohngebäude mit Handel und Dienstleistungen, 1123 Wohn- und Geschäftsgebäude, 1222 Wohn- und Wirtschaftsgebäude, 2051–2056 Kaufhaus, Einkaufszentrum, Markthalle, Laden, Kiosk, Apotheke | "Gebäude des Groß- und Einzelhandels"; 1120, 1123, 1222: decision 22.10.2026 |
| 20003 | 2070–2073 Beherbergung (Hotel, Jugendherberge, Hütte mit Übernachtung), 2080–2083 Bewirtung (Gaststätte, Hütte ohne Übernachtung, Kantine) | "Beherbergung und Gastronomie" |
| 20004 | 3051 Krankenhaus, 3242 Sanatorium | "Krankenhäuser" |
| 20005 | 2092 Kino, 3030–3038 Gebäude für kulturelle Zwecke (Schloss, Theater, Konzertgebäude, Museum, Rundfunk, Veranstaltungsgebäude, Bibliothek, Burg), 3100 Gebäude für öffentliche Zwecke mit Wohnen | "Kultureinrichtungen"; 3100: decision 22.10.2026 |
| 20006 | 2160 Gebäude für Forschungszwecke, 3020–3024 Bildung und Forschung (allgemein und berufsbildende Schule, Hochschule, Forschungsinstitut), 3065 Kinderkrippe, Kindergarten, Kindertagesstätte | "Bildungseinrichtungen" |
| 20007 | 3210–3212 Sport, Turnhalle, Gebäude zum Sportplatz, 3230 Gebäude im Stadion | "Sporteinrichtungen" |
| 20008 | 3220–3222 Badegebäude, Hallenbad, Gebäude im Freibad, 3241 Badegebäude für medizinische Zwecke | "Schwimmbäder" |
| 20009 | 2140–2143 Vorratshaltung, Kühlhaus, Speicher, Lager; 2150 Speditionsgebäude | "Lagergebäude" |
| 20010 | 1130 Wohngebäude mit Gewerbe und Industrie, 1131 Wohn- und Betriebsgebäude, 1220 Land- und forstwirtschaftliches Wohn- und Betriebsgebäude, 2320 Gebäude für Industrie mit Wohnen, 2100–2121 Gewerbe und Industrie, Produktion, Fabrik, Betriebsgebäude, Brauerei, Brennerei, Werkstatt, Sägewerk; 2170–2172 Grundstoffgewinnung; 2200–2213 sonstige Gebäude für Gewerbe und Industrie, Mühlen, Schöpfwerk | "Industrie und Gewerbe"; 1130, 1131, 1220, 2320: decision 22.10.2026 |
| 2000 | every other function of the groups Wirtschaft oder Gewerbe (2xxx) and öffentliche Zwecke (3xxx), 1310 Gebäude zur Freizeitgestaltung, 1313 Gartenhaus | not predominantly Wohnen, no fitting subtype |

Without a known function the building type of F\|Heat (`building_type`) decides: EFH, RH, MFH and GMFH → 1000, NWG → 2000, anything else → 9999. LANUV names these the residential types (`WG_Typ`: "EFH = Ein- und Zweifamilienhaus, RH = Reihenhaus, MFH = Mehrfamilienhaus, GMFH = Großes Mehrfamilienhaus (inkl. Hochhäuser)") and separates them by touching buildings and floor area ("EFH: max. zwei Hauptgebäude, die sich berühren, mit max. 280 m² Nutzfläche; RH: min. drei …; MFH: Nutzfläche 280–400 m²; GMFH: > 400 m²", Kurzdokumentation, "Gebäudemerkmale" 7). The subtypes 10001–10004 count dwellings (1–2 freistehend, 1–2 gereiht, 3–12, 13 and more), which the LANUV types do not tell, so only the main category 1000 is verifiable. The NRW adapter sets NWG for every LANUV `WG_NWG` = NWG; the flex adapter documents EFH, RH, MFH and GMFH.

**Construction period of a building (E15).** First the construction year (`construction_year`, flex adapter), else the LANUV age class (`age`, the year after the type in `GEBAEUDETY`: "Wohngebäudetyp + Baualtersklasse"), else 9999. The NRW `BAK` is not used: it comes from `validFrom`, the date of the parcel record. Written is the main category; a LANUV class across two categories gets the one with the larger part of its years, an even split would be 9999 (`mapping.construction_period`). A building the NRW adapter merged from parts of different classes ("1945, 2022") is 9999 unless the classes fall into one category.

| LANUV class | years (LANUV, "Gebäudemerkmale" 3) | WP_Baualtersklasse |
| --- | --- | --- |
| 1900 | vor 1900 | 1000 bis 1949 |
| 1945 | 1900 bis 1945 | 1000 |
| 1960 | 1946 bis 1960 | 2000 1950–1969 (11 of 15 years) |
| 1970 | 1961 bis 1970 | 2000 (9 of 10) |
| 1980, 1985 | 1971 bis 1980, 1981 bis 1985 | 3000 1970–1989 |
| 1995 | 1986 bis 1995 | 4000 1990–2015 (6 of 10) |
| 2000, 2005, 2010, 2015 | 1996 bis 2000 … 2011 bis 2015 | 4000 |
| 2022 | ab 2016 | 5000 ab 2016 |

The years of the main categories are checked against the XSD (`tests/test_xwp_evidence.py`).

**Not written.**

- `WP_EnergieBaublock`: its `waermeMenge` and `waermeDichte` are "Erzeugernutzwärme" (XSD), the heat the generators deliver, losses in the building included. F\|Heat's heat demand is useful heat: LANUV "Raumwärmebedarf (Nutzenergie)" plus hot water, or the calculated demand. F\|Heat has no Erzeugernutzwärme, and without the two the class would carry nothing. The heat lines and supply areas take the heat demand, because their XSD documentation asks for "Wärmeverbrauch oder Wärmebedarf" without that restriction.
- `verteilungBaujahr`: optional, the predominant category is what the plan asks for.

**Data protection.** A block is a single building; whether the municipality publishes them at this resolution is its decision. The report's notes say so whenever blocks are written.

## Feature ids

`uuid5(<F|Heat namespace>, "<RS>/<feature type>/<key>")`, so reruns and plan updates keep the ids (TP "Architecture"):

| Feature | Key | Source |
| --- | --- | --- |
| `WP_Plan` | plan name (mode plan) | TP |
| `WP_Bereich` | `<plan name, plan_id or "">/<nummer>/<hash of the boundary>` | TP; the boundary keeps two exports into one plan apart |
| `WP_Waermelinie`, supply areas | hash of the geometry, normalised and rounded to 0.1 m | Interpretation: the WLD has no stable street id |
| `WP_Waermenetz` | `NetworkResult.key`, else its name, else `N01`, `N02`, … | TP |
| `WP_GebaeudeBaublock` | hash of its area, also written as `baublockId` | Interpretation: a building id of the data source is no canonical column of F\|Heat (`building_id` is a running number) |

A second feature with the same key gets `#2`. Geometry `gml:id`s and the root `gml:id` are new on every write (xplan-tools). In mode fragment without `plan_id` the area refers to `uuid5(<F|Heat namespace>, "<RS>/WP_Plan")`, the same for every export of the municipality.

## Checks

The report collects all findings instead of stopping at the first, and **files are written only when there is none**: the export writes to `<name>.partial.<suffix>` next to the target, checks, and moves the files into place only without findings, so a written file is verifiably conformant (TP "Validation and testing"):

1. **structure**: xplan-tools validates every feature (mandatory fields, code lists, extra fields) and the references. In mode fragment a stand-in for the municipality's plan takes the place of the plan outside the file, so every other reference is checked as well. Nothing is written then.
2. **schema**: the GML against the XSD, offline through an XML catalog (`schema_dir=`, test data in `tests/fixtures/xwp/xsd-0.9.6/`). The XSD is not shipped: the repository `spezifikation` has no licence file. Without `schema_dir` the notes say so; the tests check the writer against the XSD in CI.
3. **consistency**: valid, non-empty geometries inside the plan boundary (0.5 m tolerance); the heat lines carry the heat demand of the street segments inside the plan boundary (computed apart from the mapper); `laenge` of a network equals its route length; the supply areas carry the heat demand of the suitability polygons inside the plan boundary; every heated building inside the plan boundary lies in exactly one building block, and the blocks carry the floor area of these buildings when every one has a floor area (both computed apart from the mapper). A geographic CRS is rejected before anything is built.
4. **conformity**: the conformity conditions of the XSD documentation the schema does not enforce (`mapping.CONFORMITY`): the three suitability stages of a target-year area outside the small heat planning (`verfahrensart` 2000), `medium` and `temperatur` of an existing network (`status` 1000).

Besides the findings the report carries **notes**, which do not make it fail: which plan boundary was used (passed or the union of the parcels), how many heat lines were cut at it with the heat demand outside, which map features lie wholly outside it and were left out, how many heated buildings lie outside it and belong to no building block, that building blocks are single buildings (data protection), whether the GML was checked against the XSD, and, in mode fragment, the derived plan id and that `WP_Bereich.nummer` has to be unique within the municipality's plan (XSD documentation of `nummer`).

## Not mapped

No XWärmeplan slot: nominal diameters, flow velocities, volume flows, simultaneity factor, heat losses per edge, the hourly load profile. They stay in the F|Heat GeoPackage and tables (TP). Out of scope for version 1 (TP "Summary"): the rest of the stock analysis (`WP_EnergieBaublock`, see above), energy balance, aggregates, measures, the heat source (`source_gdf`; XSD 0.9.6 has no class for a feed-in point or a generation plant).

## Interpretations

Where neither the standard nor the technical plan decides:

- **Ids from a geometry hash** for heat lines and supply areas: the WLD has no stable street id, and the standard does not regulate ids (`implementierung`, `Referenzplaene/readme.md`).
- **`WP_Bereich` number 0, name "F|Heat"**: the XSD only asks for both; numbers start at 0 by default (XSD documentation of `nummer`).

## Decisions (E1–E4)

| | Technical plan | Standard | Decision | Implemented |
| --- | --- | --- | --- | --- |
| E1 Version | 0.9.5 with xplan-tools 1.20 on Python 3.12 | 0.9.6 is the newest version xplan-tools supports (1.26.0), 0.9.7 the newest of the standard | 0.9.6 with xplan-tools 1.26 on Python 3.13 (ADR 0002); 0.9.7 once xplan-tools supports it | yes |
| E2 Suitability from thresholds | stage from the heat demand density, thresholds in the config | code 5000 means "no statement necessary or possible (either simplified procedure or supply type Prüfgebiet)" | supply type Prüfgebiet (4000, 40001–40003) or simplified procedure (`verfahrensart` 3000) → 5000 in `eignungDezentraleVersorgung`, `eignungWaermenetz`, `eignungWasserstoffnetz`; thresholds only otherwise; option stays, off by default. Other supply types outside the small heat planning need all three stages, which F\|Heat cannot give; the conformity check stops such an export | yes |
| E3 Energy carrier of the source | code from the config, quantity from F\|Heat | `eeNachEnergietraeger` is described "for status Bestehend" without a conformity condition | no conflict: written when the config names a carrier, else not | yes |
| E4 Network area | buffer around all edges, dissolved, width configurable, default `buffer_distance` | only asks for a MultiSurface | buffer around all edges of `net_gdf` (route, house and source connections), dissolved, cut to the plan boundary; width `network_buffer`, default the calculation's `buffer_distance` (50 m); no planning area | yes |
| E12 Building data | version 1 without building blocks | `WP_Baublock`: "ein Gebäude oder mehrere Gebäude oder Liegenschaften" (WPG § 3) | the heated buildings as `WP_GebaeudeBaublock` (decision 22.10.2026); no `WP_EnergieBaublock`, whose heat values are Erzeugernutzwärme | yes |
| E13 Area of a block | – | "ein Gebäude" is a block | every heated building with its footprint (decision 22.10.2026) | yes |
| E14 Building type | – | `WP_GebaeudeTyp`, 1000 after GEG § 3 | ALKIS function, else the LANUV type to the main category, else 9999 | yes |
| E15 Construction period | – | `WP_Baualtersklasse` | construction year, else the LANUV age class, to the main category with the larger part; else 9999 | yes |

Further decisions of 21.10.2026, implemented: in mode `fragment` the municipality's `plan_id` is optional (without it, an id derived from the RS and a note in the report); the supply type and suitability per area (`SupplyDecision`) and the status per network are dropped, the config's values apply to every area and network.

## Open

Nothing.

## xplan-tools 1.26: handled in the writer

- The GML writer takes the envelope of the plan geometry and fails without a `WP_Plan`; for a fragment F\|Heat builds the root and lets xplan-tools serialise each feature.
- xplan-tools reads a file only as a whole collection and rejects a fragment: `gehoertZuPlan` points outside the file, and a mandatory reference is never dropped, not even with `DROP_INVALID_REFS`. A fragment is meant for merging into the municipality's plan, not for reading on its own; `writer.read_features` reads its features one by one with the models of xplan-tools (used by the round-trip test).
- `schemaLocation` points to `xsd/waermeplan.xsd` on `main`, which is 0.9.7 since 13.10.2026, and JSON-FG's `describedby` to `json/0.9/`, which does not exist; both are rewritten to the 0.9.6 paths.
- `BaseCollection.from_features` needs the features as a dict; `repo_factory` is deprecated in favour of `Datasource(...).repo()`.
