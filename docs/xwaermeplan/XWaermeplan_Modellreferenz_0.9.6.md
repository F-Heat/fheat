# XWärmeplan 0.9.6 – vollständige Modellreferenz mit F|Heat-Abdeckung

Quelle: maschinenlesbares Modell `xwp09.py` aus XPlan-Tools 1.26.0 (PyPI, 07.09.2026), Namespace `http://www.xwaermeplan.de/0/9/6`. Generiert, nicht von Hand gepflegt. Vor Phase 1 gegen die XSD im Repo `xleitstelle/xwaermeplan/spezifikation` prüfen (siehe Plan, Phase 0).

Abdeckung: **A** = automatisch aus F|Heat-Daten · **T** = teilweise automatisch, Rest Eingabe/Import · **E** = nur Eingabe/Import · – = abstrakt bzw. Datentyp

## Übersicht Objektarten

| Klasse | Oberklasse | Abdeckung | Quelle in F\|Heat |
|---|---|---|---|
| `WP_AnschlussGruenesMethan` | WP_Geometrieobjekt | E | Eingabe/Import |
| `WP_Anschlusszwang` | WP_Geometrieobjekt | E | Eingabe/Import |
| `WP_Ausschlussgebiet` | WP_Flaechenobjekt | E | Import (z. B. Schutzgebiete-WFS NRW, später Adapter) |
| `WP_Baublock` | WP_Flaechenobjekt | – | abstrakt |
| `WP_BeplantesTeilgebiet` | WP_Flaechenobjekt | – | abstrakt |
| `WP_Bereich` | – | A | ein Bereich je Plan (nummer 0), Geltungsbereich = Analysegebiet |
| `WP_Eignungspruefung` | WP_Flaechenobjekt | T | Vorschlag: Blöcke unter WLD-/Dichteschwelle → istUngeeignetWaermenetz; Wasserstoff nur Eingabe |
| `WP_EnergieBaublock` | WP_Baublock | T | aus `polygons_gdf` (Wärmedichteblöcke): waermeMenge, waermeDichte; Energieträger/Erzeuger nur mit Zusatzdaten (Schornsteinfeger/Kehrbuch) |
| `WP_EnergieRaster` | WP_Flaechenobjekt | A | optional: 100-m-Raster (INSPIRE-Gitter) aus Gebäuden |
| `WP_Energiebilanz` | – | T | Basisjahr: Summe Wärmebedarf, Anteil leitungsgebundene Wärme; Energieträger/THG nur mit Zusatzdaten |
| `WP_Energieeinsparpotenzialgebiet` | WP_BeplantesTeilgebiet | E | Eingabe/Import |
| `WP_EnergieeinsparungGebaeude` | WP_Flaechenobjekt | T | Differenz Bedarf heute vs. Sanierungsszenario je Block (BAK-spezifische Reduktionsfaktoren, konfigurierbar) |
| `WP_Flaechenobjekt` | WP_Objekt | – | abstrakt |
| `WP_GebaeudeBaublock` | WP_Baublock | A | Gebäude je Block aggregiert: gebaeudetyp (Lastprofil/ALKIS-Funktion), ueberwiegendBaujahr + verteilungBaujahr (Baujahr), nutzflaeche (m²→ha) |
| `WP_Geometrieobjekt` | WP_Objekt | – | abstrakt |
| `WP_Grossverbraucher` | WP_Geometrieobjekt | T | Vorschlag: Gebäude über Bedarfsschwelle; Rest Eingabe |
| `WP_Kaeltelinie` | WP_Linienobjekt | E | Import (F\|Heat rechnet keine Kälte) |
| `WP_Kaeltenetz` | WP_ThermischeNetze | E | Import |
| `WP_Kaelteversorgungsgebiet` | WP_Flaechenobjekt | E | Import |
| `WP_Linienobjekt` | WP_Objekt | – | abstrakt |
| `WP_Massnahme` | – | E | Eingabe/Import (Tabelle) |
| `WP_NichtBeplantesTeilgebiet` | WP_Flaechenobjekt | E | Eingabe/Import |
| `WP_Objekt` | – | – | abstrakt |
| `WP_Plan` | – | T | Metadaten aus `XwpPlanConfig`; `raeumlicherGeltungsbereich` = Analysegebiet (`provide_boundary`) |
| `WP_PotenzialWaermenutzung` | WP_Geometrieobjekt | T | Wärmequellen der Netzplanung (Energieträger vom Planer); weitere Potenziale per Import |
| `WP_PotenzialWaermespeicherung` | WP_Geometrieobjekt | E | Import |
| `WP_PotenzialanalyseAggregiert` | – | T | waermebedarfsreduktionGebaeude aus Einsparszenario; Rest Eingabe |
| `WP_TextAbschnitt` | – | E | Eingabe |
| `WP_ThermischeNetze` | WP_Flaechenobjekt | – | abstrakt |
| `WP_WaermeKaelteNetz` | WP_ThermischeNetze | E | Import |
| `WP_WaermeinfrastrukturAggregiert` | – | T | anzahlGebaeude, waermenetzePlanung (Anzahl/Trassenlänge), Anschlüsse aus Netzen; Rest Eingabe |
| `WP_Waermelinie` | WP_Linienobjekt | A | aus `wld_gdf`: heat_demand→waermeMenge (kWh→MWh), heat_line_density→waermelinienDichte (÷1000), length→laenge |
| `WP_Waermenetz` | WP_ThermischeNetze | T | geplante Netze aus `net_gdf` (Flächenobjekt: Puffer um Trasse bzw. Planungsgebiet), laenge, anzahlGebaeudeAnschluss, temperatur = Vorlauf; Bestandsnetze per Import |
| `WP_WaermeversorgungsgebietStuetzjahr` | WP_Waermversorgungsgebiet | T | wie Zieljahr, je Stützjahr 2030/2035/2040 |
| `WP_WaermeversorgungsgebietUmsetzung` | WP_Waermversorgungsgebiet | E | Eingabe |
| `WP_WaermeversorgungsgebietZieljahr` | WP_Waermversorgungsgebiet | T | Planungsgebiete + Einteilung durch Planer; Vorschlag der Eignungsstufen aus WLD/Wärmedichte (Schwellwerte konfigurierbar) |
| `WP_Waermversorgungsgebiet` | WP_BeplantesTeilgebiet | – | abstrakt |

## Klassen im Detail

### WP_AnschlussGruenesMethan
FeatureType · Oberklasse: WP_Geometrieobjekt

Grundstück, das an einem bestehenden oder in Planung befindlichem Gasverteilernetz mit grünem Methan anliegt (WPG § 28 Abs. 1).

### WP_Anschlusszwang
FeatureType · Oberklasse: WP_Geometrieobjekt

Gebiet oder Straßenabschnitt mit Anschluss- und Benutzungszwang aufgrund eines Satzungsbeschlusses entsprechend WPG Anlage 2 IV.

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `satzungsbeschluss` | Date | 0..1 |  | Datum des Satzungsbeschlusses |

### WP_Ausschlussgebiet
FeatureType · Oberklasse: WP_Flaechenobjekt

Ausschlussgebiete entsprechend WPG Anlage 2 II.

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `artSchutzgebiet` | WP_SchutzgebietTyp | 0..1 |  | Art des Ausschlussgebiets |
| `sonstigerAusschluss` | CharacterString | 0..1 |  | Art des Ausschlussgebiets, wenn kein Schutzgebiet |

### WP_Baublock
FeatureType (abstrakt) · Oberklasse: WP_Flaechenobjekt

Abstrakte Oberklasse für alle baublockbezogene WP-Fachobjekte. Gemäß WPG § 3 ist "Baublock" ein Gebäude oder mehrere Gebäude oder Liegenschaften, das oder die von mehreren oder sämtlichen Seiten von Straßen, Schienen oder sonstigen natürlichen oder baulichen Grenzen umschlossen und für die Zwecke der Wärmeplanung als zusammengehörig zu betrachten ist oder sind.

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `baublockId` | CharacterString | 0..1 |  | ID des Baublocks |

### WP_BeplantesTeilgebiet
FeatureType (abstrakt) · Oberklasse: WP_Flaechenobjekt

Abstrakte Oberklasse für beplante Teilgebiete. Gemäß § 3 WPG ist  "beplantes Teilgebiet" ein Teil des beplanten Gebiets, das aus mehreren Grundstücken oder aus Teilen von, aus einzelnen oder mehreren Baublöcken besteht und von der planungsverantwortlichen Stelle für die Untersuchung der möglichen Wärmeversorgungsarten sowie für die entsprechende Einteilung in voraussichtliche Wärmeversorgungsgebiete zusammengefasst wird.

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `istVerkuerzteWaermeplanung` | Boolean | 0..1 |  | Teilgebiet, für das eine verkürzte Wärmeplanung gemäß § 14 Abs. 4 WPG durchgeführt wurde = true |

### WP_Bereich
FeatureType · Oberklasse: –

Diese Klasse modelliert einen Bereich eines Wärmeplans, z.B. einen räumlichen oder sachlichen Teilbereich. Im Fall eines gemeinsamen Wärmeplans dienen Bereiche der gesonderten Darstellung der Ergebnisse für jede Gemeinde. Bei einer getrennten Darstellung einer gemeinsam durchgeführten Planung können die Gemeindeflächen der Partner als Bereiche vermerkt werden.

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `id` | UUID | 1 |  | Der Identifikator des Features. |
| `nummer` | Integer | 1 |  | Nummer des Bereichs. Bereichsnummern beginnen standardmäßig mit 0 und sollten, wenn einem Planobjekt mehrere Bereichsobjekte zugeordnet sind, eindeutig sein. |
| `name` | CharacterString | 1 |  | Bezeichnung des Bereiches (kann für Kodierung von Links in GML, HTML, JSON verwendet werden) |
| `bedeutung` | CharacterString | 0..1 |  | Detaillierte Erklärung der semantischen Bedeutung eines Bereiches |
| `geltungsbereich` | GM_MultiSurface | 0..1 |  | Räumliche Abgrenzung des Bereiches |
| `gehoertZuPlan` | WP_Plan | 1 |  | Referenz eines Bereichs auf den zugehörigen Plan |

