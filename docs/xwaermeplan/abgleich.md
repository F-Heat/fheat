# XWärmeplan: Abgleich Spezifikation, Modell und Referenzpläne

Stand: 12.10.2026 (Phase 0). Zielversion: **0.9.6**.

## Geprüfte Quellen

| Quelle | Stand |
|---|---|
| XSD `xsd/waermeplan.xsd` aus `gitlab.opencode.de/xleitstelle/xwaermeplan/spezifikation` | Commit `2f7715e`, 08.09.2026, Namespace `http://www.xwaermeplan.de/0/9/6`, `version="0.9.6"` |
| JSON-Schema `json/0.9.6/featurecollection.json` und `features.json` aus demselben Repo | Commit `2f7715e` |
| Referenzpläne `Referenzplaene/*` aus `…/xwaermeplan/implementierung` | Commit `52b9e3e`, 06.10.2026: Aachen, Kiel, Oberhausen, Rheinberg, je als GML und JSON-FG aus XMAS/XPlan-Tools (`*_xmas.*`) und aus ldproxy (`*_ldproxy*`) |
| `docs/xwaermeplan/xwp_0.9.6_modell.json` | aus XPlan-Tools 1.26.0 (`xwp09.py`) |

**Zielversion:** Die XSD ist 0.9.6, also nicht neuer als die Modellreferenz. Es bleibt bei **0.9.6**.

**Rangfolge:** Maßgeblich sind die offiziellen Schemas (XSD, JSON-Schema). Sie gehen den Referenzplänen und XPlan-Tools vor. Wo ein Referenzplan abweicht, folgt F|Heat dem Schema; die Abweichung steht unten als Befund.

## 1. XSD gegen `xwp_0.9.6_modell.json`

Verglichen wurden Klassen, Attribute (je Klasse eigene Attribute), Multiplizitäten, Reihenfolge der Attribute, `abstract` und die Codes aller Aufzählungen.

| Prüfung | Ergebnis |
|---|---|
| Klassen und Datentypen | 54 in beiden, gleiche Namen |
| Aufzählungen | 21 in beiden, gleiche Codes in gleicher Reihenfolge |
| Attribute je Klasse | gleich, bis auf `WP_Objekt.uuid` (siehe A1) |
| Multiplizitäten | gleich |
| Reihenfolge (entscheidend für `xsd:sequence`) | gleich |
| `abstract` | gleich |

### A1 `WP_Objekt.uuid` fehlt in der XSD

Das Modell von XPlan-Tools (und die relationale DDL im Repo `implementierung`, Spalte `uuid`) kennen `WP_Objekt.uuid` (CharacterString, 0..1). XSD und JSON-Schema kennen es nicht.

Folge für F|Heat: kein Element `uuid` in GML, keine Eigenschaft `uuid` in JSON-FG. Die UUID eines Objekts steht in GML in `gml:id` (und, wie bei XPlan-Tools, in `gml:identifier codeSpace="urn:uuid"`), in JSON-FG in `id`. Der Modellgenerator (Phase 1) liest die XSD und erzeugt `uuid` daher nicht als Fachattribut.

### A2 Einheiten stehen nicht in der XSD

Alle Messwerte haben in der XSD den Typ `gml:MeasureType` ohne festgelegte Einheit, im JSON-Schema den Typ `number`. Die Einheit kommt nur aus dem UML-Modell (`uom` in `xwp_0.9.6_modell.json`). Der Generator übernimmt sie von dort; in GML wird sie als `uom` geschrieben, in JSON-FG gar nicht (die Zahl gilt in der Modelleinheit).

### A3 Uneinheitliche Einheiten im Modell selbst

| Attribut | Einheit im Modell | Bemerkung |
|---|---|---|
| `WP_Massnahme.treibausgaseEinsparung` | `tCO2e/a` | alle anderen THG-Werte: `tCO2-eq/a` |
| `WP_Waermversorgungsgebiet.sanierungsrate` | `vH/a` | sonst `%` für Anteile |
| `WP_Energiebilanz.eeGesamtGebaeude`, `eeGesamtProzesse` | `MWh` | die übrigen Endenergiewerte der Bilanz: `MWh/a` |
| `WP_VersorgungsgebieteAggregiert.endenergieverbrauch`, `WP_WaermeinfrastrukturAggregiert.bedarfGruenesMethanZieljahr`, `WP_PotenzialanalyseAggregiert.*WaermebedarfsreduktionGebaeude` | `MWh` | Jahreswerte ohne `/a` |

F|Heat schreibt die Einheit **genau wie im Modell**. Der Abschnitt dient als Rückmeldung an die XLeitstelle.

## 2. Referenzpläne gegen die XSD (GML)

Geprüft offline mit der vendorten XSD und dem XML-Katalog (`src/fheat_core/xwp/spec/0.9.6/xsd/catalog.xml`), jeweils die ganze Datei:

| Datei | Ergebnis |
|---|---|
| `Aachen_v096_xmas.gml`, `Kiel_v096_xmas.gml`, `Oberhausen_v096_xmas.gml`, `Rheinberg_v096_xmas.gml` | gültig |
| `Aachen_v096_ldroxy.gml`, `Kiel_v096_ldproxy.gml`, `Oberhausen_v096_ldproxy.gml`, `Rheinberg_v096_ldproxy.gml` | gültig |

### G1 Einheiten weichen vom Modell ab (XSD prüft das nicht)

