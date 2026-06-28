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


def comfort_isochrone(
    origin,
    minutes=10.0,
    hour=14.0,
    profile="default",
    comfort_aware=True,
    mode="walk",
    *,
    scenario_edge_uids: list[str] | None = None,
    added_shade_fraction: float = 0.0,
) -> dict:
    gd = get_geo()
    graph = gd.graphs.get(mode) or next(iter(gd.graphs.values()))
    if scenario_edge_uids:
        enrich = enrich_edges_scenario(hour, scenario_edge_uids, added_shade_fraction)
    else:
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


# ------------------------------------------------------------- what-if / counterfactual twin


def _shaded_target_utci(hour: float) -> float:
    field = solar_comfort.get_field(hour)
    t_air = field.t_air
    from app.data.adapters import get_environment

    env = get_environment(hour)
    shaded_mrt = np.array([[t_air + 3.5]], dtype=np.float32)
    return float(
        solar_comfort.utci_raster(t_air, shaded_mrt, env["wind_speed_ms"], env["relative_humidity"])[0, 0]
    )


def _uid_lookup() -> dict[str, tuple]:
    gd = get_geo()
    edges = gd.edges
    return {uid: (u, v, k) for (u, v, k), uid in zip(edges.index, edges["uid"])}


def _scenario_utci(base_utci: float, added_shade_fraction: float, shaded_utci: float) -> float:
    return base_utci * (1 - added_shade_fraction) + shaded_utci * added_shade_fraction


def enrich_edges_scenario(hour: float, edge_uids: list[str], added_shade_fraction: float) -> dict:
    """Edge enrich map with shade intervention applied to selected street segments."""
    base = enrich_edges(hour)
    if not edge_uids or added_shade_fraction <= 0:
        return base
    uid_to_key = _uid_lookup()
    shaded_utci = _shaded_target_utci(hour)
    target = set(edge_uids)
    out = dict(base)
    for uid in target:
        key = uid_to_key.get(uid)
        if key is None:
            continue
        e = out.get(key)
        if e is None:
            continue
        new_utci = _scenario_utci(float(e["utci"]), added_shade_fraction, shaded_utci)
        new_shade = min(1.0, float(e["shade"]) + added_shade_fraction)
        out[key] = {**e, "utci": new_utci, "shade": new_shade}
    return out


def _network_summary(records: list[tuple], hour: float) -> dict:
    """Length-weighted UTCI/shade summary + band percentages."""
    if not records:
        return {
            "hour": hour,
            "avg_utci_c": 0.0,
            "avg_shade_pct": 0.0,
            "network_km": 0.0,
            "band_pct": {b: 0.0 for b in ["Comfortable", "Moderate", "Strong", "Very Strong", "Extreme"]},
            "dangerous_network_pct": 0.0,
            "equity_note": "No network data.",
        }

    utci = np.array([r[1] for r in records])
    shade = np.array([r[2] for r in records])
    length = np.array([r[3] for r in records])
    total = length.sum() or 1.0

    bands = {b: 0.0 for b in ["Comfortable", "Moderate", "Strong", "Very Strong", "Extreme"]}
    for u_val, ln in zip(utci, length):
        bands[solar_comfort.heat_risk_band(float(u_val))] += ln
    band_pct = {b: round(v / total * 100.0, 1) for b, v in bands.items()}
    dangerous_pct = band_pct["Very Strong"] + band_pct["Extreme"]
    return {
        "hour": hour,
        "avg_utci_c": round(float((utci * length).sum() / total), 1),
        "avg_shade_pct": round(float((shade * length).sum() / total) * 100.0, 1),
        "network_km": round(total / 1000.0, 2),
        "band_pct": band_pct,
        "dangerous_network_pct": round(dangerous_pct, 1),
        "equity_note": _equity_note(dangerous_pct, band_pct["Comfortable"]),
    }


def _collect_edge_records(hour: float, scenario_uids: set[str] | None = None, added_shade_fraction: float = 0.0):
    gd = get_geo()
    enrich = enrich_edges(hour)
    edges = gd.edges
    shaded_utci = _shaded_target_utci(hour) if scenario_uids else 0.0
    records = []
    for (u, v, k), uid, geom in zip(edges.index, edges["uid"], edges.geometry):
        e = enrich.get((u, v, k))
        if e is None:
            continue
        utci = float(e["utci"])
        shade = float(e["shade"])
        if scenario_uids and uid in scenario_uids:
            utci = _scenario_utci(utci, added_shade_fraction, shaded_utci)
            shade = min(1.0, shade + added_shade_fraction)
        records.append((uid, utci, shade, geom.length, geom))
    return records