### WP_Eignungspruefung
FeatureType · Oberklasse: WP_Flaechenobjekt

Ergebnisdarstellung der Eignungprüfung und zur Durchführung einer verkürzten Wärmeplanung nach § 14 WPG. WP_Eignungsprüfung dient der eigenständigen Ergebnisdarstellung der Wärmeplanung bevor das Zielszenario entwickelt ist.

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `istUngeeignetWaermenetz` | Boolean | 0..1 |  | Das  beplante Gebiet oder Teilgebiet eignet sich mit hoher Wahrscheinlichkeit nicht für eine Versorgung durch ein Wärmenetz = true |
| `istUngeeignetWasserstoffnetz` | Boolean | 0..1 |  | Das beplante Gebiet oder Teilgebiet eignet sich mit hoher Wahrscheinlichkeit nicht für eine Versorgung durch ein Wasserstoffnetz = true |
| `istVerkuerzteWaermeplanung` | Boolean | 0..1 |  | Für das Gebiet oder Teilgebiet, das sich mit hoher Wahrscheinlichkeit nicht für eine Versorgung durch ein Wärmenetz oder ein Wasserstoffnetz eignet, wird eine verkürzte Wärmeplanung durchgeführt = true.  In WP_Waermeversorgungsgebiet wird Attribut "istVerkuerzteWaermeplanung" auf "true" gesetzt und in "versorgungsart" als voraussichtliches Gebiet für die dezentrale Wärmeversorgung definiert. |
| `istVerzichtWaermeplanung` | Boolean | 0..1 |  | Für das beplante Gebiet oder Teilgebiet, dessen Wärmeversorgung vollständig oder nahezu vollständig auf erneuerbaren Energien, unvermeidbarer Abwärme oder einer Kombination hieraus beruht, wird auf die Durchführung einer Wärmeplanung verzichtet = true |

### WP_EnergieBaublock
FeatureType · Oberklasse: WP_Baublock

Baublockbezogene Informationen zum Wärmeverbrauch und zur dezentralen Wärmeerzeugung entsprechend WPG Anlage  2 I.2.1, I.2.3 und 2 I.2.4 sowie darüber hinausgehende optionale Informationen.

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `waermeMenge` | Measure | 0..1 | MWh/a | Jährlicher Wärmebedarf oder Wärmeverbrauch  aller Objekte, die einem Baublock zugeordnet sind (Erzeugernutzwärme) |
| `waermeDichte` | Measure | 0..1 | MWh/(ha*a) | Wärmeverbrauch oder Wärmebedarf pro Hektar und Jahr (Erzeugernutzwärme) |
| `eeNachEnergietraeger` | WP_EndenergieEnergietraeger | 0..* |  | Jährlicher Endenergieverbrauch oder -bedarf für Wärme je Energieträger |
| `eeNachEnTrEnthaeltLeitungsgebWaerme` | Boolean | 0..1 |  | Im Attribut eeNachEnergietraeger ist leitungsgebundene Wärme erfasst = true. Leitungsgebunde Wärme ist auf Baublockebene nicht in Energieträger aufgeschlüsselt = false. |
| `eeNachVersorgungsart` | WP_WaermeversorgungArt | 0..1 |  | Jährlicher Endenergieverbrauch/-bedarf für Wärme nach Versorgungsart dezentral und leitungsgebunden |
| `enthaeltProzesswaermeGHD` | Boolean | 0..1 |  | Daten zur Wärme und Endenergie enthalten die Prozesswärme aus dem Gebäudesektor GHD = true. Annahme: Prozesswärme der Industrie wird über WP_Grossverbraucher erfasst. |
| `waermeErzeuger` | WP_WaermeerzeugerAngaben | 0..* |  | Angaben zu dezentralen Wärmeerzeugern |
| `anzahlAnschluesseWaermenetz` | Integer | 0..1 |  | Anzahl der Hausanschlüsse an ein Wärmenetz |
| `refWaermeNetzID` | CharacterString | 0..1 |  | ID des Wärmenetzes, zum dem der Baublock gehört, siehe WP_Waermenetz |

### WP_EnergieRaster
FeatureType · Oberklasse: WP_Flaechenobjekt

Informationen zum Wärmebedarf in einer 100 mal 100 Meter Rasterdarstellung.

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `rasterID` | CharacterString | 0..1 |  | ID der Rasterzelle |
| `waermeMenge` | Measure | 0..1 | MWh/a | Jährlicher Wärmeverbrauch oder Wärmebedarf aller Objekte, die der Rasterzelle zugeordnet sind (Erzeugernutzwärme) |
| `waermeDichte` | Measure | 0..1 | MWh/(ha*a) | Wärmedichte pro Rasterzelle und Jahr (Erzeugernutzwärme) |
| `eeNachEnergietraeger` | WP_EndenergieEnergietraeger | 0..1 |  | "Anteile der Energieträger an der Wärmeversorgung von Wohngebäuden oder von Wohngebäuden und Nichtwohngebäuden pro Rasterzelle und Jahr" Jährlicher Endenergieverbrauch oder -bedarf für Wärme je Energieträger |

### WP_Energiebilanz
FeatureType · Oberklasse: –

Indikatoren der Energiebilanz für das beplante Gebiet als Ganzes und für verschiedene Betrachtungszeitpunkte. Betrifft Zielszenario und Bestandsanalye  entsprechend WPG Anlage 2 I und III.

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `id` | UUID | 1 |  | Der Identifikator des Features. |
| `name` | CharacterString | 1 |  | Name der Tabelle (kann für Kodierung von Links in GML, HTML, JSON verwendet werden) |
| `regionalSchluessel` | CharacterString | 0..1 |  | Amtlicher Regionalschlüssel der betreffenden Gemeinde (Attribut istGemeinsamerWaermeplan = true) |
| `betrachtungszeitpunkt` | WP_Betrachtungszeitpunkt | 1 |  | Betrachtungszeitpunkt für die Daten der Energiebilanz |
| `eeGesamtNachEnergietraeger` | WP_EndenergieAngaben | 1..* |  | Jährliche Endenergie der gesamten Wärmeversorgung nach Energieträgern |
| `eeGesamtNachEnergiesektor` | WP_EndenergieSektor | 0..1 |  | Jährliche Endenergie der gesamten Wärmeversorgung nach Energiesektoren |
| `eeLeitungsgebWaermeNachEnergietraeger` | WP_EndenergieEnergietraeger | 0..* |  | Jährliche Endenergie der leitungsgebundenen Wärmeversorgung nach Energieträgern |
| `eeGasnetzNachEnergietraeger` | WP_EndenergieEnergietraeger | 0..* |  | Jährliche Endenergie aus Gasnetzen nach Energieträgern |
| `eeGesamtGebaeude` | Measure | 0..1 | MWh | Endenergie der Wärmeversorgung von Gebäuden gesamt |
| `eeGesamtProzesse` | Measure | 0..1 | MWh | Endenergie gesamt für Prozesswärme aus den Sektoren GHD und Industrie.  Hinweis: Der Wert kann u.U. auch Endenergieverbrauch für stoffliche Zwecke enthalten. |
| `anteilLeitungsgebWaermeversorgung` | Measure | 0..1 | % | Anteil der leitungsgebundenen Wärmeversorgung an der Endenergie der Wärmeversorgung |
| `thgEmissionenGesamt` | Measure | 0..1 | tCO2-eq/a | Jährliche Emission von Treibhausgasen im Sinne von § 2 Nummer 1 des Bundes-Klimaschutzgesetzes der gesamten Wärmeversorgung des beplanten Gebiets in Tonnen Kohlendioxid-Äquivalent |
| `thgEmissionenNachEnergietraeger` | WP_Treibhausgasemissionen | 0..* |  | Jährliche Emission von Treibhausgasen im Sinne von § 2 Nummer 1 des Bundes-Klimaschutzgesetzes der gesamten Wärmeversorgung des beplanten Gebiets in Tonnen Kohlendioxid-Äquivalent |
| `thgEmissionenNachEnergiesektor` | WP_TreibhausgasemissionenSektor | 0..1 |  | Jährliche Emission von Treibhausgasen im Sinne von § 2 Nummer 1 des Bundes-Klimaschutzgesetzes der gesamten Wärmeversorgung des beplanten Gebiets in Tonnen Kohlendioxid-Äquivalent |
| `territorialerEmissionsfaktorStrom` | Measure | 0..1 | tCO2-eq/MWh | Territorialer Emissionsfaktor der lokalen Stromerzeugung, der anstelle des Bundesstrommix in die THG-Bilanz eingehen kann. |
| `gehoertZuPlan` | WP_Plan | 1 |  |  |

### WP_Energieeinsparpotenzialgebiet
FeatureType · Oberklasse: WP_BeplantesTeilgebiet

Gebiet, für das ein erhöhtes Energieeinsparpotenzial nach § 18 Absatz 5 vorliegt, entsprechend WPG Anlage 2 IV.

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `eignungSanierungsgebiet` | Boolean | 0..1 |  | Gebiet erscheint geeignet, zukünftig in einer gesonderten städtebaulichen Entscheidung als Sanierungsgebiet (im Sinne des Ersten Abschnitts des Ersten Teils des Zweiten Kapitels des Baugesetzbuchs) festgelegt zu werden = true |
| `massnahmenReduktionEeBedarf` | Boolean | 0..1 |  | Gebiet mit einem hohen Anteil an Gebäuden mit einem hohen spezifischen Endenergiekennwert für Raumwärme, in denen Maßnahmen zur Reduktion des Endenergiebedarfs besonders geeignet sind, die Transformation zu einer treibhausgasneutralen Wärmeversorgung zu unterstützen = true |
| `anteilGebHoherEeKennwert` | Measure | 0..1 | % | Anteil an Gebäuden mit einem hohen spezifischen Endenergiekennwert für Raumwärme |
| `erhoehteHitzebelastung` | Boolean | 0..1 |  | Gebiet, für das eine erhöhte Hitzebelastung bekannt ist = true |