| Plan | Attribut | im Plan | laut Modell |
|---|---|---|---|
| Rheinberg, Aachen | `WP_Energiebilanz.eeGesamtGebaeude`, `eeGesamtProzesse` | `MWh/a` | `MWh` |
| Oberhausen | dieselben | `MWh` | `MWh` |

Alle übrigen `uom`-Werte in den vier Plänen stimmen mit dem Modell überein.

## 3. Referenzpläne gegen das JSON-Schema (JSON-FG)

Geprüft mit dem vendorten JSON-Schema und JSON-FG 0.2.2 (siehe `kodierung.md`, Abschnitt JSON-FG), je Feature gegen die Definition seines `featureType`, bis zu 300 Features je Objektart.

**Kein Referenzplan ist gegen das offizielle Schema gültig.** Das gilt für beide Varianten.

### J1 XMAS/XPlan-Tools (`*_xmas.json`)

| Abweichung | Schema verlangt | Plan enthält |
|---|---|---|
| Messwerte | Zahl, z. B. `"laenge": 142.0` | Objekt `{"value": 142.0, "uom": "m"}` |
| Verweise (`gehoertZuBereich`, `gehoertZuPlan`, `bereich`, `energiebilanz`, …) | JSON-FG-Link-Objekt mit `href` und `rel` | nackte UUID als Zeichenkette |
| `geometry` bei Flächen-, Linien- und Planobjekten | MultiPolygon bzw. MultiLineString (GeoJSON, WGS84) | `null`; die Geometrie steht nur in `place` (EPSG:25832) |

Gegenprobe: Werden in allen vier XMAS-Plänen genau diese drei Punkte umgestellt (Zahl statt Objekt, `{"href": "#<uuid>", "rel": "related"}` statt UUID, `geometry` = `place` nach WGS84 umgerechnet, `time: null`), sind **alle** geprüften Features gültig. Das Schema ist also erfüllbar, und es gibt keine weiteren Abweichungen.

### J2 ldproxy (`*_ldproxy*.json`, geprüft: Rheinberg)

| Abweichung | Schema verlangt | Plan enthält |
|---|---|---|
| Aufzählungen | Code, z. B. `"1000"` | Text mit Code, z. B. `"Regelverfahren (1000)"` |
| Verweise | Link-Objekt mit `href` **und** `rel` | Link-Objekt mit `href` und `title`, ohne `rel` |
| Pflichtmitglieder | `time`, `place`, `geometry` je Feature | `time` fehlt bei fast allen Features, `place` bei Objekten ohne Raumbezug |
| `geometry` | wie J1 | `null` |
| `id` | UUID | `WP_Plan.<uuid>` (Typpräfix) |
| Mehrfachwerte | Array (z. B. `kostentragenderSektor`, `versorgungsmedium`) | einzelne Zeichenkette |
| Messwerte | Zahl | `{value, uom}` |

### J3 JSON-Schema verweist auf eine nicht mehr verfügbare JSON-FG-Version

`features.json` verweist auf `https://beta.schemas.opengis.net/json-fg/geometry-objects.json`. Unter dieser Adresse liefert der OGC-Server inzwischen JSON-FG 0.3; die Datei `geometry-objects.json` gibt es dort nicht mehr (HTTP 404). Passend zum Schema ist **JSON-FG 0.2.2**; die Dateien stammen aus dem OGC-Repo `opengeospatial/ogc-feat-geo-json`, Tag `v0.2.2`. `link.json` gehört seit JSON-FG 0.2 nicht mehr zum Standard, liegt aber noch als informatives Schema auf dem beta-Server und wird von dort übernommen. Ohne die vendorten Dateien lässt sich das XWärmeplan-JSON-Schema nicht auflösen.

## 4. GeoPackage

Im Repo `implementierung` gibt es **kein GeoPackage-Schema**. Vorhanden sind:

- `postgres/relational/XWärmeplan.sql`: relationale PostgreSQL-DDL, 86 Tabellen. Eine Tabelle je konkreter Objektart (Kleinbuchstaben, z. B. `wp_waermelinie`), Spalten in Kleinbuchstaben, Fremdschlüssel `<rolle>_fk`, Codelisten-Spalten `<attribut>_fkcl` mit eigener Tabelle je Aufzählung (`code`, `model`, `documentation`, `description`), Kindtabellen für mehrwertige Datentypen (z. B. `wp_energiebaublock_eenachenergietraeger`), Geometriespalte `position` mit Geometrietyp und EPSG:25832.
- `postgres/Coretable/xwp096core.backup`: Datenbank-Dump im „Coretable“-Schema von XPlan-Tools/XMAS (Objekte als JSON in einer Tabelle).

Folge für Phase 4: Es gilt der Zweig „kein offizielles Schema“. Das F|Heat-GeoPackage ist ein nicht normatives Austauschformat und übernimmt Tabellen- und Spaltennamen der relationalen DDL, soweit GeoPackage das zulässt.

## 5. Offene Punkte

| Punkt | Stand |
|---|---|
| Lizenz der Spezifikationsdateien und Referenzpläne | Beide GitLab-Repos haben keine Lizenzdatei und keine Lizenzangabe in den Projektmetadaten. Die vendorten Dateien und die Auszüge der Referenzpläne in `tests/fixtures/xwp/` sind mit Herkunft gekennzeichnet; die Nutzungsbedingungen sollten bei der XLeitstelle erfragt werden, bevor ein Release veröffentlicht wird. |
| Rückmeldung an die XLeitstelle | A3, G1, J1–J3 betreffen den Standard bzw. die Referenzpläne, nicht F\|Heat. |
