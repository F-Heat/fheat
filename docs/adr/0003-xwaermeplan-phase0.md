# ADR 0003: XWärmeplan-Export in Phase 0

- Status: angenommen
- Datum: 21.10.2026
- Ergänzt: [ADR 0002](0002-xwaermeplan-xplan-tools.md)
- Ergänzt durch: [ADR 0004](0004-xwaermeplan-zwei-ausgaben.md)
- Kontext: Technischer Plan „F-Heat → XWärmeplan Export“ (Philipp Sommer, 19.10.2026), Abbildung in [`docs/xwp_mapping.md`](../xwp_mapping.md)

## Kontext

ADR 0002 hat den Export auf xplan-tools gestellt. Offen waren die WP1-Fragen des technischen Plans und einige Stellen, an denen der technische Plan und der Standard nicht dasselbe sagen. In Phase 0 gibt es meist noch keinen beschlossenen Wärmeplan der Gemeinde, oft auch noch keine Kennung dafür; der Teildatensatz (`mode="fragment"`) verlangte sie trotzdem. Die Versorgungsart je Planungsgebiet (`SupplyDecision`) war eine Planungsentscheidung im Werkzeug, die der technische Plan nicht vorsieht. Und xplan-tools 1.26 liest einen Teildatensatz nicht wieder ein, weil `WP_Bereich.gehoertZuPlan` auf einen Plan außerhalb der Datei zeigt.

## Entscheidungen

1. **Leitlinie.** F|Heat gibt das, was es berechnet, XWärmeplan-konform aus; es wird kein Werkzeug für die Wärmeplanung selbst. Der technische Plan gilt; was F|Heat nicht berechnet, kommt aus `XWPExportConfig` mit dessen Standardwerten. Widersprechen sich technischer Plan und Standard, gilt der technische Plan, außer die Ausgabe wäre dadurch nicht konform. Die Fälle E1–E4 stehen in `docs/xwp_mapping.md`.
2. **Kennung des Gemeindeplans freiwillig.** Im Teildatensatz verweist der Bereich auf `plan_id`; fehlt sie, auf `uuid5` aus dem Regionalschlüssel, für alle Exporte einer Gemeinde gleich. Der Bericht nennt die abgeleitete Kennung als Hinweis.
3. **Bereich mit Grenze im Schlüssel.** Der Schlüssel des `WP_Bereich` enthält den Geometrie-Hash der Grenze, damit zwei Teildatensätze in denselben Plan nicht dieselbe Bereichs-ID bekommen.
4. **Verweise auch im Teildatensatz prüfen.** Ein Platzhalter für den Gemeindeplan nimmt dessen Stelle ein, sodass xplan-tools alle übrigen Verweise prüft; geschrieben wird der Teildatensatz ohne den Platzhalter.
5. **Rundlauf eines Teildatensatzes Objekt für Objekt.** Weil xplan-tools die Datei als Ganzes ablehnt, liest `writer.read_features` jedes Objekt einzeln mit dem Modell von xplan-tools; der Test vergleicht IDs, Werte und Verweise.
6. **Keine Festlegungen je Gebiet oder je Netz.** `SupplyDecision` und `NetworkResult.status` entfallen; Versorgungsart und Netzstatus der Config gelten für alle Gebiete und Netze.
7. **Netzfläche nach dem technischen Plan (E4).** Puffer um alle Kanten des Netzes, aufgelöst, Breite `network_buffer`, Standard `buffer_distance` der Rechnung (50 m); das Planungsgebiet wird dafür nicht mehr verwendet.
8. **Hinweise im Bericht.** `ExportReport.notes` hält fest, was der Nutzer wissen muss, ohne dass der Export als fehlerhaft gilt: verwendete Grenze, abgeleitete Kennung, Eindeutigkeit von `WP_Bereich.nummer` im Zielplan.

## Folgen

- fheat-web muss `SupplyDecision`, den Status je Netz und die Übergabe des Planungsgebiets als Netzfläche entfernen, bevor `FHEAT_REF` auf diesen Stand gehoben wird.
- Die Netzfläche wird größer und folgt den Leitungen: im Burgsteinfurt-Beispiel 36,4 ha statt 26,9 ha (Planungsgebiet), einschließlich des Anschlusses der Wärmequelle.
- Ein Teildatensatz lässt sich mit xplan-tools nur objektweise lesen, nicht als Plan; er ist zum Einfügen in den Plan der Gemeinde gedacht.
