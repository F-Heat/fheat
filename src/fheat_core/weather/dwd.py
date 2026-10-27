"""Measured DWD temperature year at a place, via the ``wetterdienst`` package.

Hourly air temperature (2 m) of the DWD stations, DWD Open Data
("Datenbasis: Deutscher Wetterdienst"). The nearest station that measured
at least ``min_coverage`` of the year is used; gaps of up to
:data:`MAX_INTERPOLATION_GAP` hours are interpolated, longer ones are filled
from the next stations by distance. The DWD values are UTC; the year is
returned in CET (UTC+1 all year, like the test reference years and the BDEW
profiles).

``wetterdienst`` changes its API often, so it is pinned in the ``[dwd]``
extra and only used inside this module. It needs Python >= 3.11.

Cache (folder of :func:`fheat_core.cache.cache_dir`):

- ``dwd/tt_<station>_<year>.csv`` the filled year, ``.json`` next to it the
  station, coverage and date of retrieval. A finished year practically
  never changes, so the files do not expire.
- ``dwd/lookup.json`` place (0.01°) and year → station and distance, so a
  repeated request needs neither the station list nor the values.
- ``wetterdienst/`` the raw downloads of ``wetterdienst``.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

from fheat_core import cancel
from fheat_core.cache import PathLike
from fheat_core.cache import cache_dir as resolve_cache_dir
from fheat_core.weather.base import TemperatureYear, WeatherDataError

logger = logging.getLogger(__name__)

PARAMETER = ("hourly", "temperature_air", "temperature_air_2m")
INSTALL_HINT = 'pip install "fheat[dwd]"'
MAX_INTERPOLATION_GAP = 6  # h; longer gaps are filled from the next station
CET_OFFSET = pd.Timedelta(hours=1)
CACHE_SUBDIR = "dwd"
LOOKUP_FILE = "lookup.json"


def load_dwd_temperature(
    lat: float,
    lon: float,
    year: int,
    *,
    max_distance_km: float = 50.0,
    min_coverage: float = 0.95,
    cache_dir: Optional[PathLike] = None,
) -> TemperatureYear:
    """Measured hourly temperatures [°C] of ``year`` at (``lat``, ``lon``) (WGS84).

    Raises :class:`WeatherDataError` for a year that is not finished yet, when
    no station within ``max_distance_km`` covers the year or the DWD request
    fails, and ImportError when ``wetterdienst`` is not installed.
    """
    if year >= date.today().year:
        raise WeatherDataError(
            f"The year {year} is not finished yet; DWD years are available up to {date.today().year - 1}."
        )
    root = resolve_cache_dir(cache_dir)
    folder = root / CACHE_SUBDIR
    folder.mkdir(exist_ok=True)
    key = f"{lat:.2f},{lon:.2f},{year},{max_distance_km:g},{min_coverage:g}"
    lookup = _read_json(folder / LOOKUP_FILE)
    if key in lookup:
        cached = _read_cached(folder, lookup[key]["station_id"], year, lookup[key]["distance_km"])
        if cached is not None:
            return cached

    request = _request(year, root / "wetterdienst")
    stations = _stations(request, lat, lon, year, max_distance_km)
    if stations.empty:
        raise WeatherDataError(
            f"No DWD station with hourly temperatures of {year} within {max_distance_km:g} km of ({lat:.3f}, {lon:.3f})."
        )

    hours = pd.date_range(f"{year}-01-01", f"{year}-12-31 23:00", freq="h")
    fetched: dict[str, pd.Series] = {}

    def values(station_id: str) -> pd.Series:
        if station_id not in fetched:
            cancel.raise_if_cancelled()
            fetched[station_id] = _station_values(request, station_id, year)
        return fetched[station_id]

    primary = None
    for station in stations.itertuples(index=False):
        distance_km = round(float(station.distance), 1)
        cached = _read_cached(folder, station.station_id, year, distance_km)
        if cached is not None and cached.coverage >= min_coverage:
            _remember(folder, key, station.station_id, distance_km)
            return cached
        coverage = float(values(station.station_id).reindex(hours).notna().mean())
        if coverage >= min_coverage:
            primary = station
            break
        logger.info(
            "DWD station %s (%s) measured only %.0f %% of %d, trying the next one.",
            station.station_id, station.name, coverage * 100, year,
        )
    if primary is None:
        raise WeatherDataError(
            f"No DWD station within {max_distance_km:g} km of ({lat:.3f}, {lon:.3f}) "
            f"measured {min_coverage:.0%} of {year}."
        )

    filled = _interpolate_short_gaps(values(primary.station_id)).reindex(hours)
    for station in stations.itertuples(index=False):
        if not filled.isna().any():
            break
        if station.station_id != primary.station_id:
            filled = filled.fillna(_interpolate_short_gaps(values(station.station_id)).reindex(hours))
    if filled.isna().any():
        raise WeatherDataError(
            f"{int(filled.isna().sum())} hours of {year} are missing at DWD station {primary.station_id} "
            f"and at all stations within {max_distance_km:g} km."
        )

    distance_km = round(float(primary.distance), 1)
    result = TemperatureYear(
        series=filled.rename("temperature"),
        source="dwd",
        station_id=primary.station_id,
        station_name=primary.name,
        distance_km=distance_km,
        coverage=round(coverage, 4),
    )
    _write_cached(folder, result, year)
    _remember(folder, key, primary.station_id, distance_km)
    return result


def _request(year: int, wd_cache: Path):
    """The ``wetterdienst`` request of the hourly temperatures around ``year``."""
    try:
        from wetterdienst import Options, Settings
        from wetterdienst.provider.dwd.observation import DwdObservationRequest
    except ImportError as e:
        raise ImportError(
            f"The DWD temperature year needs the package wetterdienst (Python >= 3.11): {INSTALL_HINT}"
        ) from e
    # one day more on both sides: the shift to CET and the interpolation at
    # the turn of the year need the neighbouring hours
    return DwdObservationRequest(
        parameters=[PARAMETER],
        start=f"{year - 1}-12-31",
        end=f"{year + 1}-01-01",
        options=Options(unit_targets={"temperature": "degree_celsius"}),  # default is Kelvin
        settings=Settings(cache_dir=wd_cache),
    )


def _stations(request, lat: float, lon: float, year: int, max_distance_km: float) -> pd.DataFrame:
    """Stations within ``max_distance_km`` that measured in ``year``, nearest first."""
    try:
        df = _to_pandas(request.filter_by_distance(latlon=(lat, lon), distance=max_distance_km).df)
    except Exception as e:  # network or API errors of wetterdienst, whatever their type
        raise WeatherDataError(f"DWD station list not available: {e}") from e
    if df.empty:
        return df
    start = pd.to_datetime(df["start_timestamp"], utc=True)
    end = pd.to_datetime(df["end_timestamp"], utc=True)
    active = (start <= pd.Timestamp(f"{year}-12-31", tz="UTC")) & (end >= pd.Timestamp(f"{year}-01-01", tz="UTC"))
    return df[active].sort_values("distance").reset_index(drop=True)


def _station_values(request, station_id: str, year: int) -> pd.Series:
    """Temperatures of one station as an hourly CET series around ``year`` (NaN = not measured)."""
    try:
        df = _to_pandas(request.filter_by_station_id(station_id=[station_id]).values().all().df)
    except Exception as e:  # network or API errors of wetterdienst, whatever their type
        raise WeatherDataError(f"DWD values of station {station_id} not available: {e}") from e
    window = pd.date_range(f"{year - 1}-12-31", f"{year + 1}-01-01 23:00", freq="h")
    if df.empty:
        return pd.Series(float("nan"), index=window)
    cet = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert(None) + CET_OFFSET
    series = pd.Series(pd.to_numeric(df["value"], errors="coerce").to_numpy(dtype=float), index=cet.to_numpy())
    return series.groupby(level=0).mean().reindex(window)


def _interpolate_short_gaps(series: pd.Series, max_gap: int = MAX_INTERPOLATION_GAP) -> pd.Series:
    """Fill gaps of at most ``max_gap`` values linearly; longer gaps stay NaN."""
    missing = series.isna()
    run = (missing != missing.shift()).cumsum()
    short = missing & (missing.groupby(run).transform("sum") <= max_gap)
    return series.where(~short, series.interpolate(limit_area="inside"))


def _to_pandas(frame) -> pd.DataFrame:
    """``wetterdienst`` returns polars frames."""
    return frame.to_pandas() if hasattr(frame, "to_pandas") else pd.DataFrame(frame)


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_atomic(path: Path, text: str) -> None:
    # several workers may share the cache: never leave a half-written file
    part = path.with_name(f"{path.name}.{os.getpid()}.part")
    part.write_text(text, encoding="utf-8")
    os.replace(part, path)


def _cache_stem(folder: Path, station_id: str, year: int) -> Path:
    return folder / f"tt_{station_id}_{year}"


def _read_cached(folder: Path, station_id: str, year: int, distance_km: float) -> Optional[TemperatureYear]:
    stem = _cache_stem(folder, station_id, year)
    meta = _read_json(stem.with_suffix(".json"))
    if not meta:
        return None
    try:
        series = pd.read_csv(stem.with_suffix(".csv"), index_col=0, parse_dates=True)["temperature"].rename_axis(None)
    except (OSError, ValueError, KeyError):
        return None
    hours = pd.date_range(f"{year}-01-01", f"{year}-12-31 23:00", freq="h")
    if not series.index.equals(hours) or series.isna().any():
        return None
    return TemperatureYear(
        series=series,
        source="dwd",
        station_id=station_id,
        station_name=meta.get("station_name"),
        distance_km=distance_km,
        coverage=float(meta.get("coverage", 0.0)),
    )


def _write_cached(folder: Path, result: TemperatureYear, year: int) -> None:
    stem = _cache_stem(folder, result.station_id, year)
    _write_atomic(stem.with_suffix(".csv"), result.series.round(2).to_csv(index_label="time"))
    meta = {
        "station_id": result.station_id,
        "station_name": result.station_name,
        "year": year,
        "coverage": result.coverage,
        "retrieved": date.today().isoformat(),
        "source": "Deutscher Wetterdienst",
    }
    _write_atomic(stem.with_suffix(".json"), json.dumps(meta, ensure_ascii=False))


def _remember(folder: Path, key: str, station_id: str, distance_km: float) -> None:
    lookup = _read_json(folder / LOOKUP_FILE)
    lookup[key] = {"station_id": station_id, "distance_km": distance_km}
    _write_atomic(folder / LOOKUP_FILE, json.dumps(lookup))
