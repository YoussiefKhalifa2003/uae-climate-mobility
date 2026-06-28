"""Phase 4-lite — Multi-layer indoor/outdoor pedestrian network.

Adds air-conditioned corridor edges between major refuges with AirlockGate
portal nodes. Indoor edges bypass outdoor climate penalties; outdoor segments
after an airlock incur thermal-shock adjustment.
"""

from __future__ import annotations

import logging
import math

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
from shapely.geometry import LineString, Point

from app.core.geo_engine import GeoData

logger = logging.getLogger(__name__)

INDOOR_UTCI_C = 21.0
INDOOR_TEMP_C = 21.0
THERMAL_SHOCK_SECONDS = 120.0
THERMAL_SHOCK_MULTIPLIER = 1.45

_airlocks: list[dict] = []
_indoor_attached = False


def get_airlocks() -> list[dict]:
    return list(_airlocks)


def attach_indoor_network(gd: GeoData) -> None:
    """Inject indoor corridor edges into the walk graph (once per load)."""
    global _airlocks, _indoor_attached
    if _indoor_attached:
        return
    if gd.refuges is None or len(gd.refuges) < 2:
        _indoor_attached = True
        return

    graph = gd.graphs.get("walk")
    if graph is None:
        _indoor_attached = True
        return

    ref = gd.refuges.copy()
    cx = ref.geometry.x.mean()
    cy = ref.geometry.y.mean()
    ref["_d"] = np.hypot(ref.geometry.x - cx, ref.geometry.y - cy)

    malls = ref[ref.refuge_type.isin(["amenity", "mall"])].nsmallest(1, "_d")
    metros = ref[ref.refuge_type.isin(["railway", "subway", "public_transport", "metro"])].nsmallest(1, "_d")
    if malls.empty:
        malls = ref.nsmallest(1, "_d")
    if metros.empty:
        metros = ref.nsmallest(2, "_d")
    if len(malls) == 0 or len(metros) == 0:
        _indoor_attached = True
        return

    mall_pt = malls.geometry.iloc[0]
    metro_pt = metros.geometry.iloc[0]
    if mall_pt.distance(metro_pt) < 80 and len(metros) > 1:
        metro_pt = metros.geometry.iloc[1]
    elif mall_pt.distance(metro_pt) < 80:
        metro_pt = Point(mall_pt.x + 400, mall_pt.y + 200)

    mid = Point((mall_pt.x + metro_pt.x) / 2, (mall_pt.y + metro_pt.y) / 2)
    corridor_pts = [mall_pt, mid, metro_pt]

    max_nid = max(graph.nodes) if graph.nodes else 0
    node_ids: list[int] = []
    airlock_flags: list[bool] = []

    for i, pt in enumerate(corridor_pts):
        nid = _nearest_or_add_node(graph, pt.x, pt.y, max_nid + i + 1)
        node_ids.append(nid)
        airlock_flags.append(i in (0, len(corridor_pts) - 1))

    new_edge_rows = []
    for i in range(len(node_ids) - 1):
        u, v = node_ids[i], node_ids[i + 1]
        xa, ya = graph.nodes[u]["x"], graph.nodes[u]["y"]
        xb, yb = graph.nodes[v]["x"], graph.nodes[v]["y"]
        geom = LineString([(xa, ya), (xb, yb)])
        length = float(geom.length)
        rev = LineString([(xb, yb), (xa, ya)])
        graph.add_edge(u, v, length=length, geometry=geom, indoor=True, layer="indoor", speed_kph=4.5)
        graph.add_edge(v, u, length=length, geometry=rev, indoor=True, layer="indoor", speed_kph=4.5)
        new_edge_rows.append({"u": u, "v": v, "key": 0, "length": length, "geometry": geom, "indoor": True})
        new_edge_rows.append({"u": v, "v": u, "key": 0, "length": length, "geometry": rev, "indoor": True})

    for nid, is_gate in zip(node_ids, airlock_flags):
        graph.nodes[nid]["airlock"] = is_gate
        graph.nodes[nid]["layer"] = "indoor_portal" if is_gate else "indoor"

    if gd.edges is not None and new_edge_rows:
        extra = gpd.GeoDataFrame(new_edge_rows, geometry="geometry", crs=f"EPSG:{gd.utm_epsg}")
        extra = extra.set_index(["u", "v", "key"])
        extra["uid"] = [f"{u}_{v}_{k}" for (u, v, k) in extra.index]
        extra["indoor"] = True
        gd.edges = pd.concat([gd.edges, extra])

    _airlocks = []
    from pyproj import Transformer

    t = Transformer.from_crs(f"EPSG:{gd.utm_epsg}", "EPSG:4326", always_xy=True)
    for nid, is_gate in zip(node_ids, airlock_flags):
        if not is_gate:
            continue
        x, y = graph.nodes[nid]["x"], graph.nodes[nid]["y"]
        lon, lat = t.transform(x, y)
        _airlocks.append({"node_id": nid, "lat": lat, "lon": lon, "label": "AirlockGate"})

    _indoor_attached = True
    logger.info("Indoor corridor attached: %d segments, %d airlocks", len(new_edge_rows), len(_airlocks))


def _nearest_or_add_node(graph: nx.MultiDiGraph, x: float, y: float, new_id: int) -> int:
    best, best_d = None, 1e18
    for n, d in graph.nodes(data=True):
        dd = (d["x"] - x) ** 2 + (d["y"] - y) ** 2
        if dd < best_d:
            best_d, best = dd, n
    if best is not None and best_d < 60**2:
        return best
    graph.add_node(new_id, x=float(x), y=float(y), airlock=True, layer="indoor_portal")
    return new_id


def edge_is_indoor(graph: nx.MultiDiGraph, u: int, v: int) -> bool:
    data = graph.get_edge_data(u, v)
    if not data:
        return False
    k = min(data, key=lambda kk: data[kk].get("length", 1.0))
    return bool(data[k].get("indoor", False))


def thermal_shock_penalty(elapsed_outdoor_s: float) -> float:
    """Exponential decay of cardiovascular adjustment lag after leaving AC."""
    if elapsed_outdoor_s >= THERMAL_SHOCK_SECONDS:
        return 1.0
    return 1.0 + (THERMAL_SHOCK_MULTIPLIER - 1.0) * math.exp(-3.0 * elapsed_outdoor_s / THERMAL_SHOCK_SECONDS)
