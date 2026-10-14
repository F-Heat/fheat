# Umsetzungsplan: XWärmeplan in F|Heat und F|Heat.connect

Stand: 12.10.2026 · Ziel: F|Heat bildet den Standard XWärmeplan vollständig ab und schreibt standardkonforme Dateien.
Schwerpunkt: Core (`fheat_core`) und Dateiausgaben. Die Web-Anbindung (`fheat-web`) folgt in den letzten Phasen.

Begleitdateien in diesem Ordner:

- `XWaermeplan_Modellreferenz_0.9.6.md`: alle 54 Klassen und 21 Aufzählungen des Standards mit Attributen, Multiplizitäten, Einheiten und der Spalte „Abdeckung durch F|Heat“.
- `xwp_0.9.6_modell.json`: dasselbe maschinenlesbar. Claude Code nutzt die Datei in Phase 1 als Abgleich für den Generator.

---

## 1. Ausgangslage

### 1.1 Standard

| Punkt | Befund |
|---|---|
| Aktuelle Version | **0.9.6**, Namespace `http://www.xwaermeplan.de/0/9/6`. Quelle: XPlan-Tools 1.26.0 (PyPI, 07.09.2026), Modul `xwp09.py`, aus dem UML-Modell generiert. |
| Online-Objektartenkatalog | xleitstelle.de zeigt noch **0.92 vom 02.01.2026**. Der Katalog ist veraltet: 0.9.6 hat u. a. `WP_Waermelinie` statt `WP_Waermeliniendichte`, `WP_EnergieBaublock` statt `WP_Waermeverbrauch`/`WP_DezentraleErzeugung`, `WP_Waermenetz` als Flächenobjekt, neue Kälte-Klassen, `WP_Energiebilanz` und `WP_WaermeinfrastrukturAggregiert`. |
| Status | Noch nicht verbindlich. FIT-SB hat am 26.06.2026 empfohlen, den Standard in den IT-Planungsrat einzubringen. Klassen und Attribute können sich bis zur Verabschiedung noch ändern, deshalb wird die Version im Code gekapselt (siehe 2.2). |
| Kodierungen | GML 3.2 (XSD im Repo `xleitstelle/xwaermeplan/spezifikation`, Pfad `xsd/waermeplan.xsd`), JSON-FG (`json/<version>/featurecollection.json`), Datenbank/GeoPackage. Das Repo `implementierung` enthält laut Beschreibung „weitere Implementierungsschemata und Referenzpläne“. |
| Geprüft in Phase 0 | XSD, JSON-Schema und Referenzpläne aus beiden GitLab-Repos sind lokal abgeglichen; Ergebnis in `abgleich.md` und `kodierung.md`. |

### 1.2 Code

| Repo | Stand, den ich gelesen habe | Relevantes |
|---|---|---|
| `fheat` | lokaler Fork `Pat-FHM/fheat`, Branch `fix/topotherm-street-geometry`, Commit `4181641` (09.10.) | Pipeline download → adjust → status → network → results. Ausgaben über `FHeatOrchestrator.save_outputs()`: Layer als GPKG/FGB/GeoJSON/OGR-GML, Tabellen (CSV/XLSX), Diagramme. `export/xplan.py` ist ein Platzhalter (`NotImplementedError`). |
| `fheat-web` | lokal, Branch `dev`, Commit `3ee8716` (12.10.) | Backend Python **3.12** (Dockerfile), installiert `fheat` per Git-Commit (`FHEAT_REF`). Ergebnisdateien je Netz über `artifacts.publish_result_artifacts()`. |

Wichtigste Lücken:

1. Kein XWärmeplan-Datenmodell, keine Plan-Metadaten (Gemeinde/ARS, Beschlussdaten, Verfahrensart, Zieljahr …).
2. Einheiten und Struktur passen nicht: F|Heat rechnet in kWh/a und kWh/(a·m), XWärmeplan erwartet MWh/a und MWh/(m·a); Flächen in ha.
3. Die Baualtersklassen von F|Heat (B…J, Grenzen 1918/1948/1957/1968/1978/1983/1994/2001) lassen sich nicht sauber auf `WP_Baualtersklasse` (Grenzen 1918/1949/1959/1969/1979/1989/1999/2009/2015) abbilden. Das Baujahr selbst muss als Spalte erhalten bleiben.
4. Es fehlt ein Gebäudetyp nach `WP_GebaeudeTyp` (heute nur Lastprofil EFH/MFH/GHA/GMK/GKO und ALKIS-Funktion).
5. Viele Klassen haben keine Datenquelle in F|Heat (Maßnahmen, Texte, Bestandsnetze, Schutzgebiete, Kälte …). Sie brauchen einen Import- bzw. Eingabeweg, sonst ist „vollständig“ nicht erreichbar.

### 1.3 Abdeckung (Kurzfassung, Details in der Modellreferenz)

