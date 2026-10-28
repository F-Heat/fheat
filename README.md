# F|Heat

**F|Heat** is a Python toolkit for **district-heating network planning from geodata**. Given buildings, streets, parcels and a heat-source location, it computes heat-line density (*Wärmeliniendichte*, WLD), derives suitability polygons (*Eignungspolygone*), dimensions a pipe network (diameters, flow velocities, heat losses, simultaneity factor / *Gleichzeitigkeitsfaktor*), and produces an hourly load profile, a result summary and result tables (pipe quantities per diameter, connected buildings per load profile).

> Domain terms are German because the tool targets German municipal heat planning (*kommunale Wärmeplanung*), in particular the federal state of North Rhine-Westphalia (NRW).

## Packages

The repository is a monorepo of four installable packages:

| Package | Role |
|---|---|
| [`fheat_core`](src/fheat_core/) | Adapter-agnostic pipeline: orchestrator, data schemas, geometry/network/SLP algorithms, and the step functions. This is the engine. |
| [`fheat_nrw`](src/fheat_nrw/) | Adapter that **downloads NRW open geodata** (building heat model via OpenGeoData NRW, cadastral parcels via the ALKIS WFS) and processes it into schema-compliant frames. |
| [`fheat_flex`](src/fheat_flex/) | Adapter for **user-supplied** GeoPackages, with a column mapping onto the core schema. Use this when you bring your own data. |
| [`fheat_eu`](src/fheat_eu/) | **Europe-wide heat source data** (Fraunhofer ISI, Hotmaps) for any adapter: wastewater plants, industrial excess heat, waste incineration, rivers, hydrothermal. |
| [`fheat_de`](src/fheat_de/) | **Germany-wide open data** for any adapter: biogas CHP units of the Marktstammdatenregister and their clusters. |

