from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any, ClassVar, Optional


class NetworkMode(str, Enum):
    """Which algorithm generates the pipe network in the NETWORK phase."""

    PHASE0 = "phase0"   # shortest path (Dijkstra) — historical default
    EXPERT = "expert"   # topotherm single-time-step MILP


@dataclass
class TopothermConfig:
    """Parameters for the expert mode (topotherm STS).

    Only relevant when ``FHeatConfig.network_mode == NetworkMode.EXPERT``.
    Supply/return temperature are NOT repeated here — they are taken from
    :class:`FHeatConfig` so there is exactly one source of truth.
    """

    # --- what to optimise -------------------------------------------------
    optimization_mode: str = "economic"   # "economic" | "forced"

    # --- solver -----------------------------------------------------------
    solver: str = "highs"
    mip_gap: float = 1e-4
    time_limit: int = 10_000

    # --- physical boundary conditions ------------------------------------
    ambient_temperature: float = -12.0        # °C, design outdoor temperature
    ground_thermal_conductivity: float = 2.4  # W/(m·K)
    max_pressure_loss: float = 250.0          # Pa/m
    pipe_depth: float = 2.0                   # m
    pipe_roughness: float = 1e-5              # m

    # --- geometry preprocessing ------------------------------------------
    connection_buffer: float = 2.5            # m, merges nearby connection nodes

    # --- economics --------------------------------------------------------
    heat_price: float = 120e-3      # €/kW  (revenue)
    source_price: float = 80e-3     # €/kW  (variable production cost)
    source_c_inv: float = 0.0       # €/kW  (source investment)
    source_c_irr: float = 0.08      # interest rate, sources
    source_lifetime: float = 40.0   # years
    source_max_power: float = 1e6   # kW
    pipes_c_irr: float = 0.08       # interest rate, piping
    pipes_lifetime: float = 40.0    # years

    # --- escape hatch -----------------------------------------------------
    settings_yaml: Optional[str] = None
    """Path to a native topotherm ``config.yaml``. Loaded first; the fields
    above then override it. Use only for parameters not exposed here."""

    _ALLOWED_MODES: ClassVar[frozenset] = frozenset({"economic", "forced"})

    def __post_init__(self) -> None:
        if self.optimization_mode not in self._ALLOWED_MODES:
            raise ValueError(
                f"optimization_mode '{self.optimization_mode}' is not allowed. "
                f"Allowed values: {sorted(self._ALLOWED_MODES)}"
            )
        if self.mip_gap < 0:
            raise ValueError("mip_gap must be >= 0.")
        if self.time_limit <= 0:
            raise ValueError("time_limit must be > 0.")
        if self.connection_buffer <= 0:
            raise ValueError("connection_buffer must be > 0.")


