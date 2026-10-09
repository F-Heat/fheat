"""Exceptions raised by the pipeline."""
from __future__ import annotations

# Codes of PipelineInputError: stable identifiers an application can turn
# into its own message (the exception text is meant for developers).
NO_BUILDINGS = "no_buildings"  # NETWORK: no building to connect in the planning area


class PipelineInputError(ValueError):
    """A step was started without the inputs it needs.

    Raised e.g. when the NETWORK step runs without a heat source or when a
    step is started before the frames of an earlier step exist. ``code`` is
    one of the constants above, or None.
    """

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.code = code
