"""Phase 8 — Dubai Walk 2040 intervention physics.

Distinct mitigation curves for canopy, misting, and xeriscape forestry.
"""

from __future__ import annotations

from enum import Enum

from app.core import solar_comfort
from app.data.adapters import get_environment


class InterventionType(str, Enum):
    SOLID_CANOPY = "SolidCanopy"
    ACTIVE_MISTING = "ActiveMisting"
    XERISCAPE_FORESTRY = "XeriscapeForestry"
    LEGACY_SHADE = "LegacyShade"  # backward-compatible uniform shade blend


INTERVENTION_META = {
    InterventionType.SOLID_CANOPY: {
        "label": "Solid Canopy",
        "description": "90% solar load cut — MRT drop, humidity unchanged.",
        "color": [56, 189, 248, 220],
    },
    InterventionType.ACTIVE_MISTING: {
        "label": "Active Misting",
        "description": "Up to −8°C dry bulb via evaporation; local RH surge.",
        "color": [129, 140, 248, 220],
    },
    InterventionType.XERISCAPE_FORESTRY: {
        "label": "Ghaf Xeriscape",
        "description": "Native transpiration: −4°C ambient, 30% solar shield.",
        "color": [52, 211, 153, 220],
    },
    InterventionType.LEGACY_SHADE: {
        "label": "Generic Shade",
        "description": "Uniform shade fraction blend (legacy counterfactual).",
        "color": [251, 191, 36, 220],
    },
}


def _recompute_utci(t_air: float, mrt: float, wind: float, rh: float) -> float:
    import numpy as np

    mrt_arr = np.array([[mrt]], dtype=np.float32)
    return float(solar_comfort.utci_raster(t_air, mrt_arr, wind, rh)[0, 0])


def apply_intervention(
    *,
    base_utci: float,
    base_shade: float,
    hour: float,
    intervention: str | InterventionType,
    intensity: float = 1.0,
    legacy_shade_fraction: float = 0.7,
) -> tuple[float, float, dict]:
    """Return (new_utci, new_shade, physics_meta) for one edge segment."""
    itype = InterventionType(intervention) if isinstance(intervention, str) else intervention
    intensity = max(0.0, min(1.0, float(intensity)))
    env = get_environment(hour)
    t_air = float(env["air_temp_c"])
    rh = float(env["relative_humidity"])
    wind = float(env["wind_speed_ms"])

    # Approximate MRT from UTCI inversion: use outdoor unshaded MRT proxy.
    mrt_out = t_air + max(0.0, (base_utci - t_air) * 0.85 + 8.0 * (1.0 - base_shade))
    meta: dict = {"intervention": itype.value, "intensity": intensity}

    if itype == InterventionType.LEGACY_SHADE:
        shaded_utci = _shaded_target_utci(hour)
        new_utci = base_utci * (1 - legacy_shade_fraction * intensity) + shaded_utci * legacy_shade_fraction * intensity
        new_shade = min(1.0, base_shade + legacy_shade_fraction * intensity)
        meta["method"] = "linear_shade_blend"
        return new_utci, new_shade, meta

    if itype == InterventionType.SOLID_CANOPY:
        solar_cut = 0.90 * intensity
        mrt = mrt_out * (1.0 - solar_cut) + t_air * solar_cut * 0.15
        new_utci = _recompute_utci(t_air, mrt, wind, rh)
        new_shade = min(1.0, base_shade + 0.92 * intensity)
        meta.update({"mrt_delta_c": round(mrt_out - mrt, 2), "rh_delta_pct": 0.0})
        return new_utci, new_shade, meta

    if itype == InterventionType.ACTIVE_MISTING:
        t_drop = 8.0 * intensity
        t_local = t_air - t_drop
        rh_surge = min(98.0, rh + 12.0 * intensity)
        mrt = mrt_out - t_drop * 0.65
        new_utci = _recompute_utci(t_local, mrt, wind, rh_surge)
        new_shade = min(1.0, base_shade + 0.25 * intensity)
        meta.update({"t_air_delta_c": -t_drop, "rh_delta_pct": rh_surge - rh})
        return new_utci, new_shade, meta

    if itype == InterventionType.XERISCAPE_FORESTRY:
        t_drop = 4.0 * intensity
        t_local = t_air - t_drop
        solar_cut = 0.30 * intensity
        mrt = mrt_out * (1.0 - solar_cut) + (t_local + 2.0) * solar_cut
        rh_local = min(95.0, rh + 3.0 * intensity)
        new_utci = _recompute_utci(t_local, mrt, wind, rh_local)
        new_shade = min(1.0, base_shade + 0.30 * intensity)
        meta.update({"t_air_delta_c": -t_drop, "transpiration_shield_pct": round(solar_cut * 100, 1)})
        return new_utci, new_shade, meta

    return base_utci, base_shade, meta


def _shaded_target_utci(hour: float) -> float:
    field = solar_comfort.get_field(hour)
    t_air = field.t_air
    env = get_environment(hour)
    import numpy as np

    shaded_mrt = np.array([[t_air + 3.5]], dtype=np.float32)
    return float(
        solar_comfort.utci_raster(t_air, shaded_mrt, env["wind_speed_ms"], env["relative_humidity"])[0, 0]
    )


def intervention_roi_per_km(
    baseline_utci: float,
    scenario_utci: float,
    length_m: float,
    intervention: str,
) -> float:
    """Cooling return on investment proxy: °C·km reduced per km treated."""
    if length_m <= 0:
        return 0.0
    km = length_m / 1000.0
    return round(max(0.0, baseline_utci - scenario_utci) / max(km, 1e-6), 2)


def dubai_walkability_index(
    summary: dict,
    *,
    iso_area_km2: float | None = None,
    baseline_index: float | None = None,
) -> dict:
    """0–100 Dubai Walk Master Plan comfort score from network + reachability."""
    band = summary.get("band_pct", {})
    comfortable = float(band.get("Comfortable", 0))
    dangerous = float(summary.get("dangerous_network_pct", 0))
    shade = float(summary.get("avg_shade_pct", 0))
    utci = float(summary.get("avg_utci_c", 35))
    utci_component = max(0.0, min(30.0, 46.0 - utci)) / 30.0 * 100.0
    iso_bonus = min(12.0, (iso_area_km2 or 0) * 40.0)

    score = (
        0.30 * comfortable
        + 0.25 * max(0.0, 100.0 - dangerous)
        + 0.20 * shade
        + 0.15 * utci_component
        + 0.10 * iso_bonus
    )
    score = round(max(0.0, min(100.0, score)), 1)

    delta = round(score - baseline_index, 1) if baseline_index is not None else None
    return {
        "score": score,
        "delta_vs_baseline": delta,
        "components": {
            "comfortable_pct": comfortable,
            "safety_pct": round(max(0.0, 100.0 - dangerous), 1),
            "shade_pct": shade,
            "utci_component": round(utci_component, 1),
            "reachability_bonus": round(iso_bonus, 1),
        },
    }
