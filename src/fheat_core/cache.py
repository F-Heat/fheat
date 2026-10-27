"""Local cache folder for downloaded reference data.

The folder is the ``cache_dir`` argument, else the environment variable
``FHEAT_CACHE_DIR``, else ``~/.cache/fheat``. Shared by the NRW downloads
(:mod:`fheat_nrw.cache`) and the DWD temperature years
(:mod:`fheat_core.weather.dwd`).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Union

ENV_CACHE_DIR = "FHEAT_CACHE_DIR"
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "fheat"

PathLike = Union[str, Path]


def cache_dir(override: Optional[PathLike] = None) -> Path:
    """The cache folder (created if missing)."""
    if override is not None:
        folder = Path(override)
    elif os.environ.get(ENV_CACHE_DIR):
        folder = Path(os.environ[ENV_CACHE_DIR])
    else:
        folder = DEFAULT_CACHE_DIR
    folder.mkdir(parents=True, exist_ok=True)
    return folder