### WP_EnergieeinsparungGebaeude
FeatureType · Oberklasse: WP_Flaechenobjekt

Raumbezogenes Potenzial zur Energieeinsparung durch Wärmebedarfsreduktion in Gebäuden entsprechend WPG Anlage 2 II.

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `waermebedarfsreduktion` | Measure | 0..1 | MWh/a | Absolute Reduktion des Wärmebedarfs (Erzeugernutzwärme) im Betrachtungsgebiet zwischen Basisjahr und Zieljahr, resultierend aus Effizienzmaßnahmen an Gebäudehülle und Anlagentechnik/Verteilung), unabhängig von einem Wechsel des Wärmeerzeugers. |
| `waermebedarfsreduktionRelativ` | Measure | 0..1 | % | Relative Reduktion des Wärmebedarfs (Erzeugernutzwärme) im Betrachtungsgebiet zwischen Basisjahr und Zieljahr, resultierend aus Effizienzmaßnahmen an Gebäudehülle und Anlagentechnik/Verteilung), unabhängig von einem Wechsel des Wärmeerzeugers. |
| `neWaermebedarfsreduktion` | Measure | 0..1 | MWh/a | Absolute Reduktion der Nutzenergie für Raumwärme und Trinkwarmwasser im Betrachtungsgebiet zwischen Basisjahr und Zieljahr, resultierend aus energetischer Sanierung der Gebäudehülle, unabhängig von Anlagentechnik und Wärmeerzeuger. |
| `neWaermebedarfsreduktionRelativ` | Measure | 0..1 | % | Relative Reduktion des Nutzenergie für Raumwärme und Trinkwarmwasser im Betrachtungsgebiet zwischen Basisjahr und Zieljahr, resultierend aus energetischer Sanierung der Gebäudehülle, unabhängig von Anlagentechnik und Wärmeerzeuger. |
| `eeWaermebedarfsreduktion` | Measure | 0..1 | MWh/a | Absolute Reduktion es Endenergiebedarfs im Betrachtungsgebiet zwischen Basisjahr und Zieljahr. Enthält zusätzlich zur Wärmebedarfsreduktion den Effekt aus einem Wechsel des Wärmeerzeugers. |
| `eeWaermebedarfsreduktionRelativ` | Measure | 0..1 | % | Absolute Reduktion es Endenergiebedarfs im Betrachtungsgebiet zwischen Basisjahr und Zieljahr. Enthält zusätzlich zur Wärmebedarfsreduktion den Effekt aus einem Wechsel des Wärmeerzeugers. |

### WP_Flaechenobjekt
FeatureType (abstrakt) · Oberklasse: WP_Objekt

Abstrakte Oberklasse für alle WP-Fachobjekte mit (Multi-)Flächengeometrie.

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `position` | GM_MultiSurface | 1 |  | Flächengeometrie |

### WP_GebaeudeBaublock
FeatureType · Oberklasse: WP_Baublock

Baublockbezogene Informationen zu Gebäudedaten entsprechend WPG Anlage 2 I.2.5 und I.2.6 sowie darüber hinausgehende optionale Informationen.

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `gebaeudetyp` | WP_GebaeudeTyp | 1 |  | Überwiegender Gebäudetyp im Baublock |
| `ueberwiegendBaujahr` | WP_Baualtersklasse | 1 |  | Überwiegendes Baujahr der Gebäude über Zuordnung in Baualtersklassen |
| `verteilungBaujahr` | WP_BaujahrAngaben | 0..* |  | Anteilige Erfassung der Baujahre der Gebäude über Baualtersklassen |
| `nutzflaeche` | Measure | 0..1 | ha | Gesamtnutzfläche der Gebäude im Baublock in Hektar |

### WP_Geometrieobjekt
FeatureType (abstrakt) · Oberklasse: WP_Objekt

Abstrakte Oberklasse für alle WP-Fachobjekte mit variabler Geometrie.

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `position` | WP_VariableGeometrie | 1 |  | Punkt- oder Flächengeometrie |

### WP_Grossverbraucher
FeatureType · Oberklasse: WP_Geometrieobjekt

Kunden oder Letztverbraucher entsprechend WPG Anlage 2 I.2.7 (bestehende sowie bekannte potenzielle Großverbraucher von Wärme oder Gas sowie bekannte potenzielle Großverbraucher, die gasförmige Energieträger nach § 3 Absatz 1 Nummer 4, 8, 12 oder Nummer 15 Buchstabe e, f, j oder Absatz 2 WPG zu stofflichen Zwecken einsetzen).

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `name` | CharacterString | 0..1 |  | Name des Großverbrauchers |
| `status` | WP_Status | 1 |  | Statusangabe: "bestehend" oder "potenziell" |
| `energiebedarf` | WP_EnergiebedarfArt | 1 |  | Art des Energiebedarfs (Wärme und Kälte) |
| `energieeinsatz` | WP_EnergieeinsatzArt | 1 |  | Einsatzart der Energie (thermisch und stofflich) |
| `versorgungsmedium` | WP_Versorgungsmedium | 1..* |  | Medium der leitungsgebundenen Versorgung |
| `eeProzesswaerme` | Measure | 0..1 | MWh/a | Endenergie Prozesswärme |
| `bedarfTemperaturniveau` | Measure | 0..1 | °C | Das Temperaturniveau ist die am Übergabepunkt erforderliche Grenztemperatur des Energieträgers – bei Wärme die minimal notwendige, bei Kälte die maximal zulässige Vorlauftemperatur – zur Deckung des spezifischen Bedarfs unter den gegebenen Systembedingungen. |

### WP_Kaeltelinie
FeatureType · Oberklasse: WP_Linienobjekt

Wärmeliniendichten in Megawattstunden pro Meter und Jahr in Form einer straßenabschnittbezogenen Darstellung entsprechend  WPG Anlage 2 I.2.2.

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `kaeltelinienDichte` | Measure | 0..1 | MWh/(m*a) | Kälteliniendichte |
| `laenge` | Measure | 0..1 | m | Länge des Abschnitts der Wärmelinie |

### WP_Kaeltenetz
FeatureType · Oberklasse: WP_ThermischeNetze

Informationen zum Kältenetz entsprechend WPG Anlage 2 I.2.8.a).

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `inbetriebnahmeJahr` | Integer | 1 |  | Jahr der Inbetriebnahme |
| `energietraeger` | WP_Energietraeger | 0..1 |  | Art der Energieträger der Kälteerzeugung |

### WP_Kaelteversorgungsgebiet
FeatureType · Oberklasse: WP_Flaechenobjekt

Baublockbezogenes Gebiet mit Bedarf an aktiver Kälteerzeugung und Kühlung, der über ein Kälte- oder ein integriertes Wärme- und Kältenetz gedeckt werden könnte.

### WP_Linienobjekt
FeatureType (abstrakt) · Oberklasse: WP_Objekt

Abstrakte Oberklasse für alle WP-Fachobjekte mit (Multi-)Liniengeometrie.

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `position` | GM_MultiCurve | 1 |  | Liniengeometrie |

### WP_Massnahme
FeatureType · Oberklasse: –

Maßnahmen der Umsetzungsstrategie entsprechend WPG Anlage 2 VI.

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `id` | UUID | 1 |  | Der Identifikator des Features. |
| `regionalSchluessel` | CharacterString | 0..1 |  | Amtlicher Regionalschlüssel der betreffenden Gemeinde (Attribut istGemeinsamerWaermeplan = true) |
| `kategorie` | WP_KategorieMassnahme | 1 |  | Kategorie, der die Maßnahme zugeordnet werden kann |
| `bezeichnung` | CharacterString | 1 |  | Bezeichnung der Maßnahme |
| `beginnUmsetzung` | Date | 0..1 |  | Zeitpunkt, an dem dem die Maßnahme beginnen soll |
| `abschlussUmsetzung` | Date | 1 |  | Zeitpunkt, an dem dem die Maßnahme abgeschlossen sein soll |
| `kosten` | Integer | 0..1 |  | Erwartete Kosten für Planung und Umsetzung der Maßnahme in Euro |
| `kostentragenderSektor` | WP_Kostentraeger | 0..2 |  | Kostentragender Sektor |
| `endenergieEinsparung` | Measure | 0..1 | MWh/a | Erwartete Einsparung von Endenergie |
| `treibausgaseEinsparung` | Measure | 0..1 | tCO2e/a | Erwartete Einsparung von Treibhausgasen |
| `finanzierung` | WP_Finanzierungsmechanismus | 0..2 |  | Ermittelter Finanzierungsmechanismus zur Umsetzung (mandatorisch für Gebiete mit mehr als 45.000 Einwohnern) |
| `begruendung` | CharacterString | 0..1 |  | Begründung bzw. Erläuterung der Maßnahme |
| `refDokument` | WP_ExterneReferenz | 0..1 |  | Referenz auf ein externes Dokument zu der Maßnahme |
| `gehoertZuPlan` | WP_Plan | 1 |  | Relation der Maßnahme  auf den zugehörigen Plan |

### WP_NichtBeplantesTeilgebiet
FeatureType · Oberklasse: WP_Flaechenobjekt

Gebiet, das nicht als voraussichtliches Wärmeversorgungsgebiete überplant ist.

### WP_Objekt
FeatureType (abstrakt) · Oberklasse: –

Abstrakte Oberklasse für alle XWärmeplan-Fachobjekte. Die Attribute dieser Klasse werden über den Vererbungs-Mechanismus an alle Fachobjekte weitergegeben.

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `id` | UUID | 1 |  | Der Identifikator des Features. |
| `uuid` | CharacterString | 0..1 |  | Eindeutiger Identifier des Objektes |
| `aufschrift` | CharacterString | 0..1 |  | Spezifischer Text zur Beschriftung von Planinhalten |
| `refTextInhalt` | WP_TextAbschnitt | 0..1 |  | Referenz eines raumbezogenen Fachobjektes auf einen textuell formulierten Planinhalt |
| `refMassnahme` | WP_Massnahme | 0..1 |  | Referenz eines raumbezogenen Fachobjektes auf eine Maßnahme zur Umsetzung des Wärmeplans |
| `gehoertZuBereich` | WP_Bereich | 1 |  | Verweis auf den Bereich, zu dem der Planinhalt gehört |

