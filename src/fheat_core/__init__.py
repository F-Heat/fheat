"""fheat_core — adapter-agnostic district-heating pipeline.

The version is single-sourced from the installed distribution metadata
(``pyproject.toml``); bump it there for releases.
"""
from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("fheat")
except PackageNotFoundError:  # running from a source tree without an install
    __version__ = "0.0.0+unknown"
