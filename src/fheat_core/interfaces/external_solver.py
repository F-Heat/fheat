"""Generischer Platzhalter für externe Solver-Schnittstellen.

Dient als Vorlage. Implementierung folgt in einer späteren Phase,
sobald die jeweiligen Datenkontrakte definiert sind.
Wird nicht vom Orchestrator aufgerufen.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from fheat_core.state import PipelineState


class ExternalSolverInterface(ABC):
    """Abstrakte Schnittstelle zu einem externen Solver. Noch nicht implementiert."""

    @abstractmethod
    def export(self, state: PipelineState) -> dict:
        ...


def export(state: PipelineState) -> dict:
    raise NotImplementedError(
        "export ist noch nicht implementiert (Platzhalter)."
    )