@dataclass
class FHeatConfig:
    """Pipeline parameters.

    Contains only calculation parameters, NOT data-source parameters.
    Data-source-specific configuration (paths, column mappings, regional
    parameters such as municipality name) belongs in the adapter constructor.
    """

    # Network parameters
    supply_temperature: float = 80.0
    return_temperature: float = 50.0

    # Which algorithm builds the network
    network_mode: str = NetworkMode.PHASE0.value
    topotherm: Optional[TopothermConfig] = None

    # WLD / suitability polygons
    wld_threshold: float = 500.0
    buffer_distance: float = 50.0

    # Which heat demand of the buildings the pipeline uses, when the adapter
    # provides both: "calculated" (floor area × specific demand of the age
    # class, the data source value where none can be calculated) or "dataset"
    # (the value of the data source, for NRW the LANUV RW_WW).
    heat_demand_basis: str = "calculated"

    # Share of the standardised pipe costs that is civil works (trench,
    # backfill, surface restoration). Only this share is multiplied by the
    # civil works factor of the road surface; 0 = the surface has no effect.
    civil_cost_share: float = 0.60

    # BDEW SLP parameters (German standard load profile)
    building_class: int = 3      # NRW default per BGW 2006
    wind_class: int = 1
    year: int = 2022

    # Output
    output_dir: str = "./output"
    output_format: str = "gpkg"
    output_language: str = "de"  # "de" = German column labels, "raw" = canonical IDs
    # Result tables (summary, pipes per DN, buildings per load profile, load
    # profile): None = not written, "csv" = one file each, "xlsx" = one workbook
    # (needs the [excel] extra).
    table_format: Optional[str] = None
    # Load profile charts (hourly and sorted, normal and extra insulation):
    # None = not drawn, "png" / "svg" = one file each (needs the [plots]
    # extra). With table_format="xlsx" they are also embedded in the workbook.
    plot_format: Optional[str] = None

    _ALLOWED_FORMATS: ClassVar[frozenset] = frozenset({"gpkg", "fgb", "geojson", "gml"})
    _ALLOWED_LANGUAGES: ClassVar[frozenset] = frozenset({"de", "raw"})
    _ALLOWED_TABLE_FORMATS: ClassVar[frozenset] = frozenset({None, "csv", "xlsx"})
    _ALLOWED_PLOT_FORMATS: ClassVar[frozenset] = frozenset({None, "png", "svg"})
    _ALLOWED_HEAT_DEMAND_BASES: ClassVar[frozenset] = frozenset({"calculated", "dataset"})

    def __post_init__(self) -> None:
        if self.supply_temperature <= self.return_temperature:
            raise ValueError(
                f"supply_temperature ({self.supply_temperature} °C) must be greater than "
                f"return_temperature ({self.return_temperature} °C)."
            )
        if self.output_format not in self._ALLOWED_FORMATS:
            raise ValueError(
                f"output_format '{self.output_format}' is not allowed. "
                f"Allowed formats: {sorted(self._ALLOWED_FORMATS)}"
            )
        if self.output_language not in self._ALLOWED_LANGUAGES:
            raise ValueError(
                f"output_language '{self.output_language}' is not allowed. "
                f"Allowed values: {sorted(self._ALLOWED_LANGUAGES)}"
            )
        if self.table_format not in self._ALLOWED_TABLE_FORMATS:
            raise ValueError(
                f"table_format '{self.table_format}' is not allowed. "
                "Allowed values: None, 'csv', 'xlsx'"
            )
        if self.plot_format not in self._ALLOWED_PLOT_FORMATS:
            raise ValueError(
                f"plot_format '{self.plot_format}' is not allowed. "
                "Allowed values: None, 'png', 'svg'"
            )
        if self.heat_demand_basis not in self._ALLOWED_HEAT_DEMAND_BASES:
            raise ValueError(
                f"heat_demand_basis '{self.heat_demand_basis}' is not allowed. "
                f"Allowed values: {sorted(self._ALLOWED_HEAT_DEMAND_BASES)}"
            )

        if not 0.0 <= self.civil_cost_share <= 1.0:
            raise ValueError(
                f"civil_cost_share ({self.civil_cost_share}) must be between 0 and 1."
            )

        allowed_modes = {m.value for m in NetworkMode}
        if self.network_mode not in allowed_modes:
            raise ValueError(
                f"network_mode '{self.network_mode}' is not allowed. "
                f"Allowed values: {sorted(allowed_modes)}"
            )
        if self.network_mode == NetworkMode.EXPERT.value and self.topotherm is None:
            self.topotherm = TopothermConfig()


# ============================================================
# XWaermeplan export
# ============================================================


@dataclass
class XwpGemeinde:
    """A municipality (WP_Gemeinde): name and official regional keys."""

    name: str
    regional_schluessel12: Optional[str] = None  # ARS, 12 digits
    regional_schluessel9: Optional[str] = None   # Verband/Samtgemeinde, 9 digits

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("XwpGemeinde.name must not be empty.")
        for attr, n in (("regional_schluessel12", 12), ("regional_schluessel9", 9)):
            value = getattr(self, attr)
            if value is not None and not (len(value) == n and value.isdigit()):
                raise ValueError(f"XwpGemeinde.{attr} must be {n} digits, got {value!r}.")


