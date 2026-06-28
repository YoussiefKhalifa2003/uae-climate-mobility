"""Hybrid traffic backend: optional TomTom live flow + physics simulation fallback."""

from __future__ import annotations

import logging
import time

import httpx

from app.config import settings
from app.data import provenance

logger = logging.getLogger(__name__)

_TOMTOM_FLOW = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"

_cache: tuple[float, dict[str, float]] | None = None
_CACHE_TTL = 120.0


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
