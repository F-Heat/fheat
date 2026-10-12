# XWärmeplan 0.9.6: Kodierung in GML und JSON-FG

Stand: 12.10.2026 (Phase 0). Dieses Dokument legt fest, wie F|Heat XWärmeplan-Dateien schreibt. Grundlage sind die offiziellen Schemas (`src/fheat_core/xwp/spec/0.9.6/`) und die Referenzpläne der XLeitstelle. Wo beide auseinandergehen, gilt das Schema (siehe `abgleich.md`).

Der Standard selbst macht laut `Referenzplaene/readme.md` „(bislang) keine Vorgaben, wie IDs und Links in den GML- und JSON-FG-Instanzen kodiert sein müssen“. Was hier als **F|Heat-Festlegung** markiert ist, ist deshalb eine eigene Wahl innerhalb der Schemas.

## 1. Spezifikationsdateien im Repo

| Pfad | Inhalt |
|---|---|
| `src/fheat_core/xwp/spec/0.9.6/xsd/waermeplan.xsd` | XSD XWärmeplan 0.9.6 |
| `…/xsd/schemas.opengis.net/…`, `…/xsd/www.w3.org/…` | GML 3.2.1, ISO 19139 (von GML importiert), XLink, `xml.xsd`, OGC API Features `core-sf.xsd` (Wurzel `sf:FeatureCollection`) und das davon importierte GML-SF-Profil |
| `…/xsd/catalog.xml` | OASIS-XML-Katalog: Remote-URL → lokale Datei, für `http://` und `https://` |
| `…/json/featurecollection.json`, `…/json/features.json` | JSON-Schema XWärmeplan 0.9.6 |
| `…/json/json-fg/*.json` | JSON-FG 0.2.2 (OGC-Repo, Tag `v0.2.2`) und `link.json` vom beta-Server |
| `…/json/catalog.json` | Schema-`$id` → lokale Datei |
| `scripts/fetch_xwp_spec.py` | holt alles neu, z. B. für eine neue Version |
| `tests/fixtures/xwp/*_auszug.*` | Auszüge aus vier Referenzplänen (siehe 6.) |

**Offline-Validierung GML:** Die Wurzel-XSD importiert GML über `http://schemas.opengis.net/gml/3.2.1/gml.xsd`. Ein `lxml`-Resolver, der die Einträge aus `catalog.xml` auf die lokalen Dateien umlenkt, und ein Parser mit `no_network=True` genügen. Da die Instanzen als Wurzel `sf:FeatureCollection` haben, braucht die Validierung ein kleines Hüll-Schema, das `waermeplan.xsd` und `core-sf.xsd` importiert. Damit sind alle acht Referenz-GMLs in Phase 0 offline als gültig geprüft.

**Offline-Validierung JSON-FG:** `referencing.Registry` mit allen Einträgen aus `catalog.json`. Geprüft wird **jedes Feature gegen `features.json#<featureType>`**. Die Definition `FeatureCollection` prüft die Features nur dann gegen die XWärmeplan-Klasse, wenn die Collection selbst ein `featureType` trägt; bei gemischten Collections (der Normalfall) prüft sie nur gegen das allgemeine JSON-FG-Feature.

## 2. Gemeinsame Regeln

| Punkt | Regel |
|---|---|
| Identität | Jedes Objekt mit eigener Identität (`WP_Plan`, `WP_Bereich`, alle Fachobjekte, `WP_Energiebilanz`, `WP_Massnahme`, `WP_TextAbschnitt`, `…Aggregiert`) hat eine UUID (v4, Kleinbuchstaben). Sie bleibt über erneute Exporte desselben Objekts stabil. |
| Datentypen | `WP_Gemeinde`, `WP_ExterneReferenz`, `WP_Betrachtungszeitpunkt`, `WP_EndenergieAngaben` usw. haben keine Identität und werden im Elternobjekt verschachtelt. |
| Aufzählungen | immer der **Code** (`"1000"`), nie der Text. |
| Messwerte | in der Einheit des UML-Modells (`uom` in `xwp_0.9.6_modell.json`), auch wo das Modell uneinheitlich ist (`abgleich.md`, A3). |
| Koordinatensystem | EPSG:25832, Koordinaten auf 3 Nachkommastellen (mm), wie in den Referenzplänen. |
| Reihenfolge der Objekte | Plan, Bereich(e), Objekte ohne Raumbezug, dann Fachobjekte nach Objektart (wie die XMAS-Referenzpläne). Für die Gültigkeit unerheblich, erleichtert aber den Vergleich. |

