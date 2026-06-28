"""Module 4 - Multi-objective, multimodal, profile-aware router.

Blends distance, shade-deficit, thermal stress (UTCI), inhaled air-pollution
dose, and refuge proximity into per-edge costs, then produces several labeled
alternatives (Fastest / Coolest / Cleanest-Air / Balanced / Cool-Refuge) with
rich, genuinely useful metrics for each. Vulnerable-group profiles reweight the
objectives so a child, an asthmatic, or a wheelchair user each gets a route
tuned to what actually keeps them safe.
"""

from __future__ import annotations

import logging
import math

import networkx as nx
import numpy as np

import time

from app.core import solar_comfort
from app.core.air_quality import BREATHING_RATE, get_field, inhaled_dose, pm25_to_aqi, sample_pm25_utm
from app.core.climate_intelligence import compute_cvs, thermal_horizon
from app.core.geo_engine import get_geo

logger = logging.getLogger(__name__)

# Free-flow speeds (m/s) by travel mode — used when OSM edge speed unavailable.
MODE_SPEED = {"walk": 1.35, "bike": 4.5, "drive": 9.0}

_HIGHWAY_KPH: dict[str, float] = {
    "motorway": 100,
    "trunk": 80,
    "primary": 60,
    "secondary": 50,
    "tertiary": 40,
    "residential": 30,
    "living_street": 20,
    "unclassified": 40,
    "service": 25,
}


def _parse_maxspeed(val) -> float | None:
    if val is None:
        return None
    try:
        kph = float(str(val).split()[0])
        if "mph" in str(val).lower():
            kph *= 1.609
        return kph
    except (ValueError, IndexError):
        return None


def _highway_kph(highway) -> float:
    if isinstance(highway, list):
        highway = highway[0] if highway else "unclassified"
    return _HIGHWAY_KPH.get(str(highway), 40.0)


def _edge_speed_kph(graph, u, v, k, mode: str, profile: dict) -> float:
    data = graph[u][v][k]
    if mode == "walk":
        return MODE_SPEED["walk"] * 3.6 * profile["speed_mult"]
    if mode == "bike":
        return MODE_SPEED["bike"] * 3.6 * profile["speed_mult"]
    parsed = _parse_maxspeed(data.get("maxspeed"))
    if parsed:
        return parsed
    if data.get("speed_kph"):
        return float(data["speed_kph"])
    return _highway_kph(data.get("highway", "unclassified"))


def _congestion_map() -> dict[str, float]:
    try:
        from app.data.traffic_adapter import apply_tomtom_to_congestion
        from app.core.traffic_sim import get_sim

        return apply_tomtom_to_congestion(get_sim().segment_congestion())
    except Exception:
        return {}

# Activity intensity (for inhalation dose) by mode.
MODE_ACTIVITY = {"walk": "walk", "bike": "bike", "drive": "drive"}

# Emission + cost factors.
CO2_ICE_G_PER_KM = 192.0
CO2_EV_G_PER_KM = 52.0  # UAE grid intensity for an EV
FUEL_L_PER_100KM = 8.0
PETROL_AED_PER_L = 2.99

# Profile -> objective weights and physiology overrides.
# w_shade: penalty for sun exposure; w_heat: UTCI penalty; w_air: PM2.5 penalty;
# refuge_pull: attraction toward refuges; hydration_mult / speed_mult tweak physiology.
PROFILES = {
    "default": {"w_shade": 1.0, "w_heat": 1.0, "w_air": 1.0, "refuge_pull": 0.4, "hydration_mult": 1.0, "speed_mult": 1.0},
    "child": {"w_shade": 1.6, "w_heat": 1.8, "w_air": 1.6, "refuge_pull": 0.9, "hydration_mult": 1.3, "speed_mult": 0.8},
    "elderly": {"w_shade": 1.8, "w_heat": 2.0, "w_air": 1.3, "refuge_pull": 1.1, "hydration_mult": 1.4, "speed_mult": 0.7},
    "asthma": {"w_shade": 0.8, "w_heat": 1.0, "w_air": 3.0, "refuge_pull": 0.7, "hydration_mult": 1.0, "speed_mult": 0.9},
    "athlete": {"w_shade": 0.6, "w_heat": 0.8, "w_air": 1.4, "refuge_pull": 0.2, "hydration_mult": 1.6, "speed_mult": 1.4},
    "wheelchair": {"w_shade": 1.4, "w_heat": 1.6, "w_air": 1.2, "refuge_pull": 1.0, "hydration_mult": 1.2, "speed_mult": 0.6},
}

