"""F|Heat analysis results -> XWaermeplan inventory (Bestand) and potential.

Attribute by attribute as in docs/xwaermeplan/abbildung_bestand.md:
WP_Plan, WP_Bereich, WP_Waermelinie, WP_GebaeudeBaublock, WP_EnergieBaublock,
WP_EnergieRaster (optional) and WP_WaermeinfrastrukturAggregiert for the
base year. WP_Energiebilanz is not built: it requires the final energy per
energy carrier, which F|Heat does not know (supplement file, phase 8).
"""
from __future__ import annotations

import datetime
import math
import uuid
from collections import Counter
from dataclasses import dataclass, field

import geopandas as gpd
import pandas as pd
from pyproj import Transformer
from shapely.geometry import MultiLineString, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform, unary_union
from shapely.validation import make_valid

from fheat_core import columns as cols
from fheat_core.config import XwpConfig
from fheat_core.xwp.document import XwpPlanDocument
from fheat_core.xwp.mapping import units
from fheat_core.xwp.mapping.age_class import assign_age_classes, to_upper
from fheat_core.xwp.mapping.blocks import Block, build_blocks, merge_small_blocks, polygonal
from fheat_core.xwp.mapping.building_type import assign_building_types
from fheat_core.xwp.model import Ref
from fheat_core.xwp.model import current as m

BOUNDARY_BUFFER_M = 50.0  # outline around the buildings when the adapter has none
RASTER_SIZE_M = 100


@dataclass
class InventoryContext:
    """Intermediate results phase 7 builds on."""

    plan: object
    in_bereich: Ref
    ids: "Ids"
    heated: pd.DataFrame  # buildings with heat demand, plus _type and _age
    blocks: list[Block]
    block_features: dict[str, tuple]  # block key -> (WP_GebaeudeBaublock, WP_EnergieBaublock)
    area: BaseGeometry
    base_year: int | None


@dataclass
class MappingNotes:
    """What the mapping left out, for the check report (phase 9)."""

    blocks_dropped: int = 0
    buildings_in_dropped_blocks: int = 0
    raster_cells_dropped: int = 0
    lines_without_demand: int = 0
    # phase 7
    networks: int = 0
    networks_skipped: list[str] = field(default_factory=list)
    proposed_supply_areas: int = 0
    proposed_suitability_checks: int = 0
    messages: list[str] = field(default_factory=list)


class Ids:
    """Stable UUIDs: the same plan and object give the same id on every export."""

    def __init__(self, plan_name: str, municipality_key: str | None):
        self.namespace = uuid.uuid5(uuid.NAMESPACE_URL, f"https://fheat.de/xwp/{municipality_key or ''}/{plan_name}")

    def __call__(self, *parts) -> str:
        return str(uuid.uuid5(self.namespace, "/".join(str(p) for p in parts)))


def build_inventory(
    buildings: gpd.GeoDataFrame,
    wld: gpd.GeoDataFrame | None,
    config: XwpConfig,
    *,
    parcels: gpd.GeoDataFrame | None = None,
    streets: gpd.GeoDataFrame | None = None,
    boundary: BaseGeometry | gpd.GeoDataFrame | None = None,
    data_year: int | None = None,
) -> tuple[XwpPlanDocument, MappingNotes]:
    """Plan document with plan, area, heat lines, building blocks and base year figures."""
    doc, notes, _ = inventory(buildings, wld, config, parcels=parcels, streets=streets,
                              boundary=boundary, data_year=data_year)
    return doc, notes


def inventory(
    buildings: gpd.GeoDataFrame,
    wld: gpd.GeoDataFrame | None,
    config: XwpConfig,
    *,
    parcels: gpd.GeoDataFrame | None = None,
    streets: gpd.GeoDataFrame | None = None,
    boundary: BaseGeometry | gpd.GeoDataFrame | None = None,
    data_year: int | None = None,
    link: bool = True,
) -> tuple[XwpPlanDocument, MappingNotes, InventoryContext]:
    """:func:`build_inventory` plus the intermediate results; ``link=False`` leaves reverse links to the caller."""
    plan_cfg = config.plan
    ids = Ids(plan_cfg.name, plan_cfg.gemeinde.regional_schluessel12)
    notes = MappingNotes()
    doc = XwpPlanDocument(id=ids("dokument"))
    area = _boundary(boundary, buildings)
    base_year = plan_cfg.basisjahr or data_year

    plan = _plan(config, area, base_year, ids)
    bereich = m.WP_Bereich(
        id=ids("WP_Bereich", 0), nummer=0, name=f"Geltungsbereich {plan_cfg.gemeinde.name}",
        geltungsbereich=area, gehoertZuPlan=Ref.to(plan),
    )
    doc.add(plan, bereich)
    in_bereich = Ref.to(bereich)

    if wld is not None:
        doc.add(*_heat_lines(wld, in_bereich, ids, notes))

    heated = buildings[buildings[cols.HEAT_DEMAND] > 0].copy()
    heated["_type"] = (
        heated[cols.XWP_BUILDING_TYPE].astype("string").fillna("9999")
        if cols.XWP_BUILDING_TYPE in heated.columns else assign_building_types(heated)
    )
    heated["_age"] = assign_age_classes(heated, config.construction_year_sources)

    blocks = build_blocks(heated, parcels=parcels, streets=streets, boundary=area)
    blocks, dropped = merge_small_blocks(blocks, config.privacy_min_buildings)
    notes.blocks_dropped = len(dropped)
    notes.buildings_in_dropped_blocks = sum(b.n for b in dropped)
    if dropped:
        notes.messages.append(
            f"{len(dropped)} Baublock/Baublöcke mit zusammen {notes.buildings_in_dropped_blocks} Gebäuden "
            f"unter der Datenschutzschwelle ({config.privacy_min_buildings}) und ohne Nachbarn: nicht ausgegeben."
        )
    block_features = {}
    for block in blocks:
        features = _block_features(block, heated, in_bereich, ids)
        block_features[block.key] = tuple(features)
        doc.add(*features)

    if config.energy_raster:
        doc.add(*_raster(heated, config.privacy_min_buildings, in_bereich, ids, notes))

    if base_year is not None:
        doc.add(_infrastructure(heated, buildings, base_year, plan, ids))
    else:
        notes.messages.append("Kein Basisjahr: WP_WaermeinfrastrukturAggregiert für das Basisjahr fehlt.")

    if link:
        doc.link_reverse()
    context = InventoryContext(plan, in_bereich, ids, heated, blocks, block_features, area, base_year)
    return doc, notes, context