### WP_Plan
FeatureType · Oberklasse: –

Die Klasse modelliert einen Wärmeplan gemäß § 23 Wärmeplanungsgesetz (WPG). Sie umfasst die in der Anlage 2 aufgeführte kartografische Darstellung der Bestands- und Potenzialanalyse, die Einteilung in Wärmeversorgungsgebiete, die Indikatoren des Zielszenarios, die Darstellung der Wärmeversorgungsarten für das Zieljahr sowie Maßnahmen der Umsetzungsstrategie. Die textlichen und grafischen Erläuterungen der Eignungsprüfung, Bestandsanalyse, des Zielszenarios und der Umsetzungsstrategie können dem Wärmeplan als externe Referenzen beigefügt werden.

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `id` | UUID | 1 |  | Der Identifikator des Features. |
| `name` | CharacterString | 1 |  | Name des Wärmeplans. Das Attribut name setzt sich aus den Attributen nameBasis, nummer und fassungsbezeichnung zusammen. (kann für Kodierung von Links in GML, HTML, JSON verwendet werden) |
| `nameBasis` | CharacterString | 0..1 |  | Unveränderlicher Basisname des Plans |
| `fassungsbezeichnung` | CharacterString | 0..1 |  | Bezeichnung einer fortlaufenden Fassung des Plans |
| `nummer` | CharacterString | 0..1 |  | Nummer des Plans |
| `internalId` | CharacterString | 0..1 |  | Interner Identifikator des Plans |
| `beschreibung` | CharacterString | 0..1 |  | Kommentierende Beschreibung des Plans |
| `planungsverantwortlicheStelle` | WP_Gemeinde | 1 |  | Planungsverantwortliche Stelle bzw. planungsverantwortliche Stelle, die in der interkommunalen Kooperation  den Wärmeplan hauptverantwortlich erstellt |
| `verfahrensart` | WP_VerfahrenArt | 1 |  | Verfahrensart |
| `istPlanungGemeindeverband` | Boolean | 0..1 |  | Wärmeplanung wurde in landesrechtlich verankertem Gemeindeverband durchgeführt = true. Default = false. |
| `istPlanungKonvoi` | Boolean | 0..1 |  | Wärmeplanung wurde in freiwilliger Kooperation benachbarter Gemeinden (im Konvoi) durchgeführt = true. Default = false. |
| `istGemeinsamerWaermeplan` | Boolean | 0..1 |  | Dieser Wärmeplan ist ein gemeinsamer Wärmeplan von mindestens zwei planungsverantwortlichen Stellen = true. Default = false. |
| `beteiligteGemeinden` | WP_Gemeinde | 0..* |  | Weitere beteiligte Gemeinden bei einer interkommunalen Zusammenarbeit in der Wärmeplanung und/oder bei der gemeinsamen Erstellung dieses Wärmeplans |
| `gesetzlicheGrundlage` | WP_GesetzlicheGrundlage | 1 |  | Gesetzliche Grundlage des Wärmeplans |
| `foerderkennzeichen` | CharacterString | 0..1 |  | Förderkennzeichen bei einer Förderung durch die Kommunalrichtlinie |
| `zieljahr` | CharacterString | 1 |  | Das Jahr, in dem spätestens die Umstellung auf eine treibhausgasneutrale Wärmeversorgung abgeschlossen sein soll. |
| `basisJahrDatenerfassung` | CharacterString | 1 |  | Basisjahr der Datenerfassung |
| `hatEnergieeinsparpotenzialgebiete` | Boolean | 0..1 |  | Es sind Teilgebiete mit erhöhtem Energieeinsparpotenzial (§ 18 Abs. 5 WPG) ausgewiesen  = true. Default = false. Siehe:  WP_Energieeinsparpotenzialgebiet |
| `hatKlimaneutraleWaermeversGeb` | Boolean | 0..1 |  | Es sind Teilgebiete ausgewiesen, in denen die Wärmeversorgung (nahezu) vollständig auf erneuerbaren Energien, unvermeidbarer Abwärme oder einer Kombination hieraus beruht (§ 14 Abs. 6 WPG) = true. Default = false. |
| `istFortschreibung` | Boolean | 0..1 |  | Der Plan ist eine Forschreibung (§ 25 WPG) = true. Default = false. |
| `ersetztPlan` | WP_VerbundenerPlan | 0..1 |  | Verweis auf vorherigen Wärmeplan, der durch den vorliegenden Plan ersetzt wird. |
| `aufstellungsbeschlussDatum` | Date | 0..1 |  | Beschluss oder die Entscheidung der planungsverantwortlichen Stelle über die Durchführung der Wärmeplanung gemäß § 13 WPG |
| `beschlussDatum` | Date | 1 |  | WPG § 13: Der Wärmeplan wird durch das nach Maßgabe des Landesrechts zuständige Gremium oder die zuständige Stelle beschlossen |
| `technHerstellDatum` | Date | 0..1 |  | Datum der letzten technischen oder fachlichen Änderung an diesem Plan im datenhaltenden System |
| `technischePlanerstellung` | CharacterString | 0..* |  | Bezeichnung der Institution oder Firma, die den Plan technisch erstellt hat. |
| `externeReferenz` | WP_ExterneReferenz | 0..* |  | Referenz auf eine digital verfügbare Ressource |
| `raeumlicherGeltungsbereich` | GM_MultiSurface | 1 |  | Grenze des räumlichen Geltungsbereiches des Plans |
| `energiebilanz` | WP_Energiebilanz | 0..* |  | Referenz auf Energiebilanzen |
| `infrastruktur` | WP_WaermeinfrastrukturAggregiert | 0..* |  | Referenz auf aggregierte Daten der Gebäude und Netzinfrastruktur |
| `potenzialanalyse` | WP_PotenzialanalyseAggregiert | 0..* |  | Referenz auf Daten der Potenzialanalyse |
| `massnahme` | WP_Massnahme | 0..* |  | Referenz auf eine Maßnahme zur Umsetzung des Wärmeplans |
| `text` | WP_TextAbschnitt | 0..* |  | Referenz des Plans auf einen Text |
| `bereich` | WP_Bereich | 0..* |  | Referenz des Plans auf einen Bereich |

### WP_PotenzialWaermenutzung
FeatureType · Oberklasse: WP_Geometrieobjekt

Raumbezogenes Potenzial zur Nutzung/Erzeugung von Wärme aus erneuerbaren Energien und zur Nutzung von unvermeidbarer Abwärme entsprechend WPG Anlage 2 II.

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `verzeichnisID` | CharacterString | 0..1 |  | Vollständige ID eines landesspezifischen Verzeichnis, z.B. "See-ID:  6884 (AWGN)" |
| `energietraeger` | WP_Energietraeger | 1 |  | Potenzieller Energieträger |
| `waermepotenzial` | Measure | 0..1 | MWh/a | Jährliche potenziell nutzbare/erzeugbare Wärmemenge (Erzeugernutzwärme) |
| `durchfluss` | Measure | 0..1 | m3/s | Durchfluss eines Fließgewässers |
| `volumen` | Measure | 0..1 | m3 | Volumen eines stehenden Gewässers |
| `deltaT` | Measure | 0..1 | K | ΔT: Bei der Berechnung angenommene Temperaturauskühlung eines Gewässers durch Wärmeentzug |
| `hinweis` | CharacterString | 0..1 |  | Textlicher Hinweis, Erläuterung |

### WP_PotenzialWaermespeicherung
FeatureType · Oberklasse: WP_Geometrieobjekt

Raumbezogenes Potenzial zur Wärmespeicherung entsprechend WPG Anlage 2 II.

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `potenzielleKapazitaet` | Measure | 1 | MWh | Potenzielle maximal speicherbare Wärmemenge (Erzeugernutzwärme) |

### WP_PotenzialanalyseAggregiert
FeatureType · Oberklasse: –

