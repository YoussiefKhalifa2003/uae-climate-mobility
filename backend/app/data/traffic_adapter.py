"""Hybrid traffic backend: optional TomTom live flow + physics simulation fallback."""

from __future__ import annotations

import logging
import math
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from app.config import settings
from app.data import provenance

logger = logging.getLogger(__name__)

_TOMTOM_FLOW = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"

_cache: tuple[float, dict[str, float]] | None = None
_CACHE_TTL = 120.0


def current_uae_hour() -> float:
    now = datetime.now(ZoneInfo(settings.timezone))
    return now.hour + now.minute / 60.0


def is_hour_near_now(hour: float, window: float = 0.5) -> bool:
    diff = abs(float(hour) - current_uae_hour())
    return min(diff, 24.0 - diff) < window


def diurnal_traffic_factor(hour: float) -> float:
    """UAE demand curve — wide spread so the map visibly changes across the day."""
    h = float(hour) % 24.0
    morning = math.exp(-((h - 8.0) ** 2) / 2.8)
    evening = math.exp(-((h - 17.5) ** 2) / 3.2)
    midday = 0.35 + 0.2 * math.exp(-((h - 13.0) ** 2) / 10.0)
    night = 0.06 if (h < 5.5 or h > 22.5) else 0.14
    peak = max(morning, evening)
    return float(min(1.0, max(0.05, night + 0.88 * peak + midday * 0.55)))


def diurnal_emission_scale(hour: float) -> float:
    """Scale traffic emissions / congestion for the selected clock hour."""
    return diurnal_traffic_factor(hour)


def _fetch_tomtom_bbox() -> dict[str, float] | None:
    """Fetch TomTom flow for a bbox around the sector center. Returns edge-key-less speed map."""
    if not settings.tomtom_api_key:
        return None
    try:
        lat, lon = settings.center_lat, settings.center_lon
        # TomTom uses point queries; sample a small grid around center.
        offsets = [(-0.008, 0), (0.008, 0), (0, -0.008), (0, 0.008), (0, 0)]
        speeds: list[float] = []
        for dlat, dlon in offsets:
            url = (
                f"{_TOMTOM_FLOW}?point={lat + dlat},{lon + dlon}"
                f"&unit=KMPH&key={settings.tomtom_api_key}"
            )
            r = httpx.get(url, timeout=settings.live_data_timeout_s)
            r.raise_for_status()
            flow = r.json().get("flowSegmentData", {})
            cur = flow.get("currentSpeed")
            free = flow.get("freeFlowSpeed") or cur
            if cur and free:
                speeds.append(max(0.0, min(1.0, 1.0 - float(cur) / float(free))))
        if not speeds:
            return None
        avg_cong = sum(speeds) / len(speeds)
        provenance.set_source(
            "traffic",
            "Live Traffic",
            "live:tomtom",
            True,
            f"Avg congestion factor {avg_cong:.0%} from TomTom Flow API",
        )
        return {"__tomtom_avg__": avg_cong}
    except Exception as exc:  # noqa: BLE001
        logger.info("TomTom traffic unavailable (%s)", exc)
        return None


def get_live_traffic_hint() -> dict[str, float] | None:
    """Optional live traffic hint; None if unavailable."""
    global _cache
    now = time.time()
    if _cache and now - _cache[0] < _CACHE_TTL:
        return _cache[1]
    hint = _fetch_tomtom_bbox()
    if hint:
        _cache = (now, hint)
    return hint


def traffic_provenance(sim_congested_pct: float) -> None:
    """Record traffic source after sim stats are known."""
    hint = get_live_traffic_hint()
    if hint:
        return  # already set by TomTom fetch
    provenance.set_source(
        "traffic",
        "Live Traffic",
        "simulated:agent-model",
        False,
        "24k agents on OSM roads — add TOMTOM_API_KEY in .env for live regional flow",
    )


def traffic_provenance_for_hour(hour: float, sim_congested_pct: float) -> None:
    """Provenance for time-slider traffic — TomTom at current hour, diurnal sim otherwise."""
    hint = get_live_traffic_hint()
    if is_hour_near_now(hour):
        if hint:
            return
        traffic_provenance(sim_congested_pct)
        return
    if hint:
        factor = diurnal_traffic_factor(hour)
        provenance.set_source(
            "traffic",
            "Live Traffic",
            "live:tomtom",
            True,
            f"TomTom key active — map uses diurnal curve × {factor:.0%} at hour {hour:.1f}; live blend at current time",
        )
        return
    factor = diurnal_traffic_factor(hour)
    provenance.set_source(
        "traffic",
        "Live Traffic",
        "simulated:agent-diurnal",
        False,
        f"Hour {hour:.1f} UAE — agent model × {factor:.0%} rush-hour curve (add TOMTOM_API_KEY for live flow)",
    )


def congestion_for_hour(hour: float) -> dict[str, float]:
    """Per-edge congestion 0–1 for the selected UAE hour."""
    from app.core.traffic_sim import get_sim

    base = get_sim().segment_congestion()
    factor = diurnal_traffic_factor(hour)
    # Amplify spread so rush vs night is obvious on the map (green vs amber/red).
    floor = 0.04 + 0.08 * factor
    scaled = {
        uid: round(min(1.0, max(0.0, floor + c * factor * 0.92)), 3)
        for uid, c in base.items()
    }
    if is_hour_near_now(hour):
        return apply_tomtom_to_congestion(scaled)
    return scaled


def apply_tomtom_to_congestion(base: dict[str, float]) -> dict[str, float]:
    """Blend TomTom regional congestion into per-edge map when live data exists."""
    hint = get_live_traffic_hint()
    if not hint or "__tomtom_avg__" not in hint:
        return base
    boost = hint["__tomtom_avg__"]
    if boost <= 0.01:
        return base
    out = {}
    for uid, c in base.items():
        out[uid] = round(min(1.0, c * 0.65 + boost * 0.35), 3)
    return out