| Abdeckung | Klassen |
|---|---|
| **A** automatisch | `WP_Bereich`, `WP_Waermelinie`, `WP_GebaeudeBaublock`, `WP_EnergieRaster` |
| **T** teilweise automatisch, Rest Eingabe | `WP_Plan`, `WP_EnergieBaublock`, `WP_Waermenetz`, `WP_WaermeversorgungsgebietZieljahr`/`Stuetzjahr`, `WP_Eignungspruefung`, `WP_EnergieeinsparungGebaeude`, `WP_Grossverbraucher`, `WP_PotenzialWaermenutzung`, `WP_Energiebilanz`, `WP_WaermeinfrastrukturAggregiert`, `WP_PotenzialanalyseAggregiert` |
| **E** nur Eingabe/Import | `WP_Massnahme`, `WP_TextAbschnitt`, `WP_WaermeversorgungsgebietUmsetzung`, `WP_Energieeinsparpotenzialgebiet`, `WP_NichtBeplantesTeilgebiet`, `WP_PotenzialWaermespeicherung`, `WP_Ausschlussgebiet`, `WP_Anschlusszwang`, `WP_AnschlussGruenesMethan`, `WP_WaermeKaelteNetz`, `WP_Kaeltenetz`, `WP_Kaeltelinie`, `WP_Kaelteversorgungsgebiet` |

„Vollständig aufnehmen“ heißt deshalb: **jede** Klasse kann im Programm gehalten, ergänzt, validiert und geschrieben werden. Was F|Heat berechnen kann, wird automatisch befüllt; der Rest kommt über eine Ergänzungsdatei (Core) bzw. Formulare (Web).

---

## 2. Architekturentscheidungen

### 2.1 Eigene Writer statt XPlan-Tools als Laufzeitabhängigkeit

XPlan-Tools kann XWärmeplan lesen, schreiben und konvertieren, verlangt aber **Python 3.13 (<3.14) und GDAL**. topotherm braucht genau 3.12, das Web-Backend läuft auf 3.12. Deshalb:

- `fheat_core` bekommt ein eigenes, schlankes Modell und eigene Writer (GML mit `lxml`, JSON-FG mit `json`, GeoPackage mit `geopandas`/`pyogrio`). Keine neue Pflichtabhängigkeit außer `lxml` im neuen Extra `[xwp]`.
- XPlan-Tools dient nur als **unabhängiger Prüfstein für GML in CI** (eigener Job mit Python 3.13): Es muss unsere GML-Dateien fehlerfrei einlesen können. Für JSON-FG taugt XPlan-Tools nicht als Prüfstein, weil es Messwerte als `{value, uom}` und Verweise als nackte UUID schreibt; das widerspricht dem offiziellen Schema.
- Zusätzlich XSD-Validierung mit `lxml` gegen die vendorte XSD und JSON-Schema-Validierung gegen das vendorte JSON-Schema.
- **Rangfolge:** Maßgeblich sind die offiziellen Schemas (XSD für GML, JSON-Schema für JSON-FG). Sie gelten vor den Referenzplänen und vor dem Verhalten von XPlan-Tools. F|Heat folgt dem Schema auch dann, wenn kein Referenzplan dagegen gültig ist. Abweichende Referenzpläne werden als Befund in `docs/xwaermeplan/abgleich.md` festgehalten.

### 2.2 Versionskapsel

```
src/fheat_core/xwp/
  __init__.py            # öffentliche API: build_plan(), write_gml(), write_jsonfg(), write_gpkg(), validate()
  spec/0.9.6/            # vendorte XSD, JSON-Schema, Lizenzhinweis
  model/
    v0_9_6.py            # GENERIERT: Dataclasses + Enums + Metadaten (Multiplizität, Einheit, XML-Reihenfolge)
    base.py              # Basistypen: Measure, Geometrie-Wrapper, Referenzen, Validierung
  mapping/               # F|Heat-State → XWP-Objekte (Fachlogik, versionsnah)
  encode/                # gml.py, jsonfg.py, gpkg.py (versionsneutral, metadatengetrieben)
  supplement/            # Ergänzungsdatei lesen/Vorlage erzeugen
  decode/gml.py          # Rückleser für Round-Trip-Tests und Import bestehender Pläne
scripts/gen_xwp_model.py # Generator: XSD (+ Abgleich mit xwp_0.9.6_modell.json) → model/v0_9_6.py
```

Ein Versionswechsel (z. B. 1.0) heißt dann: XSD austauschen, Generator laufen lassen, Mapping-Diffs beheben. Encoder bleiben unverändert, weil sie nur Metadaten lesen.

### 2.3 Annahmen, die ich gesetzt habe

