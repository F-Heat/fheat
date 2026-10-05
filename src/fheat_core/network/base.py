"""Contract for network-generation backends.

A backend turns the prepared input frames (buildings, streets, source) into a
NetSchema-compliant ``net_gdf``. Which backend runs is decided by
``FHeatConfig.network_mode`` — the step itself contains no algorithm.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Tuple

import geopandas as gpd


class NetworkBackend(ABC):
    """Strategy interface for the NETWORK phase."""

    #: registry key, must match a NetworkMode value
    name: str = ""

    @abstractmethod
    def build(
        self,
        buildings: gpd.GeoDataFrame,
        streets: gpd.GeoDataFrame,
        source: gpd.GeoDataFrame,
        config,
        adapter,
    ) -> Tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
        """Return ``(net_gdf, buildings)``.

        ``net_gdf`` must satisfy :data:`fheat_core.schemas.NetSchema`.
        ``buildings`` is returned so a backend that decides which buildings are
        connected (topotherm's ``economic`` mode) can write ``connect`` back.
        Backends that do not change it return it unchanged.
        """
        ...


class NetworkBackendError(RuntimeError):
    """Raised when a backend cannot produce a network."""
