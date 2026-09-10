from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import ClassVar, Optional


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

    # BDEW SLP parameters (German standard load profile)
    building_class: int = 3      # NRW default per BGW 2006
    wind_class: int = 1
    year: int = 2022

    # Output
    output_dir: str = "./output"
    output_format: str = "gpkg"
    output_language: str = "de"  # "de" = German column labels, "raw" = canonical IDs

    _ALLOWED_FORMATS: ClassVar[frozenset] = frozenset({"gpkg", "fgb", "geojson", "gml"})
    _ALLOWED_LANGUAGES: ClassVar[frozenset] = frozenset({"de", "raw"})

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

        allowed_modes = {m.value for m in NetworkMode}
        if self.network_mode not in allowed_modes:
            raise ValueError(
                f"network_mode '{self.network_mode}' is not allowed. "
                f"Allowed values: {sorted(allowed_modes)}"
            )
        if self.network_mode == NetworkMode.EXPERT.value and self.topotherm is None:
            self.topotherm = TopothermConfig()
