"""XPlan export — placeholder.

Wird nicht vom Orchestrator aufgerufen. Implementierung folgt in einer
späteren Phase, sobald das XPlanGML-Mapping definiert ist.
"""
from __future__ import annotations

from fheat_core.state import PipelineState


def export_to_xplan(state: PipelineState) -> dict:
    raise NotImplementedError(
        "export_to_xplan ist noch nicht implementiert (Platzhalter)."
    )
