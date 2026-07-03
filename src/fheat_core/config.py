from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar


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
