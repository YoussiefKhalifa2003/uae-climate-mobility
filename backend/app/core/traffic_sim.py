"""Module 3 - GPU-vectorized traffic + emissions simulation.

Thousands of agents flow along precomputed shortest-path corridors on the OSM
road graph. All per-frame math (position interpolation, congestion density,
emissions) is fully vectorized through ``compute.xp`` so it runs on the RTX
4080 Super when CuPy is present (NumPy fallback otherwise).

State is kept as padded route matrices so every agent updates in a handful of
array ops regardless of how many agents there are.

Outputs:
  * a compact Float32 frame ``[lon, lat, speed_norm, emission_norm] * N`` for
    the WebSocket stream, and
  * a coarse emission grid consumed by the air-quality engine.
"""

from __future__ import annotations

import logging
import random

import numpy as np

from app.config import settings
from app.core import compute
from app.core.geo_engine import get_geo

logger = logging.getLogger(__name__)

# Coarse congestion / emission grid resolution (cells per axis).
_GRID = 128
# Congestion model.
_CAP = 6.0  # agents per cell before slowdown begins
_SLOW_K = 0.06  # slowdown per excess agent
_MIN_SPEED_FACTOR = 0.12
_EMISSION_BASE = 1.0
_EMISSION_CONGESTION = 4.0  # stop-go traffic emits far more
_EMISSION_DECAY = 0.82  # temporal smoothing of the emission grid