# Route presets: emphasis multipliers applied on top of the profile weights.
PRESETS = {
    "Fastest": {"label": "Fastest", "color": [56, 132, 255, 220], "shade": 0.0, "heat": 0.0, "air": 0.0, "refuge": 0.0,
                "description": "Shortest travel time, ignores comfort."},
    "Coolest": {"label": "Coolest", "color": [52, 211, 153, 235], "shade": 2.5, "heat": 2.5, "air": 0.3, "refuge": 0.5,
                "description": "Maximises shade and lowest heat stress."},
    "Cleanest": {"label": "Cleanest Air", "color": [129, 140, 248, 230], "shade": 0.3, "heat": 0.4, "air": 3.0, "refuge": 0.3,
                 "description": "Minimises inhaled pollution dose."},
    "Balanced": {"label": "Balanced", "color": [251, 191, 36, 230], "shade": 1.0, "heat": 1.0, "air": 1.0, "refuge": 0.5,
                 "description": "Sensible blend of speed, heat and air."},
    "Refuge": {"label": "Cool Refuge", "color": [244, 114, 182, 235], "shade": 1.6, "heat": 1.8, "air": 0.6, "refuge": 2.5,
               "description": "Hops between air-conditioned oases with cooling breaks."},
}

MULTIMODAL_PRESET = {
    "label": "Park & Walk Cool",
    "color": [45, 212, 191, 240],
    "description": "Drive to nearest metro/shaded hub, walk the cool last mile.",
}

_HUB_TYPES = {"station", "subway", "railway", "public_transport", "metro"}
_TRANSFER_MIN = {"station": 4.0, "subway": 4.0, "railway": 4.0, "metro": 4.0, "mall": 6.0, "amenity": 5.0}


# ----------------------------------------------------------- node lookup


class _NodeIndex:
    def __init__(self, graph):
        self.nodes = list(graph.nodes)
        self.xy = np.array([[graph.nodes[n]["x"], graph.nodes[n]["y"]] for n in self.nodes])

    def nearest(self, x: float, y: float):
        d = (self.xy[:, 0] - x) ** 2 + (self.xy[:, 1] - y) ** 2
        return self.nodes[int(np.argmin(d))]


_node_index: dict[int, _NodeIndex] = {}


def _index_for(graph) -> _NodeIndex:
    key = id(graph)
    if key not in _node_index:
        _node_index[key] = _NodeIndex(graph)
    return _node_index[key]


def _to_utm(lat: float, lon: float):
    from pyproj import Transformer

    gd = get_geo()
    t = Transformer.from_crs("EPSG:4326", f"EPSG:{gd.utm_epsg}", always_xy=True)
    return t.transform(lon, lat)


# ------------------------------------------------------- edge enrichment


_enrich_cache: dict[float, dict] = {}


def enrich_edges(hour: float) -> dict:
    """Per-edge environmental attributes for `hour`: shade, utci, pm25, refuge dist."""
    key = round(hour * 2) / 2.0
    if key in _enrich_cache:
        return _enrich_cache[key]

    gd = get_geo()
    field = solar_comfort.get_field(hour)
    air = get_field()

    # refuge KD positions in UTM
    refuge_xy = None
    if gd.refuges is not None and len(gd.refuges):
        refuge_xy = np.array([[g.x, g.y] for g in gd.refuges.geometry])

    enrich: dict[tuple, dict] = {}
    edges = gd.edges
    for (u, v, k), uid, geom in zip(edges.index, edges["uid"], edges.geometry):
        mid = geom.interpolate(0.5, normalized=True)
        shade = field.edge_shade.get(uid, 0.0)
        comfort = solar_comfort.sample_utm(mid.x, mid.y, hour)
        pm = sample_pm25_utm(air, mid.x, mid.y)
        refuge_dist = 9999.0
        if refuge_xy is not None:
            dd = (refuge_xy[:, 0] - mid.x) ** 2 + (refuge_xy[:, 1] - mid.y) ** 2
            refuge_dist = float(math.sqrt(dd.min()))
        enrich[(u, v, k)] = {
            "uid": uid,
            "shade": shade,
            "utci": comfort["utci"],
            "pm25": pm,
            "refuge_dist": refuge_dist,
        }
    _enrich_cache[key] = enrich
    return enrich


def _xy_to_latlon(x: float, y: float):
    from pyproj import Transformer

    gd = get_geo()
    t = Transformer.from_crs(f"EPSG:{gd.utm_epsg}", "EPSG:4326", always_xy=True)
    lon, lat = t.transform(x, y)
    return lat, lon


def invalidate_enrichment() -> None:
    _enrich_cache.clear()


# --------------------------------------------------------- cost + routing


