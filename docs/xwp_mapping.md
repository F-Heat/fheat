# XWärmeplan mapping

F|Heat → XWärmeplan 0.9.6, as implemented in [`fheat_core/export/xwp/`](../src/fheat_core/export/xwp/). Status: proposal for the WP1 sign-off, 20.10.2026. Codes and units live in `mapping.py`, the logic in `mappers.py`; `tests/test_xwp_mapping.py` checks the tables against the model of xplan-tools 1.26.

Version 1 writes `WP_Plan` with one `WP_Bereich`, `WP_Waermelinie`, `WP_Waermenetz` and one class of supply areas. GML is the normative encoding and is checked against the XSD. JSON-FG is written as xplan-tools writes it (measures as `{value, uom}`, references as bare UUIDs); that does not validate against the official JSON schema.

## Plan and area

| XWärmeplan | Source | Transformation |
| --- | --- | --- |
| `WP_Plan.name` | `XWPExportConfig.plan_name` | |
| `WP_Plan.planungsverantwortlicheStelle` | `municipality_name`, `municipality_key` | `WP_Gemeinde` with `regionalSchluessel12` = RS (rule below) or `regional_key` |
| `WP_Plan.verfahrensart` | `procedure` | default 1000 Regelverfahren |
| `WP_Plan.gesetzlicheGrundlage` | `legal_basis` | default 1000 WPG |
| `WP_Plan.zieljahr` | `target_year` | default 2045, as text |
| `WP_Plan.basisJahrDatenerfassung` | `base_year` | as text |
| `WP_Plan.beschlussDatum` | `decision_date` | mandatory in 0.9.6; a draft without it uses `mode="fragment"` |
| `WP_Plan.raeumlicherGeltungsbereich` | `boundary=` of the export, else union of `parcels_gdf` | MultiPolygon |
| `WP_Bereich.nummer`, `.name` | `area_number` (0), `area_name` ("F\|Heat") | |
| `WP_Bereich.geltungsbereich` | plan boundary | |
| `WP_Bereich.gehoertZuPlan` | the `WP_Plan`; in mode fragment `plan_id` | the municipality's plan, not in the file |

**Regionalschlüssel.** Since 2009 a municipality outside any association repeats its three-digit code after a 0: RS = AGS[0:5] + "0" + AGS[5:8] + AGS[5:8]. Steinfurt 05566084 → 055660084084, Münster (kreisfrei) 05515000 → 055150000000. Every NRW municipality is outside any association; the NRW adapter gives the AGS as `NRWDataAdapter.municipality_key`. For a member of an Amt, Samt- or Verbandsgemeinde the RS has to be passed as `regional_key`.

## WP_Waermelinie (WPG Anlage 2 I.2.2)

| XWärmeplan | Source (`wld_gdf`) | Transformation |
| --- | --- | --- |
| `position` | geometry | LineString → MultiLineString |
| `waermeMenge` | `heat_demand` (kWh/a) | ÷ 1000 → MWh/a |
| `waermelinienDichte` | `heat_line_density` (kWh/(a·m)) | ÷ 1000 → MWh/(m·a) |
| `laenge` | `length` (m) | unchanged |

Segments without heat demand or length are left out. Lines are not cut to the plan boundary (their length is an attribute); a segment beyond it is reported.

## WP_Waermenetz (WPG Anlage 2 I.2.8 a)

One per `NetworkResult` (a pipeline state in phase RESULTS).

| XWärmeplan | Source | Transformation |
| --- | --- | --- |
| `position` | network's `planning_area_gdf`; without one, the route (edges other than `Hausanschluss`) | route buffered by `network_buffer` (10 m); cut to the plan boundary |
| `laenge` | `result_summary.total_route_length_m` | m, route without house connections |
| `anzahlGebaeudeAnschluss` | `result_summary.total_buildings` | connected buildings, not house-connection edges |
| `status` | `NetworkResult.status`, else `network_status` | default 3000 potenziell |
| `medium` | `network_medium` | default 1000 Wasser |
| `temperatur` | `result_summary.supply_temperature_c` | °C |
| `name`, `netzID`, `betreiber` | `NetworkResult.name`, `.key`, `.operator` | |
| `eeNachEnergietraeger` | `source_energy_carrier` + `total_heat_demand_mwh_a + total_loss_mwh_a` | only when the carrier is set; the schema describes the attribute for existing networks |

