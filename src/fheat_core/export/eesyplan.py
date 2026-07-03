"""eesyplan export — placeholder.

Wird nicht vom Orchestrator aufgerufen. Implementierung folgt in einer
späteren Phase, sobald das eesyplan-Schnittstellen-Schema final ist.
"""
from __future__ import annotations

from fheat_core.state import PipelineState


def export_to_eesyplan(state: PipelineState) -> dict:
    raise NotImplementedError(
        "export_to_eesyplan ist noch nicht implementiert (Platzhalter)."
    )
