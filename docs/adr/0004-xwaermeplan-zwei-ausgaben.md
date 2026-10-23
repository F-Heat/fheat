# ADR 0004: Interne Namen bleiben; F|Heat- und XWärmeplan-Ausgabe nebeneinander

- Status: angenommen
- Datum: 22.10.2026
- Ergänzt: [ADR 0002](0002-xwaermeplan-xplan-tools.md), [ADR 0003](0003-xwaermeplan-phase0.md)
- Kontext: Technischer Plan „F-Heat → XWärmeplan Export“ (Philipp Sommer, 19.10.2026), Abbildung in [`docs/xwp_mapping.md`](../xwp_mapping.md)

## Kontext

Der Umsetzungsplan für Phase 0 sah in seiner ersten Änderung (A5) vor, XWärmeplan ab dem Schritt `adjust` zum Datenmodell von F|Heat zu machen. Dazu gehörten:
- Layer mit Typbezeichnungen `WP_*`/`FH_*`;
- Gebäudetyp und Baualtersklasse schon in `adjust`;
- eine Namensregel für Erweiterungen;
- umbenannte Spalten in den Adaptern;
- andere Einheiten;
- ein Umgang mit alten Ergebnissen.

Dagegen spricht zweierlei. F|Heat setzt XWärmeplan nur zum Teil um, und der Standard ändert sich weiter; seit 13.10.2026 liegt 0.9.7 vor. Als Datenmodell träfe jede Änderung des Standards Kern, Adapter, F|Heat-Ausgabe und Web.

## Entscheidungen

1. **Interne Namen bleiben.**
   - Spaltennamen, Einheiten und Anzeigenamen bleiben, wie sie sind, als Konstanten und Dicts in `columns.py` (`LABELS_DE`).
   - XWärmeplan kommt nur im Exporter `fheat_core.export.xwp` vor, der F|Heat nur über die Konstanten aus `columns.py` liest.
   - Klassen, Attribute, Codes, Einheiten und Umrechnungen stehen nur in `mapping.py`, als Tabelle je Klasse, jede Zeile belegt.
   - Damit ist das Datenmodell XWärmeplan ab `adjust` verworfen, samt den Folgeentscheidungen dazu.
2. **Zwei Ausgaben nebeneinander, der Nutzer wählt** (eine, die andere oder beide).
   - Die **F|Heat-Ausgabe** (`save_outputs`) bleibt, wie sie ist: alle Layer und Tabellen, mit internen Namen oder deutschen Bezeichnungen.
   - Die **XWärmeplan-Ausgabe** (`export_xwaermeplan`) enthält nur Klassen und Attribute von XWärmeplan, jede belegt mit XSD oder Objektartenkatalog.
   - Straßen, Flurstücke, Leitungen, die Wärmequelle und alle Werte ohne Attribut in XWärmeplan bleiben in der F|Heat-Ausgabe.
3. **Nur nachweislich konform.**
   - Der Bericht hat vier Prüfebenen: Aufbau (xplan-tools), Schema (GML gegen die XSD, wenn `schema_dir` sie bereitstellt), Konsistenz mit dem F|Heat-Ergebnis und neu Konformität.
   - Die Ebene Konformität prüft die Bedingungen der XSD-Dokumentation, die das Schema nicht erzwingt. Außerhalb der kleinen Wärmeplanung braucht ein Gebiet für das Zieljahr alle drei Eignungsstufen. Ein bestehendes Netz braucht `medium` und `temperatur`.
   - Der Export schreibt erst `<name>.partial.gml` und schiebt die Datei nur ohne Befund an ihren Platz. Sonst gibt es keine Datei, nur den Bericht mit den Befunden.
   - Hinweise (`notes`) blockieren nicht.
4. **Die XSD wird nicht mitgeliefert.**
   - Das Repo `spezifikation` der XLeitstelle enthält keine Lizenzdatei.
   - Die Schemaprüfung läuft, wenn der Aufrufer die XSD 0.9.6 mit XML-Katalog als `schema_dir` übergibt. Ohne `schema_dir` sagt ein Hinweis, dass die GML nicht gegen die XSD geprüft wurde.
   - Die Tests prüfen den Writer gegen die XSD unter `tests/fixtures/xwp/xsd-0.9.6/`, offline und in CI.
5. **Gebäude als Baublöcke (E12–E15),** über ADR 0002 Nr. 3 hinaus.
   - Nach WPG § 3, zitiert in der XSD bei `WP_Baublock`, ist ein Baublock „ein Gebäude oder mehrere Gebäude oder Liegenschaften“. Deshalb wird jedes beheizte Gebäude mit seinem Grundriss ein `WP_GebaeudeBaublock`.
   - Ein Gebäude zählt, wenn sein repräsentativer Punkt in der Plangrenze liegt; der Grundriss wird an der Plangrenze geschnitten.
   - `gebaeudetyp` kommt aus der ALKIS-Gebäudefunktion, sonst aus dem LANUV-Typ. Belegbar ist dort nur die Oberkategorie 1000, weil LANUV nach Nutzfläche unterscheidet, XWärmeplan nach der Zahl der Wohnungen.
   - `ueberwiegendBaujahr` kommt aus dem Baujahr, sonst aus der LANUV-Baualtersklasse, jeweils als Oberkategorie.
   - Ohne Beleg steht 9999. Die Tabellen und Belege stehen in `docs/xwp_mapping.md`.
6. **Kein `WP_EnergieBaublock`.**
   - Die XSD beschreibt `waermeMenge` und `waermeDichte` der Klasse als „Erzeugernutzwärme“. Der Wärmebedarf von F|Heat ist Nutzwärme (LANUV: „Raumwärmebedarf (Nutzenergie)“).
   - Ohne diese beiden Werte hätte die Klasse keinen Inhalt.
7. **Kein JSON-FG.**
   - JSON-FG, wie xplan-tools 1.26 es schreibt, hat im Beispiel Burgsteinfurt 1669 Befunde gegen das JSON-Schema 0.9.6: Messwerte stehen als `{value, uom}` statt als Zahl, Verweise als nackte UUID statt als Link-Objekt.
   - Nach dem Umbau ist die Datei gültig, aber xplan-tools kann sie nicht mehr lesen.
   - Da eine nicht konforme Datei den Export nicht verlässt, schreibt der Export nur GML. Die Messung steht in `docs/xwp_mapping.md`.

## Folgen

- Eine Änderung des Standards trifft nur `mapping.py`, die Mapper und die Testdaten, nicht Kern, Adapter, F|Heat-Ausgabe oder Web.
- `export_xwaermeplan` nimmt genau eine `.gml`-Datei; der Bericht nennt sie in `file`, mit Befunden steht dort `None`. fheat-web muss das übernehmen und bei Befunden den Bericht ohne Datei zeigen.
- Ein Baublock ist ein einzelnes Gebäude. Ob die Gemeinde die Werte so veröffentlicht, entscheidet sie (Datenschutz); der Bericht weist darauf hin.
- Wer außerhalb der Tests gegen die XSD prüfen will, muss sie selbst bereitstellen.
- JSON-FG kann folgen, wenn Standard und xplan-tools übereinstimmen.