All five are import packages shipped from a single distribution named `fheat` (see [Installation](#installation)). The whole logic is derived from the former QGIS plugin to adress the flexibility with other applications.

## Architecture

```
DataAdapter ──fetch──▶ PipelineState ──▶ FHeatOrchestrator ──▶ outputs (.gpkg + summary + tables)
(source of data)        (frames)          (runs the phases)
```

- A **`DataAdapter`** (`fheat_nrw` or `fheat_flex`) supplies schema-compliant GeoDataFrames: `buildings`, `streets`, `parcels` and optionally the heat `source`. All region- and source-specific logic lives in the adapter.
- **`FHeatConfig`** holds only *calculation* parameters (temperatures, WLD threshold, buffer distance, SLP year/class).
- **`FHeatOrchestrator`** runs the pipeline phase by phase, and can resume from any phase:

  | Phase | Step | Produces |
  |---|---|---|
  | `INITIAL` | download | input frames from the adapter |
  | `DOWNLOADED` | adjust | cleaned geometry, schema-validated frames |
  | `ADJUSTED` | status | heat-line density + suitability polygons |
  | `STATUS` | network | pipe network with sizing & losses |
  | `NETWORK` | results | hourly load profile + result summary + pipe quantities per DN + buildings per load profile |

Adapters must produce data conforming to the contracts in [`schemas.py`](src/fheat_core/schemas.py); the core validates against the same schemas as it goes.

### Stages: analysis and network planning

The phases form two stages. Every step can still be run on its own with
`run_step(phase)`; the stage runners are a convenience.

| Stage | Steps | Area | Needs |
|---|---|---|---|
| Analysis (*Potenzialanalyse*) — `run_analysis()` | download → adjust → status | the complete input area, e.g. a whole town or district | no heat source |
| Planning (*Netzplanung*) — `run_planning()` | network → results | buildings inside `state.planning_area_gdf` | heat source (`state.source_gdf`) |

The analysis shows where a heat network makes sense (heat line density and
suitability polygons for the whole area). The user then picks a planning area,
for example one of the suitability polygons, and a heat source:

```python
orch.run_analysis()                                    # download → adjust → status
orch.state.planning_area_gdf = orch.state.polygons_gdf.iloc[[0]]
orch.state.source_gdf = my_source_gdf                  # Point(s), any CRS
orch.run_planning()                                    # network → results
orch.save_outputs(clip_to_planning_area=True)
```

- Network and results connect the buildings with `connect == 1` whose representative point lies inside the planning area (`fheat_core.selection.connected_mask`). The `connect` flags are not changed, so another planning area can be tried without repeating the analysis. Without a planning area all buildings with `connect == 1` are connected (previous behaviour).
- The route to the heat source uses all routable streets, also outside the planning area, so a source outside the area is connected along the streets.
- A step started without its inputs raises `fheat_core.errors.PipelineInputError`, e.g. the network step without a heat source.
- `run_until(phase)` runs the missing steps up to any phase; `run_all()` still runs the whole pipeline.
- `save_outputs(layers=[...])` writes only some layers (e.g. `["wld", "eignungspolygone"]` after the analysis), `clip_to_planning_area=True` only the features in the planning area (network and source stay complete).

### Cancelling a calculation

`FHeatOrchestrator(..., should_stop=fn)` makes a running step cancellable ([`fheat_core/cancel.py`](src/fheat_core/cancel.py)). F|Heat asks `fn()` before every step and at checkpoints of the network step: before and after its backend, between the backends' parts and in the pauses before an Overpass request is retried. While HiGHS optimises in the expert mode, a solver callback asks `fn()` at most twice a second. Once it returns `True`, the step ends with `fheat_core.cancel.CalculationCancelled`, usually within a second. Gurobi and CPLEX stop at the checkpoints around the optimisation only.

```python
orch = FHeatOrchestrator(config=config, adapter=adapter, should_stop=lambda: stop_requested.is_set())
try:
    orch.run_planning()
except CalculationCancelled:
    ...  # the state of the step is undefined, as after any failure
```

- `CalculationCancelled` is a `BaseException`, like `KeyboardInterrupt`, so the pipeline's `except Exception` blocks (retried downloads, optional layers) do not swallow it. Catch it explicitly.
- `fn` should be cheap and thread-safe: the solver callback runs on HiGHS' thread. If it raises during the optimisation, the optimisation goes on.
- `with fheat_core.cancel.cancellable(fn): ...` makes code cancellable without the orchestrator, e.g. a single step function.

### Network modes

The `NETWORK` phase dispatches to an interchangeable backend, selected by `FHeatConfig.network_mode`. The step itself contains no algorithm; both backends live in [`fheat_core/network/`](src/fheat_core/network/) behind the `NetworkBackend` contract and return the same `NetSchema`-compliant `net_gdf`, so everything downstream (load profile, summary, export labels) is identical.

| Mode | Backend | How the route is found |
|---|---|---|
| `"phase0"` *(default)* | [`dijkstra.py`](src/fheat_core/network/dijkstra.py) | union of the shortest paths from the source to every building along the street graph |
| `"expert"` | [`topotherm_backend.py`](src/fheat_core/network/topotherm_backend.py) | mixed-integer optimisation ([topotherm](https://github.com/jylambert/topotherm) single-time-step MILP) |

**topotherm determines the topology only** — which street segments are built, and (in `optimization_mode="economic"`) which buildings are worth connecting. The simultaneity factor (GLF), volume flow, DN, velocity and heat losses are then computed by F|Heat with the *same* functions Phase 0 uses, from F|Heat's own pipe catalogue. That keeps the two modes directly comparable and every column meaning the same thing in both.

The expert mode is opt-in and has extra requirements:

```bash
pip install -e ".[topotherm]"
pip install -e "git+https://github.com/jylambert/topotherm@v0.6.0#egg=topotherm" --src ../vendor
```

**topotherm is not published on PyPI** — it lives only at [jylambert/topotherm](https://github.com/jylambert/topotherm). The `[topotherm]` extra therefore ships the solver and the pandas pin but *not* topotherm itself: a direct git URL in the published metadata would make this package unuploadable to PyPI.

- **`-e` is required** — a regular install of topotherm 0.6.0 omits its `topotherm.models` subpackage and then fails at import with a confusing "circular import" error. Editable installs read from the checkout and work.
- **`--src` matters too.** pip drops editable VCS checkouts into `./src` by default, which would land inside this project’s own `src/` tree. Point it somewhere else.
- **Python 3.12 — exactly** — topotherm 0.6.0 uses PEP 701 f-string syntax, so it cannot even be imported on 3.10/3.11, and its own `requires-python = ">=3.10,<=3.13"` excludes 3.13.1 and newer (under PEP 440, `3.13.11 <= 3.13` is false) as well as 3.14. The core itself keeps its `>=3.10` floor.
- **A MILP solver** — the extra pulls in `highspy` (open source); Gurobi or CPLEX work too but are not required.
- **pandas < 3** — pinned in the extra, because topotherm 0.6.0 breaks on pandas 3.x. The pin deliberately sits in the extra so users who never touch the expert mode are not held back.

`import fheat_core` and the `"phase0"` mode work unchanged without any of this installed — topotherm is imported lazily, inside the expert branch only.

```python
from fheat_core.config import FHeatConfig, NetworkMode, TopothermConfig

config = FHeatConfig(
    supply_temperature=80.0,
    return_temperature=50.0,
    network_mode=NetworkMode.EXPERT.value,
    topotherm=TopothermConfig(
        optimization_mode="economic",  # "economic" (default) | "forced"
        solver="highs",
        heat_price=120e-3,             # €/kW revenue
        source_price=80e-3,            # €/kW variable production cost
    ),
)
```

In `"economic"` mode the optimiser may leave unprofitable buildings unconnected; their `connect` flag is set to `0` so the load profile and summary stay consistent. If *nothing* is profitable the backend raises with the parameters to adjust rather than returning an empty network. See [`examples/burgsteinfurt_topotherm.py`](examples/burgsteinfurt_topotherm.py).

### Civil works / road surfaces

The network step prices every edge with the standardised pipe costs of its DN — `cost_main` for routes, `cost_h-connect` for house connections, in € per metre of trench, from the pipe catalogue [`pipe_data.csv`](src/fheat_core/data/pipe_data.csv) — and scales the civil works part of them with what lies on top of the route. For an edge of length `l`, pipe costs `c`, civil works factor `f` and civil works share `s`:

```
m          = (1 − s) + s · f      # cost multiplier of the edge
pipe_cost  = l · c · m            # €
civil_cost = l · c · s · f        # of which civil works, €
```

- `FHeatConfig.civil_cost_share` is `s`, the share of the pipe costs that is civil works (trench, backfill, surface restoration). Default `0.6`, allowed `0…1`; `0` means the road surface has no effect on the costs.
- `f` is the area-weighted mean of the layer polygons under a 1.5 m buffer around the edge, multiplied over the layers ([`civil_cost.py`](src/fheat_core/algorithms/civil_cost.py)). A layer without data under an edge contributes 1.0.
- `"phase0"` keeps its length-based topology; the costs are written onto the finished net. `"expert"` puts `m` into topotherm's pipe cost term, so the optimisation avoids expensive routes.
- The net gets the columns `civil_cost_factor`, `road_surface` (the dominant surface along the edge), `pipe_cost` and `civil_cost`; the result summary `civil_cost_share`, `total_pipe_cost_eur`, `total_civil_cost_eur` and `mean_civil_cost_factor` (length-weighted). They are left out when the pipe catalogue has no cost columns (an adapter's own catalogue may omit them; a warning is logged).

The layers come from the adapter (`DataAdapter.fetch_landuse`, `fetch_osm_surface`); without them every factor is 1.0. The NRW adapter loads two:

| Layer | Source | Axis | Licence |
|---|---|---|---|
| land use | ALKIS "Tatsächliche Nutzung", WFS `wfs_nw_alkis_vereinfacht`, layer `ave:Nutzung` | legal/planning (road, railway, water, green space …) | [Datenlizenz Deutschland – Zero 2.0](https://www.govdata.de/dl-de/zero-2-0) |
| road surface | OpenStreetMap `highway`/`surface` via the Overpass API | material (asphalt, paving stones, gravel …) | [ODbL](https://opendatacommons.org/licenses/odbl/), © OpenStreetMap contributors |

Both are loaded for the bounding box of the loaded buildings, streets and source. If a download fails (service down, Overpass busy), the adapter logs one warning, the layer is left out and its factor is 1.0 — the pipeline continues. `NRWDataAdapter(download_landuse=False, download_osm_surface=False)` switches them off, `landuse_path=` / `osm_surface_path=` use local files instead, `landuse_wfs=` / `osm_overpass_url=` other endpoints. A state resumed from `STATUS` without the layers gets them from the adapter in the network step.

**Open points.** The factor tables ([`fheat_nrw/civil_cost.py`](src/fheat_nrw/civil_cost.py), [`fheat_nrw/osm_surface.py`](src/fheat_nrw/osm_surface.py)) and the pipe costs are the values of the previous F|Heat version; the source of the pipe costs is still to be documented, and both are to be calibrated with values from practice. topotherm's own cost regression (`a`, `b`) is not yet aligned with `pipe_data.csv`.

### Expansion potential of the pipes

[`expansion_potential(net, source, pipe_info, building_power)`](src/fheat_core/algorithms/expansion.py) tells, for every pipe of a calculated net, how much building power can still be connected at it before a DN on its way to the source would have to go up to the next size, and how many buildings of `building_power` kW that is. It is computed on request from the net and never stored or exported; `mean_building_power(net)` gives the mean power of the connected buildings as a starting value.

A pipe with `n` buildings of together `P` kW keeps its DN while `GLF(n + k) · (P + k · p) < C`, with `C` the capacity of the DN (its `max_volumeFlow` at the temperatures of the net's calculation). The connectable power `ΔP = k · p` is the fixed point of

```
ΔP = C / GLF(n + ΔP / p) − P
```

iterated from `ΔP = 0`: the reserve divided by today's GLF, then again with the GLF of the added buildings, until it no longer changes. It rises to the first `ΔP` at which the pipe is full, so every step stays on the safe side.

- New buildings on a pipe also run through every pipe before it. All pipes are computed with the same `p`, so `expandable_power` [kW] is the smallest `ΔP` along the way to the source and `potential_buildings` is `expandable_power / p`, rounded down.
- House connections get no values; a pipe already beyond the largest DN gets 0.

[`resize_pipes(net, nominal_diameter, pipe_info, supply_temperature, return_temperature, civil_cost_share)`](src/fheat_core/network/resize.py) gives edges another DN by hand, e.g. a larger one to remove such a bottleneck. Possible are the DN the sizing would choose for every edge and the larger ones (`possible_diameters(net, pipe_info)`); a smaller one is refused. Buildings, power and volume flow stay; velocity, heat losses, `pipe_cost` and `civil_cost` follow the new DN with the formulas of the network step, the civil works factor of each edge stays.

### Potential data (Potenzialdaten)

Four optional layers show the planner where solar thermal and geothermal heat could come from. They are information, no input of the network calculation. The adapter provides them (`DataAdapter.fetch_geothermal_shallow`, `fetch_geothermal_blocks`, `fetch_geothermal_deep`, `fetch_solar_thermal`); the `DOWNLOADED` step puts them on the state, and `save_outputs()` writes them:

| State / file | Content | NRW source | Scale |
|---|---|---|---|
| `geothermal_shallow_gdf` / `geothermie_kennwerte` | thermal conductivity for 40/60/80/100 m probes [W/(m·K)], collector extraction at 1800/2400 h [W/m²], a screening value for borehole extraction [W/m], `geothermal_status` | GD NRW, WFS IS GT 50 | 1:50,000 |
| `geothermal_blocks_gdf` / `geothermie_baubloecke` | shallow (ONG) and medium-deep (MTG, 1,000 m probes) geothermal yield per building block, today and 2045 [MWh/a], heating load [kW] | LANUK heat study, municipality ZIP | building block |
| `geothermal_deep_gdf` / `geothermie_tief` | hydrothermal doublet per cell: power [MW] and yield [MWh/a] P10/P50/P90 for the medium-deep and deep reservoir, `deep_potential_mwh`, distance, cell centre as `source_candidate_lat`/`_lon` | LANUK heat study, NRW file (2 MB) | 3 × 3 km raster |
| `solar_thermal_gdf` / `solarthermie_freiflaechen` | ground-mounted solar thermal per Flur: usable area, yield per collector type [MWh/a] and per m² [kWh/(m²·a)], distance to the area and to the nearest building with heat demand | LANUK heat study, NRW file (63 MB) | Flur |

- The buildings get the values of their block (`ong_*`, `mtg_*` — the value of the whole block, repeated on each building, never split; sum per block, not per building) and the shallow values at their location (`borehole_extraction_*`, `collector_extraction_*`). The result summary adds `ong_potential_mwh_a` and `mtg_potential_mwh_a` (blocks of the connected buildings, each once), `deep_potential_max_mwh_a` (largest cell value around the area) and `solar_thermal_flat_plate_mwh_a` / `solar_thermal_area_m2` (all Flure around the area).
- **Not assessed is not zero.** Where the GD has no assessment (gaps, e.g. collectors in built-up areas) or LANUK left a block empty, the value is NaN and the status `not_assessed` (`partly_assessed` when only some GD layers cover a place).
- **Borehole extraction is a screening value, not for design.** The download of the GD NRW has no extraction rate in kWh/(m·a), so it is taken from the conductivity (deepest probe available) with the table of VDI 4640 sheet 2 (2001) for small plants below 30 kW: λ < 1.5 → 25/20 W/m, 1.5–3.0 → 60/50 W/m, > 3.0 → 84/70 W/m (1800/2400 h). The 2019 edition requires a simulation for the design. Own table: `borehole_extraction_path=` (format of [`borehole_extraction.json`](src/fheat_nrw/data/borehole_extraction.json)).
- **Deep geothermal is a rough estimate**; whether a well finds water is unknown (LANUK). One hypothetical plant per cell, so `deep_potential_mwh` is an upper bound. No heat source is placed: put `source_coordinates=(lat, lon)` on a cell yourself if you want.
- Field names, units and checks of the sources: [`docs/potenzialdaten.md`](docs/potenzialdaten.md).

Licences and attribution:

| Source | Licence | Data as of |
|---|---|---|
| Geologischer Dienst NRW, WFS `https://www.wfs.nrw.de/gd/wfs_nw_inspire-gt50` (Informationssystem Geothermie, IS GT 50) | [Datenlizenz Deutschland – Namensnennung 2.0](https://www.govdata.de/dl-de/by-2-0); name "Geologischer Dienst NRW", the service URL and the retrieval date | service, retrieved per run |
| LANUK (formerly LANUV), Wärmestudie NRW, `https://www.opengeodata.nrw.de/produkte/umwelt_klima/energie/kwp/` | [Datenlizenz Deutschland – Zero 2.0](https://www.govdata.de/dl-de/zero-2-0) | 01.09.2024 (files of 18.12.2024 / 20.02.2025) |

Large files are downloaded once into a cache and loaded again only when `index.json` lists a newer file: `NRWDataAdapter(cache_dir=...)`, else the environment variable `FHEAT_CACHE_DIR`, else `~/.cache/fheat`. If a download fails, the adapter logs one warning and leaves the layer out; the pipeline continues. Switches and local files:

```python
NRWDataAdapter(
    city_name="Burgsteinfurt",
    download_geothermal_shallow=False,   # or geothermal_shallow_path= (GeoPackage, layers ews40 … ewk2400), geothermal_wfs=
    download_geothermal_blocks=False,    # or geothermal_blocks_path= (LANUK ONG/MTG file)
    download_geothermal_deep=False,      # or geothermal_deep_path=, geothermal_deep_buffer=5000 (m)
    download_solar_thermal=False,        # or solar_thermal_path=, solar_thermal_buffer=2000 (m)
    download_heat_sources=False,         # or fordatis_path=, wastewater_path=, heat_source_buffers={...}
)
```

### Heat sources (Wärmequellen)

Further optional layers show heat sources near the area, with the values of a climate-neutral 2050 from Manz et al. (2024), "Spatial analysis of renewable and excess heat potentials for climate-neutral district heating in Europe", *Renewable Energy* 224, 120111. Every value comes for two network temperatures: HT (supply 70–90 °C, `heat_ht_mwh`) and LT (60–70 °C, `heat_lt_mwh`). The layers are kept within the maximum distance of the paper and never clipped to the planning area. Like the potential layers they are information only; a point layer carries `source_candidate_lat`/`_lon` as a suggestion; no heat source is placed automatically.

| State / file | Content | Source | Distance |
|---|---|---|---|
| `wastewater_gdf` / `klaeranlagen` | heat taken from the wastewater [kW, MWh/a] and after the heat pump (SPF 2.7 HT / 3.6 LT) | NRW: LANUK list of the municipal plants (real annual wastewater volume × 5 K); elsewhere Hotmaps via Fordatis | 2 km |
| `industrial_heat_gdf` / `industrie_abwaerme` | excess heat at 95 °C (HT) / 55 °C (LT) after the transformation of the industry; name, operator, sector | ISI industrial database via Fordatis, names from Hotmaps | 20 km |
| `waste_incineration_gdf` / `muellverbrennung` | theoretical excess heat and the part a CHP plant recovers (66 % HT / 76 % LT) | peta 5 via Fordatis | 20 km |
| `river_heat_gdf` / `fluesse_seen` | zones of rivers and lakes; one typical heat pump project (30/80/150 MW) per zone | Copernicus via Fordatis | 5 km |
| `hydrothermal_gdf` / `hydrothermie` | 1 km cells where GeoDH maps an aquifer; **not in NRW** (the LANUK doublet raster is far better there) | Fordatis | 15 km |
| `study_dh_areas_gdf` / `waermenetzgebiete_studie` | the study's district heating areas of the municipality, demand 2050 | Fordatis | municipality |
| `study_potentials_df` / table `studie_waermequellen` | the study's supply and utilization potential per source and scenario | Fordatis workbook (needs `[excel]`) | municipality |
| `biogas_gdf` / `biogas_bhkw` | biogas CHP units today (≥ 250 kW, in operation or planned, with a Höchstbemessungsleistung): electricity = HBL × 8,760 h, CHP heat by the unit's KWK power ratio (else 0.45/0.41) | Marktstammdatenregister, export of 01.10.2026 | inside the area |
| `biogas_clusters_gdf` / `biogas_cluster` | units joined by chains of at most 3 km; hull + 500 m, a single unit a 1.5 km circle; sums of power, electricity and heat | from `biogas_gdf` | inside the area |

The result summary adds the sums around the area (`wastewater_*`, `industrial_heat_*`, `waste_incineration_heat_*`, `hydrothermal_*`) and the largest river project (`river_heat_max_mwh_a`); a key is left out when nothing is there. The study table only lists the sources with a supply. The study's petrothermal (a flat estimate) and biomass (a value of the whole NUTS 2 region) are not loaded. Limits and checks against the paper: [`docs/potenzialdaten.md`](docs/potenzialdaten.md), section 9. The biogas layers are today's stock, not 2050, and their heat is an upper bound (part heats the digester or is sold already); method and checks: section 10. The flexible adapter loads the same layers with `FlexDataAdapter(..., download_heat_sources=True, lau_id="DE_05566084")` (off by default).

| Source | Licence |
|---|---|
| Fraunhofer ISI, dataset to Manz et al. (2024), Fordatis, DOI [10.24406/fordatis/280.5](https://doi.org/10.24406/fordatis/280.5) | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |
| Hotmaps Industrial Database (Fraunhofer ISI et al.) | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |
| LANUK, Kommunale Kläranlagen NRW, `https://www.opengeodata.nrw.de/produkte/umwelt_klima/wasser/abwasser/abwasser_kom/` | [Datenlizenz Deutschland – Zero 2.0](https://www.govdata.de/dl-de/zero-2-0) |
| Bundesnetzagentur, Marktstammdatenregister, Gesamtdatenexport `https://download.marktstammdatenregister.de/Stichtag/` | [Datenlizenz Deutschland – Namensnennung 2.0](https://www.govdata.de/dl-de/by-2-0) |
### Temperature year (Temperaturjahr)

The hourly outdoor temperatures only shape the load profile of the `RESULTS` step (profile, tables, charts); network, diameters and costs do not use them. Sources, first match wins:

1. the adapter's series (`DataAdapter.provide_temperature()`),
2. with `FHeatConfig(temperature_source="dwd", year=2023)` the measured year of the nearest DWD station at the centre of the planning area (else of the connected buildings),
3. the bundled example year (place and year unknown; the default, `temperature_source="example"`).

The DWD year comes from DWD Open Data via [wetterdienst](https://github.com/earthobservations/wetterdienst) (extra `[dwd]`, Python ≥ 3.11): the nearest station within 50 km that measured at least 95 % of the year, gaps up to 6 h interpolated, longer ones filled from the next stations; UTC is shifted to CET (UTC+1 all year, like the BDEW profiles). Only finished years are available. If the request fails, the example year is used with a warning and the reason lands in the summary (`temperature_fallback=False` stops the step instead). The summary names the source, station, distance and year and gives the mean and lowest temperature and the heating degree days G20/15 (VDI 3807) for a plausibility check. Leap years have 8784 hours; a series without timestamps (the example year) repeats 28 February.

The retrieved years are cached as CSV (`dwd/` in the cache folder: `FHEAT_CACHE_DIR`, else `~/.cache/fheat`) and do not expire. Attribution: "Datenbasis: Deutscher Wetterdienst" ([DWD terms of use](https://www.dwd.de/EN/service/copyright/copyright_node.html)).

## Installation

Requires **Python ≥ 3.10**. The geospatial stack (GeoPandas, Shapely, etc.) is easiest to install with `conda`/`mamba`, but `pip` works on most platforms.

Not yet published to PyPI, so install from the repository. From the repo root:

```bash
pip install -e .              # core pipeline + flexible adapter (your own data)
pip install -e ".[nrw]"       # + NRW auto-download adapter (owslib, lxml)
pip install -e ".[full]"      # everything: NRW adapter + German holidays
pip install -e ".[full,dev]"  # everything + pytest, for development
pip install -e ".[topotherm]" # + expert network mode; topotherm itself needs a second, editable install — see above
pip install -e ".[excel,plots]" # + Excel export and load profile charts of the results
pip install -e ".[xwp]"       # + XWärmeplan export (xplan-tools; Python 3.13 and system GDAL, see below)
pip install -e ".[dwd]"       # + DWD temperature year at the planning area (wetterdienst; Python >= 3.11)
```

All five import packages — `fheat_core`, `fheat_nrw`, `fheat_flex`, `fheat_eu`, `fheat_de` — ship from the single `fheat` distribution. The extras only add the optional third-party dependencies a given adapter needs: the NRW adapter pulls in `owslib`/`lxml`, and holiday-aware load profiles pull in `workalendar`. All bundled reference data ships as plain text — CSV for tabular tables (pipe catalogue, example temperature year, NRW city index) and JSON for the keyed building-typology lookups (`fheat_nrw/data/*.json`) — so no package reads Excel of its own. The separate `[excel]` extra adds `openpyxl` for the optional `.xlsx` *export* of the result tables (`table_format="xlsx"`) and for reading the study workbook of the heat sources (without it that table is left out), and `[plots]` adds `matplotlib` only for the optional load profile charts (`plot_format`, see below).

## Quick start

### NRW adapter — download and analyse automatically

```python
from fheat_core.config import FHeatConfig
from fheat_core.orchestrator import FHeatOrchestrator
from fheat_nrw.adapter.data_adapter import NRWDataAdapter

adapter = NRWDataAdapter(
    city_name="Burgsteinfurt",              # Stadtteil/Gemarkung; or municipality_name="Steinfurt"
    source_coordinates=(52.1592, 7.3268),   # (lat, lon) WGS84 — heat-source location, optional
    heat_attribute="RW_WW",                 # NRW raw heat-demand column
)

config = FHeatConfig(
    supply_temperature=70.0,
    return_temperature=50.0,
    wld_threshold=500.0,     # kWh/(a·m)
    buffer_distance=50.0,    # m
    heat_demand_basis="calculated",  # or "dataset" (the LANUV RW_WW value)
    year=2022,
    output_dir="./output",
)

orch = FHeatOrchestrator(config=config, adapter=adapter)
orch.run_all()                       # download → adjust → status → network → results
saved = orch.save_outputs()          # writes GeoPackages to output_dir
print(orch.state.result_summary)
```

Running the NRW adapter requires internet access (NRW WFS and ZIP downloads).

The NRW adapter keeps two heat demands per building: the value of the data
source (`heat_demand_dataset`, the LANUV `RW_WW`) and the calculated one
(`heat_demand_calculated`: floor area × specific demand of the construction
age class). `heat_demand_basis` chooses which one the pipeline uses from the
adjust step on (`"calculated"` falls back to the data source value where no
specific demand exists); the thermal power is then heat demand ÷ full load
hours. The QGIS plugin offers the same choice as `RW_WW [kWh/a]` / `WB [kWh/a]`.

The adapter downloads a whole municipality (`municipality_name`) or a whole
district (*Gemarkung*: `city_name`, or the unique `district_key` from the
`schluessel` column of [`cities.csv`](src/fheat_nrw/data/cities.csv)). Some
district names exist in several municipalities (e.g. *Altendorf*); `city_name`
then raises and asks for the `district_key`. `source_coordinates` are only
needed for the network step. `adapter.provide_boundary()` returns the outline
of the downloaded area; [`fheat_nrw.area`](src/fheat_nrw/area.py) cuts a
district out of an already downloaded municipality (`district_boundary`,
`clip_to_boundary`).

### Flexible adapter — bring your own data

This is a feature which was most requested by users outside NRW. The `fheat_flex` adapter takes **user-supplied GeoPackages** and a column mapping onto the canonical schema. The example below assumes you have a directory `data/` with four GeoPackages: `buildings.gpkg`, `streets.gpkg`, `parcels.gpkg`, and `source.gpkg`. The column names in your data can be arbitrary; the adapter maps them onto the canonical schema.

```python
from fheat_flex.adapter.data_adapter import FlexDataAdapter

adapter = FlexDataAdapter(
    buildings_path="data/buildings.gpkg",
    streets_path="data/streets.gpkg",
    parcels_path="data/parcels.gpkg",
    source="data/source.gpkg",
    column_map={                  # map YOUR columns onto the canonical schema
        "waermebedarf":          "heat_demand",       # see fheat_core.columns
        "vollbenutzungsstunden": "full_load_hours",
        "lastprofil":            "load_profile",
    },
)
# ... same FHeatConfig + FHeatOrchestrator usage as above
```

The pipeline uses canonical, language-neutral column names internally (see
`fheat_core/columns.py`). On export, `save_outputs()` translates them back to
German display labels by default (`output_language="de"`); set
`output_language="raw"` to keep the canonical identifiers.

### Result tables

After the `RESULTS` step the state holds, besides `load_profile_df` and
`result_summary`:

- `pipe_summary_df` — one row per nominal diameter of the pipe catalogue
  (unused diameters as zero): number of house connections, house connection
  length, route length, heat loss and heat loss with extra insulation [MWh/a].
- `building_summary_df` — number and heat demand [MWh/a] of the connected
  buildings per load profile (`EFH, MFH, GHA, GMK, GKO`, further profiles
  appended, buildings without a profile in a last row).

`result_summary` additionally reports `total_house_connection_length_m`,
`total_route_length_m` and `total_loss_extra_insulation_mwh_a`, and — when the
net carries pipe costs — the pipe investment (see
[Civil works / road surfaces](#civil-works--road-surfaces)); `pipe_summary_df`
then has a `pipe_cost` column per DN.

`save_outputs()` writes these tables only if `FHeatConfig.table_format` is set:

| `table_format` | Output |
|---|---|
| `None` (default) | no tables — unchanged behaviour |
| `"csv"` | `ergebnisuebersicht.csv`, `rohrmengen.csv`, `gebaeude_lastprofil.csv`, `lastprofil.csv` |
| `"xlsx"` | `fheat-ergebnisse.xlsx` with the sheets `Übersicht`, `Rohre`, `Statistiken`, `Lastprofil`; `Rohre` and `Statistiken` end with a bold `Gesamt` row (requires `pip install "fheat[excel]"`) |

The column labels follow `output_language` like the geodata export.

### Result charts

With `FHeatConfig.plot_format="png"` (or `"svg"`) `save_outputs()` also draws
the four load profile charts of the former QGIS plugin (requires
`pip install "fheat[plots]"`):

| File | Content |
|---|---|
| `Lastprofil` | hourly total heat demand incl. loss and the loss itself [MW] |
| `Lastprofil_geordnet` | the same, hours sorted descending (load duration curve) |
| `Lastprofil_extra_Daemmung` | hourly total and loss with extra insulation |
| `Lastprofil_extra_Daemmung_geordnet` | the same, sorted descending |

With `table_format="xlsx"` the charts are embedded in the `Lastprofil` sheet
as well, next to the data. Chart labels are German.

### XWärmeplan export

F|Heat has two outputs side by side; use one, the other or both:

- **F|Heat output**, `save_outputs()`: every layer and table as above, with
  the canonical column names (`output_language="raw"`) or German labels
  (`"de"`), as GeoPackage, FlatGeobuf, GeoJSON or GML. That GML
  (`output_format="gml"`) is plain OGR-GML of the F|Heat layers, not
  XWärmeplan.
- **XWärmeplan output**, `export_xwaermeplan()`: only classes and attributes
  of the German standard XWärmeplan 0.9.6, each one backed by the XSD or the
  feature catalogue, written through
  [xplan-tools](https://pypi.org/project/xplan-tools/), the library of the
  XLeitstelle. It holds the heat line density as `WP_Waermelinie`, each
  calculated network as `WP_Waermenetz`, the suitability polygons as supply
  areas, each heated building as a `WP_GebaeudeBaublock`, plus `WP_Plan` and
  `WP_Bereich`. Streets, parcels, pipes, the heat source and every value
  without an XWärmeplan attribute stay in the F|Heat output. The file is
  written only when the checks below find nothing.

Plan data F|Heat does not compute comes from `XWPExportConfig`:

```python
import datetime
from fheat_core.export.xwp import XWPExportConfig, export_xwaermeplan

config = XWPExportConfig(
    plan_name="Wärmeplan Steinfurt",
    municipality_name="Steinfurt",
    municipality_key="05566084",          # AGS; the Regionalschlüssel is derived
    base_year=2022,
    decision_date=datetime.date(2026, 6, 30),
)
report = export_xwaermeplan(orch.state, config, "output/waermeplan.gml")
print(report.ok, report.counts, report.issues)
```

A draft without a council decision uses `mode="fragment"`: it writes the area
and the map features for merging into the municipality's plan, whose UUID goes
in `plan_id=` (optional; without it the area refers to an id derived from the
Regionalschlüssel, named in `report.notes`). xplan-tools cannot read a fragment
on its own, because its area points to a plan outside the file.
`networks=[NetworkResult(state, name=...), ...]` exports several networks.

The report collects every finding of four checks:

1. **structure**: xplan-tools validates every feature (mandatory fields, code
   lists) and the references between them;
2. **schema**: the GML against the XSD 0.9.6, offline, when `schema_dir=`
   names a folder with `waermeplan.xsd` and an OASIS XML catalog
   `catalog.xml` for the imported OGC and W3C schemas (as in
   [`tests/fixtures/xwp/xsd-0.9.6/`](tests/fixtures/xwp/xsd-0.9.6/)). F|Heat
   does not ship the XSD, because the repository of the XLeitstelle names no
   licence; without `schema_dir` a note says the GML was not checked;
3. **consistency** with the F|Heat result: geometries inside the plan
   boundary, heat demand of the heat lines and supply areas, network length,
   every heated building in exactly one building block;
4. **conformity**: the conditions of the standard the XSD does not enforce.

Only an export without findings writes the file (`report.file`), so a written
file is verifiably conformant; otherwise `report.issues` holds the findings
and no file is written. `report.notes` holds hints that do not block, e.g.
that building blocks are single buildings, whose publication the municipality
decides (data protection). The export writes GML only: JSON-FG as xplan-tools
writes it does not validate against the JSON schema of XWärmeplan, and the
valid form cannot be read by xplan-tools. Mapping, decisions and limits:
[`docs/xwp_mapping.md`](docs/xwp_mapping.md).

The extra needs **Python 3.13** (xplan-tools 1.26 asks for `>=3.13,<3.14`)
and the GDAL Python binding, which PyPI has no wheel for; its version has to
match the GDAL library.

- Linux (as the CI job `xwp`): `apt install gdal-bin libgdal-dev`, then
  `pip install numpy setuptools wheel`,
  `pip install --no-build-isolation "gdal==$(gdal-config --version)"` and
  `pip install -e ".[xwp]"`.
- Windows: GDAL and its binding from conda-forge, where xplan-tools takes them
  itself (its pixi environment covers `linux-64` and `win-64`), e.g.
  `conda create -n fheat-xwp -c conda-forge python=3.13 gdal`,
  `conda activate fheat-xwp`, then `pip install -e ".[xwp]"`. F|Heat tests
  the extra on Linux only.

Worked examples are in [`examples/`](examples/): [`burgsteinfurt.py`](examples/burgsteinfurt.py) (NRW adapter, runnable with the bundled planning area `planungsgebiet.gpkg`), [`burgsteinfurt_xwp.py`](examples/burgsteinfurt_xwp.py) (the same area as XWärmeplan) and an introductory notebook [`fheat_einfuehrung.ipynb`](examples/fheat_einfuehrung.ipynb). If you want to add an own area of interest for the analysis you can import it by exporting a polygon with using QGIS.

## Tests

```bash
pip install -e ".[dev]"
pytest                       # runs the offline suite
pytest -m network            # only the tests that hit the live services (NRW, DWD)
```

Tests marked `network` require internet and are skipped unless selected with `-m network`; `slow` tests are long-running.

## License

Distributed under the **GNU General Public License v3.0 or later** — see [LICENSE](LICENSE).

The optional extra `[xwp]` installs [xplan-tools](https://gitlab.opencode.de/xleitstelle/xplanung/xplan-tools)
of the XLeitstelle, licensed under the **EUPL-1.2-or-later**. F|Heat neither
ships nor modifies it. The XSD of XWärmeplan is not shipped either (see
[XWärmeplan export](#xwärmeplan-export)).

## Funding notice

![Förderlogo](https://www-backend.fh-muenster.de/iep/fheat/f-heat.connect-start.php.media/73867/Foerdermittelgeber_Logo.jpg.scaled/b159e0672c75c3bc726462d37fb2efd2.jpg)

This project is co-funded by the European Union and the State of North Rhine-Westphalia under the EFRE/JTF Programme NRW 2021–2027, supported by the Ministry of Economic Affairs, Industry, Climate Action and Energy of North Rhine-Westphalia. Project duration: 1 December 2025 – 30 November 2028.
