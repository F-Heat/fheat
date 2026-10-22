# XWärmeplan mapping

F|Heat → XWärmeplan 0.9.6, as implemented in [`fheat_core/export/xwp/`](../src/fheat_core/export/xwp/). Status 21.10.2026. Codes, units and the written properties live in `mapping.py`, the logic in `mappers.py`. Two tests keep the tables honest: `tests/test_xwp_mapping.py` against the model of xplan-tools 1.26, `tests/test_xwp_evidence.py` against the original of the XLeitstelle (XSD and feature catalogue, without xplan-tools).

Version 1 writes `WP_Plan` with one `WP_Bereich` (mode `plan`) or only the `WP_Bereich` (mode `fragment`), plus `WP_Waermelinie`, `WP_Waermenetz` and one class of supply areas. GML is checked against the XSD. JSON-FG is written as xplan-tools writes it (measures as `{value, uom}`, references as bare UUIDs); that does not validate against the official JSON schema yet.

## Guiding rule

F|Heat writes what it computes in the XWärmeplan standard; it is not a tool for the heat planning itself. The technical plan (Philipp Sommer, 19.10.2026) sets the scope: what F|Heat does not compute comes from `XWPExportConfig` with that plan's defaults. Nothing beyond it: no further object types, no decisions per area, no editing of plan content. Where the technical plan and the standard disagree, the technical plan applies unless the output would not conform; then the standard applies (decisions E1–E4 below).

## Sources

Every row names its source in the column **Source**:

| Short | Source |
| --- | --- |
| XSD | `waermeplan.xsd` 0.9.6, element and multiplicity (`tests/fixtures/xwp/xsd-0.9.6/`, Git blob `7898e8b`) |
| OAK | feature catalogue 0.9.6, unit of a measure (`objektartenkatalog/XWaermeplan096.zip`, extract in `tests/fixtures/xwp/oak-0.9.6-einheiten.json`) |
| TP | technical plan, section "Mapping matrix" unless named otherwise |
| Interpretation | neither says it; reason in the section below |

## Plan and area

| XWärmeplan | Source | Transformation | Source |
| --- | --- | --- | --- |
| `WP_Plan.name` | `XWPExportConfig.plan_name` | | XSD `WP_Plan/name` 1..1; TP |
| `WP_Plan.planungsverantwortlicheStelle` | `municipality_name`, `municipality_key` | `WP_Gemeinde` with `name` and `regionalSchluessel12` = RS (rule below) or `regional_key` | XSD `WP_Plan/planungsverantwortlicheStelle` 1..1, `WP_Gemeinde/name` 1..1; TP |
| `WP_Plan.verfahrensart` | `procedure` | default 1000 Regelverfahren | XSD `WP_VerfahrenArtType`; TP |
| `WP_Plan.gesetzlicheGrundlage` | `legal_basis` | default 1000 WPG | XSD `WP_GesetzlicheGrundlageType`; TP |
| `WP_Plan.zieljahr` | `target_year` | default 2045, as text | XSD `WP_Plan/zieljahr` 1..1 (string); TP |
| `WP_Plan.basisJahrDatenerfassung` | `base_year` | as text | XSD 1..1 (string); TP |
| `WP_Plan.beschlussDatum` | `decision_date` | mandatory in 0.9.6; a draft without it uses `mode="fragment"` | XSD `WP_Plan/beschlussDatum` 1..1; TP "Risks" |
| `WP_Plan.raeumlicherGeltungsbereich` | `boundary=` of the export, else union of `parcels_gdf` | MultiPolygon | XSD 1..1 MultiSurface; TP |
| `WP_Bereich.nummer`, `.name` | `area_number` (0), `area_name` ("F\|Heat") | | XSD `WP_Bereich/nummer`, `/name` 1..1; Interpretation (values) |
| `WP_Bereich.geltungsbereich` | plan boundary | | XSD 0..1 MultiSurface |
| `WP_Bereich.gehoertZuPlan` | the `WP_Plan`; in mode fragment `plan_id`, without one `uuid5` of the RS | the municipality's plan, not in the file; a derived id is named in the report's notes | XSD `WP_Bereich/gehoertZuPlan` 1..1; decision 21.10.2026 |

**Regionalschlüssel.** Since 2009 a municipality outside any association repeats its three-digit code after a 0: RS = AGS[0:5] + "0" + AGS[5:8] + AGS[5:8]. Steinfurt 05566084 → 055660084084, Münster (kreisfrei) 05515000 → 055150000000. Every NRW municipality is outside any association; the NRW adapter gives the AGS as `NRWDataAdapter.municipality_key`. For a member of an Amt, Samt- or Verbandsgemeinde the RS has to be passed as `regional_key`. Source: Destatis (Krajzar, "Methoden – Verfahren – Entwicklungen" 1/2009), not XWärmeplan; the technical plan's form `ss r kk 0000 ggg` is the one before 2009 and gives the same key only for kreisfreie Städte.

