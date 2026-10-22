# ADR 0002: XWärmeplan-Export auf xplan-tools

- Status: angenommen
- Datum: 20.10.2026
- Löst ab: [ADR 0001](0001-xwaermeplan.md)
- Ergänzt durch: [ADR 0003](0003-xwaermeplan-phase0.md), [ADR 0004](0004-xwaermeplan-zwei-ausgaben.md)
- Kontext: Technischer Plan „F-Heat → XWärmeplan Export“ (Philipp Sommer, 19.10.2026), Abbildung in [`docs/xwp_mapping.md`](../xwp_mapping.md)

## Kontext

ADR 0001 hat XWärmeplan mit eigenem, aus der XSD generiertem Modell und eigenen Writern umgesetzt, damit F|Heat unter Python 3.12 bleibt. Das sind rund 6.600 Zeilen, die bei jeder Version des Standards nachgezogen werden müssen. Die XLeitstelle pflegt mit xplan-tools ein Python-Modell je Version mit Prüfung von Pflichtfeldern, Codelisten und Verweisen sowie Lese- und Schreibwegen für GML und JSON-FG. xplan-tools 1.20.0 ist die letzte Version für Python 3.12 und bringt XWärmeplan 0.9.5; ab 1.21 verlangt es Python 3.13, 1.26.0 bringt 0.9.6. Seit 13.10.2026 liegt im Repo `spezifikation` die XSD 0.9.7, für die es noch kein xplan-tools gibt.

## Entscheidungen

1. **Export als dünner Adapter auf xplan-tools** im Paket `fheat_core.export.xwp`. Nur die Mapper kennen F|Heat; Builder und Writer reichen an xplan-tools weiter. Die Pipeline und `FHeatOrchestrator` bleiben unverändert.
2. **Zielversion 0.9.6 mit xplan-tools 1.26 unter Python 3.13**, gepinnt auf `>=1.26,<1.27` im Extra `[xwp]`. 0.9.5 unter Python 3.12 wäre sofort lauffähig, bliebe aber zwei Versionen hinter dem Standard stehen. Der Export importiert xplan-tools erst beim Aufruf; ohne das Extra bleibt F|Heat unter 3.10 bis 3.14 installierbar.
3. **Umfang Version 1:** `WP_Plan`, ein `WP_Bereich`, `WP_Waermelinie`, `WP_Waermenetz` und eine Klasse von Versorgungsgebieten. Bestandsanalyse, Baublöcke, Energiebilanz, Maßnahmen und die Ergänzungsdatei aus ADR 0001 entfallen. Die beheizten Gebäude kamen mit ADR 0004 als `WP_GebaeudeBaublock` hinzu.
4. **Eigene Export-Konfiguration** `XWPExportConfig`, getrennt von `FHeatConfig` (nur Rechenparameter). Zwei Modi: `plan` mit allen Pflichtangaben einschließlich Beschlussdatum, `fragment` nur mit Bereich und Fachobjekten zum Einfügen in den Plan der Gemeinde.
5. **Codes und Einheiten als Tabellen** in `mapping.py`; ein Test gleicht sie mit dem Modell von xplan-tools ab. Unbekannte Codes lösen einen Fehler aus, kein stiller Rückfall auf 9999.
6. **Stabile IDs:** `uuid5` aus Regionalschlüssel, Objektart und einem F|Heat-Schlüssel.
7. **Prüfung auf drei Ebenen** in einem Bericht: Struktur (xplan-tools), Schema (GML gegen die XSD, offline), Konsistenz mit dem F|Heat-Ergebnis. Mit ADR 0004 kam die Ebene Konformität hinzu; eine Datei wird nur ohne Befund geschrieben, und zwar nur als GML, das normative Format (warum kein JSON-FG: ADR 0004).
8. **Keine Eignungsstufe ohne ausdrückliche Schwellen.** Die Dichte der verschmolzenen Eignungspolygone ist nicht die Baublockdichte, auf die sich die Leitfadenschwellen beziehen.

## Folgen

- fheat-web braucht ein Backend unter Python 3.13 mit GDAL-Python-Bindung. topotherm deklariert `requires-python <=3.13`, was pip für 3.13.1 und später ablehnt; das muss topotherm ändern oder fheat-web bei der Installation umgehen.
- fheat-web nutzt bis zum Anheben von `FHEAT_REF` die alte Schnittstelle (`fheat_core.xwp`) und braucht einen Folge-Branch: Planformular auf `XWPExportConfig`, Ergänzungsdatei und GeoPackage entfallen.
- Die XSD 0.9.6 samt OGC- und W3C-Schemas liegt nur noch als Testdatei unter `tests/fixtures/xwp/xsd-0.9.6/`; im Paket wird sie nicht mitgeliefert.
- Der Wechsel auf 0.9.7 heißt: xplan-tools anheben, `mapping.py` und die Mapper an geänderte Namen anpassen (u. a. wird `beschlussDatum` optional, `planstatus` und `reporting` werden Pflicht), XSD-Testdaten tauschen.
- Lizenz: xplan-tools steht unter EUPL-1.2-or-later, F|Heat unter GPL-3.0-or-later. Die EUPL 1.2 nennt die GPLv3 als kompatibel; vor dem Release mit der Rechtsberatung bestätigen.
