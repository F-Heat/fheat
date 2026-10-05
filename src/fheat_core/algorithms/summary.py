"""Result tables: pipe quantities per DN and connected buildings per load profile.

They reproduce the result overview of the former F|Heat QGIS plugin
(``summarize_pipes`` in ``net_analysis.py``) on canonical column names.
"""
from __future__ import annotations

import pandas as pd

from fheat_core import columns as cols

# Fixed row order of the building summary; further profiles are appended.
LOAD_PROFILE_ORDER = ("EFH", "MFH", "GHA", "GMK", "GKO")

_PIPE_VALUE_COLUMNS = [
    cols.N_HOUSE_CONNECTIONS,
    cols.HOUSE_CONNECTION_LENGTH,
    cols.ROUTE_LENGTH,
    cols.HEAT_LOSS_MWH,
    cols.HEAT_LOSS_EXTRA_INSULATION_MWH,
]


def _numeric(df: pd.DataFrame, column: str) -> pd.Series:
    """Column as float with missing values (or a missing column) counted as 0."""
    if column not in df.columns:
        return pd.Series(0.0, index=df.index)
    return pd.to_numeric(df[column], errors="coerce").fillna(0.0)


def _is_house_connection(net: pd.DataFrame) -> pd.Series:
    if cols.TYPE not in net.columns:
        return pd.Series(False, index=net.index)
    return net[cols.TYPE] == cols.EDGE_TYPE_HOUSE_CONNECTION


def summarize_pipes(net_gdf: pd.DataFrame | None, pipe_info: pd.DataFrame | None) -> pd.DataFrame:
    """Pipe quantities per nominal diameter.

    One row per DN of the pipe catalogue, in catalogue order and including
    unused diameters (all zero). Diameters that occur in the net but not in
    the catalogue are appended in order of appearance; edges without a DN
    are ignored.

    House connections are edges of type ``Hausanschluss``; every other edge
    (street pipe, source connection) counts as route. The connection count is
    the number of house-connection edges, as in the QGIS plugin. In phase 0 a
    building the router cannot reach gets no edge, so the count can be lower
    than the number of connected buildings.
    """
    catalogue = list(pipe_info["DN"]) if pipe_info is not None and "DN" in pipe_info.columns else []

    if net_gdf is None or net_gdf.empty or cols.NOMINAL_DIAMETER not in net_gdf.columns:
        edges = pd.DataFrame(columns=[cols.NOMINAL_DIAMETER, *_PIPE_VALUE_COLUMNS])
    else:
        net = net_gdf[net_gdf[cols.NOMINAL_DIAMETER].notna()]
        house = _is_house_connection(net)
        length = _numeric(net, cols.LENGTH)
        edges = pd.DataFrame(
            {
                cols.NOMINAL_DIAMETER: net[cols.NOMINAL_DIAMETER].to_numpy(),
                cols.N_HOUSE_CONNECTIONS: house.astype(int).to_numpy(),
                cols.HOUSE_CONNECTION_LENGTH: length.where(house, 0.0).to_numpy(),
                cols.ROUTE_LENGTH: length.where(~house, 0.0).to_numpy(),
                cols.HEAT_LOSS_MWH: (_numeric(net, cols.HEAT_LOSS) / 1000).to_numpy(),
                cols.HEAT_LOSS_EXTRA_INSULATION_MWH: (
                    _numeric(net, cols.HEAT_LOSS_EXTRA_INSULATION) / 1000
                ).to_numpy(),
            }
        )

    order = list(dict.fromkeys([*catalogue, *pd.unique(edges[cols.NOMINAL_DIAMETER])]))
    totals = edges.groupby(cols.NOMINAL_DIAMETER, sort=False)[_PIPE_VALUE_COLUMNS].sum()
    result = totals.reindex(pd.Index(order, name=cols.NOMINAL_DIAMETER), fill_value=0).reset_index()

    result[cols.N_HOUSE_CONNECTIONS] = result[cols.N_HOUSE_CONNECTIONS].astype(int)
    for column in _PIPE_VALUE_COLUMNS[1:]:
        result[column] = result[column].astype(float)
    return result


def summarize_buildings(buildings_gdf: pd.DataFrame) -> pd.DataFrame:
    """Number and heat demand [MWh/a] of buildings per load profile.

    Expects buildings already filtered to ``connect == 1``. Rows follow
    ``LOAD_PROFILE_ORDER`` (missing profiles as zero), further profiles are
    appended alphabetically. Buildings without a profile form a last row with
    ``load_profile = NA`` so that the counts always add up to the building
    total of the result summary.
    """
    if cols.LOAD_PROFILE in buildings_gdf.columns:
        profile = buildings_gdf[cols.LOAD_PROFILE].astype(object)
    else:
        profile = pd.Series(pd.NA, index=buildings_gdf.index, dtype=object)
    demand = _numeric(buildings_gdf, cols.HEAT_DEMAND) / 1000

    missing = profile.isna()
    known = profile[~missing]
    counts = known.value_counts()
    demand_by_profile = demand[~missing].groupby(known).sum()
    others = sorted(set(counts.index) - set(LOAD_PROFILE_ORDER), key=str)

    rows = [
        (name, int(counts.get(name, 0)), float(demand_by_profile.get(name, 0.0)))
        for name in [*LOAD_PROFILE_ORDER, *others]
    ]
    if missing.any():
        rows.append((pd.NA, int(missing.sum()), float(demand[missing].sum())))
    return pd.DataFrame(rows, columns=[cols.LOAD_PROFILE, cols.N_BUILDINGS, cols.HEAT_DEMAND_MWH])


def network_length_split(net_gdf: pd.DataFrame | None) -> tuple[float, float]:
    """House connection length and route length [m] over all edges.

    Unlike :func:`summarize_pipes` no edge is skipped, so both values always
    add up to the total network length.
    """
    if net_gdf is None or net_gdf.empty:
        return 0.0, 0.0
    length = _numeric(net_gdf, cols.LENGTH)
    house = _is_house_connection(net_gdf)
    return float(length[house].sum()), float(length[~house].sum())