@dataclass
class XwpExterneReferenz:
    """A document or web resource of the plan (WP_ExterneReferenz)."""

    name: str
    url: str
    art: Optional[str] = None  # code of WP_ExterneReferenzTyp, e.g. "1000" = Wärmeplan als PDF
    beschreibung: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.name or not self.url:
            raise ValueError("XwpExterneReferenz needs name and url.")
        if self.art is not None:
            _check_code("WP_ExterneReferenzTyp", self.art, "XwpExterneReferenz.art")


@dataclass
class XwpPlanConfig:
    """Plan metadata of WP_Plan that F|Heat cannot derive from its data.

    Codes are those of the XWaermeplan enumerations (strings such as "1000").
    ``extra`` sets any further WP_Plan attribute by its XWaermeplan name
    (e.g. ``{"nummer": "WP-2026-01", "istFortschreibung": True}``).
    """

    name: str
    gemeinde: XwpGemeinde
    beschluss_datum: Optional[date] = None  # required by WP_Plan; the check report flags it while unknown
    aufstellungsbeschluss_datum: Optional[date] = None
    verfahrensart: str = "1000"          # WP_VerfahrenArt: Regelverfahren
    gesetzliche_grundlage: str = "1000"  # WP_GesetzlicheGrundlage: WPG
    zieljahr: int = 2045
    basisjahr: Optional[int] = None      # basisJahrDatenerfassung; None = year of the data
    beteiligte_gemeinden: list[XwpGemeinde] = field(default_factory=list)
    foerderkennzeichen: Optional[str] = None
    technische_planerstellung: list[str] = field(default_factory=list)
    externe_referenzen: list[XwpExterneReferenz] = field(default_factory=list)
    beschreibung: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)

    # WP_Plan attributes set by the fields above or derived by F|Heat
    _COVERED: ClassVar[frozenset] = frozenset({
        "name", "planungsverantwortlicheStelle", "beschlussDatum", "aufstellungsbeschlussDatum",
        "verfahrensart", "gesetzlicheGrundlage", "zieljahr", "basisJahrDatenerfassung",
        "beteiligteGemeinden", "foerderkennzeichen", "technischePlanerstellung", "externeReferenz",
        "beschreibung", "raeumlicherGeltungsbereich", "energiebilanz", "infrastruktur",
        "potenzialanalyse", "massnahme", "text", "bereich",
    })

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("XwpPlanConfig.name must not be empty.")
        _check_code("WP_VerfahrenArt", self.verfahrensart, "XwpPlanConfig.verfahrensart")
        _check_code("WP_GesetzlicheGrundlage", self.gesetzliche_grundlage, "XwpPlanConfig.gesetzliche_grundlage")
        for attr in ("zieljahr", "basisjahr"):
            year = getattr(self, attr)
            if year is not None and not 1990 <= year <= 2100:
                raise ValueError(f"XwpPlanConfig.{attr} ({year}) is not a plausible year.")
        if self.basisjahr is not None and self.basisjahr > self.zieljahr:
            raise ValueError("XwpPlanConfig.basisjahr must not be after zieljahr.")
        if (self.aufstellungsbeschluss_datum and self.beschluss_datum
                and self.aufstellungsbeschluss_datum > self.beschluss_datum):
            raise ValueError("XwpPlanConfig.aufstellungsbeschluss_datum must not be after beschluss_datum.")
        from fheat_core.xwp.model import current

        plan_attrs = {a.name for a in current.WP_Plan.__xwp__.attrs}
        for key in self.extra:
            if key not in plan_attrs:
                raise ValueError(f"XwpPlanConfig.extra: WP_Plan has no attribute {key!r}.")
            if key in self._COVERED:
                raise ValueError(f"XwpPlanConfig.extra: {key!r} is set by a field of XwpPlanConfig or by F|Heat.")