Zusammenfassende aggregierte Daten der Potenzialanalyse für das Planungsgebiet entsprechend WPG Anlage 2 II.

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `id` | UUID | 1 |  | Der Identifikator des Features. |
| `name` | CharacterString | 1 |  | Name der Tabelle (kann für Kodierung von Links in GML, HTML, JSON verwendet werden) |
| `regionalSchluessel` | CharacterString | 0..1 |  | Amtlicher Regionalschlüssel der betreffenden Gemeinde (Attribut istGemeinsamerWaermeplan = true) |
| `waermebedarfsreduktionGebaeude` | Measure | 0..1 | MWh | Potenziale zur Energieeinsparung durch Wärmebedarfsreduktion von Gebäuden (Erzeugernutzwärme) nach Anlage 2 Abschnitt II und § 16 Abs. 2 WPG (Zieljahr gegenüber Basisjahr). |
| `neWaermebedarfsreduktionGebaeude` | Measure | 0..1 | MWh | Potenziale zur Energieeinsparung durch Wärmebedarfsreduktion von Gebäuden (Nutzenergie) nach Anlage 2 Abschnitt II und § 16 Abs. 2 WPG (Zieljahr gegenüber Basisjahr). |
| `eeWaermebedarfsreduktionGebaeude` | Measure | 0..1 | MWh | Potenziale zur Energieeinsparung durch Wärmebedarfsreduktion von Gebäuden (Endenergie) nach Anlage 2 Abschnitt II und § 16 Abs. 2 WPG (Zieljahr gegenüber Basisjahr). |
| `erneuerbareEnergienAbwaerme` | WP_EndenergieEnergietraeger | 1..* |  | Potenziale erneuerbarer Energien (EE) und unvermeidbarer Abwärme zur Wärmeversorgung nach Energieträgern nach Anlage 2 Abschnitt II und § 16 Abs. 1 WPG Konformitätsbedingungen: zulässige Enumerationswerte 12003, 2000 bis 32004, 40001, 4100, ab 5000 |
| `technischeSynergieeffekte` | Boolean | 0..1 |  | Es wurden technische Synergieeffekte identfiziet = true.  Technische Synergieeffekte entstehen durch die gemeinsame Nutzung oder Integration von Infrastrukturen und Technologien, die Effizienzsteigerungen und Kosteneinsparungen bei der Wärmeversorgung ermöglichen. Dazu zählen bspw. die Nutzung lokaler Erneuerbarer Energiequellen zur Wärmeerzeugung oder die Nutzung der Vorteile der Sektorkopplung. (Anforderung gilt für Gemeindegebiet mit mehr als 45.000 Einwohnern, WPG § 21) |
| `organisatorischeSynergieeffekte` | Boolean | 0..1 |  | Es wurden organisatorische Synergieeffekte identfiziet = true.  Organisatorische Synergieeffekte beziehen sich auf die Zusammenarbeit und Koordination zwischen verschiedenen Akteuren und Institutionen, die zu einer besseren Planung, Steuerung und Umsetzung von Wärmeprojekten führt. Beispiele können die Bündelung von Ressourcen oder die gemeinsame Durchführung der Bürgerbeteiligung und -information sein. (Anforderung gilt für Gemeindegebiet mit mehr als 45.000 Einwohnern, WPG § 21) |
| `finanzielleSynergieeffekte` | Boolean | 0..1 |  | Es wurden finanzielle Synergieeffekte identfiziet = true.  Finanzielle Synergieeffekte resultieren aus der Bündelung von Ressourcen und Investitionen, die zu einer Reduzierung der Kosten und einer verbesserten Wirtschaftlichkeit der Wärmeversorgung führen. Dazu zählen u.a. die gemeinsame Fördermittelakquise oder Förderung und Umsetzung von Energieeffizienzmaßnahmen in privaten und gewerblichen Gebäuden. (Anforderung gilt für Gemeindegebiet mit mehr als 45.000 Einwohnern, WPG § 21) |
| `beruecksichtigungEEGemeinschaften` | Boolean | 0..1 |  | Es wurden Erneuerbare-Energie-Gemeinschaften berücksichtigt  = true.  Gemäß WPG §21 (2) soll eine Bewertung der Rolle von Erneuerbare-Energie-Gemeinschaften oder anderer von den Verbrauchern ausgehender Initiativen enthalten, die aktiv zur Umsetzung lokaler Projekte im Bereich Wärmeversorgung beitragen können (Anforderung gilt für Gemeindegebiet mit mehr als 45.000 Einwohnern) |
| `gehoertZuPlan` | WP_Plan | 1 |  | Relation der Potenzialanalyse auf den zugehörigen Plan |

### WP_TextAbschnitt
FeatureType · Oberklasse: –

Ein Abschnitt der textlich formulierten Inhalte  des Plans.

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `id` | UUID | 1 |  | Der Identifikator des Features. |
| `title` | CharacterString | 1 |  | Titel des Abschnitts (kann für Kodierung von Links in GML, HTML, JSON verwendet werden) |
| `text` | CharacterString | 1 |  | Inhalt eines Abschnitts der textlichen Planinhalte |
| `refText` | WP_ExterneReferenz | 0..1 |  | Referenz auf ein externes Dokument, das den zugehörigen Textabschnitt enthält. |
| `gehoertZuPlan` | WP_Plan | 1 |  | Referenz eines Textes auf den zugehörigen Plan |

### WP_ThermischeNetze
FeatureType (abstrakt) · Oberklasse: WP_Flaechenobjekt

Oberklasse für Wärme- und Kältenetze.

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `netzID` | CharacterString | 0..1 |  | ID des Netzes (kann in WP_EnergieBaublock referenziert werden) |
| `name` | CharacterString | 0..1 |  | Natürliche oder juristische Person, die die tatsächliche Herrschaft über das Wärme-/Kältenetz ausübt, seine Arbeitsweise eigenverantwortlich bestimmt und es auf eigene Rechnung nutzt, ohne notwendigerweise Eigentümer zu sein. |
| `betreiber` | CharacterString | 0..1 |  | Natürliche oder juristische Person, die die tatsächliche Herrschaft über das Wärme-/Kältenetz ausübt, seine Arbeitsweise eigenverantwortlich bestimmt und es auf eigene Rechnung nutzt, ohne notwendigerweise Eigentümer zu sein. |
| `medium` | WP_Transportmedium | 0..1 |  | Medium des Waerme- und Kältenetzes Konformitätsbedingung: Mandatorisch bei Bestandsnetzen |
| `laenge` | Measure | 1 | m | Gesamtlänge des Netzes |
| `anzahlGebaeudeAnschluss` | Integer | 1 |  | Anzahl der Gebäude mit Anschluss an das Netz |

### WP_WaermeKaelteNetz
FeatureType · Oberklasse: WP_ThermischeNetze

Informationen zum integrierten Wärme- und Kältenetz entsprechend WPG Anlage 2 I.2.8.a).

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `inbetriebnahmeJahr` | Integer | 1 |  | Jahr der Inbetriebnahme |
| `energietraeger` | WP_Energietraeger | 0..1 |  | Art der Energieträger der Kälteerzeugung |

### WP_WaermeinfrastrukturAggregiert
FeatureType · Oberklasse: –

Zusammenfassende aggregierte Daten zu Gebäuden und Netzinfrastrukturen für das Planungsgebiet und für verschiedene Betrachtungszeitpunkte. Betrifft Zielszenario und Betandsanalye entsprechend WPG Anlage 2 I und III.

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `id` | UUID | 1 |  | Der Identifikator des Features. |
| `name` | CharacterString | 1 |  | Name der Tabelle (kann für Kodierung von Links in GML, HTML, JSON verwendet werden) |
| `regionalSchluessel` | CharacterString | 0..1 |  | Amtlicher Regionalschlüssel der betreffenden Gemeinde (Attribut istGemeinsamerWaermeplan = true) |
| `betrachtungszeitpunkt` | WP_Betrachtungszeitpunkt | 1 |  | Betrachtungszeitpunkt für die Daten der Wärmeinfrastruktur |
| `waermerzeugerMitEnergietraeger` | WP_WaermeerzeugerAnzahl | 0..* |  | Anzahl dezentraler Wärmeerzeuger, einschließlich Hausübergabestationen, nach Art der Wärmeerzeuger einschließlich des eingesetzten Energieträgers |
| `waermenetzeBestand` | WP_WaermenetzeGesamt | 0..1 |  | Wärmenetze im Bestand |
| `waermenetzePlanung` | WP_WaermenetzeGesamt | 0..1 |  | Wärmenetze in Planung oder genehmigt |
| `speicherkapazitaetWaermespeicher` | Measure | 0..1 | MWh | Speicherkapazität der Wärmespeicher |
| `gebaeudeAnschlussGasnetz` | WP_GebaeudeNetzanschluss | 0..1 |  | Gebäude mit Anschluss an ein Gasnetz |
| `gebaeudeAnschlussWaermenetzBestand` | WP_GebaeudeNetzanschluss | 0..1 |  | Bestand der Gebäude mit Anschluss an Wärmenetze |
| `gebaeudeAnschlussWaermenetzPlanung` | WP_GebaeudeNetzanschluss | 0..1 |  | Gebäude mit Anschluss an geplante Wärmenetze |
| `anzahlGebaeude` | WP_GebaeudeAnzahl | 0..1 |  | Informationen zum Gebäudebestand |
| `sanierungsrate` | Measure | 0..1 | % | Informationen zum Gebäudebestand |
| `bedarfGruenesMethanZieljahr` | Measure | 0..1 | MWh | Bedarf an grünem Methan für das Zieljahr nach § 28 Abs. 5 WPG |
| `waermeversorgungsgebieteZieljahr` | WP_VersorgungsgebieteAggregiert | 0..* |  | Aggregiere Angaben zu den Wärmeversorgungsgebiete für das Zieljahr. Die Angaben erfolgen für die geplante Versorgungsart, nacheinander kombiniert mit den Eignungsstufen. |
| `gehoertZuPlan` | WP_Plan | 1 |  | Relation der Bestandsanalyse auf den zugehörigen Plan |

### WP_Waermelinie
FeatureType · Oberklasse: WP_Linienobjekt

Wärmeliniendichten in Megawattstunden pro Meter und Jahr in Form einer straßenabschnittbezogenen Darstellung entsprechend  WPG Anlage 2 I.2.2.

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `waermeMenge` | Measure | 0..1 | MWh/a | Jährlicher Wärmeverbrauch oder Wärmebedarf aller Objekte innerhalb eines Leitungsabschnitts |
| `waermelinienDichte` | Measure | 0..1 | MWh/(m*a) | Quotient aus Wärmeverbrauch/-bedarf der Objekte  innerhalb eines Leitungsabschnitts und der Länge dieses Leitungsabschnitts |
| `laenge` | Measure | 0..1 | m | Länge des Abschnitts der Wärmelinie |

### WP_Waermenetz
FeatureType · Oberklasse: WP_ThermischeNetze

Informationen zum Wärmenetz entsprechend WPG Anlage 2 I.2.8.a).

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `status` | WP_Status | 1 |  | Errichtungsstatus des Wärmenetzes |
| `temperatur` | Measure | 0..1 | °C | Temperatur (Mandatorisch bei Bestandsnetzen) |
| `geplanteInbetriebZeit` | CharacterString | 0..1 |  | Jahr oder Zeitraum einer geplanten Inbetriebnahme |
| `eeNachEnergietraeger` | WP_EndenergieEnergietraeger | 0..1 |  | Jährlicher Endenergieverbrauch oder Bedarf nach Energieträgern (für Status "Bestehend") |

### WP_WaermeversorgungsgebietStuetzjahr
FeatureType · Oberklasse: WP_Waermversorgungsgebiet

Einteilung des beplanten Gebiets in voraussichtliche Wärmeversorgungsgebiete in den Stüztjahren entsprechend WPG Anlage 2 IV.

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `stuetzjahr` | WP_Stuetzjahr | 1 |  | Stützjahr |

