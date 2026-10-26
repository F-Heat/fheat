# Potenzialdaten NRW: Befunde der Erkundung (Phase 0)

Stand: 19.10.2026. Erzeugt mit `scripts/inspect_potential_sources.py` (Ausgabe lokal, nicht im Repo).
Grundlage für die Phasen 1 bis 5 des Umsetzungsplans „Solar- und Geothermiepotenziale“.

## 1. Kurzfassung

| Frage | Befund |
|---|---|
| Feldname der Baublock-ID in ONG/MTG | `block_id` (Text, z. B. `u1m0w7vp6zby`). Gleiche Werte wie `Block_ID` im Wärmemodell (`cols.BLOCK_ID`): in Steinfurt alle 1.374 Block-IDs der Gebäude gefunden |
| Ergiebigkeit EWS in kWh/(m·a) in IS GT? | **Nein.** GeoPackage und Raster enthalten nur Wärmeleitfähigkeit (Klassen bzw. Werte), Kollektor-Eignung und Daten zur tiefen Geothermie. Phase 2 nutzt deshalb den VDI-4640-Richtwert |
| Lizenz LANUK (Wärmestudie) | Datenlizenz Deutschland – Zero – Version 2.0 (Angabe auf der OpenGeoData-Seite des Ordners `kwp/`). `KWP-NRW_meta.zip` enthält nur Dokumentation, keine Lizenzdatei |
| Lizenz GD NRW (IS GT) | Datenlizenz Deutschland – Namensnennung – Version 2.0 (Download-Seite `ISGT/`, WFS). Quellenangabe „Geologischer Dienst NRW“ nötig |
| Lücken im WFS? | Ja, als **fehlende Fläche**, nicht als eigene Objekte. EWK1800/2400 bedecken die Stichprobe Burgsteinfurt nur zu 56 %; EWS40–100 dort lückenlos |
| GDB im ZIP direkt mit `bbox` lesbar? | Ja: `gpd.read_file("/vsizip/<zip>/<name>.gdb", layer=..., bbox=...)`. TG 0,2 s, FF-ST 1,5 s, ONG/MTG 2–11 s. `zip://<zip>!<name>.gdb` geht auch, ist bei ONG/MTG aber 4× langsamer |

**Wichtigster Befund, abweichend vom Plan:** Das Gemeinde-ZIP `KWP-NRW_<AGS>_<Name>_EPSG25832_Shape.zip`,
aus dem fheat heute schon Gebäude und Wärmelinien liest, enthält die drei LANUK-Potenziale
bereits für die Gemeinde als Shapefile:

- `Potenzial-ONG-MTG-Baublock_<AGS>_<Name>.shp`
- `Potenzial-TG-Raster_<AGS>_<Name>.shp`
- `Potenzial-FF-Solarthermie-Flur_<AGS>_<Name>.shp`

Das ONG/MTG-Shape hat **kein** Feld `block_id`, sonst dieselben Felder. Geometrie und Werte sind
identisch mit der NRW-GDB (Steinfurt: 1.386 von 1.386 Blöcken über einen Punkt im Block zugeordnet,
Abweichung `ON_kWh_ist` 0,0).

Folgerung für die Umsetzung:

- **ONG/MTG** kommt aus dem Gemeinde-ZIP (≈ 30 MB, im Zwischenspeicher). Die NRW-GDB (553 MB)
  wird nicht gebraucht. Die `block_id` eines Blocks wird aus den Gebäuden übernommen, die im
  Block liegen (Punkt im Gebäude → Block).
- **TG** und **FF-Solarthermie** kommen aus den NRW-GDBs (2 MB bzw. 63 MB, Zwischenspeicher),
  weil der Puffer um das Gebiet (5 km bzw. 2 km) über die Gemeindegrenze reicht.

## 2. Quellen und Stände (index.json)