| Frage | Default |
|---|---|
| Zielversion | 0.9.6. Phase 0 prüft, ob die XSD im Repo schon neuer ist; dann gilt die XSD. |
| Planumfang | Ein `WP_Plan` je Projekt = Analysegebiet (Gemeinde oder Gemarkung), ein `WP_Bereich` (nummer 0). Alle gerechneten Netze eines Projekts fließen ein. |
| Datenschutz | Baublock-Ausgaben nur ab einer Mindestzahl Gebäude je Block, konfigurierbar (Default 5). Kleinere Blöcke werden mit dem Nachbarblock zusammengelegt. Die Schwelle bitte fachlich gegen WPG und Landesvorgaben prüfen; das ist meine Annahme, nicht aus dem Standard. |
| Koordinatensystem | EPSG:25832 (wie F\|Heat). In JSON-FG zusätzlich `place` in 25832 und `geometry` in WGS84. |
| Eignungsvorschlag | Schwellwerte (WLD in MWh/(m·a), Wärmedichte in MWh/(ha·a)) in `XwpConfig`, Defaults aus gängigen Leitfäden (z. B. KWW Halle), Herleitung in Phase 7 dokumentieren. Die Einstufung bleibt ein Vorschlag, der Planer überschreibt sie. |

---

## 3. Phasen

Jede Phase ist **ein Branch und ein Push/PR** mit grünen Tests. Modell und Effort in Claude Code vor Beginn der Phase einstellen (`/model`). Bewährter Ablauf je Phase:

1. Neue Claude-Code-Sitzung im Repo, Modell/Effort setzen.
2. Prompt aus der Phase einfügen (bei größeren Phasen erst im Plan-Modus planen lassen, Plan bestätigen).
3. Am Ende `/code-review` laufen lassen, Findings beheben, dann committen und pushen.

Begründung der Modellwahl: **Opus 5.5** dort, wo Fachlogik, Normtreue oder Architektur über Richtigkeit entscheiden (Fehler sind teuer und schwer zu finden). **Sonnet 5.5** für klar spezifizierte Umsetzung nach Vorlage. **Haiku 5.5** für Doku und mechanische Arbeit. Effort **high** nur, wo Schemaregeln oder Einheiten verschachtelt sind; sonst medium, damit Token und Zeit nicht verpuffen.