def _weight_fn(enrich: dict, profile: dict, preset: dict):
    w_shade = profile["w_shade"] * preset["shade"]
    w_heat = profile["w_heat"] * preset["heat"]
    w_air = profile["w_air"] * preset["air"]
    w_ref = profile["refuge_pull"] * preset["refuge"]

    def fn(u, v, data):
        # data is the dict of parallel edges {key: attrs}; pick the shortest.
        best = None
        for k, attrs in data.items():
            base = attrs.get("length", 1.0)
            e = enrich.get((u, v, k))
            if e is None:
                cost = base
            else:
                shade_deficit = 1.0 - e["shade"]
                heat_norm = max(0.0, (e["utci"] - 28.0) / 20.0)
                air_norm = max(0.0, (e["pm25"] - 35.0) / 80.0)
                refuge_norm = min(1.0, e["refuge_dist"] / 250.0)  # far from refuge = costlier
                mult = 1.0 + w_shade * shade_deficit + w_heat * heat_norm + w_air * air_norm + w_ref * refuge_norm
                cost = base * mult
            best = cost if best is None or cost < best else best
        return best

    return fn


def _path_coords(graph, path) -> tuple[list, list, list]:
    """Return ([ [lon,lat], ...], [ (x,y) utm ...], [seg_len_m ...]) for a node path."""
    from pyproj import Transformer

    gd = get_geo()
    t = Transformer.from_crs(f"EPSG:{gd.utm_epsg}", "EPSG:4326", always_xy=True)
    coords_ll, coords_xy = [], []
    for n in path:
        x, y = graph.nodes[n]["x"], graph.nodes[n]["y"]
        lon, lat = t.transform(x, y)
        coords_ll.append([round(lon, 6), round(lat, 6)])
        coords_xy.append((x, y))
    seg_lengths = [
        math.hypot(coords_xy[i + 1][0] - coords_xy[i][0], coords_xy[i + 1][1] - coords_xy[i][1])
        for i in range(len(coords_xy) - 1)
    ]
    return coords_ll, coords_xy, seg_lengths


def _edge_attr_along(graph, path, enrich):
    """Collect per-segment (shade, utci, pm25, length) along a node path."""
    out = []
    for u, v in zip(path[:-1], path[1:]):
        data = graph.get_edge_data(u, v)
        # choose key with min length
        k = min(data, key=lambda kk: data[kk].get("length", 1.0))
        length = data[k].get("length", 1.0)
        e = enrich.get((u, v, k), {"shade": 0.0, "utci": 35.0, "pm25": 40.0})
        out.append((e["shade"], e["utci"], e["pm25"], length))
    return out


