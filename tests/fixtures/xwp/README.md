# Testdaten XWärmeplan

## Beispiel Burgsteinfurt (Golden-File-Test)

`burgsteinfurt_auszug.gpkg` ist ein Ausschnitt der NRW-Rohdaten um das Beispiel-Planungsgebiet (`examples/planungsgebiet.gpkg`, plus 150 m Rand), abgerufen über den F|Heat-NRW-Adapter:

| Layer | Inhalt | Quelle, Lizenz |
|---|---|---|
| `gebaeude` | 1471 Gebäude mit Wärmebedarf, Typ, Block-ID | LANUV NRW, Datensatz Kommunale Wärmeplanung (opengeodata.nrw.de), voraussichtlich Datenlizenz Deutschland – Namensnennung – 2.0 (vor Veröffentlichung prüfen) |
| `strassen` | 182 Straßenabschnitte | wie oben |
| `flurstuecke` | 959 Flurstücke | Geobasis NRW, ALKIS (INSPIRE-Flurstücke), Datenlizenz Deutschland – Zero – 2.0 |
| `planungsgebiet` | Planungsgebiet des Beispiels | F\|Heat |

`golden_burgsteinfurt.json` hält die Kennzahlen des daraus erzeugten Wärmeplans fest (`tests/test_xwp_golden.py`). Nach einer gewollten Änderung des Mappings mit `FHEAT_UPDATE_GOLDEN=1 python -m pytest -m xwp tests/test_xwp_golden.py` neu schreiben und den Diff prüfen.

## XSD 0.9.6 für die Offline-Prüfung

`xsd-0.9.6/` enthält die XSD des Standards und alle importierten Schemas mit einem XML-Katalog (`catalog.xml`), damit die Schemaprüfung kein Netz braucht. Nicht von Hand ändern.

| Ordner | Quelle | Stand |
|---|---|---|
| `waermeplan.xsd` | XLeitstelle, https://gitlab.opencode.de/xleitstelle/xwaermeplan/spezifikation, heute `xsd/0.9.6/waermeplan.xsd` | Commit `2f7715e70c35042f9e5c13c2157ddd9a02ef704c` (08.09.2026), Git-Blob `7898e8bf809b427db4034e35820deba06c55dc6e` |
| `schemas.opengis.net/` (GML 3.2.1, ISO 19139, OGC API Features `core-sf`, GML-SF-Profil) | Open Geospatial Consortium, http://schemas.opengis.net | abgerufen 12.10.2026 |
| `www.w3.org/` | W3C, http://www.w3.org/1999/xlink.xsd und http://www.w3.org/2001/xml.xsd | abgerufen 12.10.2026 |

Zeilenenden auf LF vereinheitlicht, sonst unverändert.

## Belege aus dem Original (`tests/test_xwp_evidence.py`)

`tests/test_xwp_evidence.py` prüft die Tabellen in `mapping.py` gegen diese Dateien, ohne xplan-tools und GDAL.

| Datei | Quelle im Repo `spezifikation` (Stand `main`, Commit `b98b837`, 13.10.2026) | Stand |
|---|---|---|
| `json-0.9.6/features.json`, `json-0.9.6/featurecollection.json` | `json/0.9.6/` | heruntergeladen mit CRLF (Git-Blob der Datei `96867ad…` bzw. `10b98aa…`), auf LF vereinheitlicht, sonst unverändert |
| `oak-0.9.6-einheiten.json` | `objektartenkatalog/XWaermeplan096.zip`, Git-Blob `874124ca62a76a4d42835e265438896936d6d66d` | erzeugt mit `python scripts/extract_xwp_units.py <ZIP> tests/fixtures/xwp/oak-0.9.6-einheiten.json` |

`oak-0.9.6-einheiten.json` enthält Klasse → Attribut → Maßeinheit aus den Paketen `WP_Basisobjekte`, `WP_Raumobjekte` und `WP_Reporting`; die übrigen Pakete im ZIP sind veraltet. Die XSD selbst führt keine Einheiten. Im Katalog fehlt bei `°C` das Grad-Zeichen (U+FFFD); das Skript setzt es wieder ein (`REPAIRS`). Nicht von Hand ändern.

## Lizenz

- **OGC-Schemas:** OGC Document/Software Notice, https://www.ogc.org/about/policies/ ; Weitergabe mit Herkunftsangabe erlaubt.
- **W3C `xml.xsd`, `xlink.xsd`:** W3C Software and Document License.
- **XWärmeplan (XLeitstelle):** Das Repo `spezifikation` enthält keine Lizenzdatei. Die Datei liegt hier nur zur Validierung in den Tests; die Nutzungsbedingungen sind bei der XLeitstelle zu klären.
