"""Network-generation backends and their registry."""
from __future__ import annotations

from fheat_core.network.base import NetworkBackend, NetworkBackendError
from fheat_core.network.dijkstra import DijkstraBackend

__all__ = ["NetworkBackend", "NetworkBackendError", "DijkstraBackend", "get_backend"]


def get_backend(mode: str) -> NetworkBackend:
    """Return the backend for ``mode``.

    topotherm is imported lazily so that Phase 0 keeps working without the
    optional dependency installed.
    """
    if mode == DijkstraBackend.name:
        return DijkstraBackend()
    if mode == "expert":
        from fheat_core.network.topotherm_backend import TopothermBackend

        return TopothermBackend()
    raise ValueError(
        f"Unknown network_mode {mode!r}. Allowed: 'phase0', 'expert'."
    )