@dataclass
class XwpSuitabilityConfig:
    """Thresholds for the proposed WP_Eignungsstufe of a heat network.

    Each tuple holds the lower bounds of the stages 1000 (sehr wahrscheinlich
    geeignet), 2000 (wahrscheinlich geeignet) and 3000 (wahrscheinlich
    ungeeignet), descending; below the last bound: 4000. The stage is only a
    proposal that the planner overrides. Defaults: heat density after the
    KEA-BW guideline on municipal heat planning (70/175/415 MWh/(ha·a)); heat
    line density an assumption to be confirmed in phase 7.
    """

    heat_line_density: tuple[float, float, float] = (1.5, 1.0, 0.5)  # MWh/(m·a)
    heat_density: tuple[float, float, float] = (415.0, 175.0, 70.0)  # MWh/(ha·a)

    def __post_init__(self) -> None:
        for attr in ("heat_line_density", "heat_density"):
            bounds = tuple(getattr(self, attr))
            if len(bounds) != 3 or not bounds[0] > bounds[1] > bounds[2] >= 0:
                raise ValueError(f"XwpSuitabilityConfig.{attr} needs three descending bounds >= 0, got {bounds}.")
            setattr(self, attr, bounds)


@dataclass
class XwpConfig:
    """Parameters of the XWaermeplan export (see docs/xwaermeplan)."""

    plan: XwpPlanConfig
    formats: tuple[str, ...] = ("gml", "jsonfg", "gpkg")
    # Building blocks with fewer buildings are merged with a neighbour before
    # they are published (data protection). An assumption, to be checked
    # against the WPG and the rules of the federal state.
    privacy_min_buildings: int = 5
    suitability: XwpSuitabilityConfig = field(default_factory=XwpSuitabilityConfig)
    precision: int = 3  # decimal places of EPSG:25832 coordinates
    energy_raster: bool = False  # WP_EnergieRaster on the 100 m INSPIRE grid
    # Where the construction year for WP_Baualtersklasse comes from, first hit
    # wins: construction_year (true year, e.g. flex adapter), age (LANUV age
    # class, NRW), parcel_year (validFrom of the parcel, NRW; a weak proxy).
    construction_year_sources: tuple[str, ...] = ("construction_year", "age", "parcel_year")

    _ALLOWED_FORMATS: ClassVar[frozenset] = frozenset({"gml", "jsonfg", "gpkg"})
    _ALLOWED_YEAR_SOURCES: ClassVar[frozenset] = frozenset({"construction_year", "age", "parcel_year"})

    def __post_init__(self) -> None:
        self.formats = tuple(self.formats)
        if not self.formats or set(self.formats) - self._ALLOWED_FORMATS:
            raise ValueError(f"XwpConfig.formats must be a non-empty subset of {sorted(self._ALLOWED_FORMATS)}.")
        if self.privacy_min_buildings < 1:
            raise ValueError("XwpConfig.privacy_min_buildings must be >= 1.")
        if not 0 <= self.precision <= 6:
            raise ValueError("XwpConfig.precision must be between 0 and 6.")
        self.construction_year_sources = tuple(self.construction_year_sources)
        if not self.construction_year_sources or set(self.construction_year_sources) - self._ALLOWED_YEAR_SOURCES:
            raise ValueError(
                f"XwpConfig.construction_year_sources must be a non-empty subset of "
                f"{sorted(self._ALLOWED_YEAR_SOURCES)}."
            )


def _check_code(enum_name: str, code: str, where: str) -> None:
    from fheat_core.xwp.model import current

    codes = {e.code for e in current.ENUMS[enum_name]}
    if str(code) not in codes:
        raise ValueError(f"{where}: {code!r} is not a code of {enum_name} ({sorted(codes)}).")
