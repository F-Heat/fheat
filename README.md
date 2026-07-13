# F|Heat

**F|Heat** is a Python toolkit for **district-heating network planning from geodata**. Given buildings, streets, parcels and a heat-source location, it computes heat-line density (*Wärmeliniendichte*, WLD), derives suitability polygons (*Eignungspolygone*), dimensions a pipe network (diameters, flow velocities, heat losses, simultaneity factor / *Gleichzeitigkeitsfaktor*), and produces an hourly load profile and a result summary.

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
DataAdapter ──fetch──▶ PipelineState ──▶ FHeatOrchestrator ──▶ outputs (.gpkg + summary)
(source of data)        (frames)          (runs the phases)
```

- A **`DataAdapter`** (`fheat_nrw` or `fheat_flex`) supplies four schema-compliant GeoDataFrames: `buildings`, `streets`, `parcels`, `source`. All region- and source-specific logic lives in the adapter.
- **`FHeatConfig`** holds only *calculation* parameters (temperatures, WLD threshold, buffer distance, SLP year/class).
- **`FHeatOrchestrator`** runs the pipeline phase by phase, and can resume from any phase:

  | Phase | Step | Produces |
  |---|---|---|
  | `INITIAL` | download | input frames from the adapter |
  | `DOWNLOADED` | adjust | cleaned geometry, schema-validated frames |
  | `ADJUSTED` | status | heat-line density + suitability polygons |
  | `STATUS` | network | shortest-path pipe network with sizing & losses |
  | `NETWORK` | results | hourly load profile + result summary |

Adapters must produce data conforming to the contracts in [`schemas.py`](src/fheat_core/schemas.py); the core validates against the same schemas as it goes.

## Installation

Requires **Python ≥ 3.10**. The geospatial stack (GeoPandas, Shapely, etc.) is easiest to install with `conda`/`mamba`, but `pip` works on most platforms.

Not yet published to PyPI, so install from the repository. From the repo root:

```bash
pip install -e .              # core pipeline + flexible adapter (your own data)
pip install -e ".[nrw]"       # + NRW auto-download adapter (owslib, lxml)
pip install -e ".[full]"      # everything: NRW adapter + German holidays
pip install -e ".[full,dev]"  # everything + pytest, for development
```

All three import packages — `fheat_core`, `fheat_nrw`, `fheat_flex` — ship from the single `fheat` distribution. The extras only add the optional third-party dependencies a given adapter needs: the NRW adapter pulls in `owslib`/`lxml`, and holiday-aware load profiles pull in `workalendar`. All bundled reference data ships as plain text — CSV for tabular tables (pipe catalogue, example temperature year, NRW city index) and JSON for the keyed building-typology lookups (`fheat_nrw/data/*.json`) — so no package reads Excel. The separate `[excel]` extra adds `openpyxl` only for the optional `.xlsx` *export* in the examples.

## Quick start

### NRW adapter — download and analyse automatically

```python
from fheat_core.config import FHeatConfig
from fheat_core.orchestrator import FHeatOrchestrator
from fheat_nrw.adapter.data_adapter import NRWDataAdapter

adapter = NRWDataAdapter(
    city_name="Burgsteinfurt",              # Stadtteil/Gemarkung
    source_coordinates=(52.1592, 7.3268),   # (lat, lon) WGS84 — heat-source location
    heat_attribute="RW_WW",                 # NRW raw heat-demand column
)

config = FHeatConfig(
    supply_temperature=70.0,
    return_temperature=50.0,
    wld_threshold=500.0,     # kWh/(a·m)
    buffer_distance=50.0,    # m
    year=2022,
    output_dir="./output",
)

orch = FHeatOrchestrator(config=config, adapter=adapter)
orch.run_all()                       # download → adjust → status → network → results
saved = orch.save_outputs()          # writes GeoPackages to output_dir
print(orch.state.result_summary)
```

Running the NRW adapter requires internet access (NRW WFS and ZIP downloads).

### Flexible adapter — bring your own data

This is a feature which was most requested by users outside NRW. The `fheat_flex` adapter takes **user-supplied GeoPackages** and a column mapping onto the canonical schema. The example below assumes you have a directory `data/` with four GeoPackages: `buildings.gpkg`, `streets.gpkg`, `parcels.gpkg`, and `source.gpkg`. The column names in your data can be arbitrary; the adapter maps them onto the canonical schema.

```python
from fheat_flex.adapter.data_adapter import FlexDataAdapter

adapter = FlexDataAdapter(
    buildings_path="data/buildings.gpkg",
    streets_path="data/streets.gpkg",
    parcels_path="data/parcels.gpkg",
    source="data/source.gpkg",
    column_map={                      # map YOUR columns onto the canonical schema
        "wb_wld":                "heat_demand",       # see fheat_core.columns
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
