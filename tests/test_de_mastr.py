"""Tests for fheat_de.mastr (MaStR export → three tables of strings).

- a local export: the three XML files (UTF-16) become tables, missing
  fields are "", only the CHP plants of biomass units are kept
- the tables are cached as CSV and read from there the next time
- a remote export is read by range requests; a dropped connection is tried
  again after growing pauses, a server without range requests is an error
"""
from __future__ import annotations

import io
import urllib.request
import zipfile

import pytest

from fheat_de import mastr

URL = "https://example.org/Stichtag/Gesamtdatenexport_20261001_26.1.zip"


def _xml(root: str, tag: str, records: list[dict]) -> bytes:
    body = "".join(
        f"<{tag}>" + "".join(f"<{k}>{v}</{k}>" for k, v in record.items()) + f"</{tag}>" for record in records
    )
    return f'<?xml version="1.0" encoding="utf-16"?><{root}>{body}</{root}>'.encode("utf-16")


def _export() -> bytes:
    units = [
        {"EinheitMastrNummer": "SEE1", "NameStromerzeugungseinheit": "BHKW Hof Müller", "EinheitBetriebsstatus": "35",
         "Hauptbrennstoff": "2445", "Nettonennleistung": "500.000", "Laengengrad": "7.3", "Breitengrad": "52.1",
         "EegMaStRNummer": "EEG1", "KwkMaStRNummer": "KWK1", "Landkreis": "Steinfurt"},
        {"EinheitMastrNummer": "SEE2", "EinheitBetriebsstatus": "35", "Hauptbrennstoff": "2445"},
    ]
    eeg = [{"EegMaStRNummer": "EEG1", "BiogasHoechstbemessungsleistung": "400.000", "AnlageBetriebsstatus": "35"}]
    kwk = [
        {"KwkMastrNummer": "KWK1", "ElektrischeKwkLeistung": "500.000", "ThermischeNutzleistung": "520.000"},
        {"KwkMastrNummer": "KWK9", "ElektrischeKwkLeistung": "1.000", "ThermischeNutzleistung": "2.000"},
    ]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(mastr.FILE_UNITS, _xml("EinheitenBiomasse", mastr.TAG_UNIT, units))
        archive.writestr(mastr.FILE_EEG, _xml("AnlagenEegBiomasse", mastr.TAG_EEG, eeg))
        archive.writestr(mastr.FILE_KWK, _xml("AnlagenKwk", mastr.TAG_KWK, kwk))
        archive.writestr("EinheitenWind.xml", b"not needed")
    return buffer.getvalue()


@pytest.fixture
def export_file(tmp_path):
    path = tmp_path / "Gesamtdatenexport_20261001_26.1.zip"
    path.write_bytes(_export())
    return path


class TestLocalExport:
    def test_tables(self, export_file, tmp_path):
        tables = mastr.read_biomass_tables(tmp_path / "cache", str(export_file))
        assert list(tables.units.columns) == list(mastr.UNIT_FIELDS)
        assert tables.units["NameStromerzeugungseinheit"].tolist() == ["BHKW Hof Müller", ""]
        assert tables.units.loc[0, "Nettonennleistung"] == "500.000"
        assert "Landkreis" not in tables.units.columns
        assert tables.eeg["BiogasHoechstbemessungsleistung"].tolist() == ["400.000"]
        assert tables.kwk["KwkMastrNummer"].tolist() == ["KWK1"]
        assert tables.date == "01.10.2026"

    def test_cached_tables_are_read_again(self, export_file, tmp_path, monkeypatch):
        first = mastr.read_biomass_tables(tmp_path / "cache", str(export_file))
        assert len(list((tmp_path / "cache").glob("mastr-Gesamtdatenexport_20261001_26.1_*.csv"))) == 3

        def no_export(_):
            raise AssertionError("export opened again")

        monkeypatch.setattr(mastr, "_open_export", no_export)
        again = mastr.read_biomass_tables(tmp_path / "cache", str(export_file))
        assert again.units.equals(first.units)
        assert again.kwk.equals(first.kwk)

    def test_missing_file_in_the_export(self, tmp_path):
        path = tmp_path / "Gesamtdatenexport_20261001_26.1.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(mastr.FILE_UNITS, _xml("EinheitenBiomasse", mastr.TAG_UNIT, []))
        with pytest.raises(RuntimeError, match=mastr.FILE_EEG):
            mastr.read_biomass_tables(tmp_path / "cache", str(path))


class _Response:
    def __init__(self, status, data=b"", size=None):
        self.status, self._data = status, data
        self.headers = {"Content-Length": str(size if size is not None else len(data))}

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeServer:
    """urlopen of a server holding one file; ``drop`` connections fail first."""

    def __init__(self, data: bytes, ranges: bool = True, drop: int = 0):
        self.data, self.ranges, self.drop, self.requests = data, ranges, drop, 0

    def __call__(self, request, timeout=None):
        self.requests += 1
        if self.drop:
            self.drop -= 1
            raise ConnectionResetError("dropped")
        if request.get_method() == "HEAD":
            return _Response(200, size=len(self.data))
        if not self.ranges:
            return _Response(200, self.data)
        first, last = request.get_header("Range").removeprefix("bytes=").split("-")
        return _Response(206, self.data[int(first):int(last) + 1])


@pytest.fixture
def no_wait(monkeypatch):
    """The pauses between two attempts, recorded instead of waited."""
    waits = []
    monkeypatch.setattr(mastr.cancel, "sleep", waits.append)
    return waits


class TestRemoteExport:
    def test_read_by_range_requests(self, tmp_path, monkeypatch, no_wait):
        server = FakeServer(_export(), drop=2)
        monkeypatch.setattr(urllib.request, "urlopen", server)
        tables = mastr.read_biomass_tables(tmp_path, URL)
        assert tables.units["EinheitMastrNummer"].tolist() == ["SEE1", "SEE2"]
        assert tables.date == "01.10.2026"
        assert (tmp_path / "mastr-Gesamtdatenexport_20261001_26.1_units.csv").exists()
        assert no_wait == [1.0, 2.0]

    def test_server_without_ranges(self, tmp_path, monkeypatch):
        monkeypatch.setattr(urllib.request, "urlopen", FakeServer(_export(), ranges=False))
        with pytest.raises(RuntimeError, match="Teilbereiche"):
            mastr.read_biomass_tables(tmp_path, URL)

    def test_server_gone(self, tmp_path, monkeypatch, no_wait):
        monkeypatch.setattr(urllib.request, "urlopen", FakeServer(b"", drop=len(mastr.HTTP_RETRY_WAITS) + 1))
        with pytest.raises(RuntimeError, match="nicht lesbar"):
            mastr.read_biomass_tables(tmp_path, URL)
        assert not list(tmp_path.glob("*.csv"))
        assert no_wait == list(mastr.HTTP_RETRY_WAITS)


@pytest.mark.parametrize("export, date", [
    (URL, "01.10.2026"),
    ("C:/data/Gesamtdatenexport_20260701_26.1.zip", "01.07.2026"),
    ("export.zip", None),
])
def test_export_date(export, date):
    assert mastr.export_date(export) == date
