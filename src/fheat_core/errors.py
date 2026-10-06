"""Exceptions raised by the pipeline."""
from __future__ import annotations


class PipelineInputError(ValueError):
    """A step was started without the inputs it needs.

    Raised e.g. when the NETWORK step runs without a heat source or when a
    step is started before the frames of an earlier step exist.
    """
