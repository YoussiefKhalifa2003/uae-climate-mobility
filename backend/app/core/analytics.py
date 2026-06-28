"""Module 5 - Analytics & Planner insights.

Three planner/analyst tools built on the same enriched network:
  * comfort isochrones  - heat-aware reachability ("how far can I comfortably
    walk in 10 min at 2pm?"),
  * city heat-exposure + equity summary - which streets are worst and how much
    of the network is dangerous,
  * what-if scenarios   - shade a set of streets (add trees/awnings) and see the
    city-wide comfort improvement instantly.
"""

from __future__ import annotations

import logging
import math

import networkx as nx
import numpy as np

from app.core import solar_comfort
from app.core.geo_engine import get_geo
from app.core.router import MODE_SPEED, PROFILES, _index_for, _to_utm, enrich_edges

logger = logging.getLogger(__name__)


# ------------------------------------------------------------- isochrone


def comfort_isochrone(origin, minutes=10.0, hour=14.0, profile="default", comfort_aware=True, mode="walk") -> dict:
    gd = get_geo()
    graph = gd.graphs.get(mode) or next(iter(gd.graphs.values()))
    enrich = enrich_edges(hour)
    prof = PROFILES.get(profile, PROFILES["default"])
    speed = MODE_SPEED[mode] * prof["speed_mult"]
    budget_s = minutes * 60.0

    def time_weight(u, v, data):
        best = None
        for k, attrs in data.items():
            length = attrs.get("length", 1.0)
            t = length / speed
            if comfort_aware:
                e = enrich.get((u, v, k))
                if e is not None:
                    heat_penalty = 1.0 + prof["w_heat"] * max(0.0, (e["utci"] - 30.0) / 12.0)
                    t *= heat_penalty
            best = t if best is None or t < best else best
        return best

    ox, oy = _to_utm(origin["lat"], origin["lon"])
    src = _index_for(graph).nearest(ox, oy)
    lengths = nx.single_source_dijkstra_path_length(graph, src, cutoff=budget_s, weight=time_weight)

    if len(lengths) < 3:
        return {"type": "FeatureCollection", "features": [], "reachable_nodes": len(lengths)}

    from pyproj import Transformer
    from shapely.geometry import MultiPoint

    pts = [(graph.nodes[n]["x"], graph.nodes[n]["y"]) for n in lengths]
    hull = MultiPoint(pts).convex_hull.buffer(40.0)  # smooth the boundary a touch
    t = Transformer.from_crs(f"EPSG:{gd.utm_epsg}", "EPSG:4326", always_xy=True)
    hull_wgs = _transform_geom(hull, t)

    # Reachable area (km^2) is a useful planner metric.
    area_km2 = hull.area / 1e6
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "minutes": minutes,
                    "comfort_aware": comfort_aware,
                    "reachable_nodes": len(lengths),
                    "area_km2": round(area_km2, 3),
                },
                "geometry": hull_wgs.__geo_interface__,
            }
        ],
    }


def _transform_geom(geom, transformer):
    from shapely.ops import transform as shp_transform

    return shp_transform(lambda x, y, z=None: transformer.transform(x, y), geom)


# -------------------------------------------------------- heat exposure