### Verweise in 0.9.6

Die XSD kennt genau diese Verweise (`gml:ReferenceType`); ein Verweis vom Bereich auf seine Fachobjekte (etwa `planinhalt`) existiert in 0.9.6 **nicht**:

| Von | Eigenschaft | Mult. | Auf | Gegenrichtung |
|---|---|---|---|---|
| `WP_Plan` | `energiebilanz` | 0..* | `WP_Energiebilanz` | `gehoertZuPlan` |
| `WP_Plan` | `infrastruktur` | 0..* | `WP_WaermeinfrastrukturAggregiert` | `gehoertZuPlan` |
| `WP_Plan` | `potenzialanalyse` | 0..* | `WP_PotenzialanalyseAggregiert` | `gehoertZuPlan` |
| `WP_Plan` | `massnahme` | 0..* | `WP_Massnahme` | `gehoertZuPlan` |
| `WP_Plan` | `text` | 0..* | `WP_TextAbschnitt` | `gehoertZuPlan` |
| `WP_Plan` | `bereich` | 0..* | `WP_Bereich` | `gehoertZuPlan` |
| `WP_Bereich`, `WP_Energiebilanz`, `WP_Massnahme`, `WP_TextAbschnitt`, `WP_WaermeinfrastrukturAggregiert`, `WP_PotenzialanalyseAggregiert` | `gehoertZuPlan` | 1 | `WP_Plan` | siehe oben |
| alle Fachobjekte (`WP_Objekt`) | `gehoertZuBereich` | 1 | `WP_Bereich` | – |
| alle Fachobjekte | `refTextInhalt` | 0..1 | `WP_TextAbschnitt` | – |
| alle Fachobjekte | `refMassnahme` | 0..1 | `WP_Massnahme` | – |

**F|Heat-Festlegung:** Paare mit Gegenrichtung werden immer in **beide** Richtungen geschrieben (wie alle Referenzpläne). Alle Verweise zeigen auf Objekte in derselben Datei.

## 3. GML

### 3.1 Aufbau

```xml
<?xml version='1.0' encoding='UTF-8'?>
<sf:FeatureCollection
    xmlns="http://www.xwaermeplan.de/0/9/6"
    xmlns:gml="http://www.opengis.net/gml/3.2"
    xmlns:xlink="http://www.w3.org/1999/xlink"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:sf="http://www.opengis.net/ogcapi-features-1/1.0/sf"
    xsi:schemaLocation="http://www.xwaermeplan.de/0/9/6 https://gitlab.opencode.de/xleitstelle/xwaermeplan/spezifikation/-/raw/main/xsd/waermeplan.xsd http://www.opengis.net/ogcapi-features-1/1.0/sf http://schemas.opengis.net/ogcapi/features/part1/1.0/xml/core-sf.xsd http://www.opengis.net/gml/3.2 https://schemas.opengis.net/gml/3.2.1/gml.xsd"
    gml:id="GML_<uuid der Collection>">
  <sf:featureMember>
    <WP_Plan gml:id="GML_<uuid>">
      <gml:identifier codeSpace="urn:uuid"><uuid></gml:identifier>
      <name>…</name>
      …
      <bereich xlink:href="#GML_<uuid des Bereichs>"/>
    </WP_Plan>
  </sf:featureMember>
  <sf:featureMember>…</sf:featureMember>
</sf:FeatureCollection>
```

