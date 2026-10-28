"""Biomass units of the Marktstammdatenregister (MaStR) of the Bundesnetzagentur.

Source: Gesamtdatenexport of the MaStR, licence Datenlizenz Deutschland –
Namensnennung – Version 2.0. The quarterly exports under ``/Stichtag/`` are
fixed, so a table in the cache is never loaded again. Checked 2026-10-28:
the export of 01.10.2026 is a ZIP of 3.2 GB with 440 XML files (UTF-16);
only three are read (11 MB compressed). The server answers HTTP range
requests, so these files are read straight out of the remote ZIP and the
rest is never downloaded.

The three files become three tables of strings, kept in the cache as CSV:
the biomass units, their EEG plants and the CHP plants they belong to.
Field names: documentation of the Gesamtdatenexport (download page of the
MaStR).
"""
from __future__ import annotations

import io
import os
import re
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import IO, Iterator, NamedTuple, Optional
from urllib.parse import urlparse
from xml.etree import ElementTree

import pandas as pd

from fheat_core import cache, cancel

MASTR_EXPORT_URL = (
    "https://download.marktstammdatenregister.de/Stichtag/Gesamtdatenexport_20261001_26.1.zip"
)
HTTP_TIMEOUT = 120
#: pauses [s] before the next attempt of a request: the server drops all
#: connections for 1-20 s now and then (checked 2026-10-28)
HTTP_RETRY_WAITS = (1.0, 2.0, 4.0, 8.0, 16.0)
READ_BUFFER = 8 << 20  # 8 MiB per range request: the three files in about 4 requests

#: XML file, element of one record, fields kept; a field missing in a record is ""
FILE_UNITS = "EinheitenBiomasse.xml"
TAG_UNIT = "EinheitBiomasse"
UNIT_FIELDS = (
    "EinheitMastrNummer", "NameStromerzeugungseinheit", "EinheitBetriebsstatus", "Hauptbrennstoff",
    "Nettonennleistung", "Bruttoleistung", "Gemeinde", "Gemeindeschluessel", "Laengengrad", "Breitengrad",
    "Inbetriebnahmedatum", "EegMaStRNummer", "KwkMaStRNummer",
)
FILE_EEG = "AnlagenEegBiomasse.xml"
TAG_EEG = "AnlageEegBiomasse"
EEG_FIELDS = (
    "EegMaStRNummer", "EegInbetriebnahmedatum", "BiogasHoechstbemessungsleistung",
    "BiogasInanspruchnahmeFlexiPraemie",
)
FILE_KWK = "AnlagenKwk.xml"
TAG_KWK = "AnlageKwk"
KWK_FIELDS = ("KwkMastrNummer", "ElektrischeKwkLeistung", "ThermischeNutzleistung")


class MastrTables(NamedTuple):
    """Biomass units, their EEG plants and CHP plants (all values strings, missing = "")."""

    units: pd.DataFrame
    eeg: pd.DataFrame
    kwk: pd.DataFrame
    #: reference date of the export ("01.10.2026"), None if its name does not tell
    date: Optional[str]


class _RemoteFile(io.RawIOBase):
    """Read-only, seekable view of a file on a server that answers range requests."""

    def __init__(self, url: str, timeout: int = HTTP_TIMEOUT) -> None:
        self._url = url
        self._timeout = timeout
        self._pos = 0
        _, headers, _ = self._fetch(urllib.request.Request(url, method="HEAD"))
        self._size = int(headers["Content-Length"])

    def _fetch(self, request: urllib.request.Request):
        """Status, headers and body of ``request``, tried again after the pauses of HTTP_RETRY_WAITS."""
        for wait in (*HTTP_RETRY_WAITS, None):
            try:
                with urllib.request.urlopen(request, timeout=self._timeout) as resp:
                    return resp.status, resp.headers, resp.read()
            except OSError:  # URLError, TimeoutError, a dropped connection
                if wait is None:
                    raise
                cancel.sleep(wait)

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        start = {io.SEEK_SET: 0, io.SEEK_CUR: self._pos, io.SEEK_END: self._size}[whence]
        self._pos = start + offset
        return self._pos

    def readinto(self, buffer) -> int:
        cancel.raise_if_cancelled()
        end = min(self._pos + len(buffer), self._size)
        if end <= self._pos:
            return 0
        request = urllib.request.Request(self._url, headers={"Range": f"bytes={self._pos}-{end - 1}"})
        status, _, data = self._fetch(request)
        if status != 206:
            raise RuntimeError(f"Server von '{self._url}' liefert keine Teilbereiche (HTTP {status}).")
        buffer[:len(data)] = data
        self._pos += len(data)
        return len(data)