def _metrics(graph, path, enrich, mode: str, profile: dict) -> dict:
    coords_ll, coords_xy, seg_lengths = _path_coords(graph, path)
    segs = _edge_attr_along(graph, path, enrich)
    total_len = sum(s[3] for s in segs) or 1.0

    shade_w = sum(s[0] * s[3] for s in segs) / total_len
    utci_w = sum(s[1] * s[3] for s in segs) / total_len
    max_utci = max((s[1] for s in segs), default=utci_w)

    cong_map = _congestion_map() if mode == "drive" else {}
    base_time_min = 0.0
    heat_delay_min = 0.0
    traffic_delay_min = 0.0
    weighted_speed = 0.0

    for u, v in zip(path[:-1], path[1:]):
        data = graph.get_edge_data(u, v)
        k = min(data, key=lambda kk: data[kk].get("length", 1.0))
        length = data[k].get("length", 1.0)
        uid = f"{u}_{v}_{k}"
        kph = _edge_speed_kph(graph, u, v, k, mode, profile)
        free_ms = max(kph / 3.6, 0.4)

        if mode == "drive":
            cong = cong_map.get(uid, 0.0)
            actual_ms = free_ms * (1.0 - cong * 0.68)
            seg_base = length / free_ms / 60.0
            seg_act = length / max(actual_ms, 0.4) / 60.0
            base_time_min += seg_base
            traffic_delay_min += max(0.0, seg_act - seg_base)
            weighted_speed += (actual_ms * 3.6) * length
        else:
            e = enrich.get((u, v, k), {"utci": 35.0})
            heat_pen = 1.0 + profile["w_heat"] * max(0.0, (e["utci"] - 30.0) / 12.0) * 0.35
            seg_base = length / free_ms / 60.0
            seg_heat = seg_base * heat_pen
            base_time_min += seg_base
            heat_delay_min += max(0.0, seg_heat - seg_base)
            weighted_speed += (free_ms * 3.6 / heat_pen) * length

    duration_min = base_time_min + heat_delay_min + traffic_delay_min
    avg_speed_kph = (weighted_speed / total_len) if total_len else kph
    speed = avg_speed_kph / 3.6

    # Inhalation dose along the midpoints of each segment.
    mid_xy = [
        ((coords_xy[i][0] + coords_xy[i + 1][0]) / 2, (coords_xy[i][1] + coords_xy[i + 1][1]) / 2)
        for i in range(len(coords_xy) - 1)
    ]
    dose = inhaled_dose(mid_xy, seg_lengths, speed, MODE_ACTIVITY[mode])

    km = total_len / 1000.0
    co2_ice = km * CO2_ICE_G_PER_KM
    co2_ev = km * CO2_EV_G_PER_KM
    fuel_cost = km / 100.0 * FUEL_L_PER_100KM * PETROL_AED_PER_L

    # Physiology for active modes.
    heat_factor = 1.0 + max(0.0, (utci_w - 30.0) / 15.0)
    if mode == "walk":
        hydration = duration_min * 12.0 * heat_factor * profile["hydration_mult"]
        calories = duration_min * 3.8  # ~3.5 MET, 70kg
    elif mode == "bike":
        hydration = duration_min * 16.0 * heat_factor * profile["hydration_mult"]
        calories = duration_min * 8.0
    else:
        hydration = 0.0
        calories = 0.0

    band = solar_comfort.heat_risk_band(max_utci)

    metrics = {
        "distance_m": round(total_len, 1),
        "duration_min": round(duration_min, 1),
        "base_duration_min": round(base_time_min, 1),
        "traffic_delay_min": round(traffic_delay_min, 1),
        "heat_delay_min": round(heat_delay_min, 1),
        "avg_speed_kph": round(avg_speed_kph, 1),
        "shade_pct": round(shade_w * 100.0, 1),
        "avg_utci_c": round(utci_w, 1),
        "max_heat_risk": band,
        "heat_risk_score": round(solar_comfort.heat_risk_score(max_utci), 1),
        "inhaled_pm25_ug": dose["inhaled_pm25_ug"],
        "aqi": dose["avg_aqi"],
        "co2_ice_g": round(co2_ice, 1),
        "co2_ev_g": round(co2_ev, 1),
        "fuel_cost_aed": round(fuel_cost, 2),
        "hydration_ml": round(hydration, 0),
        "calories_kcal": round(calories, 0),
        "refuge_stops": 0,
    }
    cvs = compute_cvs(metrics, profile.get("_name", "default"))
    metrics["cvs_score"] = cvs["score"]
    metrics["cvs_band"] = cvs["band"]
    metrics["cvs_components"] = cvs["components"]

    return {
        "coords": coords_ll,
        "coords_xy": coords_xy,
        "path_nodes": path,
        "metrics": metrics,
    }


def _nearby_refuges(coords_xy, max_dist=120.0, spacing=350.0):
    """Refuges within `max_dist` of the path, thinned to ~`spacing` apart."""
    gd = get_geo()
    if gd.refuges is None or not len(gd.refuges):
        return []
    from pyproj import Transformer

    t = Transformer.from_crs(f"EPSG:{gd.utm_epsg}", "EPSG:4326", always_xy=True)
    path_arr = np.array(coords_xy)
    stops = []
    last_xy = None
    for geom, rt in zip(gd.refuges.geometry, gd.refuges.refuge_type):
        d = np.min(np.hypot(path_arr[:, 0] - geom.x, path_arr[:, 1] - geom.y))
        if d <= max_dist:
            if last_xy is not None and math.hypot(geom.x - last_xy[0], geom.y - last_xy[1]) < spacing:
                continue
            lon, lat = t.transform(geom.x, geom.y)
            stops.append({"lon": round(lon, 6), "lat": round(lat, 6), "type": rt})
            last_xy = (geom.x, geom.y)
    return stops


def _prof_with_name(profile: str) -> dict:
    p = dict(PROFILES.get(profile, PROFILES["default"]))
    p["_name"] = profile
    return p


def _attach_route_intelligence(
    graph,
    path,
    result: dict,
    mode: str,
    prof: dict,
    hour: float,
    enrich: dict,
) -> dict:
    cong = _congestion_map() if mode == "drive" else {}
    horizon = thermal_horizon(
        graph,
        path,
        mode,
        prof,
        hour,
        edge_speed_fn=_edge_speed_kph,
        congestion_map=cong,
        path_coords_fn=_path_coords,
        edge_attr_fn=_edge_attr_along,
        enrich=enrich,
    )
    path_colors = [pt["color"] for pt in horizon["points"]]
    if path_colors and len(path_colors) < len(result["coords"]):
        path_colors = path_colors + [path_colors[-1]] * (len(result["coords"]) - len(path_colors))
    return {
        **result,
        "thermal_horizon": horizon,
        "path_colors": path_colors,
    }


