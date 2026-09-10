"""Expert backend: network topology from topotherm's single-time-step (STS) MILP.

Division of labour
------------------
topotherm decides **topology only**: which street segments are built and which
buildings are connected. Everything downstream — simultaneity factor (GLF),
volume flow, DN, velocity and heat losses — is computed by fheat_core with the
*same* functions the Phase-0 backend uses, so the two modes stay comparable and
the German export labels keep their meaning.
"""
from __future__ import annotations

import logging

import geopandas as gpd
import networkx as nx
import numpy as np
from shapely.geometry import LineString

from fheat_core import columns as cols
from fheat_core.algorithms.network import (
    calculate_diameter_velocity_loss,
    calculate_glf,
    calculate_volumeflow,
)
from fheat_core.network.base import NetworkBackend, NetworkBackendError
from fheat_core.resources import load_pipe_info

logger = logging.getLogger(__name__)

_MIN_SOURCE_OFFSET = 1e-3  # m — below this a source is treated as "on the road"


def _require_topotherm():
    """Import topotherm with an actionable error message."""
    try:
        import topotherm as tt  # noqa: F401
    except SyntaxError as exc:  # PEP 701 f-string in topotherm 0.6.0
        raise NetworkBackendError(
            "topotherm 0.6.0 cannot be imported on this Python version "
            f"({exc}). The expert mode requires Python >= 3.12. "
            'Install with: pip install -e ".[topotherm]" on a 3.12+ interpreter.'
        ) from exc
    except ImportError as exc:
        raise NetworkBackendError(
            "The expert mode requires topotherm. Install it with: "
            'pip install -e ".[topotherm]"'
        ) from exc
    import topotherm as tt

    return tt


def _as_2d_float(arr) -> np.ndarray:
    """Coerce topotherm's object-dtype matrices to (rows, timesteps) float."""
    a = np.asarray(arr)
    if a.dtype == object:
        a = np.vstack([np.atleast_1d(np.asarray(x, dtype=float)) for x in a])
    else:
        a = np.asarray(a, dtype=float)
    return a.reshape(a.shape[0], -1)