### WP_WaermeversorgungsgebietUmsetzung
FeatureType · Oberklasse: WP_Waermversorgungsgebiet

Einteilung des beplanten Gebiets in voraussichtliche Wärmeversorgungsgebiete zu einem frei wählbaren Zeitpunkt, passend zu Ausbaumaßnahmen der Wärmeversorgung.

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `jahr` | CharacterString | 1 |  | Jahr, auf das sich die Einteilgung bezieht |

### WP_WaermeversorgungsgebietZieljahr
FeatureType · Oberklasse: WP_Waermversorgungsgebiet

Einteilung des beplanten Gebiets in voraussichtliche Wärmeversorgungsgebiete und Zuordnung der Eignungsstufen für die Wärmeversorgungsarten, jeweils für das Zieljahr entsprechend WPG Anlage 2 IV und V (sowie  WPG  § 28  Abs. 2).

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `eignungDezentraleVersorgung` | WP_Eignungsstufe | 0..1 |  | Eignungsstufen für die dezentrale Versorgung Konformitätsbedingung: nur optional in der kleinen Wärmeplanung |
| `eignungWaermenetz` | WP_Eignungsstufe | 0..1 |  | Eignungsstufen für Versorgung über ein Wärmenetz Konformitätsbedingung: nur optional in der kleinen Wärmeplanung |
| `eignungWasserstoffnetz` | WP_Eignungsstufe | 0..1 |  | Eignungsstufen für Versorgung über ein Wasserstoffnetz Konformitätsbedingung: nur optional in der kleinen Wärmeplanung |
| `eignungGruenesMethan` | WP_Eignungsstufe | 0..1 |  | Eignungsstufen für Versorgung mit grünem Methan |

### WP_Waermversorgungsgebiet
FeatureType (abstrakt) · Oberklasse: WP_BeplantesTeilgebiet

Abstrakte Oberklasse für Wärmeversorgungsgebiete. Die räumliche Einteilung in konkrete Wärmeversorgungsgebiete für die Betrachtungszeitpunkte ist variabel.

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `versorgungsart` | WP_WaermeversorgungsgebietTyp | 1 |  | Geplante Art der Wärmeversorgung für das betrachtete Gebiet |
| `waermeMenge` | Measure | 0..1 | MWh/a | Jährlicher Wärmebedarf aller Objekte, die dem Wärmeversorgungsgebiet zugeordnet sind |
| `eeNachEnergietraeger` | WP_EndenergieEnergietraeger | 0..* |  | Jährlicher Endenergiebedarf für Wärme je Energieträger |
| `sanierungsrate` | Measure | 0..1 | vH/a | Jährliche Sanierungsrate der Gebäude |

### WP_BaujahrAngaben
DataType · Oberklasse: –

Datentyp zur Erfassung von Baujahren über Baualtersklassen.

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `baualtersklasse` | WP_Baualtersklasse | 1 |  | Baualtersklasse der Gebäude |
| `anteil` | Measure | 1 | % | Anteil der dieser Baualtersklasse zugeordneten Gebäude am Gebäudebestand im Baublock |

### WP_Betrachtungszeitpunkt
DataType · Oberklasse: –

Datentyp zur Erfassung Betrachtungszeipunktes.

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `art` | WP_ZeitpunktArt | 1 |  | Art des Zeitpunktes |
| `jahr` | CharacterString | 1 |  | Jahr |

### WP_EndenergieAngaben
DataType · Oberklasse: –

Datentyp für die Erfassung der jährlichen Endenergie der gesamten Wärmeversorgung nach Energieträgern und Sektoren.

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `energietraeger` | WP_Energietraeger | 1 |  | Energieträger |
| `eeSektorIndustrie` | Measure | 0..1 | MWh/a | Jährliche Endenergie für den jeweiligen Energieträger im Sektor Industrie |
| `eeSektorGHD` | Measure | 0..1 | MWh/a | Jährliche Endenergie für den jeweiligen Energieträger im Sektor Gewerbe, Handel, Dienstleistungen |
| `eeSektorHaushalte` | Measure | 0..1 | MWh/a | Jährliche Endenergie für den jeweiligen Energieträger im Sektor private Haushalte |
| `eeSektorLiegenschaften` | Measure | 0..1 | MWh/a | Jährliche Endenergie für den jeweiligen Energieträger im Sektor öffentliche Liegenschaften |
| `endenergieEnTrGesamt` | Measure | 1 | MWh/a | Gesamte jährliche Endenergie für den jeweiligen Energieträger |

### WP_EndenergieEnergietraeger
DataType · Oberklasse: –

Datentyp zur Erfassung der jährlichen Endenergie einzelner Energieträger.

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `energietraeger` | WP_Energietraeger | 1 |  | Energieträger |
| `endenergie` | Measure | 1 | MWh/a | Endenergieverbrauch/-bedarf Innerhalb eines Jahres |

### WP_EndenergieSektor
DataType · Oberklasse: –

Datentyp zur Erfassung Erfassung der jährlichen Endenergie der Wärmeversorgung nach Sektoren.

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `eeSektorIndustrie` | Measure | 1 | MWh/a | Jährliche Endenergie im Sektor Industrie |
| `eeSektorGHD` | Measure | 1 | MWh/a | Jährliche Endenergie im Sektor Gewerbe, Handel, Dienstleistungen |
| `eeSektorHaushalte` | Measure | 1 | MWh/a | Jährliche Endenergie im Sektor private Haushalte |
| `eeSektorLiegenschaften` | Measure | 1 | MWh/a | Jährliche Endenergie im Sektor öffentliche Liegenschaften |
| `endenergieGesamt` | Measure | 1 | MWh/a | Gesamte jährliche Endenergie |

### WP_ExterneReferenz
DataType · Oberklasse: –

Spezifikation einer externen, digital verfügbaren Ressource.

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `art` | WP_ExterneReferenzTyp | 0..1 |  | Typ / Inhalt des referierten Dokuments oder der Internetressource |
| `referenzName` | CharacterString | 1 |  | Name bzw. Titel der externen Referenz |
| `nummer` | CharacterString | 0..1 |  | Dokumentennummer |
| `seitenangabe` | CharacterString | 0..1 |  | Seitenangabe, wenn ein umfangreiches Dokument referenziert wird |
| `referenzURL` | URI | 1 |  | URL der referierten Ressource |
| `beschreibung` | CharacterString | 0..1 |  | Beschreibung des referierten Ressource |
| `datum` | Date | 0..1 |  | Datum des referierten Dokuments oder des letzten Zugriffs auf eine Webseite |

### WP_GebaeudeAnzahl
DataType · Oberklasse: –

Datentyp zur Erfassung von Gebäuden.

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `gebaeude` | Integer | 1 |  | Anzahl Gebäude im beplanten Gebiet (ALKIS) |
| `beheizteWohngebaeude` | Integer | 1 |  | Errechnete Anzahl der beheizten Gebäude im beplanten Gebiet, die zumindest in Teilen zum Wohnen genutzt werden oder eine wohnähnliche Nutzung haben |
| `beheizteNichtwohngebaeude` | Integer | 1 |  | Errechnete Anzahl der beheizten Gebäude, die nicht unter "beheizteWohngebaeude" fallen |

### WP_GebaeudeNetzanschluss
DataType · Oberklasse: –

Datentyp mit Angaben zu beheizten Gebäuden, die an ein Gas- oder Wärmenetz angeschlossen sind.

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `anzahl` | Integer | 1 |  | Anzahl der Gebäude mit Netzanschluss im beplanten Gebiet |
| `anteil` | Measure | 1 | % | Anteil der Gebäude (mit Netzanschluss) an Gesamtheit der beheizten Gebäude im beplanten Gebiet in Prozent |

### WP_Gemeinde
DataType · Oberklasse: –

Spezifikation einer für die Aufstellung des Plans zuständigen Gemeinde.

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `name` | CharacterString | 1 |  | Name der Gemeinde. |
| `regionalSchluessel12` | CharacterString | 0..1 |  | 12-stelliger Regionalschlüssel für Gemeinde bzw. Stadt |
| `regionalSchluessel9` | CharacterString | 0..1 |  | Verkürzter Regionalschlüssel mit 9 Stellen für Verband- oder Samtgemeinde |

### WP_Treibhausgasemissionen
DataType · Oberklasse: –

Datentyp für die Erfassung der jährlichen Treibhausgasemissionen der gesamten Wärmeversorgung nach Energieträgern und Sektoren.

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `energietraeger` | WP_Energietraeger | 1 |  | Energieträger |
| `thgSektorIndustrie` | Measure | 0..1 | tCO2-eq/a | Jährliche Treibhausgasemissionen für den jeweiligen Energieträger im Sektor Industrie |
| `thgSektorGHD` | Measure | 0..1 | tCO2-eq/a | Jährliche Treibhausgasemissionen für den jeweiligen Energieträger im Sektor Gewerbe, Handel, Dienstleistungen |
| `thgSektorHaushalte` | Measure | 0..1 | tCO2-eq/a | Jährliche Treibhausgasemissionen für den jeweiligen Energieträger im Sektor private Haushalte |
| `thgSektorLiegenschaften` | Measure | 0..1 | tCO2-eq/a | Jährliche Treibhausgasemissionen für den jeweiligen Energieträger im Sektor öffentliche Liegenschaften |
| `thgEmissionenEnTrGesamt` | Measure | 1 | tCO2-eq/a | Gesamte jährliche Treibhausgasemissionen für den jeweiligen Energieträger |

### WP_TreibhausgasemissionenSektor
DataType · Oberklasse: –