def _merge_multimodal_metrics(drive_m: dict, walk_m: dict, transfer_min: float, profile_name: str) -> dict:
    """Combine drive + walk leg metrics into one trip summary."""
    total_dist = drive_m["distance_m"] + walk_m["distance_m"]
    dur_drive = drive_m["duration_min"]
    dur_walk = walk_m["duration_min"]
    total_dur = dur_drive + dur_walk + transfer_min

    def _wavg(a: float, b: float, wa: float, wb: float) -> float:
        w = wa + wb
        return (a * wa + b * wb) / w if w else a

    shade = _wavg(drive_m["shade_pct"], walk_m["shade_pct"], dur_drive, dur_walk)
    utci = _wavg(drive_m["avg_utci_c"], walk_m["avg_utci_c"], dur_drive, dur_walk)
    # Walk leg dominates heat risk for vulnerable profiles.
    max_risk = walk_m["max_heat_risk"]
    heat_score = max(drive_m["heat_risk_score"], walk_m["heat_risk_score"])

    metrics = {
        "distance_m": round(total_dist, 1),
        "duration_min": round(total_dur, 1),
        "base_duration_min": round(drive_m["base_duration_min"] + walk_m["base_duration_min"] + transfer_min, 1),
        "traffic_delay_min": round(drive_m.get("traffic_delay_min", 0.0), 1),
        "heat_delay_min": round(walk_m.get("heat_delay_min", 0.0), 1),
        "avg_speed_kph": round(total_dist / 1000.0 / (total_dur / 60.0), 1) if total_dur else 0.0,
        "shade_pct": round(shade, 1),
        "avg_utci_c": round(utci, 1),
        "max_heat_risk": max_risk,
        "heat_risk_score": round(heat_score, 1),
        "inhaled_pm25_ug": round(drive_m["inhaled_pm25_ug"] + walk_m["inhaled_pm25_ug"], 2),
        "aqi": max(drive_m["aqi"], walk_m["aqi"]),
        "co2_ice_g": drive_m["co2_ice_g"],
        "co2_ev_g": drive_m["co2_ev_g"],
        "fuel_cost_aed": drive_m["fuel_cost_aed"],
        "hydration_ml": walk_m["hydration_ml"],
        "calories_kcal": walk_m["calories_kcal"],
        "refuge_stops": walk_m.get("refuge_stops", 0),
        "transfer_min": round(transfer_min, 1),
    }
    cvs = compute_cvs(metrics, profile_name)
    metrics["cvs_score"] = cvs["score"]
    metrics["cvs_band"] = cvs["band"]
    metrics["cvs_components"] = cvs["components"]
    return metrics


def _hub_candidates(dest_x: float, dest_y: float, max_dist_m: float = 1800.0) -> list[dict]:
    """Refuges near destination suitable for park-and-walk transfer."""
    gd = get_geo()
    if gd.refuges is None or not len(gd.refuges):
        return []
    from pyproj import Transformer

    t = Transformer.from_crs(f"EPSG:{gd.utm_epsg}", "EPSG:4326", always_xy=True)
    hubs = []
    for geom, rt in zip(gd.refuges.geometry, gd.refuges.refuge_type):
        d = math.hypot(geom.x - dest_x, geom.y - dest_y)
        if d > max_dist_m:
            continue
        priority = 0 if rt in _HUB_TYPES else (1 if rt in ("mall", "amenity") else 2)
        lon, lat = t.transform(geom.x, geom.y)
        hubs.append(
            {
                "x": geom.x,
                "y": geom.y,
                "lat": lat,
                "lon": lon,
                "type": rt,
                "dist_dest_m": d,
                "priority": priority,
            }
        )
    hubs.sort(key=lambda h: (h["priority"], h["dist_dest_m"]))
    return hubs[:12]