| Punkt | Regel |
|---|---|
| Wurzel | `sf:FeatureCollection` (OGC API Features, Namespace `http://www.opengis.net/ogcapi-features-1/1.0/sf`), je Objekt ein `sf:featureMember`. So machen es XMAS/XPlan-Tools und ldproxy. |
| Namespace | XWärmeplan als Default-Namespace, Präfixe `gml`, `xlink`, `xsi`, `sf`. |
| `schemaLocation` | wie oben (XMAS-Variante). |
| `gml:id` Objekte | **F\|Heat-Festlegung:** `GML_<uuid>` wie XMAS (ldproxy: `_WP_Plan.<uuid>`). Beides ist gültig, weil `gml:id` nur ein NCName sein muss. |
| `gml:identifier` | erstes Kind jedes Objekts: `<gml:identifier codeSpace="urn:uuid"><uuid></gml:identifier>` (XMAS; ldproxy lässt es weg). Trägt die UUID, die XWärmeplan als `id` modelliert. |
| Elementreihenfolge | exakt nach `xsd:sequence`, geerbte Elemente zuerst (`WP_Objekt` → `WP_Flaechenobjekt` → Fachklasse). Deshalb steht z. B. `gehoertZuBereich` vor `position`, und `gehoertZuPlan` steht bei `WP_Energiebilanz` mitten zwischen den Fachattributen. |
| Verweise | leeres Element mit `xlink:href="#GML_<uuid>"`. |
| Messwerte | `<waermeMenge uom="MWh/a">22.23</waermeMenge>` |
| Datentypen | Eigenschaft → Element des Datentyps → Inhalt: `<planungsverantwortlicheStelle><WP_Gemeinde><name>…</name><regionalSchluessel12>…</regionalSchluessel12></WP_Gemeinde></planungsverantwortlicheStelle>` |
| Mehrfachwerte | Eigenschaft wiederholen (`<eeGesamtNachEnergietraeger>` mehrmals). |
| Boolean, Datum | `true`/`false`, `JJJJ-MM-TT` |
| Jahreszahlen | `zieljahr`, `basisJahrDatenerfassung` sind in der XSD `string`, nicht `integer`. |

### 3.2 Geometrien

| Eigenschaft | XSD-Typ | Geometrie in den Referenzplänen |
|---|---|---|
| `WP_Plan.raeumlicherGeltungsbereich` | `gml:MultiSurfacePropertyType` (Pflicht) | `gml:MultiSurface` |
| `WP_Bereich.geltungsbereich` | `gml:MultiSurfacePropertyType` (optional) | – (nicht belegt) |
| `position` der Flächenobjekte | `gml:MultiSurfacePropertyType` | `gml:MultiSurface` |
| `position` der Linienobjekte | `gml:MultiCurvePropertyType` | `gml:MultiCurve` mit `gml:LineString` |
| `position` der Objekte mit variabler Geometrie (`WP_Geometrieobjekt`: Großverbraucher, Potenziale, Anschlusszwang, Grünes Methan) | `gml:GeometryPropertyType` | `gml:MultiPoint` (Großverbraucher), `gml:MultiSurface` (Potenziale) |

```xml
<position>
  <gml:MultiSurface srsName="EPSG:25832" gml:id="GML_<uuid>">
    <gml:surfaceMember>
      <gml:Polygon gml:id="GML_<uuid>.0">
        <gml:exterior><gml:LinearRing><gml:posList>x1 y1 x2 y2 … x1 y1</gml:posList></gml:LinearRing></gml:exterior>
        <gml:interior>…</gml:interior>
      </gml:Polygon>
    </gml:surfaceMember>
  </gml:MultiSurface>
</position>
```