## WP_Waermelinie (WPG Anlage 2 I.2.2)

| XWärmeplan | Source (`wld_gdf`) | Transformation | Source |
| --- | --- | --- | --- |
| `position` | geometry | LineString → MultiLineString | XSD 1..1 MultiCurve; TP |
| `waermeMenge` | `heat_demand` (kWh/a) | ÷ 1000 → MWh/a | XSD 0..1; OAK MWh/a; TP |
| `waermelinienDichte` | `heat_line_density` (kWh/(a·m)) | ÷ 1000 → MWh/(m·a) | XSD 0..1; OAK MWh/(m*a); TP |
| `laenge` | `length` (m) | unchanged | XSD 0..1; OAK m; TP |

Segments without heat demand or length are left out. Lines are not cut to the plan boundary yet; a segment beyond it is reported (consistency).

## WP_Waermenetz (WPG Anlage 2 I.2.8 a)

One per `NetworkResult` (a pipeline state in phase RESULTS).

| XWärmeplan | Source | Transformation | Source |
| --- | --- | --- | --- |
| `position` | every edge of `net_gdf` (route, house and source connections) | buffered by `network_buffer`, default `buffer_distance` of `FHeatConfig` (50 m), dissolved; cut to the plan boundary | XSD 1..1 MultiSurface (via `WP_Flaechenobjekt`); TP; E4 |
| `laenge` | `result_summary.total_route_length_m` | m, route without house connections | XSD `WP_ThermischeNetze/laenge` 1..1; OAK m; TP |
| `anzahlGebaeudeAnschluss` | `result_summary.total_buildings` | connected buildings, not house-connection edges | XSD 1..1 "Anzahl der Gebäude mit Anschluss an das Netz"; TP |
| `status` | `network_status`, the same for every network | default 3000 potenziell | XSD `WP_StatusType`, 1..1; TP |
| `medium` | `network_medium` | default 1000 Wasser | XSD `WP_TransportmediumType`, 0..1 (mandatory for existing networks); TP |
| `temperatur` | `result_summary.supply_temperature_c` | °C | XSD 0..1; OAK °C; TP |
| `name`, `netzID`, `betreiber` | `NetworkResult.name`, `.key`, `.operator` | | XSD 0..1 each |
| `eeNachEnergietraeger` | `source_energy_carrier` + `total_heat_demand_mwh_a + total_loss_mwh_a` | only when the carrier is set | XSD 0..1, `WP_EndenergieEnergietraeger` with `energietraeger` and `endenergie` 1..1; OAK MWh/a; TP; E3 |

## Supply areas

`supply_year` picks the class: `"zieljahr"` → `WP_WaermeversorgungsgebietZieljahr`, `"2030"`/`"2035"`/`"2040"` → `WP_WaermeversorgungsgebietStuetzjahr` with `stuetzjahr` 1000/2000/3000 (XSD `WP_StuetzjahrType`; TP). One area per suitability polygon (`polygons_gdf`).

| XWärmeplan | Source | Transformation | Source |
| --- | --- | --- | --- |
| `position` | geometry | cut to the plan boundary: the polygons are parcels buffered by `buffer_distance` | XSD 1..1 MultiSurface; TP "Consistency" |
| `versorgungsart` | `supply_type`, the same for every area | default 40001 Prüfgebiet Wärmenetz; F\|Heat makes no decision per area | XSD `WP_WaermeversorgungsgebietTypType`, 1..1; TP |
| `waermeMenge` | `heat_demand` (kWh/a) | ÷ 1000 → MWh/a | XSD 0..1; OAK MWh/a; TP |
| `eignungWaermenetz` (target year only) | `heat_demand_density` with `suitability_thresholds` | not written by default, see below | XSD `WP_EignungsstufeType`, 0..1 ("only optional in the small heat planning"); TP; to be replaced by E2 |

**Why no suitability from the density by default.** The suitability polygons are dissolved, buffered parcels, so their heat demand density is far below the block density the guideline thresholds refer to. In the Burgsteinfurt example one polygon covers 119 of 151 ha with 132 MWh/(ha·a); with the KEA-BW thresholds (415/175/70) the area of the 5.2 km network would be "wahrscheinlich ungeeignet".

## Feature ids

`uuid5(<F|Heat namespace>, "<RS>/<feature type>/<key>")`, so reruns and plan updates keep the ids (TP "Architecture"):

| Feature | Key | Source |
| --- | --- | --- |
| `WP_Plan` | plan name (mode plan) | TP |
| `WP_Bereich` | `<plan name, plan_id or "">/<nummer>/<hash of the boundary>` | TP; the boundary keeps two exports into one plan apart |
| `WP_Waermelinie`, supply areas | hash of the geometry, normalised and rounded to 0.1 m | Interpretation: the WLD has no stable street id |
| `WP_Waermenetz` | `NetworkResult.key`, else its name, else `N01`, `N02`, … | TP |

