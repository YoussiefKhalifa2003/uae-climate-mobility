"""Phase 2 — probabilistic exposure bands (P50 / P95) from forecast spread."""

from __future__ import annotations


def attach_timeline_bands(
    timeline: list[dict],
    env_p50: dict,
    env_p95: dict,
    *,
    warn_utci: float = 38.0,
) -> list[dict]:
    """Augment each timeline frame with utci/pm25 P50–P95 bands."""
    if not timeline:
        return timeline

    t50 = float(env_p50.get("air_temp_c", 35.0))
    t95 = float(env_p95.get("air_temp_c", t50 + 1.5))
    dt = max(0.0, t95 - t50)

    pm50 = float(env_p50.get("pm25_ug_m3") or 35.0)
    pm95 = float(env_p95.get("pm25_ug_m3") or pm50 * 1.25)
    pm_ratio = pm95 / max(pm50, 1.0)

    out: list[dict] = []
    for f in timeline:
        sun = float(f.get("shade_pct", 0)) < 50
        slope = 0.85 if sun else 0.28
        utci = float(f["utci"])
        pm = float(f["pm25"])
        utci_p95 = round(utci + slope * dt, 1)
        utci_p05 = round(utci - slope * dt * 0.45, 1)
        pm_p95 = round(pm * pm_ratio, 1)
        frame = dict(f)
        frame["utci_p50"] = utci
        frame["utci_p95"] = utci_p95
        frame["utci_p05"] = utci_p05
        frame["pm25_p50"] = pm
        frame["pm25_p95"] = pm_p95
        frame["band_width_c"] = round(utci_p95 - utci, 1)
        out.append(frame)
    return out


def slot_band_summary(timeline: list[dict], *, warn_utci: float = 38.0, critical_utci: float = 46.0) -> dict:
    """Aggregate P95 peaks and heat-threshold confidence for one forecast slot."""
    if not timeline:
        return {
            "peak_utci_p50": 0.0,
            "peak_utci_p95": 0.0,
            "mean_utci_p95": 0.0,
            "confidence_pct": 100.0,
        }

    p50s = [float(f.get("utci_p50", f.get("utci", 0))) for f in timeline]
    p95s = [float(f.get("utci_p95", f.get("utci", 0))) for f in timeline]
    peak_p50 = max(p50s)
    peak_p95 = max(p95s)
    mean_p95 = sum(p95s) / len(p95s)

    # Share of trip where even the P95 envelope stays below the profile warn threshold.
    safe_frames = sum(1 for u in p95s if u < warn_utci)
    confidence = round(100.0 * safe_frames / len(p95s), 1)

    if peak_p95 >= critical_utci:
        confidence = min(confidence, 35.0)
    elif peak_p95 >= warn_utci:
        confidence = min(confidence, 70.0)

    return {
        "peak_utci_p50": round(peak_p50, 1),
        "peak_utci_p95": round(peak_p95, 1),
        "mean_utci_p95": round(mean_p95, 1),
        "confidence_pct": confidence,
    }