| Datei | Größe | Stand |
|---|---|---|
| `kwp/KWP-NRW-Potenzial_ONG_MTG_Baublock_EPSG25832_Geodatabase.zip` | 553 MB | 18.12.2024 |
| `kwp/KWP-NRW-Potenzial_TG_Raster_EPSG25832_Geodatabase.zip` | 2,1 MB | 20.02.2025 |
| `kwp/KWP-NRW-Potenzial_FF_Solarthermie_Flur_EPSG25832_Geodatabase.zip` | 63 MB | 18.12.2024 |
| `kwp/KWP-NRW_meta.zip` (Datensatzbeschreibung, in `metafiles`) | 3,7 MB | 18.12.2024 |
| `kwp/KWP-NRW_05566084_Steinfurt_EPSG25832_Shape.zip` (Beispiel Gemeinde) | 31 MB | 18.12.2024 |
| `ISGT/ISGT_EPSG25832_GeoPackage.zip` | 112 MB | 31.07.2026 |
| `ISGT/ISGT-raster_EPSG25832_TIFF.zip` | 16 MB | 31.07.2026 |

`index.json` liefert je Datei `name`, `size` (Text) und `timestamp` (ISO-Zeit, teils mit
Mikrosekunden). Die Metadaten-ZIP steht unter `metafiles`, nicht unter `datasets`.
Datenstand der LANUK-Werte selbst (Feld `Stand`): 01.09.2024. Alle LANUK-Daten in EPSG:25832.

## 3. LANUK ONG/MTG je Baublock

NRW-GDB: `Potenzial_ONG_MTG_Baublock_NRW.gdb`, Layer `Pot_ONG_MTG_NRW`, MultiPolygon, 492.134 Objekte.
Gemeinde-Shape: `Potenzial-ONG-MTG-Baublock_<AGS>_<Name>.shp` (Steinfurt: 1.386 Objekte).

| Feld | Typ | Einheit | Inhalt |
|---|---|---|---|
| `block_id` | Text | – | ID des Baublocks (**nur in der GDB**) |
| `AGS` | Text | – | Gemeindeschlüssel, achtstellig |
| `Gemeinde` | Text | – | Name der Gemeinde |
| `ON_kWh_ist` | Double | **kWh/a** | Potenzieller Jahresertrag oberflächennahe Geothermie, heute |
| `ON_kWh_45` | Double | kWh/a | dto. 2045 (Szenario moderat) |
| `MT_kWh_ist` | Double | kWh/a | Mitteltiefe Geothermie mit Erdwärmesonden (1.000 m), heute |
| `MT_kWh_45` | Double | kWh/a | dto. 2045 |
| `Heizlast` | Double | kW | Summierte Heizlast der Gebäude im Block |
| `Heizlast45` | Double | kW | dto. 2045 |
| `Stand` | Datum (Shape: Text `20240901`) | – | Datenstand |

- Einheit ist **kWh/a**, nicht GWh/a wie im Plan angenommen.
- Ohne Bewertung: alle Wertefelder leer (Steinfurt: 90 von 1.386 Blöcken). 0 ist ein echter Wert
  (kein Potenzial, z. B. Restriktion), leer heißt „nicht bewertet“.
- ONG und MTG schließen sich je Besitzeinheit aus (ONG hat Vorrang); die Summe ist zulässig.
- Methodik (Kurzdokumentation LANUK): Simulation je Besitzeinheit mit EED bzw. FEFLOW, Sondentiefen
  40/150/250 m (ONG) und 1.000 m (MTG), an den Wärmebedarf der Gebäude gekoppelt. Das Potenzial ist
  also ein Deckungsbeitrag für die Gebäude des Blocks, kein freies Quellpotenzial für ein Wärmenetz.

## 4. LANUK TG-Raster (Dublette, mitteltief und tief)

NRW-GDB: `Potenzial_TG_Raster_NRW.gdb`, Layer `MTG_TG_Raster_NRW`, MultiPolygon, 3.956 Zellen
(3 × 3 km, am Landesrand angeschnitten).