def counterfactual_twin(
    edge_uids: list[str],
    added_shade_fraction=0.7,
    hour=14.0,
    *,
    origin=None,
    isochrone_minutes: float | None = None,
    profile: str = "default",
) -> dict:
    """Before/after city twin for shade interventions on selected streets."""
    target = set(edge_uids)
    base_records = _collect_edge_records(hour)
    scen_records = _collect_edge_records(hour, target, added_shade_fraction)

    baseline = _network_summary([(r[0], r[1], r[2], r[3], r[4]) for r in base_records], hour)
    scenario = _network_summary([(r[0], r[1], r[2], r[3], r[4]) for r in scen_records], hour)

    base_target = [(r[0], r[1], r[2], r[3], r[4]) for r in base_records if r[0] in target]
    scen_target = [(r[0], r[1], r[2], r[3], r[4]) for r in scen_records if r[0] in target]
    target_baseline = _network_summary(base_target, hour) if base_target else None
    target_scenario = _network_summary(scen_target, hour) if scen_target else None
    target_km = sum(r[3] for r in base_target) / 1000.0 if base_target else 0.0

    improved_len = 0.0
    for b, s in zip(base_records, scen_records):
        if b[0] in target and solar_comfort.heat_risk_band(b[1]) != solar_comfort.heat_risk_band(s[1]):
            improved_len += b[3]

    from pyproj import Transformer

    gd = get_geo()
    t = Transformer.from_crs(f"EPSG:{gd.utm_epsg}", "EPSG:4326", always_xy=True)
    feats = []
    for uid, base_utci, base_shade, ln, geom in base_records:
        if uid not in target:
            continue
        scen = next((r for r in scen_records if r[0] == uid), None)
        if scen is None:
            continue
        scen_utci = scen[1]
        feats.append(
            {
                "type": "Feature",
                "properties": {
                    "uid": uid,
                    "baseline_utci_c": round(base_utci, 1),
                    "scenario_utci_c": round(scen_utci, 1),
                    "utci_delta_c": round(base_utci - scen_utci, 1),
                    "baseline_band": solar_comfort.heat_risk_band(base_utci),
                    "scenario_band": solar_comfort.heat_risk_band(scen_utci),
                    "shade_pct": round(min(1.0, base_shade + added_shade_fraction) * 100.0, 1),
                    "targeted": True,
                },
                "geometry": _transform_geom(geom, t).__geo_interface__,
            }
        )

    iso_delta = None
    if origin and isochrone_minutes:
        base_iso = comfort_isochrone(origin, isochrone_minutes, hour, profile, True, "walk")
        scen_iso = comfort_isochrone(
            origin,
            isochrone_minutes,
            hour,
            profile,
            True,
            "walk",
            scenario_edge_uids=edge_uids,
            added_shade_fraction=added_shade_fraction,
        )
        base_area = float(base_iso["features"][0]["properties"]["area_km2"]) if base_iso.get("features") else 0.0
        scen_area = float(scen_iso["features"][0]["properties"]["area_km2"]) if scen_iso.get("features") else 0.0
        gain = ((scen_area - base_area) / base_area * 100.0) if base_area > 0 else 0.0
        iso_delta = {
            "baseline_area_km2": round(base_area, 3),
            "scenario_area_km2": round(scen_area, 3),
            "area_gain_pct": round(gain, 1),
        }

    return {
        "hour": hour,
        "added_shade_fraction": added_shade_fraction,
        "baseline": baseline,
        "scenario": scenario,
        "target_baseline": target_baseline,
        "target_scenario": target_scenario,
        "delta": {
            "avg_utci_reduction_c": round(baseline["avg_utci_c"] - scenario["avg_utci_c"], 2),
            "dangerous_network_pct_reduction": round(
                baseline["dangerous_network_pct"] - scenario["dangerous_network_pct"], 1
            ),
            "network_km_upgraded_band": round(improved_len / 1000.0, 2),
            "edges_targeted": len(target),
            "target_km": round(target_km, 3),
            "target_avg_utci_reduction_c": round(
                (target_baseline["avg_utci_c"] - target_scenario["avg_utci_c"]) if target_baseline and target_scenario else 0.0,
                2,
            ),
            "target_dangerous_pct_reduction": round(
                (target_baseline["dangerous_network_pct"] - target_scenario["dangerous_network_pct"])
                if target_baseline and target_scenario
                else 0.0,
                1,
            ),
        },
        "affected_segments": {"type": "FeatureCollection", "features": feats},
        "isochrone": iso_delta,
        "shaded_target_utci_c": round(_shaded_target_utci(hour), 1),
    }


def what_if(edge_uids, added_shade_fraction=0.7, hour=14.0) -> dict:
    """Shade selected streets and report the city-wide comfort improvement."""
    twin = counterfactual_twin(edge_uids, added_shade_fraction, hour)
    return {
        "hour": hour,
        "edges_changed": twin["delta"]["edges_targeted"],
        "added_shade_fraction": added_shade_fraction,
        "baseline_avg_utci_c": twin["baseline"]["avg_utci_c"],
        "scenario_avg_utci_c": twin["scenario"]["avg_utci_c"],
        "city_utci_reduction_c": twin["delta"]["avg_utci_reduction_c"],
        "network_km_upgraded_band": twin["delta"]["network_km_upgraded_band"],
        "shaded_target_utci_c": twin.get("shaded_target_utci_c", 0.0),
    }
