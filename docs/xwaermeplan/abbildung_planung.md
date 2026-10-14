# XWärmeplan: Abbildung Planung, Gebiete, Netze (Phase 7)

Stand: 12.10.2026, abgestimmt und umgesetzt (`fheat_core/xwp/mapping/planning.py`, `build_plan`). Eingang je gerechnetem Netz: `PipelineState` mit `net_gdf`, `planning_area_gdf`, `source_gdf`, `result_summary` und den angeschlossenen Gebäuden. Abkürzungen wie in `abbildung_bestand.md`; **N** = Netzergebnis, **P** = Angabe des Planers (Konfiguration bzw. Ergänzungsdatei, Phase 8).

## WP_Waermenetz (je Netz, Flächenobjekt)

| Attribut | Mult. | Quelle |
|---|---|---|
| `position` | 1 | Planungsgebiet des Netzes; ohne Planungsgebiet 10 m Puffer um die Trasse (ohne Hausanschlüsse) |
| `netzID` | 0..1 | fortlaufend `N01`, `N02` …; auch in `WP_EnergieBaublock.refWaermeNetzID` |
| `name` | 0..1 | Netzname (P, sonst „Wärmenetz N01“) |
| `betreiber` | 0..1 | P |
| `medium` | 0..1 | 1000 Wasser |
| `laenge` [m] | 1 | N `total_route_length_m` (Trasse ohne Hausanschlüsse) |
| `anzahlGebaeudeAnschluss` | 1 | N `total_buildings` |
| `status` | 1 | 3000 potenziell; der Planer setzt je Netz 2000 (`NetworkInput.status`) |
| `temperatur` [°C] | 0..1 | Vorlauftemperatur des Netzes (`NetworkInput.supply_temperature`) |
| `geplanteInbetriebZeit` | 0..1 | P |
| `eeNachEnergietraeger` | 0..1 | **E** |

`WP_EnergieBaublock.anzahlAnschluesseWaermenetz` = angeschlossene Gebäude des Blocks, `refWaermeNetzID` = Netz mit den meisten davon.

## WP_WaermeinfrastrukturAggregiert (Zieljahr)

Zweites Objekt mit `betrachtungszeitpunkt` 3000 (Zieljahr): `waermenetzePlanung` (`anzahlNetze`, `trassenlaenge` = Σ Trassenlängen), `gebaeudeAnschlussWaermenetzPlanung` (`anzahl` = Σ Anschlüsse, `anteil` = an den beheizten Gebäuden). `waermeversorgungsgebieteZieljahr` entfällt: Pflicht ist dort die **Endenergie**, F|Heat kennt nur den Wärmebedarf (**E**).

## Wärmeversorgungsgebiete (WP_WaermeversorgungsgebietZieljahr)

**Entscheidung:** Vorschlag für jeden Baublock, vom Planer überschreibbar (Phase 8); der Prüfbericht kennzeichnet die Vorschläge. Ein Block liegt im Netzgebiet, wenn sein innerer Punkt in der Fläche eines Netzes liegt. Blöcke, die der Datenschutz verwirft, bekommen kein Gebiet.

Je Gebiet (= Baublock):

| Attribut | Quelle |
|---|---|
| `position` | Gebietsfläche |
| `versorgungsart` (1) | P; im Vorschlag: Gebiet eines Netzes → 1000 Wärmenetzgebiet, sonst 3000 dezentral |
| `waermeMenge` [MWh/a] | Σ Wärmebedarf der Gebäude im Gebiet |
| `eignungWaermenetz` | Vorschlag: Stufe aus der Wärmedichte des Blocks und Stufe aus der WLD (wärmebedarfsgewichtetes Mittel der Straßen, denen seine Gebäude zugeordnet sind), die schlechtere gilt; Schwellen `XwpSuitabilityConfig`; P überschreibt |
| `eignungDezentraleVersorgung`, `eignungWasserstoffnetz`, `eignungGruenesMethan` | P (kein F\|Heat-Verfahren) |
| `eeNachEnergietraeger`, `sanierungsrate`, `istVerkuerzteWaermeplanung` | **E** |

`WP_WaermeversorgungsgebietStuetzjahr` (2030/2035/2040) und `…Umsetzung`: nur aus P.

## WP_Eignungspruefung

Vorschlag: Baublöcke, deren Eignung für ein Wärmenetz bei 4000 (sehr wahrscheinlich ungeeignet) liegt, bekommen `istUngeeignetWaermenetz` = true. Wasserstoff, verkürzte Planung und Verzicht: P.

## Ohne automatische Befüllung

Diese Klassen haben Pflichtangaben, die F|Heat nicht kennt; sie kommen über die Ergänzungsdatei (**E**):

| Klasse | fehlende Pflichtangabe |
|---|---|
| `WP_PotenzialWaermenutzung` (Wärmequellen der Netze) | `energietraeger` |
| `WP_PotenzialanalyseAggregiert` | `erneuerbareEnergienAbwaerme` (EE-Potenziale je Energieträger) |
| `WP_Grossverbraucher` | `versorgungsmedium`, `energieeinsatz` |
| `WP_EnergieeinsparungGebaeude` | keine Pflicht; **Entscheidung:** keine Schätzung ohne belastbare Reduktionsfaktoren, Werte nur aus der Ergänzungsdatei |

Für die Wärmequellen der Netze und große Verbraucher (Gebäude über einer Bedarfsschwelle) erzeugt F|Heat **Vorlagen** in der Ergänzungsdatei: Geometrie und Wärmemenge vorbefüllt, die fehlenden Pflichtangaben trägt der Planer ein (Phase 8).

## Probe mit echten Daten (Steinfurt, offline)

Netz mit dem Dijkstra-Verfahren im Beispiel-Planungsgebiet (`examples/planungsgebiet.gpkg`): `WP_Waermenetz` N01 mit 5172 m Trasse und 294 Anschlüssen, die sich auf 20 Baublöcke verteilen; 862 vorgeschlagene Versorgungsgebiete (19 Wärmenetzgebiet, 843 dezentral), 155 vorgeschlagene Eignungsprüfungen. GML und JSON-FG gültig.
