"""The Burgsteinfurt example as XWaermeplan, offline, and its key figures.

Runs the real pipeline on ``tests/fixtures/xwp/burgsteinfurt_auszug.gpkg``
(LANUV buildings, ALKIS parcels and streets around the example planning
area): NRW building processing, analysis, Dijkstra network from the example
heat source, then ``build_plan``. Used by the golden file test and by the CI
job that reads the GML with XPlan-Tools (scripts/write_xwp_samples.py).
"""
from __future__ import annotations

import datetime
from collections import Counter
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Point

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "xwp" / "burgsteinfurt_auszug.gpkg"
SOURCE_LONLAT = (7.3268, 52.1592)  # heat source of examples/burgsteinfurt.py


def burgsteinfurt_plan():
    """(document, notes) of the example plan."""
    from fheat_core.adapters.base import DataAdapter
    from fheat_core.config import FHeatConfig, XwpConfig, XwpGemeinde, XwpPlanConfig
    from fheat_core.orchestrator import FHeatOrchestrator
    from fheat_core.state import Phase
    from fheat_core.xwp.mapping import NetworkInput, build_plan
    from fheat_nrw.adapter.data_adapter import NRWDataAdapter
    from fheat_nrw.area import boundary_from_parcels
    from fheat_nrw.processing import process_buildings, process_streets

    raw = gpd.read_file(FIXTURE, layer="gebaeude")
    parcels = gpd.read_file(FIXTURE, layer="flurstuecke")
    streets = process_streets(gpd.read_file(FIXTURE, layer="strassen").explode(index_parts=False).reset_index(drop=True))
    db, wg = NRWDataAdapter(source_coordinates=(52.0, 7.0), city_name="X")._load_building_info()
    buildings = process_buildings(raw, parcels, db, wg, "RW_WW")

    class Offline(DataAdapter):
        def fetch_buildings(self):
            return buildings

        def fetch_streets(self):
            return streets

        def fetch_parcels(self):
            return parcels

        def provide_boundary(self):
            return boundary_from_parcels(parcels)

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        orch = FHeatOrchestrator(config=FHeatConfig(output_dir=tmp, year=2022), adapter=Offline())
        orch.run_until(Phase.STATUS)
        crs = orch.state.buildings_gdf.crs
        orch.state.planning_area_gdf = gpd.read_file(FIXTURE, layer="planungsgebiet").to_crs(crs)
        orch.state.source_gdf = gpd.GeoDataFrame(geometry=[Point(*SOURCE_LONLAT)], crs="EPSG:4326").to_crs(crs)
        orch.run_until(Phase.RESULTS)
    state = orch.state
    config = XwpConfig(
        plan=XwpPlanConfig(name="Wärmeplan Burgsteinfurt (Test)", gemeinde=XwpGemeinde("Steinfurt", "055660032032"),
                           beschluss_datum=datetime.date(2026, 6, 30)),
        energy_raster=True,
    )
    return build_plan(state.buildings_gdf, state.wld_gdf, config, parcels=state.parcels_gdf, streets=state.streets_gdf,
                      boundary=Offline().provide_boundary(), data_year=2022,
                      networks=[NetworkInput(state, name="Netz Zentrum", supply_temperature=80.0)])


def key_figures(doc, notes) -> dict:
    """What a change of the mapping should make visible: structure, counts and sums."""
    def of(name):
        return doc.of_type(name)

    def total(objects, attr):
        return round(sum(getattr(o, attr) or 0.0 for o in objects), 1)

    [net] = of("WP_Waermenetz")
    target = next(i for i in of("WP_WaermeinfrastrukturAggregiert") if i.betrachtungszeitpunkt.art.code == "3000")
    base = next(i for i in of("WP_WaermeinfrastrukturAggregiert") if i.betrachtungszeitpunkt.art.code == "1000")
    return {
        "objekte": dict(sorted(Counter(type(f).__xwp__.name for f in doc.features).items())),
        "waermelinien_mwh": total(of("WP_Waermelinie"), "waermeMenge"),
        "waermelinien_m": total(of("WP_Waermelinie"), "laenge"),
        "baubloecke_mwh": total(of("WP_EnergieBaublock"), "waermeMenge"),
        "raster_mwh": total(of("WP_EnergieRaster"), "waermeMenge"),
        "gebaeudetypen": dict(sorted(Counter(f.gebaeudetyp.code for f in of("WP_GebaeudeBaublock")).items())),
        "baualtersklassen": dict(sorted(Counter(f.ueberwiegendBaujahr.code for f in of("WP_GebaeudeBaublock")).items())),
        "netz": {"laenge": net.laenge, "anschluesse": net.anzahlGebaeudeAnschluss, "status": net.status.code},
        "anschluesse_in_bloecken": sum(f.anzahlAnschluesseWaermenetz or 0 for f in of("WP_EnergieBaublock")),
        "gebaeude": {"alle": base.anzahlGebaeude.gebaeude, "wohnen": base.anzahlGebaeude.beheizteWohngebaeude,
                     "nichtwohnen": base.anzahlGebaeude.beheizteNichtwohngebaeude},
        "anschlussquote_prozent": target.gebaeudeAnschlussWaermenetzPlanung.anteil,
        "versorgungsarten": dict(sorted(Counter(f.versorgungsart.code for f in of("WP_WaermeversorgungsgebietZieljahr")).items())),
        "eignung_waermenetz": dict(sorted(Counter(f.eignungWaermenetz.code for f in of("WP_WaermeversorgungsgebietZieljahr")).items())),
        "datenschutz": {"bloecke_verworfen": notes.blocks_dropped, "rasterzellen_verworfen": notes.raster_cells_dropped},
    }
