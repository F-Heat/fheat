"""Expert backend: network topology from topotherm's single-time-step (STS) MILP.

Division of labour
------------------
topotherm decides **topology only**: which street segments are built and which
buildings are connected. Everything downstream — simultaneity factor (GLF),
volume flow, DN, velocity and heat losses — is computed by fheat_core with the
*same* functions the Phase-0 backend uses, so the two modes stay comparable and
the German export labels keep their meaning.

Civil works
-----------
With civil works layers, every candidate edge k gets its civil works factor
f_k and the multiplier m_k = (1 − s) + s·f_k (s = ``civil_cost_share``). m_k
scales topotherm's pipe cost term of that edge, so the MILP avoids expensive
routes. The factors of the built edges are handed on to the net; without
layers the model is topotherm's own, unchanged.
"""
from __future__ import annotations

import logging

import geopandas as gpd
import networkx as nx
import numpy as np
from shapely.geometry import LineString

from fheat_core import columns as cols
from fheat_core.algorithms.civil_cost import civil_factors_for_lines, cost_multiplier, usable_layers
from fheat_core.algorithms.network import (
    calculate_diameter_velocity_loss,
    calculate_glf,
    calculate_volumeflow,
)
from fheat_core.network.base import (
    EMPTY_NETWORK,
    NO_OPTIMAL_SOLUTION,
    NO_ROUTABLE_STREETS,
    SOLVER_UNAVAILABLE,
    SOURCE_ON_STREET,
    TIME_LIMIT,
    TOPOTHERM_UNAVAILABLE,
    UNMATCHED_NODES,
    NetworkBackend,
    NetworkBackendError,
)
from fheat_core.resources import resolve_pipe_info

logger = logging.getLogger(__name__)

_MIN_SOURCE_OFFSET = 1e-3  # m — below this a source is treated as "on the road"


# topotherm is not on PyPI, so the [topotherm] extra deliberately does not name
# it (see pyproject.toml) — it ships only the solver and the pandas pin. The
# install must be EDITABLE: topotherm 0.6.0 declares packages = ["topotherm"],
# omitting topotherm.models, so a regular install is importable-but-broken.
_INSTALL_HINT = (
    "Install it with: pip install --editable "
    '"git+https://github.com/jylambert/topotherm@v0.6.0#egg=topotherm" '
    "--src <dir outside this repo>, on a Python 3.12 interpreter. The "
    "--editable is required: a regular install omits topotherm.models."
)


