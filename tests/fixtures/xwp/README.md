# Testdaten XWärmeplan

Auszüge aus den Referenzplänen der XLeitstelle, https://gitlab.opencode.de/xleitstelle/xwaermeplan/implementierung, Ordner `Referenzplaene`, Commit `52b9e3e624ffa1ee88b3a4abc8fb130fe1250fb4` (06.10.2026). Die Pläne sind abgeschlossene kommunale Wärmeplanungen (Aachen, Oberhausen, Rheinberg), die die XLeitstelle in XWärmeplan 0.9.6 überführt hat.

Erzeugt mit `scripts/excerpt_xwp_reference.py` (Standardwerte: je Objektart fünf Fachobjekte mit höchstens 400 Koordinaten, alle Objekte ohne Raumbezug):

| Datei | Original |
|---|---|
| `rheinberg_xmas_auszug.gml` / `.json` | `Rheinberg_v096_xmas.gml` / `.json` |
| `rheinberg_ldproxy_auszug.gml` | `Rheinberg_v096_ldproxy.gml` |
| `oberhausen_xmas_auszug.gml` / `.json` | `Oberhausen_v096_xmas.gml` / `.json` |
| `aachen_xmas_auszug.gml` / `.json` | `Aachen_v096_xmas.gml` / `.json` |

Die GML-Auszüge sind gegen die XSD gültig. Die JSON-Auszüge folgen wie die Originale nicht dem offiziellen JSON-Schema (siehe `docs/xwaermeplan/abgleich.md`, J1) und dienen nur als Lesetest.

Das Repo `implementierung` enthält keine Lizenzdatei; Nutzungsbedingungen sind bei der XLeitstelle zu klären.

## Beispiel Burgsteinfurt (Golden-File-Test)

`burgsteinfurt_auszug.gpkg` ist ein Ausschnitt der NRW-Rohdaten um das Beispiel-Planungsgebiet (`examples/planungsgebiet.gpkg`, plus 150 m Rand), abgerufen über den F|Heat-NRW-Adapter:

| Layer | Inhalt | Quelle, Lizenz |
|---|---|---|
| `gebaeude` | 1471 Gebäude mit Wärmebedarf, Typ, Block-ID | LANUV NRW, Datensatz Kommunale Wärmeplanung (opengeodata.nrw.de), voraussichtlich Datenlizenz Deutschland – Namensnennung – 2.0 (vor Veröffentlichung prüfen) |
| `strassen` | 182 Straßenabschnitte | wie oben |
| `flurstuecke` | 959 Flurstücke | Geobasis NRW, ALKIS (INSPIRE-Flurstücke), Datenlizenz Deutschland – Zero – 2.0 |
| `planungsgebiet` | Planungsgebiet des Beispiels | F\|Heat |

`golden_burgsteinfurt.json` hält die Kennzahlen des daraus erzeugten Wärmeplans fest (`tests/test_xwp_golden.py`). Nach einer gewollten Änderung des Mappings mit `FHEAT_UPDATE_GOLDEN=1 python -m pytest tests/test_xwp_golden.py` neu schreiben und den Diff prüfen.
