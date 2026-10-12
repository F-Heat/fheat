"""F|Heat network planning -> XWaermeplan networks, supply areas and suitability (phase 7).

Attribute by attribute as in docs/xwaermeplan/abbildung_planung.md:

* one WP_Waermenetz per calculated network: area = its planning area (a
  buffer around the route without one), status 3000 (potenziell) unless the
  planner says otherwise;
* WP_EnergieBaublock gets the house connections and the network id;
* WP_WaermeinfrastrukturAggregiert for the target year with the planned
  networks and connections;
* a proposal of WP_WaermeversorgungsgebietZieljahr for every building block
  (in a network area -> 1000 Wärmenetzgebiet, otherwise 3000 dezentral) with
  a proposed eignungWaermenetz from heat density and heat line density;
* WP_Eignungspruefung for blocks whose proposal is 4000.

Proposals are counted in the notes so the check report can mark them; the
supplement file overrides them (phase 8).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Optional, Sequence

import geopandas as gpd
import pandas as pd
from shapely.ops import unary_union

from fheat_core import columns as cols
from fheat_core.config import XwpConfig
from fheat_core.selection import connected_mask
from fheat_core.state import PipelineState
from fheat_core.xwp.document import XwpPlanDocument
from fheat_core.xwp.mapping import units
from fheat_core.xwp.mapping.bestand import InventoryContext, MappingNotes, inventory
from fheat_core.xwp.mapping.blocks import polygonal
from fheat_core.xwp.model import Ref
from fheat_core.xwp.model import current as m
from fheat_core.xwp.supplement.reader import Supplement, apply_supplement

ROUTE_BUFFER_M = 10.0  # network area around the route when the network has no planning area
DEFAULT_STATUS = "3000"  # potenziell: a calculation result is no decided network


@dataclass
class NetworkInput:
    """One calculated network and what the planner says about it."""

    state: PipelineState
    name: Optional[str] = None
    status: str = DEFAULT_STATUS  # WP_Status
    betreiber: Optional[str] = None
    inbetriebnahme: Optional[str] = None  # geplanteInbetriebZeit, e.g. "2030" or "2028-2032"
    supply_temperature: Optional[float] = None  # °C; None = not reported

    def __post_init__(self) -> None:
        codes = {e.code for e in m.WP_Status}
        if str(self.status) not in codes:
            raise ValueError(f"NetworkInput.status {self.status!r} is not a code of WP_Status ({sorted(codes)}).")


def build_plan(
    buildings: gpd.GeoDataFrame,
    wld: gpd.GeoDataFrame | None,
    config: XwpConfig,
    *,
    networks: Sequence[NetworkInput] = (),
    parcels: gpd.GeoDataFrame | None = None,
    streets: gpd.GeoDataFrame | None = None,
    boundary=None,
    data_year: int | None = None,
    supplement: Supplement | None = None,
) -> tuple[XwpPlanDocument, MappingNotes]:
    """The whole plan: inventory (phase 6), networks, supply areas and suitability (phase 7)
    and the planner's supplement (phase 8). ``notes.placeholders`` holds the objects the
    supplement template offers for completion."""
    doc, notes, ctx = inventory(buildings, wld, config, parcels=parcels, streets=streets,
                                boundary=boundary, data_year=data_year, link=False)
    nets = _networks(doc, ctx, networks, notes)
    if nets:
        doc.add(_target_year_infrastructure(ctx, nets, config))
    _supply_areas(doc, ctx, nets, wld, config, notes)
    notes.placeholders = _placeholders(ctx, networks, config)
    notes.messages.extend(_messages(notes))
    doc.link_reverse()
    if supplement is not None:
        merged = apply_supplement(doc, supplement)
        notes.supplement_overridden, notes.supplement_added = merged.overridden, merged.added
        notes.supplement_skipped, notes.supplement_issues = merged.skipped, merged.issues
        notes.messages.append(
            f"Ergänzung: {merged.overridden} Objekte überschrieben, {merged.added} hinzugefügt, "
            f"{merged.skipped} nicht übernommen, {len(merged.issues)} Befunde."
        )
    return doc, notes


# --------------------------------------------------------------------------
# networks


@dataclass
class _Net:
    feature: object
    net_id: str
    area: object
    building_ids: set
    route_length: float
    connections: int


def _networks(doc: XwpPlanDocument, ctx: InventoryContext, networks, planning: MappingNotes) -> list[_Net]:
    out: list[_Net] = []
    for i, net in enumerate(networks, start=1):
        net_id = f"N{i:02d}"
        state = net.state
        if state.net_gdf is None or state.net_gdf.empty or state.buildings_gdf is None:
            planning.networks_skipped.append(f"{net.name or net_id}: kein Netzergebnis")
            continue
        edges = state.net_gdf
        route = edges[edges[cols.TYPE] != cols.EDGE_TYPE_HOUSE_CONNECTION] if cols.TYPE in edges.columns else edges
        summary = state.result_summary or {}
        route_length = float(summary.get("total_route_length_m", route[cols.LENGTH].sum()))
        bld = state.buildings_gdf
        connected = bld[connected_mask(bld, state.planning_area_gdf) & (bld[cols.HEAT_DEMAND] > 0)]
        connections = int(summary.get("total_buildings", len(connected)))
        if state.planning_area_gdf is not None and not state.planning_area_gdf.empty:
            area = polygonal(unary_union(list(state.planning_area_gdf.to_crs(bld.crs).geometry)))
        else:
            area = polygonal(unary_union(list(route.geometry)).buffer(ROUTE_BUFFER_M))
        feature = m.WP_Waermenetz(
            id=ctx.ids("WP_Waermenetz", net_id),
            gehoertZuBereich=ctx.in_bereich,
            position=area,
            netzID=net_id,
            name=net.name or f"Wärmenetz {net_id}",
            betreiber=net.betreiber,
            medium=m.WP_Transportmedium.Wasser,
            laenge=units.metres(route_length),
            anzahlGebaeudeAnschluss=connections,
            status=m.WP_Status(net.status),
            temperatur=net.supply_temperature,
            geplanteInbetriebZeit=net.inbetriebnahme,
        )
        doc.add(feature)
        ids = set(connected[cols.BUILDING_ID].astype(int)) if cols.BUILDING_ID in connected.columns else set()
        out.append(_Net(feature, net_id, area, ids, route_length, connections))
    planning.networks = len(out)
    _block_connections(ctx, out)
    return out


def _block_connections(ctx: InventoryContext, nets: list[_Net]) -> None:
    if not nets or cols.BUILDING_ID not in ctx.heated.columns:
        return
    network_of: dict[int, str] = {}
    for net in nets:
        for bid in net.building_ids:
            network_of.setdefault(bid, net.net_id)
    for block in ctx.blocks:
        ids = ctx.heated.loc[block.members, cols.BUILDING_ID].astype(int)
        hits = [network_of[b] for b in ids if b in network_of]
        if not hits:
            continue
        _, energie = ctx.block_features[block.key]
        energie.anzahlAnschluesseWaermenetz = len(hits)
        energie.refWaermeNetzID = Counter(hits).most_common(1)[0][0]


def _target_year_infrastructure(ctx: InventoryContext, nets: list[_Net], config: XwpConfig):
    year = str(config.plan.zieljahr)
    connections = sum(n.connections for n in nets)
    return m.WP_WaermeinfrastrukturAggregiert(
        id=ctx.ids("WP_WaermeinfrastrukturAggregiert", "zieljahr"),
        name=f"Wärmeinfrastruktur {year}",
        betrachtungszeitpunkt=m.WP_Betrachtungszeitpunkt(art=m.WP_ZeitpunktArt.Zieljahr, jahr=year),
        waermenetzePlanung=m.WP_WaermenetzeGesamt(
            anzahlNetze=len(nets), trassenlaenge=units.metres(sum(n.route_length for n in nets)),
        ),
        gebaeudeAnschlussWaermenetzPlanung=m.WP_GebaeudeNetzanschluss(
            anzahl=connections, anteil=units.percent(connections, len(ctx.heated)),
        ),
        gehoertZuPlan=Ref.to(ctx.plan),
    )


# --------------------------------------------------------------------------
# supply areas and suitability


def stage(value: float | None, bounds: tuple[float, float, float]) -> str:
    """WP_Eignungsstufe code for a value and three descending lower bounds."""
    if value is None:
        return "4000"
    for code, bound in zip(("1000", "2000", "3000"), bounds):
        if value >= bound:
            return code
    return "4000"


def _block_line_density(ctx: InventoryContext, wld: gpd.GeoDataFrame | None) -> dict[str, float]:
    """Heat-weighted mean heat line density [MWh/(m·a)] of the streets the block's buildings belong to."""
    if wld is None or wld.empty or cols.CONNECTED_IDS not in wld.columns or cols.BUILDING_ID not in ctx.heated.columns:
        return {}
    density_of: dict[int, float] = {}
    for ids, density in zip(wld[cols.CONNECTED_IDS], wld[cols.HEAT_LINE_DENSITY]):
        if not isinstance(ids, str) or not ids or pd.isna(density):
            continue
        for bid in ids.split(","):
            if bid:
                density_of[int(bid)] = float(density) / units.KWH_PER_MWH
    out = {}
    for block in ctx.blocks:
        rows = ctx.heated.loc[block.members]
        pairs = [(density_of.get(int(b)), h) for b, h in zip(rows[cols.BUILDING_ID], rows[cols.HEAT_DEMAND])]
        pairs = [(d, h) for d, h in pairs if d is not None]
        weight = sum(h for _, h in pairs)
        if weight > 0:
            out[block.key] = sum(d * h for d, h in pairs) / weight
    return out