| Punkt | Regel |
|---|---|
| `srsName` | **F\|Heat-Festlegung:** `EPSG:25832` (XMAS). ldproxy schreibt `http://www.opengis.net/def/crs/EPSG/0/25832`; beides ist gültig. |
| `gml:id` an Geometrien | In GML 3.2.2 nicht Pflicht. **F\|Heat-Festlegung:** wie XMAS, Multi-Geometrie `GML_<eigene uuid>`, Teile `GML_<uuid>.<n>`, damit Werkzeuge, die die ID erwarten, nicht scheitern. |
| Achsenfolge | Rechtswert Hochwert (x y), 2D, kein `srsDimension`. |
| Ringe | geschlossen (erster = letzter Punkt). Orientierung: außen gegen den Uhrzeigersinn, innen im Uhrzeigersinn (GML-Konvention, `shapely.geometry.polygon.orient(p, 1.0)`). |
| Punkte | `gml:MultiPoint/gml:pointMember/gml:Point/gml:pos` |

## 4. JSON-FG

### 4.1 Version

Das XWärmeplan-Schema ist gegen **JSON-FG 0.2.2** erzeugt (es verweist auf `geometry-objects.json`, das es ab JSON-FG 0.3 nicht mehr gibt). In 0.2.2 gilt:

- Jedes Feature hat die Mitglieder `time`, `place`, `geometry` (Werte dürfen `null` sein, wo das XWärmeplan-Schema es erlaubt).
- `geometry` ist GeoJSON, also **WGS84 (Länge, Breite)**.
- `place` trägt die Geometrie im eigentlichen Koordinatensystem, hier **EPSG:25832**, mit `coordRefSys` auf Collection- oder Feature-Ebene.

### 4.2 Aufbau

```json
{
  "type": "FeatureCollection",
  "conformsTo": [
    "http://www.opengis.net/spec/json-fg-1/0.2/conf/core",
    "http://www.opengis.net/spec/json-fg-1/0.2/conf/types-schemas"
  ],
  "coordRefSys": "http://www.opengis.net/def/crs/EPSG/0/25832",
  "features": [
    {
      "type": "Feature",
      "id": "da2ccadc-8e3f-4ede-b6b5-6e64de551205",
      "featureType": "WP_Waermelinie",
      "time": null,
      "place": {"type": "MultiLineString", "coordinates": [[[332288.068, 5715935.097], [332287.844, 5715927.035]]]},
      "geometry": {"type": "MultiLineString", "coordinates": [[[6.5799991, 51.5695116], [6.5799997, 51.5694391]]]},
      "properties": {
        "gehoertZuBereich": {"href": "#1ed3e4dc-32ad-4b54-8be5-df953493469f", "rel": "related"},
        "waermeMenge": 22.23,
        "waermelinienDichte": 0.16,
        "laenge": 142.0
      }
    }
  ]
}
```

| Punkt | Regel (Schema) | F\|Heat-Festlegung innerhalb des Schemas |
|---|---|---|
| `id` | Zeichenkette, `format: uuid` | reine UUID ohne Typpräfix |
| `featureType` | Name der XWärmeplan-Klasse | – |
| `conformsTo` | Array von Zeichenketten (optional) | die beiden URIs oben |
| `coordRefSys` | – | auf Collection-Ebene `…/EPSG/0/25832` (gilt für `place`) |
| `time` | Pflichtmitglied | `null` |
| `geometry` | Flächen-, Plan-: MultiPolygon; Linien-: MultiLineString; variable Geometrie: beliebig; ohne Raumbezug: `null` | aus `place` nach WGS84 umgerechnet, 7 Nachkommastellen |
| `place` | Pflichtmitglied | EPSG:25832, 3 Nachkommastellen; `null` ohne Raumbezug |
| Messwerte | `number` | Zahl in der Modelleinheit, **kein** `{value, uom}` |
| Verweise | JSON-FG-Link-Objekt, Pflicht `href` und `rel` | `{"href": "#<uuid>", "rel": "related"}`; mehrwertig als Array solcher Objekte |
| Aufzählungen | Code als Zeichenkette | – |
| Mehrfachwerte | Array (`minItems: 1`, oft `uniqueItems`) | auch bei nur einem Wert Array |
| Datentypen | verschachtelte Objekte | – |