## Supply areas

`supply_year` picks the class: `"zieljahr"` → `WP_WaermeversorgungsgebietZieljahr`, `"2030"`/`"2035"`/`"2040"` → `WP_WaermeversorgungsgebietStuetzjahr` with `stuetzjahr` 1000/2000/3000. One area per suitability polygon (`polygons_gdf`).

| XWärmeplan | Source | Transformation |
| --- | --- | --- |
| `position` | geometry | cut to the plan boundary: the polygons are parcels buffered by `buffer_distance` |
| `versorgungsart` | `SupplyDecision` covering the polygon, else `supply_type` | default 40001 Prüfgebiet Wärmenetz; the municipality decides |
| `waermeMenge` | `heat_demand` (kWh/a) | ÷ 1000 → MWh/a |
| `eignungWaermenetz` (target year only) | `SupplyDecision.suitability`, else `heat_demand_density` with `suitability_thresholds` | not written by default, see below |

**Why no suitability by default.** The suitability polygons are dissolved, buffered parcels, so their heat demand density is far below the block density the guideline thresholds refer to. In the Burgsteinfurt example one polygon covers 119 of 151 ha with 132 MWh/(ha·a); with the KEA-BW thresholds (415/175/70) the area of the 5.2 km network would be "wahrscheinlich ungeeignet". The export writes `eignungWaermenetz` only from the planner's decision or when thresholds are set explicitly.

## Feature ids

`uuid5(<F|Heat namespace>, "<RS>/<feature type>/<key>")`, so reruns and plan updates keep the ids:

| Feature | Key |
| --- | --- |
| `WP_Plan` | plan name (mode plan) |
| `WP_Bereich` | `<plan name or plan_id>/<nummer>` |
| `WP_Waermelinie`, supply areas | hash of the geometry, normalised and rounded to 0.1 m (the WLD has no street id) |
| `WP_Waermenetz` | `NetworkResult.key`, else its name, else `N01`, `N02`, … |

A second feature with the same key gets `#2`. Geometry `gml:id`s and the root `gml:id` are new on every write (xplan-tools).

## Checks

The report collects all findings instead of stopping at the first:

1. **structure**: xplan-tools validates every feature (mandatory fields, code lists, extra fields) and, in mode plan, the references. Nothing is written then.
2. **schema**: the written GML against the XSD, offline through an XML catalog (`schema_dir=`, test data in `tests/fixtures/xwp/xsd-0.9.6/`).
3. **consistency**: valid, non-empty geometries inside the plan boundary (0.5 m tolerance); `laenge` equals the route length; the supply areas carry the heat demand of the suitability polygons. A geographic CRS is rejected before anything is built.

## Not mapped

No XWärmeplan slot: nominal diameters, flow velocities, volume flows, simultaneity factor, heat losses per edge, the hourly load profile. They stay in the F|Heat GeoPackage and tables. Out of scope for version 1: stock analysis, building blocks (`WP_EnergieBaublock`, `WP_GebaeudeBaublock`), energy balance, aggregates, measures, the heat source (`source_gdf`).

## WP1 status

| Question | Status |
| --- | --- |
| Network geometry | Planning area, else 10 m around the route (as in the former implementation) |
| `laenge` | Route without house connections |
| `anzahlGebaeudeAnschluss` | `total_buildings` |
| Default `versorgungsart` and year | 40001 for the target year; the planner overrides per area |
| NRW AGS → RS | Rule above |
| Energy carrier of the source | Config field, off by default; open whether to write it for potential networks at all |
| Export of `source_gdf` | Open |
| Basis and thresholds of `eignungWaermenetz` | Open, off by default |

## xplan-tools 1.26: handled in the writer

- The GML writer takes the envelope of the plan geometry and fails without a `WP_Plan`; for a fragment F\|Heat builds the root and lets xplan-tools serialise each feature.
- `schemaLocation` points to `xsd/waermeplan.xsd` on `main`, which is 0.9.7 since 13.10.2026, and JSON-FG's `describedby` to `json/0.9/`, which does not exist; both are rewritten to the 0.9.6 paths.
- `BaseCollection.from_features` needs the features as a dict; `repo_factory` is deprecated in favour of `Datasource(...).repo()`.
