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

## 9. Wärmequellen: Fraunhofer ISI (Manz et al. 2024) und LANUK-Kläranlagen

Stand: 26.10.2026. Datensatz zu Manz et al. (2024), „Spatial analysis of renewable and excess heat
potentials for climate-neutral district heating in Europe“, Renewable Energy 224, 120111: Fordatis
Handle 341.5, DOI 10.24406/fordatis/280.5, Lizenz CC BY 4.0. GeoPackages in EPSG:3035, technische
Potenziale eines klimaneutralen Jahres 2050 für zwei Netztemperaturen: HT (Vorlauf 70–90 °C) und NT
(60–70 °C). Geladen über `fheat_eu` (für jeden Adapter), im Zwischenspeicher ohne Neuladen, weil das
Handle eine feste Version ist.

| Datei | Inhalt, Feld | Umrechnung in fheat | Abstand |
|---|---|---|---|
| `wwtp.gpkg` | Kläranlagen (Hotmaps), `Power in k` [kW] | × 4.421 Vlh = Entzug; nach Wärmepumpe × JAZ/(JAZ−1), JAZ 2,7 (HT) / 3,6 (NT); −999 und 0 entfallen | 2 km |
| `industrial_eh.gpkg` | Industrie (ISI-Datenbank), `EH_95_GWh` / `EH_55_GWh` | HT / NT, GWh → MWh; Namen aus Hotmaps über `ID_Site` = `SiteID` | 20 km |
| `wte.gpkg` | Müllverbrennung, `EH100PJ` (60 % des Energieeinsatzes) | × 277.778 MWh/PJ; × 0,66 (HT) / 0,76 (NT) | 20 km |
| `rivers_lakes.gpkg` | Zonen mit ≥ 20 m³/s Winterabfluss, `Capa in MW` 30/80/150 | ein typisches Projekt × 2.000 / 3.000 / 3.000 Vlh | 5 km |
| `hydrothermal_85/65.gpkg` | 1-km-Raster, `Energy_TWh` je Punkt, MultiPoint | HT (85 °C) / NT (65 °C), TWh → MWh, Zelle 1 × 1 km; nur außerhalb NRW (in NRW: LANUK-Raster, Abschnitt 4) | 15 km |
| `dh_areas.gpkg` | Wärmenetzgebiete 2050, `Dem_GWh` | über `DH_LAU_Mapping` der Gemeinde (`DE_` + AGS) | Gemeinde |
| `Results_DH_Matching_Cluster.xlsx` | `Matching_results`: Angebot und Nutzbares je Gemeinde | Tabelle `study_potentials_df`, GWh → MWh; nur Quellen mit Angebot, ohne Biomasse und Petrothermie | Gemeinde |

Nicht geladen: `petrothermal_85/65.gpkg` und `biomass_nuts2.gpkg` (siehe unten). Ohne Wärme im Umkreis
fehlt ein Wert in der Ergebnisübersicht, statt als 0 zu erscheinen.

Geprüft gegen das Paper (Tabelle 2, EU): Industrie HT 19,9 TWh, Hydrothermie 814,9 / 2.097,7 TWh,
Petrothermie HT 84,6 TWh stimmen mit den Summen der Dateien überein. Müllverbrennung DE: 45,7 TWh
× 0,76 ≈ 35 TWh wie Tabelle 5. Kläranlagen DE: kW × 4.421 h ≈ 42 TWh (Paper: 43 TWh).

Befunde und Grenzen:
- **Kläranlagen NT < HT.** Bei gleichem Entzug liefert die bessere Wärmepumpe (JAZ 3,6) weniger Wärme
  als die mit JAZ 2,7, weil weniger Strom dazukommt. Das Paper nennt für NT mehr Wärme (Tabelle 2), ohne
  die Herleitung; seine Stromanteile passen eher zu JAZ 2,4 / 3,2. fheat rechnet mit festem Entzug.
- **Hotmaps-Leistung** ist fast überall 64,4 W je Einwohnerwert der Ausbaugröße, nicht die echte
  Abwassermenge. In NRW nimmt fheat deshalb die LANUK-Liste (unten).
- **Flüsse und Seen:** Eine Zone ist kein Projekt und keine Summe; die Studie setzt in einer Zone
  mehrere Entnahmestellen im Abstand von 10 km, deren Lage nicht veröffentlicht ist. Die Summe der
  Zonen (101 TWh) ist deshalb viel kleiner als Tabelle 2 (1.156 TWh). Kein Quellenvorschlag.
- **Petrothermie** ist eine Abschätzung aus der Temperatur in 2.000 m Tiefe mit fester Fördermenge,
  fast überall gleich, und sagt über einen Ort nichts aus; fheat lädt sie nicht. Hydrothermie aus
  GeoDH weicht in NRW völlig vom LANUK-Raster ab (Rangkorrelation ≈ 0,1 auf gemeinsamen Zellen) und
  wird dort nicht geladen.
- **Biomasse** gibt es nur als Wert der ganzen NUTS-2-Region (in NRW der Regierungsbezirk, z. B. das
  ganze Münsterland), nicht für ein Gebiet; fheat lädt sie nicht.
- **Industrie:** Werte für 2050 nach dem Umbau der Industrie, bei Stahl weit unter heute (HKM
  Duisburg 31 GWh/a gegen 1.495 GWh/a heute laut Hotmaps). Standorte ab ID 5000 (in NRW 30, meist
  Chemieparks) haben keinen Namen. Bei 19 NRW-Standorten weichen die Fordatis-Koordinaten von Hotmaps
  ab (bis 55 km); geprüfte Fälle (WEPA Giershagen) zeigen Fordatis richtig, fheat nimmt deshalb sie.
