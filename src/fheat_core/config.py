from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar


@dataclass
class FHeatConfig:
    """Pipeline-Parameter.

    Enthält ausschließlich Parameter der Berechnung, NICHT der Datenquelle.
    Datenquellen-spezifische Konfiguration (Pfade, Spaltenmappings, regionale
    Parameter wie Gemeindename) gehört in den Adapter-Konstruktor.
    """

    # Netzparameter
    supply_temperature: float = 80.0
    return_temperature: float = 50.0

    # WLD / Eignungspolygone
    wld_threshold: float = 500.0
    buffer_distance: float = 50.0

    # BDEW-SLP-Parameter (deutsches Standardlastprofil)
    building_class: int = 3      # NRW-Default nach BGW 2006
    wind_class: int = 1
    year: int = 2022

    # Output
    output_dir: str = "./output"
    output_format: str = "gpkg"
    output_language: str = "de"  # "de" = deutsche Spaltenlabels, "raw" = kanonische IDs

    _ALLOWED_FORMATS: ClassVar[frozenset] = frozenset({"gpkg", "fgb", "geojson", "gml"})
    _ALLOWED_LANGUAGES: ClassVar[frozenset] = frozenset({"de", "raw"})

    def __post_init__(self) -> None:
        if self.supply_temperature <= self.return_temperature:
            raise ValueError(
                f"supply_temperature ({self.supply_temperature} °C) muss größer als "
                f"return_temperature ({self.return_temperature} °C) sein."
            )
        if self.output_format not in self._ALLOWED_FORMATS:
            raise ValueError(
                f"output_format '{self.output_format}' ist nicht zulässig. "
                f"Erlaubte Formate: {sorted(self._ALLOWED_FORMATS)}"
            )
        if self.output_language not in self._ALLOWED_LANGUAGES:
            raise ValueError(
                f"output_language '{self.output_language}' ist nicht zulässig. "
                f"Erlaubte Werte: {sorted(self._ALLOWED_LANGUAGES)}"
            )
