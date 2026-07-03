"""XPlan export — placeholder.

Not called by the orchestrator. Implementation follows in a later phase
once the XPlanGML mapping is defined.
"""
from __future__ import annotations

from fheat_core.state import PipelineState


def export(state: PipelineState) -> dict:
    raise NotImplementedError(
        "export_to_xplan is not yet implemented (placeholder)."
    )
