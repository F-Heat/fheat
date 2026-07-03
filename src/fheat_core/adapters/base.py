from abc import ABC, abstractmethod
from typing import Optional

import geopandas as gpd
import pandas as pd


class DataAdapter(ABC):
    """
    Vertrag zwischen Datenquelle und fheat_core.

    Implementierungen MÜSSEN bereits angepasste Daten liefern, die die
    Schemas in `fheat_core.schemas` erfüllen.

    Insbesondere bedeutet das für `fetch_buildings`: Gebäude sind bereits
    gemerged, mit Wärmebedarf, thermischer Leistung, Volllaststunden und
    Lastprofil annotiert. Der Adapter ist verantwortlich für ALLE
    bundesland-/datenquellen-spezifischen Anpassungen.

    Adapter-Konfiguration (Pfade, Spaltennamen, regionale Parameter)
    erfolgt im Konstruktor der konkreten Adapter-Klasse — NICHT über
    `FHeatConfig` und NICHT als Methodenparameter.
    """

    @abstractmethod
    def fetch_buildings(self) -> gpd.GeoDataFrame:
        """Gebäude konform zu BuildingsSchema."""
        ...

    @abstractmethod
    def fetch_streets(self) -> gpd.GeoDataFrame:
        """Straßen konform zu StreetsSchema."""
        ...

    @abstractmethod
    def fetch_parcels(self) -> gpd.GeoDataFrame:
        """Flurstücke konform zu ParcelsSchema."""
        ...

    @abstractmethod
    def fetch_source(self) -> gpd.GeoDataFrame:
        """Wärmequelle(n) konform zu SourceSchema (Point-Geometrie)."""
        ...

    # Optionale Daten — Default-Implementierung gibt None zurück,
    # Core lädt dann seinen eigenen Default.
    def provide_pipe_info(self) -> Optional[pd.DataFrame]:
        """Optional: Rohrkatalog (DN, di, U-Value, max_volumeFlow). None → Core-Default."""
        return None

    def provide_temperature(self) -> Optional[pd.Series]:
        """Optional: 8760 Stundentemperaturen [°C]. None → Core-Default."""
        return None

    def provide_holidays(self) -> Optional[dict]:
        """Optional: Feiertage als {date: name}-Dict. None → Core-Default."""
        return None