Datentyp zur Erfassung Erfassung der jährlichen Treibhausgasemissionen der Wärmeversorgung nach Sektoren.

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `thgSektorIndustrie` | Measure | 1 | tCO2-eq/a | Jährliche Treibhausgasemissionen im Sektor Industrie |
| `thgSektorGHD` | Measure | 1 | tCO2-eq/a | Jährliche Treibhausgasemissionen im Sektor Gewerbe, Handel, Dienstleistungen |
| `thgSektorHaushalte` | Measure | 1 | tCO2-eq/a | Jährliche Treibhausgasemissionen im Sektor private Haushalte |
| `thgSektorLiegenschaften` | Measure | 1 | tCO2-eq/a | Jährliche Treibhausgasemissionen im Sektor öffentliche Liegenschaften |
| `thgEmissionenGesamt` | Measure | 1 | tCO2-eq/a | Gesamte jährliche Treibhausgasemissionen |

### WP_VerbundenerPlan
DataType · Oberklasse: –

Spezifikation eines anderen Wärmeplans, der mit dem Ausgangsplan verbunden ist und von diesem geändert wird.

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `planName` | CharacterString | 0..1 |  | Name (Attribut "name" von "WP_Plan") des verbundenen Plans. |
| `nummer` | CharacterString | 0..1 |  | Nummer (Attribut "nummer" von "WP_Plan") des verbundenen Plans |

### WP_VersorgungsgebieteAggregiert
DataType · Oberklasse: –

Datentyp für die Erfassung der Wärmeversorgungsgebiete für das Zieljahr.

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `versorgungsart` | WP_WaermeversorgungsgebietTyp | 1 |  | Auswahl der Art des Wärmeversorgungsgebiets |
| `eignungsstufe` | WP_Eignungsstufe | 1 |  | Auswahl der Eignungsstufe |
| `anzahlGebiete` | Integer | 0..1 |  | Anzahl der Gebiete (bzw. Baublöcke) |
| `flaeche` | Measure | 1 | ha | Gesamtfläche der Gebiete |
| `endenergieverbrauch` | Measure | 1 | MWh | Endenergieverbrauch der Gebiete |

### WP_WaermeerzeugerAngaben
DataType · Oberklasse: –

Datentyp für die Erfassung von Informationen zu dezentralen Wärmeerzeugern.

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `art` | WP_WaermeerzeugerTyp | 1 |  | Art der Wärmeerzeugungsanlage |
| `anzahl` | Integer | 1 |  | Anzahl der Wärmeerzeugungsanlagen |
| `altersklasse` | WP_Altersklasse | 0..1 |  | Überwiegende Baualtersklasse der Wärmeerzeugungsanlagen |
| `feuerungsleistung` | Measure | 0..1 | MW | Gesamtfeuerungsleistung der Wärmeerzeugungsanlagen in Megawatt |

### WP_WaermeerzeugerAnzahl
DataType · Oberklasse: –

Datentyp  der dezentralen Wärmeerzeuger ( einschließlich Hausübergabestationen) und der eingesetzten Energieträger.

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `art` | WP_WaermeerzeugerTyp | 1 |  | Art der Heizung bzw. dezentralen Wärmeerzeugung |
| `anzahl` | Integer | 1 |  | Anteil des jährlichen Energieverbrauchs in Prozent |

### WP_WaermenetzeGesamt
DataType · Oberklasse: –

Datentyp mit Informationen zu den Wärmenetzen.

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `anzahlNetze` | Integer | 1 |  | Anzahl der Wärmenetze |
| `trassenlaenge` | Measure | 1 | m | Gesamte Trassenlänge |

### WP_WaermeversorgungArt
DataType · Oberklasse: –

Datentyp zur Erfassung der Endenergie über die Wärmeversorgungsart.

| Attribut | Typ | Mult. | Einheit | Beschreibung |
|---|---|---|---|---|
| `eeWaermenetzVersorgung` | Measure | 1 | MWh/a | Jährliche Endenergie der leitungsgebundenen Wärme |
| `eeDezentraleVersorgung` | Measure | 1 | MWh/a | Jährliche Endenergie der dezentralen Wärmeversorgung |

## Aufzählungen (Enumerationen)

### WP_Altersklasse

| Code | Bezeichnung |
|---|---|
| 1000 | vor 1990 |
| 2000 | 1990 bis 1999 |
| 3000 | 2000 bis 2009 |
| 4000 | 2010 bis 2019 |
| 5000 | 2020 bis 2029 |
| 6000 | ab 2030 |

### WP_Baualtersklasse

| Code | Bezeichnung |
|---|---|
| 1000 | bis 1949 (Oberkategorie) |
| 10001 | vor 1919 |
| 10002 | 1919 bis 1949 |
| 2000 | 1950 bis 1969 (Oberkategorie) |
| 20001 | 1950 bis 1959 |
| 20002 | 1960 bis 1969 |
| 3000 | 1970 bis 1989 (Oberkategorie) |
| 30001 | 1970 bis 1979 |
| 30002 | 1980 bis 1989 |
| 4000 | 1990 bis 2015 (Oberkategorie) |
| 40001 | 1990 bis 1999 |
| 40002 | 2000 bis 2009 |
| 40003 | 2010 bis 2015 |
| 5000 | ab 2016 |
| 9999 | unbekannt |

### WP_Eignungsstufe

| Code | Bezeichnung |
|---|---|
| 1000 | sehr wahrscheinlich geeignet |
| 2000 | wahrscheinlich geeignet |
| 3000 | wahrscheinlich ungeeignet |
| 4000 | sehr wahrscheinlich ungeeignet |
| 5000 | Keine Aussage notwendig oder möglich (entweder vereinfachtes Verfahren durchgeführt oder Vesorgungsart Prüfgebiet) |

### WP_EnergiebedarfArt

| Code | Bezeichnung |
|---|---|
| 1000 | Wärme |
| 2000 | Kälte |
| 3000 | Wärme und Kälte |

### WP_EnergieeinsatzArt

| Code | Bezeichnung |
|---|---|
| 1000 | Großverbrauch von Wärme und/oder Kälte |
| 2000 | Großverbrauch Gas für stoffliche Zwecke |
| 3000 | Großverbrauch von Wärme/Kälte und Gas für stoffliche Zwecke |
| 9999 | Unbekannt |

### WP_Energietraeger

| Code | Bezeichnung |
|---|---|
| 1100 | Kohle (Oberkategorie) |
| 11001 | Braunkohle |
| 11002 | Steinkohle |
| 1200 | Fossiles Gas (Oberkategorie) |
| 12001 | Erdgas |
| 12002 | Flüssiggas |
| 12003 | Grubengas |
| 1300 | Mineralölprodukte (Oberkategorie) |
| 13001 | Heizöl |
| 13002 | Dieselkraftstoff |
| 2000 | Abfall (Oberkategorie) |
| 20001 | Nicht biogener Abfall |
| 20002 | Biogener Abfall |
| 3100 | Biomasse (Oberkategorie) |
| 31001 | Feste Biomasse ohne Altholz |
| 31002 | Altholz |
| 31003 | Flüssige Biomasse |
| 3200 | Gasförmige Biomasse (Oberkategorie) |
| 32001 | Biogas |
| 32002 | Biomethan |
| 32003 | Klärgas |
| 32004 | Deponiegas |
| 4000 | Wasserstoff (H2) (Oberkategorie) |
| 40001 | Durch die Elektrolyse von Wasser hergestellter Wasserstoff unter Verwendung von Strom aus erneuerbaren Energiequellen |
| 40002 | Wasserstoff aus der Reformierung von Erdgas, dessen Erzeugung mit einem Kohlenstoffdioxid-Abscheidungsverfahren und Kohlenstoffdioxid-Speicherungsverfahren gekoppelt wird |
| 40003 | Wasserstoff, der aus Biomasse oder unter Verwendung von Strom aus Anlagen der Abfallwirtschaft hergestellt wird |
| 40004 | Wasserstoff, der über die Pyrolyse von Erdgas hergestellt wird |
| 5000 | Wasserstoffderivate (Oberkategorie) |
| 50001 | Synthetisches (grünes) Methan: der aus Ökostrom erzeugte (grüne) Wasserstoff wird mit CO2 zu Methan gewandelt |
| 6000 | Strom (Oberkategorie) |
| 60001 | Strom zum Betrieb von Wärmepumpen |
| 60002 | Strom für Betrieb von Direktheizungen |
| 7100 | Solarthermie (Oberkategorie) |
| 71001 | Solarthermie über Dachflächenanlagen |
| 71002 | Solarthermie über Freiflächenanlagen |
| 7200 | Dem Erdboden entnommene Wärme (Oberkategorie) |
| 72001 | Oberflächennahe Geothermie nutzt den Untergrund bis zu einer Tiefe von ca. 400 m |
| 72002 | Tiefe Geothermie nutzt Lagerstätten, die in größeren Tiefen als 400 m unter Geländeoberkante erschlossen werden |
| 7300 | Umweltwärme (Oberkategorie) |
| 73001 | Umweltwärme aus Grundwasser |
| 73002 | Umweltwärme aus Oberflächengewässern |
| 73003 | Umweltwärme aus Grubenwasser |
| 73004 | Umweltwärme aus Luft |
| 73005 | Umweltwärme aus Abwasser |
| 8000 | Unvermeidbare Abwärme (Oberkategorie) |
| 80001 | Abwärme unter 60 °C |
| 80002 | Abwärme 60 bis 110 °C |
| 80003 | Abwärme ab 110 °C |
| 9990 | Sonstige Energieträger (Oberkategorie) |
| 99901 | Sonstige fossile Brennstoffe |
| 99902 | Sonstige erneuerbare Energien |

### WP_ExterneReferenzTyp

| Code | Bezeichnung |
|---|---|
| 1000 | Fachgutachten zur kommunalen Wärmeplanung  als vollständiges PDF-Dokument |
| 1100 | Auszug oder Kapitel des Wärmeplandokuments (als PDF) |
| 1200 | Diagramm zur Wärmeplanung, evtl. mit Erläuterungstext |
| 1300 | Karte/Plandarstellung der Wärmeplanung |
| 1400 | Maßnahmensteckbrief der  Wärmeplanung |
| 2000 | Dokument zum Beschluss des Wärmeplans |
| 3100 | Geoportal |
| 3200 | Webseite |
| 3300 | Datenbank |
| 4000 | Webdienst (WMS, WFS, OGC API Features) |
| 9999 | Sonstiges |

