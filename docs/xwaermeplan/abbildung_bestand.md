# XWärmeplan: Abbildung Bestand und Potenzial (Phase 6)

Stand: 12.10.2026, abgestimmt und umgesetzt (`fheat_core/xwp/mapping/bestand.py`, `blocks.py`). Attribut für Attribut: welcher F|Heat-Wert in welches XWärmeplan-Attribut geht. Umrechnungen stehen zentral in `fheat_core/xwp/mapping/units.py`.

Abkürzungen: **B** = Gebäude (`buildings_gdf`), **W** = Wärmelinien (`wld_gdf`), **K** = `XwpPlanConfig`, **E** = nur über die Ergänzungsdatei (Phase 8).

## WP_Plan

| Attribut | Mult. | Quelle | Umrechnung |
|---|---|---|---|
| `name` | 1 | K `name` | – |
| `planungsverantwortlicheStelle` | 1 | K `gemeinde` | → `WP_Gemeinde` |
| `verfahrensart`, `gesetzlicheGrundlage` | 1 | K | Code |
| `zieljahr` | 1 | K `zieljahr` | Text |
| `basisJahrDatenerfassung` | 1 | K `basisjahr`, sonst Jahr der Daten (`FHeatConfig.year`) | Text |
| `beschlussDatum` | 1 | K; fehlt es, meldet der Prüfbericht die Lücke | – |
| `aufstellungsbeschlussDatum`, `beteiligteGemeinden`, `foerderkennzeichen`, `technischePlanerstellung`, `externeReferenz`, `beschreibung` | 0..1/0..* | K | – |
| übrige Attribute (`nummer`, `istFortschreibung` …) | 0..1 | K `extra` | – |
| `raeumlicherGeltungsbereich` | 1 | `adapter.provide_boundary()`; ohne Grenze: Hülle der Gebäude (Puffer 50 m) | MultiPolygon |
| `bereich`, `energiebilanz`, `infrastruktur` … | 0..* | Gegenrichtung, automatisch | – |

## WP_Bereich

Genau einer: `nummer` = 0, `name` = „Geltungsbereich <Gemeinde>“, `geltungsbereich` = wie Plan, `gehoertZuPlan` = Plan.

## WP_Waermelinie (je Straßenabschnitt mit Wärmebedarf)

| Attribut | Quelle | Umrechnung |
|---|---|---|
| `position` | W Geometrie | LineString → MultiCurve |
| `waermeMenge` [MWh/a] | W `heat_demand` [kWh/a] | ÷ 1000 |
| `waermelinienDichte` [MWh/(m·a)] | W `heat_line_density` [kWh/(a·m)] | ÷ 1000 |
| `laenge` [m] | W `length` [m] | – |
| `gehoertZuBereich` | Bereich | – |

Abschnitte mit `heat_demand` = 0 oder Länge 0 entfallen.

## Baublöcke: WP_GebaeudeBaublock und WP_EnergieBaublock

`polygons_gdf` sind Eignungspolygone (gepufferte Flurstücke entlang von Straßen über der WLD-Schwelle), keine Baublöcke nach WPG § 3. **Entscheidung:** beide Quellen, je Gebäude:

1. Hat die Quelle eine Block-ID (`block_id`; NRW: LANUV `Block_ID`), ist der Block die Vereinigung der Flurstücke seiner Gebäude. Ein Flurstück mit Gebäuden mehrerer Blöcke gehört dem Block mit den meisten.
2. Gebäude ohne Block-ID kommen in die Flächen zwischen den Straßen (vom Analysegebiet geschlossen), soweit sie nicht schon von Blöcken nach 1. belegt sind. Bahn und Gewässer fehlen in den Daten; solche Blöcke können größer sein als amtliche.

Gezählt wird über den Mittelpunkt der Gebäude, und nur Gebäude mit Wärmebedarf > 0.

Je Block, aus den Gebäuden, deren Mittelpunkt im Block liegt:

| Klasse.Attribut | Quelle | Umrechnung |
|---|---|---|
| `baublockId` (beide) | fortlaufende ID im Plan, gleich für Gebäude- und Energieblock | Text |
| `GebaeudeBaublock.gebaeudetyp` (1) | häufigster Wert von B `xwp_building_type`; Gleichstand wie beim Baujahr | Code |
| `GebaeudeBaublock.ueberwiegendBaujahr` (1) | häufigste Baualtersklasse; Gleichstand innerhalb einer Oberklasse → Oberklasse, sonst 9999 | Code |
| `GebaeudeBaublock.verteilungBaujahr` (0..*) | Anteil je Baualtersklasse an der Gebäudezahl | % |
| `GebaeudeBaublock.nutzflaeche` [ha] | Σ B `floor_area` [m²] | ÷ 10 000 |
| `EnergieBaublock.waermeMenge` [MWh/a] | Σ B `heat_demand` [kWh/a] | ÷ 1000 |
| `EnergieBaublock.waermeDichte` [MWh/(ha·a)] | `waermeMenge` / Blockfläche [ha] | – |
| `EnergieBaublock.eeNachEnergietraeger`, `waermeErzeuger`, `eeNachVersorgungsart` | – | **E** (Energieträger und Erzeuger kennt F\|Heat nicht) |
| `EnergieBaublock.anzahlAnschluesseWaermenetz`, `refWaermeNetzID` | – | Phase 7 (aus den Netzen) |

**Baualtersklasse je Gebäude** (Entscheidung): Quellen in der Reihenfolge `XwpConfig.construction_year_sources`. Ein echtes Baujahr ergibt die Unterklasse, das LANUV-Alter und das Flurstücksjahr nur die Oberklasse. Mischt ein Block beide Genauigkeiten, wird auf Oberklassen verglichen.

**Datenschutz:** Blöcke mit weniger als `XwpConfig.privacy_min_buildings` Gebäuden (Standard 5) gehen im nächstgelegenen Block auf; bei gleichem Abstand im Nachbarn mit der längsten gemeinsamen Grenze. Das wiederholt sich, bis jeder Block die Schwelle erreicht. Der zusammengelegte Block behält die ID seines größten Teils. Ein Block ohne Nachbarn, der die Schwelle nicht erreicht, wird nicht ausgegeben; der Prüfbericht zählt ihn.

## WP_EnergieRaster (optional, `XwpConfig.energy_raster`)

100-m-Zellen des INSPIRE-Gitters (EPSG:3035, ID `CRS3035RES100mN…E…`), nach EPSG:25832 umgerechnet. `rasterID`, `waermeMenge` (Σ, ÷ 1000), `waermeDichte` (÷ 1 ha). Zellen unter der Datenschutzschwelle entfallen (keine Zusammenlegung im Raster). `eeNachEnergietraeger`: **E**.

## WP_Energiebilanz

**Wird nicht automatisch erzeugt.** Pflicht ist `eeGesamtNachEnergietraeger` (1..*): die Endenergie je Energieträger. F|Heat kennt nur den Wärmebedarf (Nutzwärme), keine Energieträger und keine Endenergie. Eine Bilanz ohne diese Angaben wäre ungültig. Sie kommt über die Ergänzungsdatei (**E**). Der Plan nannte hier „Summen, soweit bekannt“; das geht wegen der Pflichtangabe nicht.

## WP_WaermeinfrastrukturAggregiert (Basisjahr)

| Attribut | Quelle |
|---|---|
| `name` | „Wärmeinfrastruktur <Basisjahr>“ |
| `betrachtungszeitpunkt` | `art` = 1000 (Basisjahr), `jahr` = Basisjahr |
| `anzahlGebaeude.gebaeude` | Zahl der Gebäude in B (**Einschränkung:** der NRW-Adapter liefert nur Gebäude mit Wärmebedarf > 0, also keine unbeheizten) |
| `anzahlGebaeude.beheizteWohngebaeude` | Gebäude mit Wärmebedarf > 0 und Gebäudetyp 1000…10004 |
| `anzahlGebaeude.beheizteNichtwohngebaeude` | übrige beheizte Gebäude (laut Definition „nicht unter beheizteWohngebaeude“, also auch 9999) |
| `gehoertZuPlan` | Plan |
| übrige (`waermerzeugerMitEnergietraeger`, Gasnetz, Bestandsnetze, Speicher …) | **E** |

Geplante Netze (`waermenetzePlanung`, `gebaeudeAnschlussWaermenetzPlanung`) und das Zieljahr folgen in Phase 7.

## Probe mit echten Daten (Steinfurt, offline)

Mit den LANUV-Gebäuden, Flurstücken und Straßen von Steinfurt (12 202 beheizte Gebäude): 2281 Wärmelinien, 1374 LANUV-Blöcke → 862 Baublöcke nach der Zusammenlegung (aus dem Straßennetz: 479), 898 Rasterzellen (1140 unter der Schwelle). GML (9,6 MB) gültig gegen die XSD, JSON-FG gültig gegen das Schema; Laufzeit des Mappings unter 2 s.
