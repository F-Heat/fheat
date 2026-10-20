# ADR 0001: XWärmeplan in F|Heat

- Status: abgelöst durch [ADR 0002](0002-xwaermeplan-xplan-tools.md) (20.10.2026). Die hier genannten Dateien unter `docs/xwaermeplan/` und `src/fheat_core/xwp/` wurden dabei entfernt; sie stehen in der Historie bis Commit `0f50c75`.
- Datum: 12.10.2026
- Kontext: `docs/xwaermeplan/XWaermeplan_Umsetzungsplan.md`, Befunde in `docs/xwaermeplan/abgleich.md` und `docs/xwaermeplan/kodierung.md`

## Kontext

F|Heat soll Wärmepläne im Standard XWärmeplan ausgeben (GML, JSON-FG, GeoPackage). Der Standard liegt in Version 0.9.6 vor und ist noch nicht verbindlich; Klassen und Attribute können sich bis zur Verabschiedung ändern. Die XLeitstelle stellt XSD, JSON-Schema, Referenzpläne und mit XPlan-Tools eine Python-Bibliothek bereit. XPlan-Tools verlangt Python 3.13 und GDAL; F|Heat muss wegen topotherm und des Web-Backends unter Python 3.12 laufen.

## Entscheidungen

1. **Zielversion 0.9.6.** Die XSD im Repo `xleitstelle/xwaermeplan/spezifikation` (Commit `2f7715e`) hat den Namespace `http://www.xwaermeplan.de/0/9/6` und stimmt mit der Modellreferenz überein (`abgleich.md`, Abschnitt 1).

2. **Schemas vor Referenzplänen.** Maßgeblich sind XSD (GML) und JSON-Schema (JSON-FG). Sie gelten vor den Referenzplänen und vor dem Verhalten von XPlan-Tools. F|Heat folgt dem Schema auch dann, wenn kein Referenzplan dagegen gültig ist; das ist für JSON-FG der Fall (`abgleich.md`, J1/J2). Abweichungen werden in `abgleich.md` dokumentiert.

3. **Eigene Writer statt XPlan-Tools als Laufzeitabhängigkeit.** `fheat_core.xwp` erhält ein schlankes, aus der XSD generiertes Modell und eigene Writer (GML mit `lxml`, JSON-FG mit `json`, GeoPackage mit `geopandas`/`pyogrio`). Neue Pflichtabhängigkeit nur `lxml` im Extra `[xwp]`.

4. **XPlan-Tools nur als GML-Prüfstein in CI.** Ein getrennter CI-Job mit Python 3.13 liest unsere GML-Ausgaben mit XPlan-Tools ein. Für JSON-FG taugt XPlan-Tools nicht als Prüfstein, weil es Messwerte als `{value, uom}` und Verweise als nackte UUID schreibt; JSON-FG wird nur gegen das offizielle Schema geprüft.

5. **Spezifikation vendort, Validierung offline.** XSD (samt GML 3.2.1, ISO 19139, XLink, OGC-API-Features-`core-sf`) und JSON-Schema (samt JSON-FG 0.2.2) liegen unter `src/fheat_core/xwp/spec/0.9.6/` mit XML-Katalog bzw. `catalog.json`. Tests und `validate()` brauchen kein Netz. `scripts/fetch_xwp_spec.py` erzeugt den Ordner neu.

6. **JSON-FG 0.2.2.** Das XWärmeplan-Schema ist gegen JSON-FG 0.2.2 erzeugt; der OGC-beta-Server liefert inzwischen 0.3 aus, wo `geometry-objects.json` fehlt. Vendort wird deshalb JSON-FG 0.2.2 aus dem OGC-Repo (Tag `v0.2.2`).

7. **Versionskapsel.** Alles Versionsabhängige liegt unter `fheat_core/xwp/` (`spec/<version>/`, generiertes `model/v0_9_6.py`, `mapping/`). Die Encoder lesen nur Modellmetadaten. Ein Versionswechsel heißt: Spezifikation neu holen, Generator laufen lassen, Mapping-Diffs beheben.

8. **Kodierung.** GML: `sf:FeatureCollection`, `gml:id="GML_<uuid>"`, `gml:identifier codeSpace="urn:uuid"`, lokale `xlink:href="#GML_<uuid>"`, `srsName="EPSG:25832"`, Einheiten als `uom` nach Modell. JSON-FG: Messwerte als Zahl, Verweise als `{"href": "#<uuid>", "rel": "related"}`, `id` als UUID, `place` in EPSG:25832, `geometry` in WGS84. Einzelheiten in `kodierung.md`.

9. **GeoPackage nicht normativ.** Es gibt kein offizielles GeoPackage-Schema. F|Heat schreibt ein Austauschformat, das sich an die relationale DDL der XLeitstelle anlehnt, und kennzeichnet es als nicht normativ. GML bleibt das normative Format.

10. **Annahmen aus dem Umsetzungsplan (Abschnitt 2.3)** gelten unverändert: ein `WP_Plan` je Projekt mit einem `WP_Bereich` (nummer 0); Datenschutzschwelle für Baublöcke (Default 5 Gebäude, fachlich zu prüfen); EPSG:25832; Eignungsstufen nur als überschreibbarer Vorschlag.

## Folgen

- Die vendorten Dateien (1,1 MB) und die Referenzplan-Auszüge (1,9 MB) liegen im Repo. Für ein Release müssen die Spezifikationsdateien als Package-Data in den Wheel (Phase 1, `pyproject.toml`).
- Ändert die XLeitstelle das JSON-Schema auf eine neuere JSON-FG-Version, muss `scripts/fetch_xwp_spec.py` angepasst werden.
- Offene Lizenzfrage zu Spezifikation und Referenzplänen (`abgleich.md`, Abschnitt 5) vor dem ersten Release klären.
