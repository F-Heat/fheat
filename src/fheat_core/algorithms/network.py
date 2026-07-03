"""Network analysis: GLF, volumeflow, pipe sizing, shortest-path network."""
from __future__ import annotations

import numpy as np
import geopandas as gpd
import networkx as nx
import pandas as pd
from shapely.geometry import LineString, Point

from fheat_core import columns as cols


def calculate_glf(n: int) -> float:
    a, b, c, d = 0.4497, 0.5512, 53.8483, 1.7627
    return a + (b / (1 + pow(n / c, d)))


def calculate_volumeflow(kw_glf: float, htemp: float, ltemp: float) -> float:
    t = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    d = [0.99984, 0.9997, 0.99821, 0.99565, 0.99222, 0.98803, 0.9832, 0.97778, 0.97182, 0.96535, 0.9584]
    c = [4.2176, 4.1921, 4.1818, 4.1784, 4.1785, 4.1806, 4.1843, 4.1895, 4.1963, 4.205, 4.2159]
    density = np.interp(int(htemp), t, d)
    cp = np.interp(int(htemp), t, c)
    return kw_glf / (density * cp * (int(htemp) - int(ltemp)))


def calculate_diameter_velocity_loss(
    volumeflow: float,
    htemp: float,
    ltemp: float,
    length: float,
    pipe_info: pd.DataFrame,
    edge_type: str,
) -> tuple[float, float, float, float]:
    start_index = 0 if edge_type == "Hausanschluss" else 2
    idx = pipe_info["max_volumeFlow"][start_index:].searchsorted(volumeflow, side="right") + start_index
    if idx >= len(pipe_info):
        idx = len(pipe_info) - 1
    d_i = pipe_info["di"].iloc[idx]
    dn = pipe_info["DN"].iloc[idx]
    u = pipe_info["U-Value"].iloc[idx]
    u_extra = pipe_info["U-Value_extra_insulation"].iloc[idx]
    r = d_i / 2
    velocity = volumeflow * 1000 / (np.pi * pow(r, 2))
    mtemp = (htemp + ltemp) / 2
    K = mtemp - 10
    loss = 8760 * 2 * (u * K * length) / 1000
    loss_extra = 8760 * 2 * (u_extra * K * length) / 1000
    return dn, velocity, loss, loss_extra


def build_street_graph(streets_gdf: gpd.GeoDataFrame, crs) -> nx.Graph:
    G = nx.Graph()
    for _, row in streets_gdf.iterrows():
        line = row["geometry"]
        coords = (
            [coord for geom in line.geoms for coord in geom.coords]
            if line.geom_type == "MultiLineString"
            else list(line.coords)
        )
        for i in range(len(coords)):
            G.add_node(coords[i])
            if i > 0:
                G.add_edge(coords[i - 1], coords[i], **{cols.TYPE: "Straßenleitung"})
    return G


def connect_buildings_to_graph(G: nx.Graph, buildings_gdf: gpd.GeoDataFrame) -> nx.Graph:
    for _, row in buildings_gdf.iterrows():
        centroid = row[cols.CENTROID]
        cp = row.get(cols.CONNECTION_POINT)
        if cp is not None and not (hasattr(cp, "__class__") and cp.__class__.__name__ == "float"):
            G.add_edge(centroid.coords[0], (cp.x, cp.y), **{cols.TYPE: "Hausanschluss"})
    return G


def connect_source_to_graph(G: nx.Graph, source_gdf: gpd.GeoDataFrame) -> nx.Graph:
    for _, row in source_gdf.iterrows():
        src = row["geometry"]
        cp = row.get(cols.CONNECTION_POINT)
        if cp is not None and not (hasattr(cp, "__class__") and cp.__class__.__name__ == "float"):
            G.add_edge(src.coords[0], (cp.x, cp.y), **{cols.TYPE: "Quellenanschluss"})
    return G


def add_edge_lengths(G: nx.Graph) -> nx.Graph:
    for u, v in G.edges():
        G.edges[u, v][cols.LENGTH] = LineString([u, v]).length
    return G


def compute_network(
    G: nx.Graph,
    buildings_gdf: gpd.GeoDataFrame,
    source_gdf: gpd.GeoDataFrame,
    pipe_info: pd.DataFrame,
    power_att: str,
    htemp: float,
    ltemp: float,
    crs,
) -> gpd.GeoDataFrame:
    net = nx.Graph()
    start = (source_gdf["geometry"].iloc[0].x, source_gdf["geometry"].iloc[0].y)

    for _, row in buildings_gdf.iterrows():
        end = (row[cols.CENTROID].x, row[cols.CENTROID].y)
        power = row[power_att]
        try:
            path = nx.shortest_path(G, start, end, weight=cols.LENGTH)
        except Exception:
            continue
        for i in range(len(path) - 1):
            u, v = path[i], path[i + 1]
            net.add_edge(u, v, **G.edges[u, v])
            _update(net, u, v, power, cols.THERMAL_POWER)
            _update(net, u, v, 1, cols.N_BUILDINGS)

    # add GLF, diameter, velocity, loss attributes (canonical column names)
    for u, v, data in net.edges(data=True):
        n = data.get(cols.N_BUILDINGS, 1)
        p = data.get(cols.THERMAL_POWER, 0.0)
        length = data.get(cols.LENGTH, 0.0)
        edge_type = data.get(cols.TYPE, "Straßenleitung")
        glf = calculate_glf(n)
        p_glf = p * glf
        vf = calculate_volumeflow(p_glf, htemp, ltemp)
        dn, vel, loss, loss_extra = calculate_diameter_velocity_loss(vf, htemp, ltemp, length, pipe_info, edge_type)
        data.update({
            cols.GLF: glf,
            cols.THERMAL_POWER_GLF: p_glf,
            cols.VOLUME_FLOW: vf,
            cols.NOMINAL_DIAMETER: dn,
            cols.VELOCITY: vel,
            cols.HEAT_LOSS: loss,
            cols.HEAT_LOSS_EXTRA_INSULATION: loss_extra,
        })

    geometries, attrs = [], {}
    for u, v, data in net.edges(data=True):
        geometries.append(LineString([u, v]))
        for k, val in data.items():
            attrs.setdefault(k, []).append(val)

    return gpd.GeoDataFrame(attrs, geometry=geometries, crs=crs)


def _update(G: nx.Graph, u, v, val, name: str) -> None:
    if name in G.edges[u, v]:
        G.edges[u, v][name] += val
    else:
        G.edges[u, v][name] = val