def _open_export(export: str) -> zipfile.ZipFile:
    """The export ZIP: a local file, else a URL read by range requests."""
    try:
        if Path(export).is_file():
            return zipfile.ZipFile(export)
        return zipfile.ZipFile(io.BufferedReader(_RemoteFile(export), READ_BUFFER))
    except (urllib.error.URLError, TimeoutError, OSError, zipfile.BadZipFile, KeyError) as e:
        raise RuntimeError(f"MaStR-Export '{export}' nicht lesbar: {e}") from e


def _records(stream: IO[bytes], tag: str, fields: tuple[str, ...]) -> Iterator[dict]:
    """The records ``tag`` of an MaStR XML file, one dict of ``fields`` each."""
    for count, (_, element) in enumerate(ElementTree.iterparse(stream)):
        if element.tag != tag:
            continue
        yield {field: (element.findtext(field) or "").strip() for field in fields}
        element.clear()
        if count % 10_000 == 0:
            cancel.raise_if_cancelled()


def _read_member(archive: zipfile.ZipFile, name: str, tag: str, fields: tuple[str, ...]) -> pd.DataFrame:
    try:
        with archive.open(name) as stream:
            return pd.DataFrame(list(_records(stream, tag, fields)), columns=list(fields))
    except KeyError as e:
        raise RuntimeError(f"MaStR-Export ohne Datei '{name}' (Aufbau geändert?).") from e
    except (urllib.error.URLError, TimeoutError, OSError, ElementTree.ParseError) as e:
        raise RuntimeError(f"MaStR-Datei '{name}' nicht lesbar: {e}") from e


def _export_name(export: str) -> str:
    """``Gesamtdatenexport_20261001_26.1`` of a URL or a local path."""
    path = urlparse(export).path if "://" in export else export
    return Path(path).name.removesuffix(".zip")


def export_date(export: str) -> Optional[str]:
    """Reference date in the name of an export ("…_20261001_…" → "01.10.2026")."""
    match = re.search(r"_(\d{4})(\d{2})(\d{2})_", _export_name(export))
    return f"{match[3]}.{match[2]}.{match[1]}" if match else None


def _write_csv(table: pd.DataFrame, target: Path) -> None:
    part = target.with_name(f"{target.name}.{os.getpid()}.part")
    try:
        table.to_csv(part, index=False, encoding="utf-8")
        os.replace(part, target)
    finally:
        if part.exists():
            part.unlink()


def read_biomass_tables(
    cache_dir: Optional[Path] = None, export: str = MASTR_EXPORT_URL
) -> MastrTables:
    """Biomass units, EEG plants and CHP plants of Germany from an MaStR export.

    ``export`` is the URL of a Gesamtdatenexport (default: the reference date
    export of :data:`MASTR_EXPORT_URL`) or the path of a downloaded one. The
    first call reads the three XML files and writes the tables to the cache
    (``mastr-<export>_<table>.csv``, 10 MB together); later calls read them
    from there. Only the CHP plants a biomass unit names are kept.
    """
    folder = cache.cache_dir(cache_dir)
    name = _export_name(export)
    paths = {table: folder / f"mastr-{name}_{table}.csv" for table in ("units", "eeg", "kwk")}
    if all(p.exists() for p in paths.values()):
        tables = {t: pd.read_csv(p, dtype=str, keep_default_na=False) for t, p in paths.items()}
    else:
        with _open_export(export) as archive:
            units = _read_member(archive, FILE_UNITS, TAG_UNIT, UNIT_FIELDS)
            eeg = _read_member(archive, FILE_EEG, TAG_EEG, EEG_FIELDS)
            kwk = _read_member(archive, FILE_KWK, TAG_KWK, KWK_FIELDS)
        kwk = kwk[kwk["KwkMastrNummer"].isin(set(units["KwkMaStRNummer"]) - {""})].reset_index(drop=True)
        tables = {"units": units, "eeg": eeg, "kwk": kwk}
        for table, path in paths.items():
            _write_csv(tables[table], path)
    return MastrTables(tables["units"], tables["eeg"], tables["kwk"], export_date(export))
