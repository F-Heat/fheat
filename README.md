# F|Heat

**F|Heat** is a Python toolkit for **district-heating network planning from geodata**. Given buildings, streets, parcels and a heat-source location, it computes heat-line density (*Wärmeliniendichte*, WLD), derives suitability polygons (*Eignungspolygone*), dimensions a pipe network (diameters, flow velocities, heat losses, simultaneity factor / *Gleichzeitigkeitsfaktor*), and produces an hourly load profile, a result summary and result tables (pipe quantities per diameter, connected buildings per load profile).

> Domain terms are German because the tool targets German municipal heat planning (*kommunale Wärmeplanung*), in particular the federal state of North Rhine-Westphalia (NRW).

## Packages

The repository is a monorepo of three installable packages:

| Package | Role |
|---|---|
| [`fheat_core`](src/fheat_core/) | Adapter-agnostic pipeline: orchestrator, data schemas, geometry/network/SLP algorithms, and the step functions. This is the engine. |
| [`fheat_nrw`](src/fheat_nrw/) | Adapter that **downloads NRW open geodata** (building heat model via OpenGeoData NRW, cadastral parcels via the ALKIS WFS) and processes it into schema-compliant frames. |
| [`fheat_flex`](src/fheat_flex/) | Adapter for **user-supplied** GeoPackages, with a column mapping onto the core schema. Use this when you bring your own data. |

All three are import packages shipped from a single distribution named `fheat` (see [Installation](#installation)). The whole logic is derived from the former QGIS plugin to adress the flexibility with other applications.

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
```

All three import packages — `fheat_core`, `fheat_nrw`, `fheat_flex` — ship from the single `fheat` distribution. The extras only add the optional third-party dependencies a given adapter needs: the NRW adapter pulls in `owslib`/`lxml`, and holiday-aware load profiles pull in `workalendar`. All bundled reference data ships as plain text — CSV for tabular tables (pipe catalogue, example temperature year, NRW city index) and JSON for the keyed building-typology lookups (`fheat_nrw/data/*.json`) — so no package reads Excel. The separate `[excel]` extra adds `openpyxl` only for the optional `.xlsx` *export* of the result tables (`table_format="xlsx"`), and `[plots]` adds `matplotlib` only for the optional load profile charts (`plot_format`, see below).

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

Worked examples are in [`examples/`](examples/): [`burgsteinfurt.py`](examples/burgsteinfurt.py) (NRW adapter, runnable with the bundled planning area `planungsgebiet.gpkg`) and an introductory notebook [`fheat_einfuehrung.ipynb`](examples/fheat_einfuehrung.ipynb). If you want to add an own area of interest for the analysis you can import it by exporting a polygon with using QGIS.

## Tests

```bash
pip install -e ".[dev]"
pytest                       # runs the offline suite
pytest -m "not network"      # explicitly skip tests that hit the live NRW services
```

Tests marked `network` require internet; `slow` tests are long-running.

## License

Distributed under the **GNU General Public License v3.0 or later** — see [LICENSE](LICENSE).

## Funding notice

![Förderlogo](https://www-backend.fh-muenster.de/iep/fheat/f-heat.connect-start.php.media/73867/Foerdermittelgeber_Logo.jpg.scaled/b159e0672c75c3bc726462d37fb2efd2.jpg)

This project is co-funded by the European Union and the State of North Rhine-Westphalia under the EFRE/JTF Programme NRW 2021–2027, supported by the Ministry of Economic Affairs, Industry, Climate Action and Energy of North Rhine-Westphalia. Project duration: 1 December 2025 – 30 November 2028.