class TopothermBackend(NetworkBackend):
    """Network generation via topotherm's STS optimisation."""

    name = "expert"

    # -- public ---------------------------------------------------------

    def build(self, buildings, streets, source, config, adapter):
        tt = _require_topotherm()
        tcfg = config.topotherm

        pipe_info = adapter.provide_pipe_info()
        if pipe_info is None:
            pipe_info = load_pipe_info()

        sinks, roads, srcs = self._to_topotherm_inputs(buildings, streets, source)
        mat, gdf_nodes = self._build_matrices(tt, sinks, roads, srcs, buildings.crs, tcfg)
        settings = self._build_settings(tt, config)
        model, opt_mats = self._solve(tt, mat, settings, tcfg)
        nodes_df, edges_df = tt.postprocessing.to_dataframe(opt_mats, mat)

        net_gdf = self._to_net_gdf(edges_df, nodes_df, buildings, pipe_info, config)
        buildings = self._writeback_connect(buildings, edges_df, nodes_df)
        return net_gdf, buildings

    # -- step 1: FHeat frames -> topotherm frames -------------------------

    @staticmethod
    def _to_topotherm_inputs(buildings, streets, source):
        """Map canonical FHeat columns onto topotherm's ts_/flh_ contract.

        The *undiversified* thermal power goes in as ``ts_0`` — the GLF is
        deliberately not applied here (it is a post-processing concern).
        """
        if cols.ROUTABLE in streets.columns:
            streets = streets[streets[cols.ROUTABLE] == 1]
        if streets.empty:
            raise NetworkBackendError("No routable streets left for the expert mode.")

        sinks = gpd.GeoDataFrame(
            {
                "ts_0": buildings[cols.THERMAL_POWER].astype(float).values,
                "flh_0": buildings[cols.FULL_LOAD_HOURS].astype(float).values,
            },
            geometry=buildings.geometry.values,
            crs=buildings.crs,
        )
        roads = streets[["geometry"]].copy()
        srcs = source[["geometry"]].copy()
        if srcs.crs != buildings.crs:
            srcs = srcs.to_crs(buildings.crs)

        # topotherm matches nodes by exact coordinate; a source sitting on a road
        # vertex produces two candidate nodes and silently drops the edge.
        road_union = roads.geometry.union_all()
        on_road = srcs.geometry.distance(road_union) < _MIN_SOURCE_OFFSET
        if bool(on_road.any()):
            raise NetworkBackendError(
                "The heat source lies exactly on the street network. topotherm "
                "cannot resolve the resulting duplicate node. Move the source "
                f"point at least {_MIN_SOURCE_OFFSET} m off the street geometry."
            )
        return sinks, roads, srcs

    # -- step 2: incidence matrices ---------------------------------------

    @staticmethod
    def _build_matrices(tt, sinks, roads, srcs, crs, tcfg):
        gdf_nodes, gdf_edges = tt.create_matrices.connect_sinks_from_gdfs(
            sinks=sinks,
            roads=roads,
            sources=srcs,
            buffer=tcfg.connection_buffer,
            crs=crs,
        )
        unmatched = int((gdf_edges["u"] == "").sum() + (gdf_edges["v"] == "").sum())
        if unmatched:
            raise NetworkBackendError(
                f"{unmatched} edge endpoints could not be matched to a node. "
                "This usually means duplicate or coincident geometries in the "
                "street/source input."
            )
        mat, gdf_nodes, _ = tt.create_matrices.create_matrices_from_gdf(gdf_nodes, gdf_edges)

        # topotherm returns object arrays here; the model needs 2-D floats.
        mat["q_c"] = _as_2d_float(mat["q_c"])
        mat["flh_sinks"] = _as_2d_float(mat["flh_sinks"])
        mat["l_i"] = np.asarray(mat["l_i"], dtype=float)
        n_src = mat["a_p"].shape[1]
        weighted = (mat["q_c"] * mat["flh_sinks"]).sum(axis=0) / mat["q_c"].sum(axis=0)
        mat["flh_sources"] = np.tile(np.round(weighted, 2), (n_src, 1))
        return mat, gdf_nodes

    # -- step 3: FHeatConfig -> topotherm Settings -------------------------

    @staticmethod
    def _build_settings(tt, config):
        tcfg = config.topotherm
        if tcfg.settings_yaml:
            settings = tt.settings.load(tcfg.settings_yaml)
        else:
            settings = tt.settings.Settings()

        # FHeatConfig stays the single source of truth for the temperatures.
        settings.temperatures.supply = float(config.supply_temperature)
        settings.temperatures.return_ = float(config.return_temperature)
        settings.temperatures.ambient = float(tcfg.ambient_temperature)

        settings.ground.thermal_conductivity = float(tcfg.ground_thermal_conductivity)
        settings.piping.max_pr_loss = float(tcfg.max_pressure_loss)
        settings.piping.depth = float(tcfg.pipe_depth)
        settings.piping.roughness = float(tcfg.pipe_roughness)

        settings.solver.mip_gap = float(tcfg.mip_gap)
        settings.solver.time_limit = int(tcfg.time_limit)

        e = settings.economics
        e.heat_price = float(tcfg.heat_price)
        e.source_price = [[float(tcfg.source_price)]]
        e.source_c_inv = [float(tcfg.source_c_inv)]
        e.source_c_irr = [float(tcfg.source_c_irr)]
        e.source_lifetime = [float(tcfg.source_lifetime)]
        e.source_max_power = [float(tcfg.source_max_power)]
        e.pipes_c_irr = float(tcfg.pipes_c_irr)
        e.pipes_lifetime = float(tcfg.pipes_lifetime)
        return settings

    # -- step 4: solve -----------------------------------------------------

    @staticmethod
    def _solve(tt, mat, settings, tcfg):
        import pyomo.environ as pyo

        r_cap = tt.hydraulic.regression_thermal_capacity(settings)
        r_loss = tt.hydraulic.regression_heat_losses(settings, r_cap)
        logger.info(
            "topotherm regression R²: capacity %.4f, losses %.4f",
            float(r_cap["r2"]),
            float(r_loss["r2"]),
        )

        model = tt.models.single_timestep.create(
            matrices=mat,
            sets=tt.models.sets.create(mat),
            economics=settings.economics,
            optimization_mode=tcfg.optimization_mode,
            regression_inst=r_cap,
            regression_losses=r_loss,
        )
        opt = pyo.SolverFactory(tcfg.solver)
        if not opt.available(False):
            raise NetworkBackendError(
                f"Solver '{tcfg.solver}' is not available. Install a MILP solver, "
                "e.g. `pip install highspy` for the open-source HiGHS solver."
            )
        opt.options["mipgap"] = settings.solver.mip_gap
        opt.options["timelimit"] = settings.solver.time_limit
        result = opt.solve(model, tee=False)

        cond = result.solver.termination_condition
        if cond != pyo.TerminationCondition.optimal:
            raise NetworkBackendError(f"topotherm optimisation failed: {cond}")

        try:
            opt_mats = tt.postprocessing.sts(model=model, matrices=mat, settings=settings)
        except ValueError as exc:
            raise NetworkBackendError(
                "topotherm built an empty network — in 'economic' mode no "
                "connection was profitable. Raise `heat_price`, lower "
                "`source_price`/`pipes_c_irr`, or use optimization_mode='forced'."
            ) from exc
        if np.asarray(opt_mats["p"]).size == 0 or np.asarray(opt_mats["q_c"]).size == 0:
            raise NetworkBackendError(
                "topotherm built an empty network — in 'economic' mode no "
                "connection was profitable. Raise `heat_price`, lower "
                "`source_price`/`pipes_c_irr`, or use optimization_mode='forced'."
            )
        return model, opt_mats

    # -- step 5: topotherm result -> NetSchema ------------------------------

    @staticmethod
    def _to_net_gdf(edges_df, nodes_df, buildings, pipe_info, config):
        """Apply FHeat's own GLF + sizing to topotherm's topology."""
        # downstream building count per edge (topotherm's a_i is directed)
        G = nx.DiGraph()
        for i, r in edges_df.iterrows():
            G.add_edge(int(r["start_node"]), int(r["end_node"]), idx=i)
        sink_nodes = set(nodes_df.index[nodes_df["type_"] == "sink"])
        n_bld = np.array(
            [
                len(({int(r["end_node"])} | nx.descendants(G, int(r["end_node"]))) & sink_nodes)
                for _, r in edges_df.iterrows()
            ],
            dtype=int,
        ).clip(min=1)

        power = edges_df["power"].to_numpy(float)      # kW, undiversified
        length = edges_df["length"].to_numpy(float)    # m
        edge_type = np.where(
            edges_df["to_consumer"].to_numpy(), "Hausanschluss", "Straßenleitung"
        )

        glf = np.array([calculate_glf(int(n)) for n in n_bld])
        power_glf = power * glf

        dn, vel, loss, loss_extra, vflow = [], [], [], [], []
        for p_glf, ln, et in zip(power_glf, length, edge_type):
            vf = calculate_volumeflow(
                p_glf, config.supply_temperature, config.return_temperature
            )
            d, v, l1, l2 = calculate_diameter_velocity_loss(
                vf,
                config.supply_temperature,
                config.return_temperature,
                ln,
                pipe_info,
                et,
            )
            vflow.append(vf)
            dn.append(d)
            vel.append(v)
            loss.append(l1)
            loss_extra.append(l2)

        geom = [
            LineString([(r["x_start"], r["y_start"]), (r["x_end"], r["y_end"])])
            for _, r in edges_df.iterrows()
        ]
        return gpd.GeoDataFrame(
            {
                cols.TYPE: edge_type,
                cols.LENGTH: length,
                cols.THERMAL_POWER: power,
                cols.N_BUILDINGS: n_bld,
                cols.GLF: glf,
                cols.THERMAL_POWER_GLF: power_glf,
                cols.VOLUME_FLOW: np.asarray(vflow, dtype=float),
                # DN is passed through *uncast*: fheat's pipe catalogue labels
                # rows "PEX 50" / "KMR 100", so this column is a string in
                # phase 0 too. Coercing to float breaks on the real catalogue.
                cols.NOMINAL_DIAMETER: dn,
                cols.VELOCITY: np.asarray(vel, dtype=float),
                cols.HEAT_LOSS: np.asarray(loss, dtype=float),
                cols.HEAT_LOSS_EXTRA_INSULATION: np.asarray(loss_extra, dtype=float),
            },
            geometry=geom,
            crs=buildings.crs,
        )

    # -- step 6: economic mode may drop buildings ---------------------------

    @staticmethod
    def _writeback_connect(buildings, edges_df, nodes_df):
        """Set connect=0 for buildings topotherm chose not to connect."""
        connected_pts = nodes_df.loc[nodes_df["type_"] == "sink", ["x", "y"]].to_numpy(float)
        if connected_pts.size == 0:
            raise NetworkBackendError(
                "topotherm built an empty network — no building was connected."
            )
        centroids = np.column_stack(
            [buildings.geometry.centroid.x.values, buildings.geometry.centroid.y.values]
        )
        d = np.linalg.norm(centroids[:, None, :] - connected_pts[None, :, :], axis=2)
        is_connected = (d.min(axis=1) < 1e-6).astype(int)

        out = buildings.copy()
        dropped = int((out[cols.CONNECT].to_numpy(int) == 1).sum() - is_connected.sum())
        out[cols.CONNECT] = is_connected
        if dropped > 0:
            logger.info("topotherm (economic) left %d building(s) unconnected.", dropped)
        return out