### WP_Finanzierungsmechanismus

| Code | Bezeichnung |
|---|---|
| 1000 | Private Investitionen |
| 2000 | Private Investitionen |
| 3000 | Förderprogramme |
| 9999 | Sonstige Finanzierung |

### WP_GebaeudeTyp

| Code | Bezeichnung |
|---|---|
| 1000 | Gebäude, das nach seiner Zweckbestimmung überwiegend dem Wohnen dient, einschließlich von Wohn-, Alten- oder Pflegeheimen sowie ähnlicher Einrichtungen (GEG § 3) |
| 10001 | Freistehendes Wohngebäude mit 1-2 Wohnungen |
| 10002 | Wohngebäude mit 1 bis 2 Wohnungen als Doppelhaus, gereihtes Haus oder sonstiger Gebäudetyp |
| 10003 | Wohngebäude mit 3 bis 12 Wohnungen |
| 10004 | Wohngebäude mit 13 oder mehr Wohnungen |
| 2000 | Gebäude, das nach seiner Zweckbestimmung NICHT überwiegend dem Wohnen dient |
| 20001 | Büro-, Verwaltungs-, Amtsgebäude |
| 20002 | Gebäude des Groß- und Einzelhandels |
| 20003 | Gebäude für Beherbergung und Gastronomie |
| 20004 | Krankenhäuser |
| 20005 | Kultureinrichtungen |
| 20006 | Bildungseinrichtungen |
| 20007 | Sporteinrichtungen |
| 20008 | Schwimmbäder |
| 20009 | Lagergebäude |
| 20010 | Industrie und Gewerbe |
| 9999 | unbekannt |

### WP_GesetzlicheGrundlage

| Code | Bezeichnung |
|---|---|
| 1000 | Wärmeplan auf Basis des Wärmeplanungsgesetz und der Umsetzungsrichtlinen der Länder |
| 2000 | Landesgesetz, z.B. Klimaschutz- und Klimawandelanpassungsgesetz Baden-Württemberg (KlimaG BW) vom 7.2.23 |
| 3000 | Über die Kommunalrichtlinie (KRL) der NKI geförderter Wärmeplan |

### WP_KategorieMassnahme

| Code | Bezeichnung |
|---|---|
| 1000 | Potenzialerschließung, Flächensicherung und Ausbau erneuerbarer Energien |
| 2000 | Wärmenetzausbau und -transformation |
| 3000 | Sanierung/Modernisierung und Effizienzsteigerung in Industrie und Gebäuden |
| 4000 | Heizungsumstellung und Transformation der Wärmeversorgung in Gebäuden und Quartieren |
| 5000 | Stromnetz- und Wasserstoffnetzausbau |
| 6000 | Verbraucherverhalten und Suffizienz |
| 9999 | Sonstige Kategorie |

### WP_Kostentraeger

| Code | Bezeichnung |
|---|---|
| 1000 | Gemeinde |
| 2000 | Sektor der privaten Haushalte |
| 3000 | Sektor Industrie |
| 4000 | Sektor Gewerbe, Handel, Dienstleistungen |
| 5000 | Sektor Energiewirtschaft |

### WP_SchutzgebietTyp

| Code | Bezeichnung |
|---|---|
| 1100 | Wasserschutzgebiet (Wasserhaushaltsgesetz - WHG) |
| 1200 | Heilquellenschutzgebiet (Wasserhaushaltsgesetz - WHG) |
| 1300 | Festgesetztes Überschwemmungsgebiet (Wasserhaushaltsgesetz - WHG) |
| 2000 | Flora-Fauna-Habitat (FFH-Richtlinie) |
| 3000 | Vogelschutzgebiet (EU-Vogelschutzrichtlinie) |
| 4000 | Feuchtgebiet internationaler Bedeutung (Ramasar-Konvention) |
| 5100 | Naturschutzgebiet (Bundesnaturschutzgesetz - BNatSchG) |
| 5200 | Landschaftsschutzgebiet (Bundesnaturschutzgesetz - BNatSchG) |
| 5300 | Nationalpark (Bundesnaturschutzgesetz - BNatSchG) |
| 5400 | Gesetzlich geschütztes Biotop (Bundesnaturschutzgesetz - BNatSchG) |
| 9999 | Sonstiges Schutzgebiet |

### WP_Status

| Code | Bezeichnung |
|---|---|
| 1000 | Wärmenetz in Betrieb oder bestehender Großverbraucher |
| 2000 | in Planung befindliches oder genehmigtes Wärmenetz |
| 3000 | potenzieller Großverbraucher oder potenzielles Wärmenetz |

### WP_Stuetzjahr

| Code | Bezeichnung |
|---|---|
| 1000 | 2030 |
| 2000 | 2035 |
| 3000 | 2040 |

### WP_Transportmedium

| Code | Bezeichnung |
|---|---|
| 1000 | Wasser |
| 2000 | Dampf |
| 3000 | Sole |
| 4000 | Kältemittel |
| 9999 | Sonstiges Medium |

### WP_VerfahrenArt

| Code | Bezeichnung |
|---|---|
| 1000 | Regelverfahren |
| 2000 | Kleine Wärmeplanung gemäß § 22 a WPG |
| 3000 | Vereinfachtes Verfahren gemäß § 22 WPG |
| 4000 | Für das beplante Gebiet oder ein Teilgebiet wurde eine verkürzte Wärmeplanung  gemäß § 14 Abs. 4 WPG |

### WP_Versorgungsmedium

| Code | Bezeichnung |
|---|---|
| 1000 | Versorgung durch Erdgas |
| 2000 | Versorgung durch Biogas |
| 3000 | Versorgung durch Wasserstoff |
| 4000 | Versorgung durch Wasserstoffderivate |
| 5000 | Leitungsgebundene Wärme |
| 6000 | Leitungsgebundene Kälte |
| 9999 | Sonstige Versorgung |

### WP_WaermeerzeugerTyp

| Code | Bezeichnung |
|---|---|
| 1000 | Stromdirektheizungen wandeln durch elektrischen Widerstand Strom in Wärme um. Bauformen sind Fußbodenheizungen, Wärmestrahler oder Nachtspeicherheizungen. |
| 2000 | Oberkategorie der Heizkessel zur Wärmeerzeugung durch Verbrennung fossiler Brennstoffe |
| 20001 | Kohleheizung |
| 20002 | Erdgasheizung |
| 20003 | Flüssiggasheizung |
| 20004 | Ölheizung |
| 3000 | leitungsgebundene Wärme, Hausübergabestation |
| 4000 | Solarthermische Anlage |
| 5000 | Blockheizkraftwerk, das das Prinzip der Kraft-Wärme-Kopplung nutzt (Oberkategorie). |
| 50001 | Mit Erdgas betriebenes Blockheizkraftwerk (BHKW) |
| 50002 | Mit Biomasse betriebenes Blockheizkraftwerk (BHKW) |
| 6000 | Oberkategrie von Heizungen, die mit Biomasse befeuert werden. |
| 60001 | Scheitholzheizung |
| 60002 | Hackschnitzelheizung |
| 60003 | Pelettheizung |
| 7000 | Eine Wärmepumpenheizung ist die Anwendung der Wärmepumpe für Heizzwecke. Sie entzieht der Umwelt thermische Energie und bringt diese unter Aufwendung technischer Arbeit mit einem Verdichter über einen thermodynamischen Kreisprozess auf ein höheres, für Heizzwecke nutzbares Temperaturniveau. |
| 70001 | Wärmeerzeugung mit Umgebungsluft |
| 70002 | Wärmeerzeugung über das Erdreich |
| 70003 | Wärmeerzeugung mit Grundwasser |
| 9999 | Sonstige dezentrale Wärmeerzeungsanlage |

### WP_WaermeversorgungsgebietTyp

| Code | Bezeichnung |
|---|---|
| 1000 | Beplantes Teilgebiet, in dem ein Wärmenetz besteht oder geplant ist und ein erheblicher Anteil der ansässigen Letztverbraucher über das Wärmenetz versorgt werden soll. |
| 10001 | Beplantes Teilgebiet, in dem Letztverbraucher, die sich in unmittelbarer Nähe zu einem bestehenden Wärmenetz befinden, mit diesem verbunden werden sollen, ohne dass hierfür der Ausbau des Wärmenetzes erforderlich würde. |
| 10002 | Beplantes Teilgebiet, in dem es bislang kein Wärmenetz gibt und das durch den Neubau von Wärmeleitungen erstmals an ein bestehendes Wärmenetz angeschlossen werden soll. |
| 10003 | Beplantes Teilgebiet, das an ein neues Wärmenetz angeschlossen werden soll. |
| 2000 | Beplantes Teilgebiet, in dem ein Wasserstoffnetz besteht oder geplant ist und ein erheblicher Anteil der ansässigen Letztverbraucher über das Wasserstoffnetz zum Zweck der Wärmeerzeugung versorgt werden soll. |
| 3000 | Beplantes Teilgebiet, das überwiegend nicht über ein Wärme- oder ein Gasnetz versorgt werden soll. |
| 4000 | Beplantes Teilgebiet, das nicht in ein voraussichtliches Wärmeversorgungsgebiet eingeteilt werden soll, weil die für eine Einteilung erforderlichen Umstände noch nicht ausreichend bekannt sind oder weil ein erheblicher Anteil der ansässigen Letztverbraucher auf andere Art mit Wärme versorgt werden soll. |
| 40001 | Prüfgebiet Wärmenetz |
| 40002 | Prüfgebiet Wasserstoffnetzgebiet |
| 40003 | Prüfgebiet für die leitungsgebundene Versorgung mit grünem Methan |

### WP_ZeitpunktArt

| Code | Bezeichnung |
|---|---|
| 1000 | Basisjahr der Bestandsanalyse |
| 2000 | Stützjahr des WPG |
| 3000 | Zieljahr |
| 4000 | frei wählbares Jahr, passend zu Ausbaumaßnahmen der Wärmeversorgung |