| Feld | Einheit | Inhalt |
|---|---|---|
| `fraction` | % | Anteil der Zelle in NRW |
| `Volllastst` | h/a | Volllaststunden (überall 6.000) |
| `MT_P10_MW`, `MT_P50_MW`, `MT_P90_MW` | MW | Leistung bestes mitteltiefes Reservoir (400–1.500 m), Wahrscheinlichkeit 10/50/90 % |
| `T_P10_MW`, `T_P50_MW`, `T_P90_MW` | MW | dto. tiefes Reservoir (1.500–5.000 m) |
| `MT_P10_GWh` … `T_P90_GWh` | GWh/a | Wärmeertrag bei 6.000 h |
| `Hinweis1` | Text | „Potenzial tiefer 5.000 m möglich“, teils mit „keine Bewertung; …“ |
| `Hinweis2` | Text | „Derzeit in Bearbeitung durch den Geologischen Dienst NRW (Masterplan Geothermie NRW)“ |
| `Stand` | Datum | 01.09.2024 |

- Das Gemeinde-Shape hat zusätzlich `Gemeinde` und `AGS`; es enthält nur Zellen, die zu mindestens
  10 % in der Gemeinde liegen.
- Keine leeren Werte. 0 MW heißt „kein Reservoir gefunden“. „keine Bewertung“ in `Hinweis1` bezieht
  sich auf Tiefen über 5.000 m; auch Zellen mit diesem Hinweis haben teils `T_P50_MW > 0`.
- LANUK-Methodik: „grobe Abschätzung“, Fündigkeit und Schüttung unbekannt. Die Bewertungsmatrix
  (Eignung der Zelle) ist **nicht** im Download, nur im Wärmekataster.

## 5. LANUK Freiflächen-Solarthermie je Flur

NRW-GDB: `Potenzial_FF_Solarthermie_Flur_NRW.gdb`, Layer `FF_Solarthermie_Flur_NRW`, MultiPolygon, 50.654 Flure.

| Feld | Einheit | Inhalt |
|---|---|---|
| `Flur_id` | – | ID der Flur (9 Zeichen, eindeutig) |
| `gemeinde` (klein!) | – | Name der Gemeinde |
| `AGS` | – | Gemeindeschlüssel |
| `Nutzfl_m2` | m² | Effektiv nutzbare Fläche (Besitzeinheiten abzüglich 3-m-Rand) |
| `Pot_FK_kWh` | kWh/a | Flachkollektor, 60 °C |
| `Pot_VR_kWh` | kWh/a | Vakuumröhre, 90 °C |
| `Po_PNS_kWh` | kWh/a | Parabolrinne Nord-Süd, 150 °C |
| `Po_POW_kWh` | kWh/a | Parabolrinne Ost-West, 150 °C |
| `Stand` | Datum | 01.09.2024 |

- **Die Feldnamen weichen von der LANUK-Spaltendoku ab** (`Pot_FK_kWh`/`Pot_VR_kWh` statt
  `Po_FK_kWh`/`Po_VR_kWh`, `gemeinde` statt `Gemeinde`). Maßgeblich sind die Dateien.
- Einheit kWh/a. Die Nutzfläche steht im Datensatz, der spezifische Ertrag ist ableitbar:
  Flachkollektor 201–305 kWh/(m²·a) (Mittel 256), Vakuumröhre 216–299, Parabolrinne N-S 113–163.
- 17.183 Flure haben keine Nutzfläche (leer) und überall 0 kWh/a: keine geeignete Fläche.
  2.815 Flure haben Splitterflächen unter 100 m².

## 6. GD NRW: WFS IS GT 50

`https://www.wfs.nrw.de/gd/wfs_nw_inspire-gt50`, WFS 2.0.0, Abruf mit owslib:
`getfeature(typename=..., bbox=(minx, miny, maxx, maxy, "urn:ogc:def:crs:EPSG::25832"),
srsname="urn:ogc:def:crs:EPSG::25832", outputFormat="GEOJSON")` (0,7 s für Burgsteinfurt).
Die GML-Antwort (`text/xml; subtype=gml/3.2`, wie bei der Flächennutzung) kann pyogrio hier
nicht lesen; deshalb GEOJSON.

