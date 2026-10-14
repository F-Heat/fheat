# XWärmeplan: Datenbasis in F|Heat

Stand: 12.10.2026 (Phase 5). Welche Gebäudedaten F|Heat für XWärmeplan bereitstellt und woher sie kommen.

## Neue Gebäudespalten

| Kanonisch | Ausgabe (deutsch) | Inhalt | NRW | Flex |
|---|---|---|---|---|
| `construction_year` | `Baujahr` | echtes Baujahr | – (nicht verfügbar) | über `column_map` |
| `parcel_year` | `Jahr_Flurstueck` | Jahr aus `validFrom` des Flurstücks; Grundlage der BAK | ja | – |
| `xwp_building_type` | `Gebaeudetyp_XWP` | Code aus `WP_GebaeudeTyp` | ja | über `column_map` oder später abgeleitet |

Bestehende Spalten bleiben unverändert, auch `construction_class` (BAK) und `age` (LANUV-Alter).

Eine Spalte „Anzahl Wohnungen“ gibt es nicht: Die NRW-Daten enthalten nur die Zahl der Adressen (`Anz_Adr`), nicht die der Wohnungen.

## Gebäudetyp (`WP_GebaeudeTyp`)

Reihenfolge, erste passende Angabe gewinnt (`fheat_core/xwp/mapping/building_type.py`):

1. Wohngebäudetyp der Quelle (LANUV `GEBAEUDETY`): EFH → 10001, RH → 10002, MFH → 10003, GMFH → 10004.
2. ALKIS-Gebäudefunktion über `fheat_core/data/xwp_gebaeudetyp.json` (alle 232 Funktionen aus `building_functions.json`). Wohngebäude nach GEG § 3, auch Wohn-, Alten- und Pflegeheime → 1000. Gemischt genutzte Gebäude mit Wohnen → 9999, weil nicht eindeutig. Nichtwohngebäude → passender Untertyp (Büro, Handel, Beherbergung, Krankenhaus, Kultur, Bildung, Sport, Schwimmbad, Lager, Industrie), sonst 2000.
3. Lastprofil, nur auf die Oberkategorie: EFH/MFH → 1000, GKO/GMK/GHA → 2000. Ein Standard-Lastprofil (Flex-Adapter) soll kein Einfamilienhaus vortäuschen.
4. Sonst 9999.

Die Tabelle ist eine fachliche Zuordnung und sollte durchgesehen werden. Einzelne Codes lassen sich in der JSON ändern.

## Baujahr und Baualtersklasse

`WP_Baualtersklasse` ist zweistufig:

| Oberklasse | Unterklassen |
|---|---|
| 1000 bis 1949 | 10001 vor 1919, 10002 1919–1949 |
| 2000 1950–1969 | 20001 1950–1959, 20002 1960–1969 |
| 3000 1970–1989 | 30001 1970–1979, 30002 1980–1989 |
| 4000 1990–2015 | 40001 1990–1999, 40002 2000–2009, 40003 2010–2015 |
| 5000 ab 2016 | – |
| 9999 unbekannt | – |

Die BAK von F|Heat (B–J, Grenzen 1918/1948/1957/1968/1978/1983/1994/2001) passt nicht auf diese Grenzen. Deshalb wird das Jahr selbst gebraucht.

**Befund zu den NRW-Quellen:**

- `validFrom` des **Flurstücks** ist kein Baujahr, sondern das Datum des Katastereintrags. In Burgsteinfurt häufen sich die Jahre 1958, 1961 und 2011, also Fortführungen und Digitalisierung. Das Jahr bleibt als `parcel_year` erhalten, ist aber nur eine schwache Näherung.
- Das **LANUV-Alter** (`age`, aus `GEBAEUDETY`, z. B. `EFH_1945`) ist gebäudebezogen. Die Zahl ist ein Stellvertreterjahr der LANUV-Altersklasse. In Burgsteinfurt kommen vor: 1900, 1945, 1960, 1970, 1980, 1985, 1995, 2000, 2005, 2010, 2015, 2022.

`XwpConfig.construction_year_sources` legt die Reihenfolge der Quellen fest, Standard `("construction_year", "age", "parcel_year")`: echtes Baujahr vor LANUV-Alter vor Flurstücksjahr. Wie ein LANUV-Stellvertreterjahr auf die Klassen verteilt wird, regelt Phase 6. Ohne die genauen Grenzen der LANUV-Klassen ist dort nur die Oberklasse sicher.
