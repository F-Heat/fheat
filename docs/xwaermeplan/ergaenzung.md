# XWärmeplan: Ergänzungsdatei

Stand: 12.10.2026 (Phase 8). F|Heat füllt aus seinen Daten Plan, Bereich, Wärmelinien, Baublöcke, Raster, Netze und Gebäudezahlen. Alles andere kommt vom Planer über die Ergänzungsdatei: Maßnahmen, Texte, Energiebilanzen, Potenziale, Bestandsnetze, Schutz- und Ausschlussgebiete, Kälte und die Entscheidung über die Versorgungsgebiete.

## Dateien

| Datei | Inhalt | Bearbeiten mit |
|---|---|---|
| `xwp_ergaenzung.gpkg` | alle 92 Tabellen des F\|Heat-Layouts (`kodierung.md`, Abschnitt 5), vorbefüllt | QGIS |
| `xwp_ergaenzung.xlsx` | nur die Tabellen ohne Geometrie: Maßnahmen, Texte, Energiebilanzen, aggregierte Angaben und ihre Kindtabellen; Codelisten als Blätter, Auswahllisten in den Code-Spalten | Excel, LibreOffice |

Beide sind optional und lassen sich kombinieren. Erzeugt werden sie mit `fheat_core.xwp.supplement.write_template(doc, gpkg, xlsx, placeholders)`.

**Vorbefüllt** sind nur Objekte, die der Planer prüfen oder vervollständigen soll:

- der Plan (Metadaten aus `XwpPlanConfig`),
- die vorgeschlagenen Wärmeversorgungsgebiete und Eignungsprüfungen, **ohne** berechnete Werte (z. B. `waermemenge`), damit eine neue Berechnung nicht von einer alten Datei überschrieben wird,
- Platzhalter für die Wärmequellen der Netze (`wp_potenzialwaermenutzung_punkt`: Energieträger und Potenzial fehlen) und, wenn `XwpConfig.large_consumer_mwh` gesetzt ist, für Großverbraucher.

## Regeln beim Einlesen

| Fall | Ergebnis |
|---|---|
| Zeile mit der `uuid` eines F\|Heat-Objekts | überschreibt dieses Objekt: jede ausgefüllte Zelle ersetzt den Wert von F\|Heat, leere Zellen lassen ihn stehen; Listen (Kindtabellen) werden als Ganzes ersetzt |
| Zeile ohne oder mit neuer `uuid` | neues Objekt; `gehoertzuplan_fk`/`gehoertzubereich_fk` leer → Plan bzw. Bereich |
| neues Objekt, dem eine Pflichtangabe fehlt | wird nicht übernommen und gemeldet (z. B. Wärmequelle ohne Energieträger) |
| zweiter `WP_Plan` | wird nicht übernommen |
| unbekannte Tabelle, unbekannte Spalte, falscher Code, unlesbares Datum | Befund mit Tabelle und Zeile; die übrigen Werte der Zeile gelten |

Kindtabellen (z. B. `wp_energiebilanz_eegesamtnachenergietraeger`) verweisen mit `<tabelle>_id` auf die `uuid` bzw. `_id` der übergeordneten Zeile. Messwerte stehen in der Einheit des Spaltenkommentars (Alias), Datumsangaben als JJJJ-MM-TT.

## Rückleser

`fheat_core.xwp.decode.gml.read_gml` liest XWärmeplan-GML: eigene Ausgaben und die Referenzpläne in beiden Varianten (XMAS/XPlan-Tools und ldproxy). Messwerte mit einer anderen Einheit als im Modell behalten ihre Einheit; `validate()` meldet die Abweichung (bei Rheinberg und Aachen: `eeGesamtGebaeude`, `eeGesamtProzesse` in MWh/a statt MWh). Geometrien in einem anderen Koordinatensystem werden nach EPSG:25832 umgerechnet.

`fheat_core.xwp.decode.gpkg.read_gpkg` liest GeoPackages im F|Heat-Layout. Lesen, Schreiben und erneutes Lesen sind für alle 29 Objektarten und alle Referenzpläne verlustfrei (Tests in `tests/test_xwp_supplement.py`).