class TrafficSim:
    def __init__(self, n_agents: int | None = None, n_routes: int = 420):
        self.n = int(n_agents or settings.agent_count)
        self.n_routes = n_routes
        self._build()

    # ----------------------------------------------------------- build
    def _build(self) -> None:
        xp = compute.xp
        gd = get_geo()
        graph = gd.graphs.get("drive") or next(iter(gd.graphs.values()))
        self._build_routes(graph, gd)
        self._build_edge_index(graph, gd)

        # Agent state (on device).
        self.route_id = xp.asarray(
            np.random.randint(0, self.n_routes, size=self.n), dtype=xp.int32
        )
        totals = self.total[self.route_id]
        self.pos = xp.asarray(np.random.rand(self.n), dtype=xp.float32) * totals
        self.base_speed = xp.asarray(
            8.0 + np.random.rand(self.n).astype(np.float32) * 6.0, dtype=xp.float32
        )  # ~29-50 km/h free-flow
        self.speed_factor = xp.ones(self.n, dtype=xp.float32)

        # Grid bookkeeping.
        minx, miny, maxx, maxy = gd.bounds_utm
        self._minx, self._miny = minx, miny
        self._sx = _GRID / max(1e-6, (maxx - minx))
        self._sy = _GRID / max(1e-6, (maxy - miny))
        self.emission_grid = xp.zeros((_GRID, _GRID), dtype=xp.float32)
        self.bounds_utm = gd.bounds_utm
        logger.info(
            "TrafficSim ready: %d agents, %d routes, backend=%s",
            self.n,
            self.n_routes,
            compute.backend_info()["backend"],
        )

    def _build_routes(self, graph, gd) -> None:
        import networkx as nx
        from pyproj import Transformer

        nodes = list(graph.nodes)
        xy = {nd: (graph.nodes[nd]["x"], graph.nodes[nd]["y"]) for nd in nodes}
        transformer = Transformer.from_crs(
            f"EPSG:{gd.utm_epsg}", "EPSG:4326", always_xy=True
        )

        routes_pts: list[np.ndarray] = []  # each [P,2] UTM
        routes_ll: list[np.ndarray] = []  # each [P,2] lon,lat
        attempts = 0
        rng = random.Random(7)
        while len(routes_pts) < self.n_routes and attempts < self.n_routes * 8:
            attempts += 1
            a, b = rng.choice(nodes), rng.choice(nodes)
            if a == b:
                continue
            try:
                path = nx.shortest_path(graph, a, b, weight="length")
            except Exception:  # noqa: BLE001
                continue
            if len(path) < 3:
                continue
            pts = np.array([xy[p] for p in path], dtype=np.float64)
            if len(pts) > 150:  # cap route complexity for padded matrices
                idx = np.linspace(0, len(pts) - 1, 150).astype(int)
                pts = pts[idx]
            lon, lat = transformer.transform(pts[:, 0], pts[:, 1])
            routes_pts.append(pts.astype(np.float32))
            routes_ll.append(np.stack([lon, lat], axis=1).astype(np.float32))

        if not routes_pts:
            raise RuntimeError("no routes could be built for traffic sim")
        self.n_routes = len(routes_pts)

        max_p = max(len(r) for r in routes_pts)
        R = self.n_routes
        xp = compute.xp
        cum = np.zeros((R, max_p), dtype=np.float32)
        xm = np.zeros((R, max_p), dtype=np.float32)
        ym = np.zeros((R, max_p), dtype=np.float32)
        lonm = np.zeros((R, max_p), dtype=np.float32)
        latm = np.zeros((R, max_p), dtype=np.float32)
        lens = np.zeros(R, dtype=np.int32)
        total = np.zeros(R, dtype=np.float32)

        for i, (pts, ll) in enumerate(zip(routes_pts, routes_ll)):
            p = len(pts)
            lens[i] = p
            d = np.r_[0.0, np.cumsum(np.hypot(np.diff(pts[:, 0]), np.diff(pts[:, 1])))]
            cum[i, :p] = d
            cum[i, p:] = d[-1]  # pad with final distance
            xm[i, :p] = pts[:, 0]
            ym[i, :p] = pts[:, 1]
            xm[i, p:] = pts[-1, 0]
            ym[i, p:] = pts[-1, 1]
            lonm[i, :p] = ll[:, 0]
            latm[i, :p] = ll[:, 1]
            lonm[i, p:] = ll[-1, 0]
            latm[i, p:] = ll[-1, 1]
            total[i] = max(d[-1], 1.0)

        self.cum = xp.asarray(cum)
        self.xm = xp.asarray(xm)
        self.ym = xp.asarray(ym)
        self.lonm = xp.asarray(lonm)
        self.latm = xp.asarray(latm)
        self.lens = xp.asarray(lens)
        self.total = xp.asarray(total)
        self.max_p = max_p

    # -------------------------------------------------- edge congestion index

    def _build_edge_index(self, graph, gd) -> None:
        """Cache drive-network edge midpoints (UTM) for fast congestion sampling."""
        try:
            import osmnx as ox
            _, edges = ox.graph_to_gdfs(graph)
        except Exception:
            edges = gd.edges
        uids, xs, ys = [], [], []
        for idx, geom in zip(edges.index, edges.geometry):
            uid = f"{idx[0]}_{idx[1]}_{idx[2]}"
            try:
                mid = geom.interpolate(0.5, normalized=True)
                xs.append(mid.x)
                ys.append(mid.y)
                uids.append(uid)
            except Exception:
                pass
        self._edge_uids: list[str] = uids
        self._edge_x = np.array(xs, dtype=np.float32)
        self._edge_y = np.array(ys, dtype=np.float32)

    def segment_congestion(self) -> dict[str, float]:
        """Vectorised: sample emission grid at each drive-edge midpoint -> 0–1."""
        grid = self.emission_grid_cpu()
        g_max = float(grid.max())
        n = len(self._edge_uids)
        if g_max <= 0 or n == 0:
            return {uid: 0.0 for uid in self._edge_uids}
        G_H, G_W = grid.shape
        minx, miny, maxx, maxy = self.bounds_utm
        ix = np.clip(
            ((self._edge_x - minx) / (maxx - minx) * G_W).astype(np.int32), 0, G_W - 1
        )
        iy = np.clip(
            ((self._edge_y - miny) / (maxy - miny) * G_H).astype(np.int32), 0, G_H - 1
        )
        values = grid[iy, ix] / g_max
        return dict(zip(self._edge_uids, values.round(3).tolist()))

    # ------------------------------------------------------------- step
    def step(self, dt: float = 0.05) -> dict:
        xp = compute.xp
        n = self.n
        ar = xp.arange(n)

        # Advance along route (slower when congested), loop at the end.
        self.pos = (self.pos + self.base_speed * self.speed_factor * dt * 20.0) % self.total[self.route_id]

        # Gather this agent's route rows.
        gc = self.cum[self.route_id]  # [n, P]
        seg = (gc <= self.pos[:, None]).sum(axis=1) - 1
        seg = xp.clip(seg, 0, self.lens[self.route_id] - 2)
        seg_next = seg + 1

        gx = self.xm[self.route_id]
        gy = self.ym[self.route_id]
        glon = self.lonm[self.route_id]
        glat = self.latm[self.route_id]

        c0 = gc[ar, seg]
        c1 = gc[ar, seg_next]
        frac = (self.pos - c0) / xp.maximum(c1 - c0, 1e-3)
        frac = xp.clip(frac, 0.0, 1.0)

        x = gx[ar, seg] * (1 - frac) + gx[ar, seg_next] * frac
        y = gy[ar, seg] * (1 - frac) + gy[ar, seg_next] * frac
        lon = glon[ar, seg] * (1 - frac) + glon[ar, seg_next] * frac
        lat = glat[ar, seg] * (1 - frac) + glat[ar, seg_next] * frac

        # Congestion from agent density in the coarse grid.
        ix = xp.clip(((x - self._minx) * self._sx).astype(xp.int32), 0, _GRID - 1)
        iy = xp.clip(((y - self._miny) * self._sy).astype(xp.int32), 0, _GRID - 1)
        flat = iy * _GRID + ix
        counts = xp.bincount(flat, minlength=_GRID * _GRID).astype(xp.float32)
        density = counts[flat]
        excess = xp.maximum(density - _CAP, 0.0)
        self.speed_factor = xp.clip(1.0 - excess * _SLOW_K, _MIN_SPEED_FACTOR, 1.0)

        # Emissions: stop-go traffic emits much more; accumulate + decay.
        emission = _EMISSION_BASE + _EMISSION_CONGESTION * (1.0 - self.speed_factor)
        em_grid = xp.bincount(
            flat, weights=emission, minlength=_GRID * _GRID
        ).astype(xp.float32).reshape(_GRID, _GRID)
        self.emission_grid = self.emission_grid * _EMISSION_DECAY + em_grid * (1 - _EMISSION_DECAY)

        em_norm = emission / (_EMISSION_BASE + _EMISSION_CONGESTION)

        return {
            "lon": compute.to_cpu(lon),
            "lat": compute.to_cpu(lat),
            "speed_norm": compute.to_cpu(self.speed_factor),
            "emission_norm": compute.to_cpu(em_norm),
        }

    def frame_bytes(self, dt: float = 0.05) -> bytes:
        """Interleaved Float32 frame for the WebSocket: [lon,lat,spd,em]*N."""
        s = self.step(dt)
        arr = np.empty((self.n, 4), dtype=np.float32)
        arr[:, 0] = s["lon"]
        arr[:, 1] = s["lat"]
        arr[:, 2] = s["speed_norm"]
        arr[:, 3] = s["emission_norm"]
        return arr.tobytes()

    def emission_grid_cpu(self) -> np.ndarray:
        return compute.to_cpu(self.emission_grid)

    def stats(self) -> dict:
        sf = compute.to_cpu(self.speed_factor)
        congested = float((sf < 0.6).mean() * 100.0)
        return {
            "agents": self.n,
            "routes": self.n_routes,
            "congested_pct": round(congested, 1),
            "avg_speed_factor": round(float(sf.mean()), 3),
        }


_SIM: TrafficSim | None = None


def get_sim() -> TrafficSim:
    global _SIM
    if _SIM is None:
        _SIM = TrafficSim()
    return _SIM


def reset_sim() -> None:
    global _SIM
    _SIM = None