def _try_multimodal(
    origin,
    destination,
    hour: float,
    profile: str,
    enrich: dict,
    *,
    include_horizon: bool = True,
) -> dict | None:
    """Drive to shaded hub, walk the last mile — returns a RouteOption dict or None."""
    gd = get_geo()
    drive_g = gd.graphs.get("drive")
    walk_g = gd.graphs.get("walk")
    if drive_g is None or walk_g is None:
        return None

    prof = _prof_with_name(profile)
    ox, oy = _to_utm(origin["lat"], origin["lon"])
    dx, dy = _to_utm(destination["lat"], destination["lon"])
    hubs = _hub_candidates(dx, dy)
    if not hubs:
        return None

    drive_idx = _index_for(drive_g)
    walk_idx = _index_for(walk_g)
    dst_walk = walk_idx.nearest(dx, dy)
    coolest_preset = PRESETS["Coolest"]
    fastest_preset = PRESETS["Fastest"]

    best = None
    best_cvs = -1.0

    for hub in hubs:
        hub_drive = drive_idx.nearest(hub["x"], hub["y"])
        hub_walk = walk_idx.nearest(hub["x"], hub["y"])
        try:
            w_drive = _weight_fn(enrich, prof, fastest_preset)
            drive_path = nx.shortest_path(drive_g, drive_idx.nearest(ox, oy), hub_drive, weight=w_drive)
            w_walk = _weight_fn(enrich, prof, coolest_preset)
            walk_path = nx.shortest_path(walk_g, hub_walk, dst_walk, weight=w_walk)
        except Exception:
            continue

        drive_res = _metrics(drive_g, drive_path, enrich, "drive", prof)
        walk_res = _metrics(walk_g, walk_path, enrich, "walk", prof)
        transfer = _TRANSFER_MIN.get(hub["type"], 5.0)
        merged = _merge_multimodal_metrics(drive_res["metrics"], walk_res["metrics"], transfer, profile)

        cvs = merged["cvs_score"]
        if cvs <= best_cvs:
            continue
        best_cvs = cvs

        path = drive_res["coords"] + walk_res["coords"][1:]
        legs = [
            {
                "mode": "drive",
                "label": f"Drive to {hub['type']}",
                "path": drive_res["coords"],
                "metrics": drive_res["metrics"],
                "transfer": {
                    "name": hub["type"].replace("_", " ").title(),
                    "type": hub["type"],
                    "lat": round(hub["lat"], 6),
                    "lon": round(hub["lon"], 6),
                },
            },
            {
                "mode": "walk",
                "label": "Shaded walk",
                "path": walk_res["coords"],
                "metrics": walk_res["metrics"],
            },
        ]

        # Thermal horizon on walk leg (where heat matters most).
        walk_horizon = None
        path_colors = None
        if include_horizon:
            walk_horizon = thermal_horizon(
                walk_g,
                walk_path,
                "walk",
                prof,
                hour + drive_res["metrics"]["duration_min"] / 60.0,
                edge_speed_fn=_edge_speed_kph,
                congestion_map={},
                path_coords_fn=_path_coords,
                edge_attr_fn=_edge_attr_along,
                enrich=enrich,
            )
            path_colors = [pt["color"] for pt in walk_horizon["points"]]

        best = {
            "label": MULTIMODAL_PRESET["label"],
            "description": MULTIMODAL_PRESET["description"],
            "color": MULTIMODAL_PRESET["color"],
            "path": path,
            "metrics": merged,
            "refuges": [{"lon": hub["lon"], "lat": hub["lat"], "type": hub["type"]}],
            "legs": legs,
            "multimodal": True,
            "thermal_horizon": walk_horizon,
            "path_colors": path_colors,
        }

    return best


# --------------------------------------------------------------- public API