Die Gegenprobe aus `abgleich.md` (J1) zeigt, dass genau diese Form für alle Features der vier XMAS-Referenzpläne gültig ist.

## 5. GeoPackage

Es gibt kein offizielles GeoPackage-Schema (`abgleich.md`, Abschnitt 4). Phase 4 schreibt ein nicht normatives F|Heat-Austauschformat und lehnt sich dabei an die relationale DDL `implementierung/postgres/relational/XWärmeplan.sql` an:

| DDL-Muster | Beispiel |
|---|---|
| Tabelle je konkreter Objektart, Name klein | `wp_waermelinie` |
| Spalten klein | `waermemenge`, `waermeliniendichte` |
| Verweis als `<rolle>_fk` | `gehoertzubereich_fk` |
| Aufzählung als `<attribut>_fkcl` (Code) + Codelisten-Tabelle (`code`, `model`, `documentation`, `description`) | `status_fkcl` → `wp_status` |
| mehrwertiger Datentyp als Kindtabelle `<klasse>_<attribut>` | `wp_energiebaublock_eenachenergietraeger` |
| Geometrie `position` mit festem Typ und EPSG:25832, variable Geometrie als `GEOMETRY` | `position geometry(MULTILINESTRING,25832)` |

Abweichung von der DDL: Eine GeoPackage-Tabelle mit gemischtem Geometrietyp (`GEOMETRY`) lässt sich in QGIS schlecht darstellen. Objektarten mit variabler Geometrie werden deshalb, wie im Umsetzungsplan (Phase 4) beschrieben, auf `_flaeche`- und `_punkt`-Tabellen aufgeteilt.

## 6. Testdaten

`tests/fixtures/xwp/` enthält Auszüge, erzeugt mit `scripts/excerpt_xwp_reference.py` (alle Objekte ohne Raumbezug, je Objektart die ersten fünf Fachobjekte mit höchstens 400 Koordinaten):

| Datei | Quelle | Objektarten |
|---|---|---|
| `rheinberg_xmas_auszug.gml`, `.json` | Rheinberg, XMAS | 12 |
| `rheinberg_ldproxy_auszug.gml` | Rheinberg, ldproxy | 12 (andere `gml:id`, kein `gml:identifier`, `srsName` als URI) |
| `oberhausen_xmas_auszug.gml`, `.json` | Oberhausen, XMAS | 14, u. a. `WP_EnergieeinsparungGebaeude`, `WP_PotenzialWaermespeicherung`, `WP_TextAbschnitt` |
| `aachen_xmas_auszug.gml`, `.json` | Aachen, XMAS | 14, u. a. `WP_EnergieRaster`, `WP_Waermenetz`, `WP_Massnahme` |

Zusammen sind 17 der 29 konkreten Objektarten belegt. Ohne Referenzbeispiel bleiben `WP_AnschlussGruenesMethan`, `WP_Anschlusszwang`, `WP_Ausschlussgebiet`, `WP_Eignungspruefung`, `WP_Energieeinsparpotenzialgebiet`, `WP_Kaeltelinie`, `WP_Kaeltenetz`, `WP_Kaelteversorgungsgebiet`, `WP_NichtBeplantesTeilgebiet`, `WP_WaermeKaelteNetz`, `WP_WaermeversorgungsgebietStuetzjahr` und `WP_WaermeversorgungsgebietUmsetzung`; für sie sorgt der Vollständigkeitstest aus Phase 2 (synthetische Minimal- und Maximalobjekte). Alle GML-Auszüge sind gegen die XSD gültig; GML- und JSON-Auszug eines Plans enthalten dieselben Objekte (gleiche UUIDs). Die JSON-Auszüge sind wie die Originale **nicht** schemakonform (`abgleich.md`, J1) und dienen nur als Lesetest.
