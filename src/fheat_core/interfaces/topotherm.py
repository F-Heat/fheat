"""topotherm interface — placeholder.

Wird nicht vom Orchestrator aufgerufen. Konkrete Implementierung folgt
in einer späteren Phase, sobald die topotherm-Datenkontrakte stehen.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from fheat_core.state import PipelineState


class TopothermInterface(ABC):
    """Abstrakte Schnittstelle zu topotherm. Noch nicht implementiert."""

    @abstractmethod
    def export(self, state: PipelineState) -> dict:
        ...


def export_to_topotherm(state: PipelineState) -> dict:
    raise NotImplementedError(
        "export_to_topotherm ist noch nicht implementiert (Platzhalter)."
    )