def route(
    origin,
    destination,
    mode: str = "walk",
    profile: str = "default",
    hour: float = 14.0,
    *,
    live: bool = True,
    include_horizon: bool = True,
    include_multimodal: bool = True,
    horizon_labels: set[str] | None = None,
) -> dict:
    """Compute route options.

    ``include_horizon=False`` skips expensive per-minute UTCI prediction (fast refresh).
    When horizon is enabled, only presets in ``horizon_labels`` get a full horizon
    (default: Balanced only).
    """
    if live:
        prepare_live_context(hour, force_env=True)
    elif include_horizon:
        # Still refresh air field from latest traffic sim without hitting weather APIs.
        from app.core import air_quality
        from app.data.adapters import get_environment

        air_quality.compute_field(get_environment(hour, force_refresh=False))

    if horizon_labels is None:
        horizon_labels = {"Balanced", "Park & Walk Cool"}

    gd = get_geo()
    graph = gd.graphs.get(mode) or next(iter(gd.graphs.values()))
    enrich = enrich_edges(hour)
    prof = _prof_with_name(profile)

    ox, oy = _to_utm(origin["lat"], origin["lon"])
    dx, dy = _to_utm(destination["lat"], destination["lon"])
    idx = _index_for(graph)
    src = idx.nearest(ox, oy)
    dst = idx.nearest(dx, dy)

    options = []
    for name, preset in PRESETS.items():
        try:
            wfn = _weight_fn(enrich, prof, preset)
            path = nx.shortest_path(graph, src, dst, weight=wfn)
        except Exception as exc:  # noqa: BLE001
            logger.info("route '%s' failed: %s", name, exc)
            continue
        result = _metrics(graph, path, enrich, mode, prof)
        refuges = _nearby_refuges([(graph.nodes[n]["x"], graph.nodes[n]["y"]) for n in path]) if name == "Refuge" else []
        result["metrics"]["refuge_stops"] = len(refuges)

        want_horizon = include_horizon and preset["label"] in horizon_labels
        if want_horizon:
            enriched = _attach_route_intelligence(graph, path, result, mode, prof, hour, enrich)
        else:
            enriched = {**result, "thermal_horizon": None, "path_colors": None}

        options.append(
            {
                "label": preset["label"],
                "description": preset["description"],
                "color": preset["color"],
                "path": enriched["coords"],
                "metrics": enriched["metrics"],
                "refuges": refuges,
                "thermal_horizon": enriched.get("thermal_horizon"),
                "path_colors": enriched.get("path_colors"),
                "multimodal": False,
            }
        )

    if mode == "drive" and include_multimodal:
        mm = _try_multimodal(origin, destination, hour, profile, enrich, include_horizon=include_horizon)
        if mm:
            options.append(mm)

    comparison = _build_comparison(options)
    realtime = _realtime_meta(hour)
    return {"options": options, "comparison": comparison, "realtime": realtime}


def prepare_live_context(hour: float, force_env: bool = False) -> dict:
    """Refresh live weather baseline + traffic air field before routing."""
    from app.core import air_quality
    from app.data.adapters import get_environment

    env = get_environment(hour, force_refresh=force_env)
    air_quality.compute_field(env)
    return env


def _realtime_meta(hour: float) -> dict:
    from app.data import provenance
    from app.data.traffic_adapter import get_live_traffic_hint

    layers = {r["layer"]: r for r in provenance.get_all()}
    env_layer = layers.get("weather", {})
    aq_layer = layers.get("aqi_point", {})
    air_layer = layers.get("air_map", {})
    traffic_layer = layers.get("traffic", {})
    hint = get_live_traffic_hint()
    return {
        "computed_at": time.time(),
        "hour": hour,
        "env_source": env_layer.get("source", "unknown"),
        "env_live": env_layer.get("live", False),
        "aqi_live": aq_layer.get("live", False),
        "air_source": air_layer.get("source", "simulated"),
        "traffic_source": traffic_layer.get("source", "simulated:agent-model"),
        "traffic_live": bool(hint),
        "tomtom_blend": hint is not None,
    }


def _build_comparison(options) -> dict:
    if not options:
        return {}
    fastest = next((o for o in options if o["label"] == "Fastest"), options[0])
    coolest = next((o for o in options if o["label"] == "Coolest"), None)
    cleanest = next((o for o in options if o["label"] == "Cleanest Air"), None)
    comp = {
        "fastest_duration_min": fastest["metrics"]["duration_min"],
        "fastest_co2_ice_g": fastest["metrics"]["co2_ice_g"],
    }
    if coolest:
        comp["shade_gain_pct"] = round(
            coolest["metrics"]["shade_pct"] - fastest["metrics"]["shade_pct"], 1
        )
        comp["time_cost_for_shade_min"] = round(
            coolest["metrics"]["duration_min"] - fastest["metrics"]["duration_min"], 1
        )
        comp["heat_risk_reduction"] = round(
            fastest["metrics"]["heat_risk_score"] - coolest["metrics"]["heat_risk_score"], 1
        )
    if cleanest:
        comp["pollution_reduction_ug"] = round(
            fastest["metrics"]["inhaled_pm25_ug"] - cleanest["metrics"]["inhaled_pm25_ug"], 2
        )
    safest = max(options, key=lambda o: o["metrics"].get("cvs_score", 0))
    comp["best_cvs_score"] = safest["metrics"].get("cvs_score", 0)
    comp["best_cvs_label"] = safest["label"]
    if fastest["metrics"].get("cvs_score") is not None:
        comp["cvs_gain_vs_fastest"] = round(
            safest["metrics"]["cvs_score"] - fastest["metrics"]["cvs_score"], 1
        )
    return comp