# --------------------------------------------------------------------------
# plan and area


def _boundary(boundary, buildings: gpd.GeoDataFrame) -> BaseGeometry:
    if isinstance(boundary, (gpd.GeoDataFrame, gpd.GeoSeries)):
        geom = unary_union(list(boundary.geometry)) if not boundary.empty else None
    else:
        geom = boundary
    if geom is None or geom.is_empty:
        geom = unary_union(list(buildings.geometry)).buffer(BOUNDARY_BUFFER_M)
    return polygonal(make_valid(geom) if not geom.is_valid else geom)


def _plan(config: XwpConfig, area: BaseGeometry, base_year: int | None, ids: Ids):
    c = config.plan

    def gemeinde(g):
        return m.WP_Gemeinde(name=g.name, regionalSchluessel12=g.regional_schluessel12,
                             regionalSchluessel9=g.regional_schluessel9)

    plan = m.WP_Plan(
        id=ids("WP_Plan"),
        name=c.name,
        beschreibung=c.beschreibung,
        planungsverantwortlicheStelle=gemeinde(c.gemeinde),
        verfahrensart=m.WP_VerfahrenArt(c.verfahrensart),
        beteiligteGemeinden=[gemeinde(g) for g in c.beteiligte_gemeinden],
        gesetzlicheGrundlage=m.WP_GesetzlicheGrundlage(c.gesetzliche_grundlage),
        foerderkennzeichen=c.foerderkennzeichen,
        zieljahr=str(c.zieljahr),
        basisJahrDatenerfassung=str(base_year) if base_year is not None else None,
        aufstellungsbeschlussDatum=c.aufstellungsbeschluss_datum,
        beschlussDatum=c.beschluss_datum,
        technischePlanerstellung=list(c.technische_planerstellung),
        externeReferenz=[
            m.WP_ExterneReferenz(
                art=m.WP_ExterneReferenzTyp(r.art) if r.art else None,
                referenzName=r.name, referenzURL=r.url, beschreibung=r.beschreibung,
            )
            for r in c.externe_referenzen
        ],
        raeumlicherGeltungsbereich=area,
    )
    for key, value in c.extra.items():
        setattr(plan, key, _coerce(m.WP_Plan.__xwp__.attr(key), value))
    return plan


def _coerce(attr, value):
    """Values of XwpPlanConfig.extra (JSON-like) to model values."""
    if attr.kind == "enum":
        enum_cls = m.ENUMS[attr.type]
        return [enum_cls(str(v)) for v in value] if attr.many else enum_cls(str(value))
    if attr.kind == "date" and isinstance(value, str):
        return datetime.date.fromisoformat(value)
    if attr.kind == "datatype":
        cls = m.CLASSES[attr.type]
        return [cls(**v) for v in value] if attr.many else cls(**value)
    return value


# --------------------------------------------------------------------------
# heat lines


def _heat_lines(wld: gpd.GeoDataFrame, in_bereich: Ref, ids: Ids, notes: MappingNotes) -> list:
    out = []
    for i, row in enumerate(wld.itertuples(index=False)):
        demand = getattr(row, cols.HEAT_DEMAND, 0.0) or 0.0
        length = getattr(row, cols.LENGTH, 0.0) or 0.0
        geom = row.geometry
        if not demand or not length or geom is None or geom.is_empty or (isinstance(demand, float) and math.isnan(demand)):
            notes.lines_without_demand += 1
            continue
        out.append(m.WP_Waermelinie(
            id=ids("WP_Waermelinie", i),
            gehoertZuBereich=in_bereich,
            position=geom if isinstance(geom, MultiLineString) else MultiLineString([geom]),
            waermeMenge=units.mwh(demand),
            waermelinienDichte=units.mwh_per_m(demand / length),
            laenge=units.metres(length),
        ))
    return out