def _require_topotherm():
    """Import topotherm with an actionable error message."""
    try:
        import topotherm as tt  # noqa: F401
    except SyntaxError as exc:  # PEP 701 f-string in topotherm 0.6.0
        raise NetworkBackendError(
            "topotherm 0.6.0 cannot be imported on this Python version "
            f"({exc}). The expert mode requires Python 3.12 — 3.10/3.11 hit "
            "this SyntaxError, and topotherm's own requires-python bound "
            '("<=3.13") excludes 3.13.1 and newer. ' + _INSTALL_HINT,
            code=TOPOTHERM_UNAVAILABLE,
        ) from exc
    except ImportError as exc:
        raise NetworkBackendError(
            "The expert mode requires topotherm. " + _INSTALL_HINT,
            code=TOPOTHERM_UNAVAILABLE,
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


def _weigh_pipe_capex(model, mat, regression_inst, economics) -> None:
    """Replace topotherm's pipe CAPEX constraint by one weighted with mat["civil_m"].

    topotherm 0.6.0 prices every candidate edge k with (a·P_k + b·λ_k)·l_k in
    ``model.capex_pipe_constr`` (single time step 0, P indexed
    [dir, "in", k, t], lambda_ indexed [dir, k]). The civil works multiplier
    m_k scales that whole term — the same m the net's pipe_cost uses. The
    regression a, b itself stays topotherm's.
    """
    import pyomo.environ as pyo
    from topotherm.models.calc import annuity

    a = float(regression_inst["a"])
    b = float(regression_inst["b"])
    # plain floats: numpy scalars on the left of a pyomo expression misbehave
    l_i = [float(v) for v in np.asarray(mat["l_i"], dtype=float)]
    m = [float(v) for v in np.asarray(mat["civil_m"], dtype=float)]
    pipe_annuity = float(annuity(economics.pipes_c_irr, economics.pipes_lifetime))

    def _rule(mdl):
        return mdl.capex_pipes == sum(
            (
                a * (mdl.P["ij", "in", k, 0] + mdl.P["ji", "in", k, 0])
                + b * (mdl.lambda_["ij", k] + mdl.lambda_["ji", k])
            )
            * l_i[k]
            * m[k]
            for k in mdl.set_n_i
        ) * pipe_annuity

    model.del_component(model.capex_pipe_constr)
    model.capex_pipe_constr = pyo.Constraint(rule=_rule, doc="CAPEX Pipe (civil works weighted)")


class TopothermBackend(NetworkBackend):
    """Network generation via topotherm's STS optimisation."""

    name = "expert"

    # -- public ---------------------------------------------------------

    def build(self, buildings, streets, source, config, adapter, civil_layers=None):
        tt = _require_topotherm()
        tcfg = config.topotherm

        pipe_info = resolve_pipe_info(adapter)

        sinks, roads, srcs = self._to_topotherm_inputs(buildings, streets, source)
        mat, gdf_nodes, gdf_edges = self._build_matrices(tt, sinks, roads, srcs, buildings.crs, tcfg)
        civil = self._candidate_civil_factors(mat, gdf_edges, civil_layers, buildings.crs, config)
        settings = self._build_settings(tt, config)
        model, opt_mats = self._solve(tt, mat, settings, tcfg)
        nodes_df, edges_df = tt.postprocessing.to_dataframe(opt_mats, mat)

        net_gdf = self._to_net_gdf(
            edges_df, nodes_df, buildings, pipe_info, config,
            civil=self._result_civil(civil, opt_mats, mat, edges_df),
        )
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
            raise NetworkBackendError(
                "No routable streets left for the expert mode.", code=NO_ROUTABLE_STREETS
            )

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
                f"point at least {_MIN_SOURCE_OFFSET} m off the street geometry.",
                code=SOURCE_ON_STREET,
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
                "street/source input.",
                code=UNMATCHED_NODES,
            )
        # topotherm drops duplicate candidate edges here; the gdf_edges it
        # returns stays aligned with the matrices: mat["l_i"][k] and column k
        # of a_i belong to gdf_edges.iloc[k] (topotherm 0.6.0).
        mat, gdf_nodes, gdf_edges = tt.create_matrices.create_matrices_from_gdf(gdf_nodes, gdf_edges)

        # topotherm returns object arrays here; the model needs 2-D floats.
        mat["q_c"] = _as_2d_float(mat["q_c"])
        mat["flh_sinks"] = _as_2d_float(mat["flh_sinks"])
        mat["l_i"] = np.asarray(mat["l_i"], dtype=float)
        n_src = mat["a_p"].shape[1]
        weighted = (mat["q_c"] * mat["flh_sinks"]).sum(axis=0) / mat["q_c"].sum(axis=0)
        mat["flh_sources"] = np.tile(np.round(weighted, 2), (n_src, 1))
        return mat, gdf_nodes, gdf_edges

    @staticmethod
    def _candidate_civil_factors(mat, gdf_edges, civil_layers, crs, config):
        """Civil works factor per candidate edge, stored as mat["civil_f"] / ["civil_m"].

        Returns the factors and surfaces in candidate order, or None without
        usable layers — then mat is left untouched and the model stays
        topotherm's own.
        """
        if not usable_layers(civil_layers):
            return None
        lines = gdf_edges.geometry.reset_index(drop=True)
        l_i = np.asarray(mat["l_i"], dtype=float)
        if len(lines) != len(l_i) or not np.allclose(lines.length.to_numpy(), l_i, rtol=1e-6, atol=1e-6):
            logger.warning(
                "topotherm's candidate edges do not match its matrices; the routes "
                "are chosen without civil works factors."
            )
            return None
        civil = civil_factors_for_lines(lines, civil_layers, crs=crs)
        factor = civil[cols.CIVIL_COST_FACTOR].to_numpy(dtype=float)
        mat["civil_f"] = factor
        mat["civil_m"] = np.atleast_1d(cost_multiplier(factor, config.civil_cost_share))
        return civil

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
        if "civil_m" in mat:
            _weigh_pipe_capex(model, mat, r_cap, settings.economics)
        opt = pyo.SolverFactory(tcfg.solver)
        if not opt.available(False):
            raise NetworkBackendError(
                f"Solver '{tcfg.solver}' is not available. Install a MILP solver, "
                "e.g. `pip install highspy` for the open-source HiGHS solver.",
                code=SOLVER_UNAVAILABLE,
            )
        opt.options["mipgap"] = settings.solver.mip_gap
        opt.options["timelimit"] = settings.solver.time_limit
        result = opt.solve(model, tee=False)

        cond = result.solver.termination_condition
        if cond != pyo.TerminationCondition.optimal:
            code = TIME_LIMIT if cond == pyo.TerminationCondition.maxTimeLimit else NO_OPTIMAL_SOLUTION
            raise NetworkBackendError(f"topotherm optimisation failed: {cond}", code=code)

        try:
            opt_mats = tt.postprocessing.sts(model=model, matrices=mat, settings=settings)
        except ValueError as exc:
            raise NetworkBackendError(
                "topotherm built an empty network — in 'economic' mode no "
                "connection was profitable. Raise `heat_price`, lower "
                "`source_price`/`pipes_c_irr`, or use optimization_mode='forced'.",
                code=EMPTY_NETWORK,
            ) from exc
        if np.asarray(opt_mats["p"]).size == 0 or np.asarray(opt_mats["q_c"]).size == 0:
            raise NetworkBackendError(
                "topotherm built an empty network — in 'economic' mode no "
                "connection was profitable. Raise `heat_price`, lower "
                "`source_price`/`pipes_c_irr`, or use optimization_mode='forced'.",
                code=EMPTY_NETWORK,
            )
        return model, opt_mats

    # -- step 5: topotherm result -> NetSchema ------------------------------

    @staticmethod
    def _result_civil(civil, opt_mats, mat, edges_df):
        """Civil works factors of the built edges, in the order of ``edges_df``.

        topotherm's postprocessing keeps the built candidate edges in their
        order: those with lambda_ij or lambda_ji set (``lambda_b_orig`` != 0).
        None without layers, or when that mapping does not add up — the step
        then intersects the result lines instead.
        """
        if civil is None:
            return None
        kept = np.flatnonzero(np.asarray(opt_mats["lambda_b_orig"], dtype=float).ravel() != 0)
        lengths = np.asarray(mat["l_i"], dtype=float)
        if len(kept) != len(edges_df) or not np.allclose(
            lengths[kept], edges_df["length"].to_numpy(float), rtol=1e-6, atol=1e-6
        ):
            logger.warning(
                "Could not map topotherm's built edges to their candidates; the civil "
                "works factors are taken from the result lines instead."
            )
            return None
        return civil.iloc[kept].reset_index(drop=True)

    @staticmethod
    def _to_net_gdf(edges_df, nodes_df, buildings, pipe_info, config, civil=None):
        """Apply FHeat's own GLF + sizing to topotherm's topology.

        ``civil`` (from :meth:`_result_civil`) adds the civil works factor and
        road surface the optimisation used for each edge.
        """
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
            edges_df["to_consumer"].to_numpy(), cols.EDGE_TYPE_HOUSE_CONNECTION, "Straßenleitung"
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
        civil_columns = {}
        if civil is not None:
            civil_columns = {
                cols.CIVIL_COST_FACTOR: civil[cols.CIVIL_COST_FACTOR].to_numpy(dtype=float),
                cols.ROAD_SURFACE: civil[cols.ROAD_SURFACE].to_numpy(),
            }
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
                **civil_columns,
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
                "topotherm built an empty network — no building was connected.",
                code=EMPTY_NETWORK,
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