A second feature with the same key gets `#2`. Geometry `gml:id`s and the root `gml:id` are new on every write (xplan-tools). In mode fragment without `plan_id` the area refers to `uuid5(<F|Heat namespace>, "<RS>/WP_Plan")`, the same for every export of the municipality.

## Checks

The report collects all findings instead of stopping at the first (TP "Validation and testing"):

1. **structure**: xplan-tools validates every feature (mandatory fields, code lists, extra fields) and the references. In mode fragment a stand-in for the municipality's plan takes the place of the plan outside the file, so every other reference is checked as well. Nothing is written then.
2. **schema**: the written GML against the XSD, offline through an XML catalog (`schema_dir=`, test data in `tests/fixtures/xwp/xsd-0.9.6/`).
3. **consistency**: valid, non-empty geometries inside the plan boundary (0.5 m tolerance); `laenge` equals the route length; the supply areas carry the heat demand of the suitability polygons. A geographic CRS is rejected before anything is built.

Besides the findings the report carries **notes**, which do not make it fail: which plan boundary was used (passed or the union of the parcels) and, in mode fragment, the derived plan id and that `WP_Bereich.nummer` has to be unique within the municipality's plan (XSD documentation of `nummer`).

## Not mapped

No XWärmeplan slot: nominal diameters, flow velocities, volume flows, simultaneity factor, heat losses per edge, the hourly load profile. They stay in the F|Heat GeoPackage and tables (TP). Out of scope for version 1 (TP "Summary"): stock analysis, building blocks (`WP_EnergieBaublock`, `WP_GebaeudeBaublock`), energy balance, aggregates, measures, the heat source (`source_gdf`; XSD 0.9.6 has no class for a feed-in point or a generation plant).

## Interpretations

Where neither the standard nor the technical plan decides:

- **Ids from a geometry hash** for heat lines and supply areas: the WLD has no stable street id, and the standard does not regulate ids (`implementierung`, `Referenzplaene/readme.md`).
- **`WP_Bereich` number 0, name "F|Heat"**: the XSD only asks for both; numbers start at 0 by default (XSD documentation of `nummer`).

## Decisions (E1–E4)

| | Technical plan | Standard | Decision | Implemented |
| --- | --- | --- | --- | --- |
| E1 Version | 0.9.5 with xplan-tools 1.20 on Python 3.12 | 0.9.6 is the newest version xplan-tools supports (1.26.0), 0.9.7 the newest of the standard | 0.9.6 with xplan-tools 1.26 on Python 3.13 (ADR 0002); 0.9.7 once xplan-tools supports it | yes |
| E2 Suitability from thresholds | stage from the heat demand density, thresholds in the config | code 5000 means "no statement necessary or possible (… supply type Prüfgebiet)" | supply type Prüfgebiet (4000, 40001–40003) → 5000 in `eignungDezentraleVersorgung`, `eignungWaermenetz`, `eignungWasserstoffnetz`; thresholds only for other supply types; option stays, off by default | no |
| E3 Energy carrier of the source | code from the config, quantity from F\|Heat | `eeNachEnergietraeger` is described "for status Bestehend" without a conformity condition | no conflict: written when the config names a carrier, else not | yes |
| E4 Network area | buffer around all edges, dissolved, width configurable, default `buffer_distance` | only asks for a MultiSurface | buffer around all edges of `net_gdf` (route, house and source connections), dissolved, cut to the plan boundary; width `network_buffer`, default the calculation's `buffer_distance` (50 m); no planning area | yes |

Further decisions of 21.10.2026, implemented: in mode `fragment` the municipality's `plan_id` is optional (without it, an id derived from the RS and a note in the report); the supply type and suitability per area (`SupplyDecision`) and the status per network are dropped, the config's values apply to every area and network.

## Open

Nothing.

## xplan-tools 1.26: handled in the writer

- The GML writer takes the envelope of the plan geometry and fails without a `WP_Plan`; for a fragment F\|Heat builds the root and lets xplan-tools serialise each feature.
- xplan-tools reads a file only as a whole collection and rejects a fragment: `gehoertZuPlan` points outside the file, and a mandatory reference is never dropped, not even with `DROP_INVALID_REFS`. A fragment is meant for merging into the municipality's plan, not for reading on its own; `writer.read_features` reads its features one by one with the models of xplan-tools (used by the round-trip test).
- `schemaLocation` points to `xsd/waermeplan.xsd` on `main`, which is 0.9.7 since 13.10.2026, and JSON-FG's `describedby` to `json/0.9/`, which does not exist; both are rewritten to the 0.9.6 paths.
- `BaseCollection.from_features` needs the features as a dict; `repo_factory` is deprecated in favour of `Datasource(...).repo()`.