# --------------------------------------------------------------------------
# building blocks


def _prevailing(codes: list[str]) -> str:
    """Most frequent code; a tie within one upper category gives that category, otherwise 9999."""
    counts = Counter(codes).most_common()
    top = [c for c, n in counts if n == counts[0][1]]
    if len(top) == 1:
        return top[0]
    uppers = {c[:1] for c in top}
    return f"{uppers.pop()}000" if len(uppers) == 1 and "9" not in uppers else "9999"


def _block_features(block: Block, heated: pd.DataFrame, in_bereich: Ref, ids: Ids) -> list:
    rows = heated.loc[block.members]
    ages = list(rows["_age"])
    if any(len(a) == 4 and a not in ("5000", "9999") for a in ages):
        ages = [to_upper(a) for a in ages]  # mixed detail: compare on upper classes
    n = len(ages)
    distribution = [
        m.WP_BaujahrAngaben(baualtersklasse=m.WP_Baualtersklasse(code), anteil=units.percent(k, n))
        for code, k in sorted(Counter(ages).items())
    ]
    area_m2 = block.geometry.area
    heat_kwh = float(rows[cols.HEAT_DEMAND].sum())
    floor = rows[cols.FLOOR_AREA].sum() if cols.FLOOR_AREA in rows.columns else None
    common = dict(gehoertZuBereich=in_bereich, position=block.geometry, baublockId=block.key)
    gebaeude = m.WP_GebaeudeBaublock(
        id=ids("WP_GebaeudeBaublock", block.key),
        gebaeudetyp=m.WP_GebaeudeTyp(_prevailing(list(rows["_type"]))),
        ueberwiegendBaujahr=m.WP_Baualtersklasse(_prevailing(ages)),
        verteilungBaujahr=distribution,
        nutzflaeche=units.hectares(floor) if floor is not None and floor == floor and floor > 0 else None,
        **common,
    )
    energie = m.WP_EnergieBaublock(
        id=ids("WP_EnergieBaublock", block.key),
        waermeMenge=units.mwh(heat_kwh),
        waermeDichte=units.mwh_per_ha(heat_kwh, area_m2),
        **common,
    )
    return [gebaeude, energie]


# --------------------------------------------------------------------------
# energy raster (INSPIRE 100 m grid, EPSG:3035)


def _raster(heated: pd.DataFrame, min_buildings: int, in_bereich: Ref, ids: Ids, notes: MappingNotes) -> list:
    to_laea = Transformer.from_crs(25832, 3035, always_xy=True)
    back = Transformer.from_crs(3035, 25832, always_xy=True).transform
    pts = heated.geometry.representative_point()
    xs, ys = to_laea.transform(pts.x.values, pts.y.values)
    cells: dict[tuple[int, int], list] = {}
    for label, x, y in zip(heated.index, xs, ys):
        key = (int(y // RASTER_SIZE_M) * RASTER_SIZE_M, int(x // RASTER_SIZE_M) * RASTER_SIZE_M)
        cells.setdefault(key, []).append(label)
    out = []
    for (north, east), labels in sorted(cells.items()):
        if len(labels) < min_buildings:
            notes.raster_cells_dropped += 1
            continue
        cell = box(east, north, east + RASTER_SIZE_M, north + RASTER_SIZE_M)
        heat_kwh = float(heated.loc[labels, cols.HEAT_DEMAND].sum())
        out.append(m.WP_EnergieRaster(
            id=ids("WP_EnergieRaster", north, east),
            gehoertZuBereich=in_bereich,
            position=Polygon(transform(back, cell).exterior.coords),
            rasterID=f"CRS3035RES{RASTER_SIZE_M}mN{north}E{east}",
            waermeMenge=units.mwh(heat_kwh),
            waermeDichte=units.mwh_per_ha(heat_kwh, RASTER_SIZE_M * RASTER_SIZE_M),
        ))
    if notes.raster_cells_dropped:
        notes.messages.append(
            f"{notes.raster_cells_dropped} Rasterzellen unter der Datenschutzschwelle ({min_buildings}) nicht ausgegeben."
        )
    return out


# --------------------------------------------------------------------------
# aggregated figures of the base year


def _infrastructure(heated: pd.DataFrame, buildings: pd.DataFrame, year: int, plan, ids: Ids):
    residential = heated["_type"].str.startswith("1").sum()
    return m.WP_WaermeinfrastrukturAggregiert(
        id=ids("WP_WaermeinfrastrukturAggregiert", "basisjahr"),
        name=f"Wärmeinfrastruktur {year}",
        betrachtungszeitpunkt=m.WP_Betrachtungszeitpunkt(art=m.WP_ZeitpunktArt.Basisjahr, jahr=str(year)),
        anzahlGebaeude=m.WP_GebaeudeAnzahl(
            gebaeude=int(len(buildings)),
            beheizteWohngebaeude=int(residential),
            beheizteNichtwohngebaeude=int(len(heated) - residential),
        ),
        gehoertZuPlan=Ref.to(plan),
    )