def _supply_areas(doc, ctx: InventoryContext, nets: list[_Net], wld, config: XwpConfig, planning: MappingNotes):
    network_area = unary_union([n.area for n in nets]) if nets else None
    line_density = _block_line_density(ctx, wld)
    thresholds = config.suitability
    for block in ctx.blocks:
        _, energie = ctx.block_features[block.key]
        density_stage = stage(energie.waermeDichte, thresholds.heat_density)
        wld_value = line_density.get(block.key)
        line_stage = stage(wld_value, thresholds.heat_line_density) if wld_value is not None else density_stage
        suitability = max(density_stage, line_stage)  # the worse stage: higher code
        in_network = network_area is not None and block.geometry.representative_point().within(network_area)
        doc.add(m.WP_WaermeversorgungsgebietZieljahr(
            id=ctx.ids("WP_WaermeversorgungsgebietZieljahr", block.key),
            gehoertZuBereich=ctx.in_bereich,
            position=block.geometry,
            versorgungsart=(m.WP_WaermeversorgungsgebietTyp.Waermenetzgebiet if in_network
                            else m.WP_WaermeversorgungsgebietTyp.GebietDezentrWaerVersorgung),
            waermeMenge=energie.waermeMenge,
            eignungWaermenetz=m.WP_Eignungsstufe(suitability),
        ))
        planning.proposed_supply_areas += 1
        if suitability == "4000":
            doc.add(m.WP_Eignungspruefung(
                id=ctx.ids("WP_Eignungspruefung", block.key),
                gehoertZuBereich=ctx.in_bereich,
                position=block.geometry,
                istUngeeignetWaermenetz=True,
            ))
            planning.proposed_suitability_checks += 1