def heat_exposure_summary(hour=14.0, worst_n=25) -> dict:
    gd = get_geo()
    enrich = enrich_edges(hour)
    edges = gd.edges

    records = []
    for (u, v, k), uid, geom in zip(edges.index, edges["uid"], edges.geometry):
        e = enrich.get((u, v, k))
        if e is None:
            continue
        records.append((uid, e["utci"], e["shade"], geom.length, geom))

    if not records:
        return {"summary": {}, "worst_segments": {"type": "FeatureCollection", "features": []}}

    utci = np.array([r[1] for r in records])
    shade = np.array([r[2] for r in records])
    length = np.array([r[3] for r in records])
    total = length.sum() or 1.0

    bands = {b: 0.0 for b in ["Comfortable", "Moderate", "Strong", "Very Strong", "Extreme"]}
    for u_val, ln in zip(utci, length):
        bands[solar_comfort.heat_risk_band(u_val)] += ln
    band_pct = {b: round(v / total * 100.0, 1) for b, v in bands.items()}

    dangerous_pct = band_pct["Very Strong"] + band_pct["Extreme"]
    summary = {
        "hour": hour,
        "avg_utci_c": round(float((utci * length).sum() / total), 1),
        "avg_shade_pct": round(float((shade * length).sum() / total) * 100.0, 1),
        "network_km": round(total / 1000.0, 2),
        "band_pct": band_pct,
        "dangerous_network_pct": round(dangerous_pct, 1),
        "equity_note": _equity_note(dangerous_pct, band_pct["Comfortable"]),
    }

    # Worst segments (hot + unshaded) for the planner overlay.
    from pyproj import Transformer

    t = Transformer.from_crs(f"EPSG:{gd.utm_epsg}", "EPSG:4326", always_xy=True)
    scored = sorted(records, key=lambda r: (r[1], -r[2]), reverse=True)[:worst_n]
    feats = []
    for uid, u_val, sh, ln, geom in scored:
        feats.append(
            {
                "type": "Feature",
                "properties": {
                    "uid": uid,
                    "utci_c": round(u_val, 1),
                    "shade_pct": round(sh * 100.0, 1),
                    "band": solar_comfort.heat_risk_band(u_val),
                },
                "geometry": _transform_geom(geom, t).__geo_interface__,
            }
        )
    return {"summary": summary, "worst_segments": {"type": "FeatureCollection", "features": feats}}


def _equity_note(dangerous_pct: float, comfortable_pct: float) -> str:
    if dangerous_pct > 40:
        return "Severe: most of the walkable network is in the dangerous heat band right now."
    if dangerous_pct > 15:
        return "Elevated: a meaningful share of streets are unsafe for vulnerable groups."
    if comfortable_pct > 60:
        return "Good: most streets are comfortable at this hour."
    return "Moderate: mixed conditions across the network."


# ------------------------------------------------------------- what-if


def what_if(edge_uids, added_shade_fraction=0.7, hour=14.0) -> dict:
    """Shade selected streets and report the city-wide comfort improvement."""
    gd = get_geo()
    enrich = enrich_edges(hour)
    field = solar_comfort.get_field(hour)
    t_air = field.t_air

    from app.data.adapters import get_environment

    env = get_environment(hour)
    # UTCI of a shaded cell (MRT ~ t_air + 3.5), used as the improved target.
    shaded_mrt = np.array([[t_air + 3.5]], dtype=np.float32)
    shaded_utci = float(
        solar_comfort.utci_raster(t_air, shaded_mrt, env["wind_speed_ms"], env["relative_humidity"])[0, 0]
    )

    edges = gd.edges
    uid_to_key = {uid: (u, v, k) for (u, v, k), uid in zip(edges.index, edges["uid"])}
    target = set(edge_uids)

    # Baseline + scenario length-weighted UTCI over the whole network.
    base_num = base_den = scen_num = improved_len = 0.0
    affected = 0
    for (u, v, k), uid, geom in zip(edges.index, edges["uid"], edges.geometry):
        e = enrich.get((u, v, k))
        if e is None:
            continue
        ln = geom.length
        base_num += e["utci"] * ln
        base_den += ln
        if uid in target:
            affected += 1
            new_shade = min(1.0, e["shade"] + added_shade_fraction)
            # Blend toward shaded UTCI by the added shade fraction.
            new_utci = e["utci"] * (1 - added_shade_fraction) + shaded_utci * added_shade_fraction
            scen_num += new_utci * ln
            if solar_comfort.heat_risk_band(new_utci) != solar_comfort.heat_risk_band(e["utci"]):
                improved_len += ln
        else:
            scen_num += e["utci"] * ln

    den = base_den or 1.0
    base_avg = base_num / den
    scen_avg = scen_num / den
    return {
        "hour": hour,
        "edges_changed": affected,
        "added_shade_fraction": added_shade_fraction,
        "baseline_avg_utci_c": round(base_avg, 2),
        "scenario_avg_utci_c": round(scen_avg, 2),
        "city_utci_reduction_c": round(base_avg - scen_avg, 2),
        "network_km_upgraded_band": round(improved_len / 1000.0, 2),
        "shaded_target_utci_c": round(shaded_utci, 1),
    }