Basis-Branch für `fheat`: `origin/dev` (`F-Heat/fheat`). Dort sind `fix/topotherm-street-geometry` (PR #9), die HiGHS-Zeitbegrenzung (PR #10) und der kooperative Abbruch (PR #11) bereits enthalten. PRs gehen nach `dev`, nie nach `main`.

### Übersicht

| # | Repo | Inhalt | Modell | Effort |
|---|---|---|---|---|
| 0 | fheat | Spezifikation holen, Version festlegen, ADR, Plan ins Repo | Opus 5.5 | high |
| 1 | fheat | Modellgenerator + generiertes Modell + Validierung | Sonnet 5.5 | high |
| 2 | fheat | GML-Writer + XSD-Validierung + Vollständigkeitstest | Opus 5.5 | high |
| 3 | fheat | JSON-FG-Writer | Sonnet 5.5 | medium |
| 4 | fheat | GeoPackage-Writer nach Implementierungsschema | Sonnet 5.5 | high |
| 5 | fheat | Datenbasis: Baujahr, Gebäudetyp, Plan-Metadaten-Config | Sonnet 5.5 | medium |
| 6 | fheat | Mapping Bestand & Potenzial | Opus 5.5 | high |
| 7 | fheat | Mapping Planung, Gebiete, Netze, Aggregate | Opus 5.5 | high |
| 8 | fheat | Ergänzungsdatei (Import) + GML-Rückleser | Sonnet 5.5 | high |
| 9 | fheat | Orchestrator-Integration, CLI, Beispiel | Sonnet 5.5 | medium |
| 10 | fheat | Konformität in CI (XPlan-Tools-Job für GML, Schema-Tests) | Sonnet 5.5 | medium |
| 11 | fheat-web | Backend: Migration, API, Export-Job, Artefakte | Sonnet 5.5 | high |
| 12 | fheat-web | Frontend: XWärmeplan-Tab | Sonnet 5.5 | medium |
| 13 | beide | Doku, Changelog, Release, `FHEAT_REF` anheben | Haiku 5.5 | medium |

Abhängigkeiten: 0 → 1 → (2, 3, 4 parallel möglich) → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12 → 13. Phase 5 kann auch direkt nach 1 laufen.

---

### Phase 0 · Spezifikation festnageln

**Repo** fheat · **Branch** `feature/xwp-0-spec` · **Opus 5.5, high**

Ziele:

- `gitlab.opencode.de/xleitstelle/xwaermeplan/spezifikation` und `…/implementierung` klonen (außerhalb des Repos, z. B. `..\xwp-spec`).
- Version der XSD ermitteln (Namespace) und mit `docs/xwaermeplan/xwp_0.9.6_modell.json` abgleichen: Klassen, Attribute, Multiplizitäten, Enum-Codes. Abweichungen in `docs/xwaermeplan/abgleich.md` festhalten. Gilt die XSD als neuer, wird sie die Zielversion.
- Im Repo `implementierung` klären: Gibt es ein GeoPackage-Schema (Tabellen, Spalten, Beziehungen)? Referenzpläne (GML/JSON-FG)? Kodierungsregeln (gml:id-Format, FeatureCollection-Typ, srsName)? Ergebnis in `docs/xwaermeplan/kodierung.md`.
- XSD, JSON-Schema und 1–3 Referenzpläne unter `src/fheat_core/xwp/spec/<version>/` bzw. `tests/fixtures/xwp/` ablegen, inkl. Lizenzhinweis. GML-3.2.1- und OGC-SF-XSDs für Offline-Validierung mit ablegen (XML-Katalog).
- ADR `docs/adr/0001-xwaermeplan.md` mit den Entscheidungen aus Abschnitt 2.
- Diesen Plan und die beiden Begleitdateien nach `docs/xwaermeplan/` kopieren.

Fertig, wenn: Zielversion feststeht, Abgleich dokumentiert, Spezifikationsdateien liegen im Repo, keine Codeänderung.

```text
Lies docs/xwaermeplan/XWaermeplan_Umsetzungsplan.md, Abschnitt 1–2 und Phase 0. Führe Phase 0 aus.
Die Spec-Repos liegen unter ..\xwp-spec\spezifikation und ..\xwp-spec\implementierung (falls nicht: klone sie dorthin).
Gleiche die XSD mit docs/xwaermeplan/xwp_0.9.6_modell.json ab und dokumentiere jede Abweichung.
Beschreibe in kodierung.md exakt, wie ein Referenzplan in GML und JSON-FG aufgebaut ist (Wurzelelement, FeatureCollection,
gml:id, xlink-Referenzen, Measures mit uom, Geometrien, srsName) und ob/wie ein GeoPackage-Schema definiert ist.
Keine Änderungen an src/ außer src/fheat_core/xwp/spec/.
```

### Phase 1 · Datenmodell generieren

**Repo** fheat · **Branch** `feature/xwp-1-model` · **Sonnet 5.5, high**

- `scripts/gen_xwp_model.py` liest die XSD (lxml) und erzeugt `src/fheat_core/xwp/model/v0_9_6.py`: eine `@dataclass` je Klasse (Vererbung wie im Modell), `Enum` je Aufzählung (Code als String, Label als Attribut), Klassenmetadaten (`abstract`, `stereotype`, `geometry_kind`) und Attributmetadaten (`multiplicity`, `uom`, `xml_name`, **Reihenfolge laut xsd:sequence inkl. geerbter Elemente**).
- `model/base.py`: `Measure(value, uom)`, Geometrie-Wrapper (Multi-Surface/Curve/Point, VariableGeometrie), `Ref[T]` für Assoziationen, `validate(obj) -> list[Issue]` (Pflichtattribute, Multiplizität, Enum-Werte, Einheiten, Geometrietyp).
- Generierte Datei ist eingecheckt, ein Test prüft, dass ein erneuter Generatorlauf keinen Diff erzeugt.
- Test: Klassen-/Attribut-/Enum-Menge stimmt mit `xwp_0.9.6_modell.json` überein (bzw. mit den in Phase 0 dokumentierten Abweichungen).
- Neues Extra `[xwp]` in `pyproject.toml` (`lxml`).

```text
Lies docs/xwaermeplan/XWaermeplan_Umsetzungsplan.md (Abschnitt 2.2, Phase 1) und docs/xwaermeplan/kodierung.md.
Setze Phase 1 um. Das Modell wird aus der XSD generiert, nicht von Hand geschrieben. Reihenfolge der Elemente
muss der xsd:sequence folgen, sonst ist die GML später ungültig. Schreibe Tests für Generator-Idempotenz,
Vollständigkeit gegen docs/xwaermeplan/xwp_0.9.6_modell.json und für validate().
```

### Phase 2 · GML-Writer

**Repo** fheat · **Branch** `feature/xwp-2-gml` · **Opus 5.5, high**

- `encode/gml.py`: metadatengetriebener Writer für ein `XwpPlanDocument` (Plan, Bereiche, Fachobjekte, Sonstiges) nach den Regeln aus `kodierung.md`: FeatureCollection, stabile `gml:id`s (aus UUIDs), `xlink:href="#…"` für alle Assoziationen, Paare mit Gegenrichtung in beide Richtungen (`bereich`/`gehoertZuPlan`, `energiebilanz`/`gehoertZuPlan` …; `gehoertZuBereich`, `refMassnahme`, `refTextInhalt` nur vom Fachobjekt aus, einen Verweis `planinhalt` gibt es in 0.9.6 nicht, siehe `kodierung.md`), Measures mit `uom`, Datentypen verschachtelt, Geometrien mit `srsName` und eigener `gml:id`, Ringorientierung, Koordinatenpräzision (konfigurierbar, Default 3 Nachkommastellen).
- `validate_gml(path)`: XSD-Validierung offline über den XML-Katalog aus Phase 0.
- **Vollständigkeitstest**: Für jede nicht-abstrakte Klasse des Modells wird synthetisch ein Minimalobjekt (nur Pflichtattribute) und ein Maximalobjekt (alle Attribute) erzeugt, geschrieben und gegen die XSD validiert. Damit ist garantiert, dass jede Klasse ausgegeben werden kann.
- Referenzplan aus `tests/fixtures/xwp/` einlesen ist erst Phase 8; hier nur Schreiben + XSD.

```text
Lies docs/xwaermeplan/kodierung.md und Phase 2 im Umsetzungsplan. Implementiere encode/gml.py metadatengetrieben
(keine klassenspezifischen if-Zweige). Baue den Vollständigkeitstest über alle konkreten Klassen (Minimal- und
Maximalobjekt) mit XSD-Validierung. Vergleiche die Struktur deiner Ausgabe mit dem Referenzplan in tests/fixtures/xwp/.
```

### Phase 3 · JSON-FG-Writer

**Repo** fheat · **Branch** `feature/xwp-3-jsonfg` · **Sonnet 5.5, medium**

- `encode/jsonfg.py`: FeatureCollection nach JSON-FG 0.2.2 mit `conformsTo`, `coordRefSys`, je Feature `featureType`, `time`, `place` (EPSG:25832) und `geometry` (WGS84). Datentypen als verschachtelte Objekte. Aufbau nach dem **offiziellen JSON-Schema**, nicht nach den Referenzplänen:
  - **Messwerte als reine Zahlen** in der Einheit des Modells (die Einheit steht nicht in der Datei),
  - **Verweise als JSON-FG-Link-Objekte** `{"href": "#<uuid>", "rel": "related"}`,
  - **`id` als UUID** (ohne Präfix).
  Details und geprüftes Beispiel in `kodierung.md`.
- Validierung gegen das vendorte JSON-Schema, **je Feature gegen die Definition seines `featureType`** (die FeatureCollection-Definition allein prüft Features ohne Collection-`featureType` nur gegen das allgemeine JSON-FG-Schema). `jsonschema` nur als Test-Abhängigkeit.
- Vollständigkeitstest aus Phase 2 um JSON-FG erweitern.

```text
Setze Phase 3 aus docs/xwaermeplan/XWaermeplan_Umsetzungsplan.md um. Maßgeblich ist das offizielle JSON-Schema
(src/fheat_core/xwp/spec/0.9.6/json/), nicht die Referenzpläne: Messwerte als reine Zahlen, Verweise als
JSON-FG-Link-Objekte, id als UUID. Halte dich an docs/xwaermeplan/kodierung.md. Erweitere den Vollständigkeitstest
um JSON-FG mit Schema-Validierung je Feature.
```

### Phase 4 · GeoPackage-Writer

**Repo** fheat · **Branch** `feature/xwp-4-gpkg` · **Sonnet 5.5, high**

- Wenn Phase 0 ein GeoPackage-Schema im Repo `implementierung` gefunden hat: `encode/gpkg.py` schreibt exakt dieses Schema (Tabellen, Spalten, Beziehungstabellen, Enum-Codes) und der Test vergleicht das Schema mit der Vorlage.
- Wenn nicht: dokumentiertes, nicht normatives Layout. Eine Tabelle je konkreter Objektart (Geometriespalte nach Geometrietyp, bei VariableGeometrie drei Tabellen `_flaeche/_linie/_punkt`), Datentypen als JSON-Spalten, Assoziationen als `*_id`-Spalten, Enum-Codes als Text plus Label-Spalte, Metadaten-Tabelle mit Version. Im README klar als „F|Heat-Austauschformat“ kennzeichnen; GML bleibt das normative Format.
- QGIS-tauglich: Layer-Namen deutsch, Feldaliase.

```text
Setze Phase 4 um. Prüfe zuerst in docs/xwaermeplan/kodierung.md, ob ein offizielles GeoPackage-Schema existiert,
und folge dem Zweig aus dem Plan. Erweitere den Vollständigkeitstest um GeoPackage (schreiben, mit geopandas
wieder lesen, Feld- und Zeilenzahl prüfen).
```

### Phase 5 · Datenbasis für die Abbildung

**Repo** fheat · **Branch** `feature/xwp-5-data` · **Sonnet 5.5, medium**

- Neue kanonische Spalten in `columns.py`/`schemas.py` (optional): `construction_year` (Baujahr), `xwp_building_type` (Code `WP_GebaeudeTyp`), `n_dwellings` (Wohnungen, falls verfügbar). Labels in `LABELS_DE`.
- NRW-Adapter: Baujahr aus `validFrom` als eigene Spalte behalten (heute wird es nach dem BAK-Binning verworfen). Gebäudetyp über eine Tabelle `fheat_core/data/xwp_gebaeudetyp.json` aus ALKIS-Funktion und Lastprofil ableiten; was nicht eindeutig ist, bekommt die Oberkategorie (1000/2000) bzw. 9999.
- Flex-Adapter: Mapping der neuen Spalten über `column_map`.
- `XwpConfig` und `XwpPlanConfig` in `config.py`: Plan-Metadaten (Name, Gemeinde mit Name/ARS12/ARS9, beteiligte Gemeinden, Verfahrensart, gesetzliche Grundlage, Zieljahr, Basisjahr, Beschlussdaten, Förderkennzeichen, technische Planerstellung, externe Referenzen), Ausgabeformate (`gml`, `jsonfg`, `gpkg`), Datenschutzschwelle, Eignungsschwellen, Koordinatenpräzision. Validierung im `__post_init__` wie bei den anderen Configs.

```text
Setze Phase 5 aus docs/xwaermeplan/XWaermeplan_Umsetzungsplan.md um. Bestehende Ausgaben dürfen sich nicht ändern
(neue Spalten nur zusätzlich). Lege die Mapping-Tabelle Gebäudetyp als JSON an und teste sie mit allen ALKIS-Funktionen
aus fheat_nrw/data/building_functions.json. Pflichtangaben von WP_Plan, die F|Heat nicht kennt, kommen aus XwpPlanConfig.
```

### Phase 6 · Mapping Bestand und Potenzial

**Repo** fheat · **Branch** `feature/xwp-6-mapping-bestand` · **Opus 5.5, high**

- `mapping/plan.py`: `WP_Plan`, `WP_Bereich` aus `XwpPlanConfig` und Analysegebiet (`adapter.provide_boundary()` bzw. Hülle der Gebäude).
- `mapping/waermelinie.py`: `WP_Waermelinie` aus `wld_gdf` (kWh/a → MWh/a, kWh/(a·m) → MWh/(m·a), Länge in m). Straßenabschnitte ohne Bedarf weglassen.
- `mapping/baublock.py`: `WP_GebaeudeBaublock` und `WP_EnergieBaublock` aus den Wärmedichteblöcken (`polygons_gdf`) und den Gebäuden darin: überwiegender Gebäudetyp, überwiegende Baualtersklasse und Verteilung (`WP_BaujahrAngaben`, Anteile in %), Nutzfläche in ha, Wärmemenge und -dichte. Datenschutzschwelle anwenden.
- `mapping/raster.py`: `WP_EnergieRaster` (100-m-INSPIRE-Gitter, optional per Config).
- `mapping/aggregiert.py` (Basisjahr): `WP_Energiebilanz` (Summen, soweit bekannt), `WP_WaermeinfrastrukturAggregiert` (`anzahlGebaeude` …).
- Alle Umrechnungen zentral in `mapping/units.py`, jede mit Test. Jede Mapping-Funktion gibt validierte Objekte zurück (`validate()` aus Phase 1).
- Integrationstest mit dem Burgsteinfurt-Beispiel offline (vorhandene Fixtures), Ergebnis-GML gegen XSD.

```text
Setze Phase 6 um. Lies dazu die Spalte "Quelle in F|Heat" in docs/xwaermeplan/XWaermeplan_Modellreferenz_0.9.6.md.
Achte besonders auf Einheiten (kWh→MWh, m²→ha) und die Datenschutzschwelle. Jede Umrechnung in mapping/units.py mit Test.
Plane zuerst im Plan-Modus und zeig mir die Abbildungstabelle Attribut für Attribut, bevor du Code schreibst.
```

### Phase 7 · Mapping Planung, Gebiete, Netze

**Repo** fheat · **Branch** `feature/xwp-7-mapping-planung` · **Opus 5.5, high**

- `mapping/netz.py`: `WP_Waermenetz` je gerechnetem Netz. Achtung: in 0.9.6 ein **Flächenobjekt**. Fläche = Puffer um die Trasse (Breite konfigurierbar) bzw. Planungsgebiet; `laenge` = Trassenlänge ohne Hausanschlüsse, `anzahlGebaeudeAnschluss`, `status` = 2000/3000, `temperatur` = Vorlauf, `medium` = Wasser.
- `mapping/gebiete.py`: `WP_WaermeversorgungsgebietZieljahr` und `…Stuetzjahr` aus Planungsgebieten mit einer Gebietseinteilung (Versorgungsart je Gebiet, vom Planer). Vorschlag der vier Eignungsstufen aus WLD und Wärmedichte (Schwellen aus `XwpConfig`). `WP_Eignungspruefung`-Vorschlag für Blöcke unter den Schwellen.
- `mapping/potenzial.py`: `WP_PotenzialWaermenutzung` aus den Wärmequellen (Energieträger vom Planer), `WP_Grossverbraucher`-Vorschläge über einer Bedarfsschwelle, `WP_EnergieeinsparungGebaeude` und `WP_PotenzialanalyseAggregiert.waermebedarfsreduktionGebaeude` aus einem einfachen Sanierungsszenario (Reduktionsfaktoren je Baualtersklasse in einer Datentabelle).
- `WP_WaermeinfrastrukturAggregiert` um geplante Netze ergänzen (`waermenetzePlanung`, Anschlüsse).
- Die Netzplanung von F|Heat rechnet heute je Netz einen eigenen `PipelineState`. Das Mapping nimmt daher eine Liste von Netzergebnissen entgegen (`build_plan(state_analysis, networks=[…], supplement=…)`).

```text
Setze Phase 7 um. WP_Waermenetz ist in 0.9.6 ein Flächenobjekt; prüfe das in der Modellreferenz. Eignungsstufen sind
nur Vorschläge und müssen durch die Ergänzungsdatei überschreibbar sein. Plane zuerst im Plan-Modus mit
Attributtabelle je Klasse.
```

### Phase 8 · Ergänzungsdatei und Rückleser

**Repo** fheat · **Branch** `feature/xwp-8-supplement` · **Sonnet 5.5, high**

- `supplement/template.py`: erzeugt aus dem Modell eine leere Vorlage `xwp_ergaenzung.gpkg` (je Objektart ein Layer mit allen Attributen, Enum-Felder mit Wertelisten) und `xwp_ergaenzung.xlsx` für Objekte ohne Raumbezug (`WP_Massnahme`, `WP_TextAbschnitt`, externe Referenzen, Gebietseinteilung je Planungsgebiet, Energieträger von Wärmequellen).
- `supplement/reader.py`: liest beide Dateien, validiert gegen das Modell, liefert Objekte bzw. Overrides (z. B. Eignungsstufe, Versorgungsart). Klare Fehlermeldungen mit Zeile/Feature.
- `decode/gml.py`: liest XWärmeplan-GML (eigene Ausgaben und Referenzpläne) ins Modell. Round-Trip-Test: Referenzplan lesen → schreiben → lesen → gleich.
- Damit sind alle **E**-Klassen abgedeckt.

```text
Setze Phase 8 um. Die Vorlage wird vollständig aus dem generierten Modell erzeugt, nicht von Hand. Schreibe den
Round-Trip-Test mit allen Referenzplänen aus tests/fixtures/xwp/ und einen Test, dass jede E-Klasse aus der
Modellreferenz über die Ergänzungsdatei befüllt werden kann.
```

### Phase 9 · Integration in Orchestrator und Ausgaben

**Repo** fheat · **Branch** `feature/xwp-9-integration` · **Sonnet 5.5, medium**

- `FHeatConfig.xwp: Optional[XwpConfig]`. `FHeatOrchestrator.save_xwp(networks=None, supplement=None)` schreibt `xwaermeplan.gml`, `xwaermeplan.json` (JSON-FG), `xwaermeplan.gpkg` und `xwaermeplan_pruefbericht.json` (Validierungsbefunde, Abdeckung je Klasse: automatisch/ergänzt/leer). Rückgabe wie `save_outputs()` (Schlüssel `xwp_gml`, `xwp_jsonfg`, `xwp_gpkg`, `xwp_report`).
- `save_outputs()` bleibt unverändert; `export/xplan.py` (Platzhalter) entfernen bzw. auf `fheat_core.xwp` umleiten. `output_format="gml"` im README als „OGR-GML, nicht XWärmeplan“ kennzeichnen.
- CLI `python -m fheat_core.xwp template|build|validate`.
- Beispiel `examples/burgsteinfurt_xwaermeplan.py`.

```text
Setze Phase 9 um. Bestehende Ausgaben und Tests dürfen sich nicht ändern. Der Prüfbericht muss pro Objektart zeigen,
ob sie automatisch, aus der Ergänzungsdatei oder gar nicht befüllt wurde, und welche Pflichtattribute fehlen.
```

### Phase 10 · Konformität in CI

**Repo** fheat · **Branch** `feature/xwp-10-ci` · **Sonnet 5.5, medium**

- Neuer CI-Job (Python 3.13, nur Linux): installiert `xplan-tools` (gepinnte Version) und liest die im Test erzeugten **GML**-Dateien damit ein. Fehler = Job rot. JSON-FG wird hier **nicht** geprüft: XPlan-Tools schreibt und erwartet ein JSON-FG, das vom offiziellen Schema abweicht (siehe 2.1 und `abgleich.md`).
- XSD-Validierung aller GML-Testausgaben und JSON-Schema-Validierung aller JSON-FG-Testausgaben im normalen Testlauf (offline).
- Golden-File-Test für das Burgsteinfurt-Beispiel (Struktur, Objektanzahlen, Summen), damit Mapping-Änderungen sichtbar werden.

```text
Setze Phase 10 um. Der XPlan-Tools-Job läuft getrennt vom Haupt-Testjob, weil XPlan-Tools Python 3.13 braucht.
Er prüft nur die GML-Ausgabe; JSON-FG wird nur gegen das offizielle Schema getestet.
Pinne die Version und dokumentiere in der CI-Datei, warum der Job existiert.
```

### Phase 11 · fheat-web Backend

**Repo** fheat-web · **Branch** `feature/xwp-backend` · **Sonnet 5.5, high**

- `FHEAT_REF` auf den Commit nach Phase 10 heben, Extra `[xwp]` im Dockerfile ergänzen, `constraints.txt` anpassen.
- Alembic-Migration `0023_xwaermeplan`: `projects.xwp_plan` (JSONB, Plan-Metadaten), Tabelle `project_xwp_objects` (Objektart, Geometrie, Attribute JSONB, Herkunft `auto|manual|import`) für ergänzte Objekte, Gebietseinteilung je Planungsgebiet (`project_planning_areas.xwp_supply_type`, Eignungsstufen).
- API: `GET/PUT /projects/{id}/xwp/plan`, `GET /projects/{id}/xwp/template` (Vorlagen-Download), `POST /projects/{id}/xwp/supplement` (Upload, validiert), `POST /projects/{id}/xwp/export` (Celery-Job), CRUD für `xwp/objects`.
- Export-Job ruft `save_xwp()` mit allen Netzen im Status `results` und veröffentlicht die Dateien als Projekt-Artefakte (`network_id` NULL, `kind="xwaermeplan"`); Media-Types `.gml` `application/gml+xml`, `.json` `application/vnd.ogc.fg+json`. Invalidierung: Geometrie- oder Parameteränderungen löschen die XWärmeplan-Artefakte wie die übrigen.
- Tests nach dem Muster der bestehenden Contract-Tests, Rollenrechte (viewer liest, editor exportiert).

```text
Setze Phase 11 aus docs/xwaermeplan/XWaermeplan_Umsetzungsplan.md (liegt im fheat-Repo) um. Halte dich an
CONTRIBUTING.md (exakte Pins, Alembic-Migration, deutsche UI-Texte, LF). Der Export ist projektweit, nicht je Netz.
```

### Phase 12 · fheat-web Frontend

**Repo** fheat-web · **Branch** `feature/xwp-frontend` · **Sonnet 5.5, medium**

- Neuer Tab „XWärmeplan“ in `ProjectView.vue`: Formular für Plan-Metadaten, Gebietseinteilung je Planungsgebiet (Versorgungsart, Eignungsstufen mit vorgeschlagenem Wert), Liste der ergänzten Objekte, Vorlage herunterladen/Ergänzung hochladen, Export starten, Prüfbericht anzeigen (Abdeckung je Klasse, fehlende Pflichtangaben mit Sprung zum Feld).
- Formularfelder und Wertelisten kommen aus einem API-Endpunkt, der die Modellmetadaten ausliefert, damit ein Versionswechsel kein Frontend-Release erzwingt.

```text
Setze Phase 12 um. Formulare aus den Modellmetadaten der API rendern, keine fest verdrahteten Enum-Listen.
UI-Texte deutsch. Frontend-Build und Lockfile wie in CONTRIBUTING.md.
```

### Phase 13 · Dokumentation und Release

**Repos** beide · **Haiku 5.5, medium**

- README-Abschnitte „XWärmeplan“ in beiden Repos (Formate, Abdeckung, Ergänzungsdatei, Grenzen), CHANGELOG, Versionsnummer, Release-Notes.
- `FHEAT_REF` in fheat-web final setzen, `scripts/release-check.sh` laufen lassen.

```text
Setze Phase 13 um. Aktualisiere README und CHANGELOG in beiden Repos auf Basis der Commits seit Phase 0.
Keine Codeänderungen außer Versionsnummern und FHEAT_REF.
```

---

## 4. Risiken

| Risiko | Gegenmaßnahme |
|---|---|
| Standard ändert sich bis zur Verabschiedung | Versionskapsel und Generator (Phase 1); Encoder metadatengetrieben. |
| GeoPackage-Schema im Repo `implementierung` fehlt oder weicht ab | Phase 0 klärt das; Phase 4 hat beide Zweige. |
| Datenlücken (Energieträger, Erzeugerbestand, THG) | Nicht schätzen, sondern über Ergänzungsdatei; Prüfbericht zeigt Lücken offen an. |
| Datenschutz bei kleinen Baublöcken | Schwelle + Zusammenlegung (Phase 6), fachlich prüfen lassen. |
| Python-Versionen (topotherm 3.12, XPlan-Tools 3.13) | XPlan-Tools nur im separaten CI-Job. |

## 5. Quellen

- [XLeitstelle: Objektartenkatalog Wärmeplan](https://xleitstelle.de/releases/objektartenkatalogWaermeplan), [Katalog 0.92](https://xleitstelle.de/downloads/catalogues/491/overview-summary.html)
- [Repo spezifikation](https://gitlab.opencode.de/xleitstelle/xwaermeplan/spezifikation), [Repo implementierung](https://gitlab.opencode.de/xleitstelle/xwaermeplan/implementierung)
- [FIT-Standard XWärmeplan](https://docs.fitko.de/fit-standards/xwaermeplan/)
- [XPlan-Tools auf PyPI](https://pypi.org/project/xplan-tools/) (Modell `xwp09.py`, Version 0.9.6)
- [nPro: XWärmeplan](https://www.npro.energy/main/en/knowledge/energy-systems/xwaermeplan)