| FeatureType | `capacity` | `capacity_uom` | `vext_scalar` |
|---|---|---|---|
| `er:Geothermie_EWS40/60/80/100` | Wärmeleitfähigkeit λ (1,8–2,3 in Burgsteinfurt) | `W/m*K` | Sondenlänge 40/60/80/100 m |
| `er:Geothermie_EWK1800` | spezifische Entzugsleistung Kollektor (25/40) | `W/m²@1800h/a` | 2 (Tiefe in m) |
| `er:Geothermie_EWK2400` | dto. (20/32) | `W/m²@2400h/a` | 2 |

- Geometrie MultiPolygon. Der WFS liefert die **ganzen** Polygone, die die Box schneiden (bis
  50 km groß), nicht zugeschnitten.
- Einzelne Geometrien sind ungültig (1 von 26 bei EWS40) → `buffer(0)`.
- `capacity` ist bei EWS `float`, bei EWK `int`.

## 7. GD NRW: Download IS GT

GeoPackage `ISGT.gpkg` (191 MB entpackt), u. a.:

- `GT1_O_Auswertung_E40/E60/E80/E100`: Wärmeleitfähigkeitsklassen (`KLASSE_WLFxx`,
  `KLASSEN_WERTEBEREICH` z. B. „2,0 - 2,4“). Inhaltlich dasselbe wie der WFS, gröber.
- `GT1_O_BK50_EWK`: Eignung Kollektor als Text (`hoch`, `mittel`, `gering`, `zu_flach`, `grundnass`).
- `GT3_T_Dublette_TG`: Reservoire für die tiefe Geothermie, bis zu drei je Fläche
  (`STRAT1..3`, `TIEFE1..3` als Klasse „0 - 500 m“, `MAECHTIGKEIT1..3`, `GESTEIN1..3`), Stand 01.06.2026.
- Höhenlinien und Tektonik der Reservoir-Oberkanten (Linien), relevante Bohrungen (Punkte).

Raster `ISGT-raster_EPSG25832_TIFF.zip`: `Mitteltiefe_GT/EWS_250m…1000m.tif` sind Wärmeleitfähigkeiten
(Werte 1,2–3,8), `Tiefe_GT/<Reservoir>_Top_m_u_GOK|Maechtigkeit_m|Temperatur.tif` für Buntsandstein,
Oberkreide, Unterkarbon und Devon.

**Keine Ergiebigkeit in kWh/(m·a).** Die Werte des Geothermieportals werden dort offenbar zur Laufzeit
berechnet. Phase 2 leitet die Entzugsleistung der Sonden deshalb als Screening-Richtwert aus λ ab
(VDI 4640 Blatt 2, Ausgabe 2001).

Für Phase 3 (Karbonate an den TG-Zellen) eignet sich der Vektorlayer `GT3_T_Dublette_TG` (Reservoir,
Tiefenklasse, Mächtigkeit, Gestein) ohne neue Abhängigkeit. Die Temperaturen gibt es nur als Raster;
das bräuchte `rasterio` und entfällt deshalb vorerst. Der Download (112 MB) für drei Textfelder je
Zelle lohnt sich nicht als Standard; Phase 3 lässt ihn deshalb weg (optional, siehe dort).

## 8. Lesen direkt vom Server

`gpd.read_file("/vsizip//vsicurl/<url>/<name>.gdb", bbox=...)` funktioniert ohne Download: TG-Raster
0,9 s, FF-Solarthermie 12,4 s je Lauf (Burgsteinfurt, 19.10.2026). Der Zwischenspeicher
(`fheat_core.cache`) braucht nach dem ersten Download 0,2 s bzw. 1,5 s und funktioniert auch, wenn
der Server kurz nicht erreichbar ist. Deshalb wird `/vsicurl` nicht verwendet.