def _placeholders(ctx: InventoryContext, networks: Sequence[NetworkInput], config: XwpConfig) -> list:
    """Objects the planner completes in the supplement template; not valid on their own."""
    out = []
    for i, net in enumerate(networks, start=1):
        source = net.state.source_gdf
        if source is None or source.empty:
            continue
        crs = net.state.buildings_gdf.crs if net.state.buildings_gdf is not None else source.crs
        geom = unary_union(list(source.to_crs(crs).geometry))
        out.append(m.WP_PotenzialWaermenutzung(
            id=ctx.ids("WP_PotenzialWaermenutzung", f"N{i:02d}"),
            gehoertZuBereich=ctx.in_bereich,
            position=geom,
            hinweis=f"Wärmequelle von {net.name or f'Wärmenetz N{i:02d}'}: Energieträger und Wärmepotenzial bitte eintragen.",
        ))
    if config.large_consumer_mwh is not None:
        big = ctx.heated[ctx.heated[cols.HEAT_DEMAND] >= config.large_consumer_mwh * units.KWH_PER_MWH]
        for label, row in big.iterrows():
            key = int(row[cols.BUILDING_ID]) if cols.BUILDING_ID in big.columns else label
            out.append(m.WP_Grossverbraucher(
                id=ctx.ids("WP_Grossverbraucher", key),
                gehoertZuBereich=ctx.in_bereich,
                position=row.geometry.representative_point(),
                status=m.WP_Status.Bestehend,
                energiebedarf=m.WP_EnergiebedarfArt.Waerme,
            ))
    return out


def _messages(planning: MappingNotes) -> list[str]:
    out = [f"Netz übersprungen: {s}" for s in planning.networks_skipped]
    if planning.proposed_supply_areas:
        out.append(
            f"{planning.proposed_supply_areas} Wärmeversorgungsgebiete (Zieljahr) sind Vorschläge von F|Heat: "
            "Versorgungsart und Eignung für ein Wärmenetz bitte prüfen."
        )
    if planning.proposed_suitability_checks:
        out.append(
            f"{planning.proposed_suitability_checks} Eignungsprüfungen (ungeeignet für ein Wärmenetz) sind Vorschläge."
        )
    return out