- **Müllverbrennung:** In `City` sind Umlaute als U+FFFD verloren („D?sseldorf“, 54 Namen). Der
  NRW-Adapter stellt sie aus `cities.csv` wieder her. Auf Luftbildern sitzen die meisten Punkte auf der
  Anlage, Essen-Karnap und Eschweiler-Weisweiler einige hundert Meter daneben.
- **Studienwerte** gibt es nur für Gemeinden mit Wärmenetzgebiet der Studie: in NRW 181 von 396.
- `hydrothermal_65.gpkg` hat einen beschädigten räumlichen Index (GDAL-Warnung); gelesen wird ohne ihn.

**LANUK „Kommunale Kläranlagen NRW“** (`abwasser_kom/KomKlaeranlagen_EPSG25832_GeoPackage.zip`,
Layer `komm_ka`, Datenlizenz Deutschland – Zero 2.0): 703 Zeilen, 601 Standorte (`standortnr`; ein
Standort mit mehreren Einleitungen behält die Zeile mit der größten Menge), Stand 2025. Felder `name`,
`ew_bemess` (Ausbaugröße), `ew` (angeschlossene Einwohner und Einwohnergleichwerte), `jabw_menge`
(m³/a), alle als Text. Entzug = Jahresabwassermenge × 1,163 kWh/(m³·K) × 5 K; dann dieselbe
Wärmepumpe wie oben. Abgleich mit Fordatis: 496 von 535 Fordatis-Punkten in NRW liegen höchstens
100 m neben einer LANUK-Anlage, 25 auf freiem Feld; der Fordatis-Jahreswert liegt im Mittel bei 0,78
des LANUK-Werts, je Anlage mit Abweichungen bis Faktor 5.

## 10. Biogas-BHKW: Marktstammdatenregister (MaStR)

Stand: 28.10.2026. Methode aus der Masterarbeit von J. Föcker (FH Münster, 2026), umgesetzt in
`fheat_de.mastr` (Lesen) und `fheat_de.biogas` (Rechnen, Cluster).

**Quelle:** Gesamtdatenexport der Bundesnetzagentur, Datenlizenz Deutschland – Namensnennung – 2.0.
fheat nimmt den Stichtagsexport `Stichtag/Gesamtdatenexport_20261001_26.1.zip` (fester Stand).
Das ZIP hat 3,2 GB und 440 XML-Dateien (UTF-16). Gebraucht werden drei davon:
`EinheitenBiomasse.xml` (24.413 Einheiten), `AnlagenEegBiomasse.xml` (15.695 EEG-Anlagen) und
`AnlagenKwk.xml` (92.653 KWK-Anlagen), zusammen 11 MB gepackt. Der Server beantwortet Range-Anfragen.
fheat liest die drei Dateien deshalb direkt aus dem entfernten ZIP (9 s) und legt sie als CSV in den
Zwischenspeicher (4 MB, danach 0,05 s). Der Server bricht ab und zu für 1 bis 20 s alle Verbindungen
ab; eine Anfrage wird deshalb nach 1, 2, 4, 8 und 16 s wiederholt.

**Auswahl:** Hauptbrennstoff Biogas (Katalogwert 2445; Biomethan, Klärgas und Deponiegas nicht),
Status in Betrieb (35) oder in Planung (31), mindestens 250 kW netto, Höchstbemessungsleistung (HBL)
der EEG-Anlage vorhanden. Die HBL gibt es nur für Anlagen mit Inbetriebnahme vor August 2014. Im
Münsterland fallen deshalb 112 von 415 Biogas-Einheiten ab 250 kW weg (82 von 208 MW), in
Deutschland 2.440 von 11.495.

**Rechnung:** Strom der EEG-Anlage = HBL × 8.760 h. Er wird nach Nettoleistung auf **alle**
Biogas-Einheiten der EEG-Anlage verteilt. Das Skript der Arbeit verteilt nur auf die Einheiten ab
250 kW; dann bekommen die großen Einheiten den Anteil kleiner BHKW derselben Anlage dazu (Münsterland:
33 EEG-Anlagen, +41,5 GWh/a Strom). Wärme = Strom × P_th/P_el der KWK-Anlage der Einheit
(`ThermischeNutzleistung` / `ElektrischeKwkLeistung`). Für Biogas-Einheiten ab 250 kW liegt das
Verhältnis im Median bei 1,01 (Arbeit: pauschal 0,45/0,41 = 1,10). Außerhalb von 0,5 bis 2,0 (4 %,
meist W statt kW eingetragen) und ohne KWK-Daten (6 %) gelten die pauschalen Wirkungsgrade.

**Abgleich Münsterland** (Kreise Borken, Coesfeld, Steinfurt, Warendorf, Stadt Münster): Es sind
dieselben 303 Einheiten wie im Skript der Arbeit. Strom 739,9 statt 781,5 GWh/a (Verteilung), Wärme
767,9 statt 857,7 GWh/a (Verteilung und KWK-Verhältnis). 3-km-Cluster: 90, davon 22 einzelne
BHKW (Kreis mit 1,5 km Radius). 15 Cluster bestehen aus mehreren BHKW an derselben Stelle; sie
bekommen wie alle Cluster aus mehreren BHKW die Hülle plus 500 m.

**Grenzen:** Das ist der Bestand heute, kein Wert für 2050. Die Wärme ist die Erzeugung des BHKW, also
eine Obergrenze: Ein Teil heizt den Fermenter, ein Teil wird schon verkauft. Bei flexibel betriebenen
Anlagen (Flexprämie) liegen die Volllaststunden der HBL im Median bei 5.020 h, bei den übrigen bei
8.341 h (NRW).
