"""Contract for network-generation backends.

A backend turns the prepared input frames (buildings, streets, source) into a
NetSchema-compliant ``net_gdf``. Which backend runs is decided by
``FHeatConfig.network_mode`` — the step itself contains no algorithm.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, Tuple

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
        civil_layers: Optional[list] = None,
    ) -> Tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
        """Return ``(net_gdf, buildings)``.

        ``net_gdf`` must satisfy :data:`fheat_core.schemas.NetSchema`.
        ``buildings`` is returned so a backend that decides which buildings are
        connected (topotherm's ``economic`` mode) can write ``connect`` back.
        Backends that do not change it return it unchanged.

        ``civil_layers`` are the civil works layers (land use, road surface;
        entries may be None). A backend that optimises costs may weigh its
        candidate routes with them and write ``civil_cost_factor`` (and
        ``road_surface``) onto the net; the step adds the factors and pipe
        costs for every backend that does not.
        """
        ...


# Codes of NetworkBackendError: stable identifiers an application can turn
# into its own message (the exception text is meant for developers).
EMPTY_NETWORK = "empty_network"                  # economic mode: no connection was profitable
SOURCE_ON_STREET = "source_on_street"            # heat source lies exactly on the street network
TIME_LIMIT = "time_limit"                        # solver reached its time limit before the optimum
NO_OPTIMAL_SOLUTION = "no_optimal_solution"      # solver ended without an optimal solution
NO_ROUTABLE_STREETS = "no_routable_streets"      # no street may carry a pipe
UNMATCHED_NODES = "unmatched_nodes"              # street/source endpoints not matched to a node
SOLVER_UNAVAILABLE = "solver_unavailable"        # MILP solver not installed
TOPOTHERM_UNAVAILABLE = "topotherm_unavailable"  # topotherm missing or not importable


class NetworkBackendError(RuntimeError):
    """Raised when a backend cannot produce a network.

    ``code`` is one of the constants above, or None for an unexpected failure.
    """

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.code = code
