"""Generic placeholder for external solver interfaces.

Serves as a template. Implementation follows in a later phase once
the respective data contracts are defined.
Not called by the orchestrator.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from fheat_core.state import PipelineState


class ExternalSolverInterface(ABC):
    """Abstract interface to an external solver. Not yet implemented."""

    @abstractmethod
    def export(self, state: PipelineState) -> dict:
        ...


def export(state: PipelineState) -> dict:
    raise NotImplementedError(
        "export is not yet implemented (placeholder)."
    )