def exposure_for_label(
    origin,
    destination,
    mode: str,
    profile: str,
    hour: float,
    label: str,
    *,
    live: bool = False,
) -> dict | None:
    """On-demand 4D exposure timeline for one route option (avoids recomputing all presets)."""
    if live:
        prepare_live_context(hour, force_env=True)

    if label == MULTIMODAL_PRESET["label"]:
        if mode != "drive":
            return None
        enrich = enrich_edges(hour)
        mm = _try_multimodal(origin, destination, hour, profile, enrich, include_horizon=True)
        if not mm or not mm.get("thermal_horizon"):
            return None
        return {"label": label, "thermal_horizon": mm["thermal_horizon"]}

    preset = next((p for p in PRESETS.values() if p["label"] == label), None)
    if preset is None:
        return None

    gd = get_geo()
    graph = gd.graphs.get(mode) or next(iter(gd.graphs.values()))
    enrich = enrich_edges(hour)
    prof = _prof_with_name(profile)

    ox, oy = _to_utm(origin["lat"], origin["lon"])
    dx, dy = _to_utm(destination["lat"], destination["lon"])
    idx = _index_for(graph)
    src = idx.nearest(ox, oy)
    dst = idx.nearest(dx, dy)

    try:
        wfn = _weight_fn(enrich, prof, preset)
        path = nx.shortest_path(graph, src, dst, weight=wfn)
    except Exception as exc:  # noqa: BLE001
        logger.info("exposure_for_label '%s' failed: %s", label, exc)
        return None

    result = _metrics(graph, path, enrich, mode, prof)
    enriched = _attach_route_intelligence(graph, path, result, mode, prof, hour, enrich)
    return {"label": label, "thermal_horizon": enriched["thermal_horizon"]}


def exposure_forecast_for_label(
    origin,
    destination,
    mode: str,
    profile: str,
    hour: float,
    label: str,
    *,
    forecast_minutes: int = 60,
    step_minutes: int = 10,
) -> dict | None:
    """World-model forecast: exposure along one route for delayed departures."""
    from app.core.exposure_world_model import build_forecast, current_uae_hour

    if label == MULTIMODAL_PRESET["label"]:
        return None

    preset = next((p for p in PRESETS.values() if p["label"] == label), None)
    if preset is None:
        return None

    gd = get_geo()
    graph = gd.graphs.get(mode) or next(iter(gd.graphs.values()))
    base_hour = hour if hour is not None else current_uae_hour()
    prof = _prof_with_name(profile)

    ox, oy = _to_utm(origin["lat"], origin["lon"])
    dx, dy = _to_utm(destination["lat"], destination["lon"])
    idx = _index_for(graph)
    src = idx.nearest(ox, oy)
    dst = idx.nearest(dx, dy)

    try:
        enrich0 = enrich_edges(base_hour)
        wfn = _weight_fn(enrich0, prof, preset)
        path = nx.shortest_path(graph, src, dst, weight=wfn)
    except Exception as exc:  # noqa: BLE001
        logger.info("exposure_forecast_for_label '%s' failed: %s", label, exc)
        return None

    forecast = build_forecast(
        graph,
        path,
        mode,
        prof,
        base_hour=base_hour,
        forecast_minutes=forecast_minutes,
        step_minutes=step_minutes,
        edge_speed_fn=_edge_speed_kph,
        congestion_map_fn=_congestion_map,
        path_coords_fn=_path_coords,
        edge_attr_fn=_edge_attr_along,
        enrich_fn=enrich_edges,
    )

    return {
        "label": label,
        **forecast,
        "realtime": _realtime_meta(base_hour),
    }


def best_departure(origin, destination, mode: str = "walk", profile: str = "default") -> dict:
    """Scan the day; recommend when to leave for the lowest heat exposure."""
    slots = []
    for hour in range(6, 23):  # daytime window
        res = route(
            origin,
            destination,
            mode,
            profile,
            float(hour),
            live=False,
            include_horizon=False,
            include_multimodal=False,
        )
        coolest = next((o for o in res["options"] if o["label"] == "Coolest"), None)
        if not coolest:
            continue
        m = coolest["metrics"]
        slots.append(
            {
                "hour": float(hour),
                "label": f"{hour:02d}:00",
                "heat_risk_score": m["heat_risk_score"],
                "max_heat_risk": m["max_heat_risk"],
                "shade_pct": m["shade_pct"],
                "avg_utci_c": m["avg_utci_c"],
            }
        )
    if not slots:
        return {"recommended_hour": 18.0, "reason": "No data; defaulting to evening.", "slots": []}
    best = min(slots, key=lambda s: s["heat_risk_score"])
    reason = (
        f"Leaving at {best['label']} gives the lowest heat-stress "
        f"({best['max_heat_risk']}, UTCI {best['avg_utci_c']} C, {best['shade_pct']}% shade)."
    )
    return {"recommended_hour": best["hour"], "reason": reason, "slots": slots}
