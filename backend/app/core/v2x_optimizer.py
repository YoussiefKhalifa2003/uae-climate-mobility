"""Phase 7 — AV / V2X traffic smoothing scenario (simulation counterfactual)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class V2XScenario:
    """GLOSA-style coordination parameters for the traffic + emissions stack."""

    v2x_coordination_active: bool = False
    av_penetration_rate: float = 0.0  # 0.0 – 1.0

    def emission_scale(self) -> float:
        """Scale line-source Q when AV platooning smooths throttle."""
        if not self.v2x_coordination_active:
            return 1.0
        p = max(0.0, min(1.0, self.av_penetration_rate))
        return 1.0 - 0.35 * p

    def speed_smoothing(self) -> float:
        """Reduce congestion-induced slowdown severity under coordination."""
        if not self.v2x_coordination_active:
            return 1.0
        p = max(0.0, min(1.0, self.av_penetration_rate))
        return 1.0 - 0.40 * p


_v2x = V2XScenario()


def get_v2x_scenario() -> V2XScenario:
    return _v2x


def set_v2x_scenario(*, active: bool | None = None, penetration: float | None = None) -> V2XScenario:
    global _v2x
    if active is not None:
        _v2x.v2x_coordination_active = bool(active)
    if penetration is not None:
        _v2x.av_penetration_rate = max(0.0, min(1.0, float(penetration)))
    return _v2x


def v2x_snapshot() -> dict:
    s = get_v2x_scenario()
    return {
        "v2x_coordination_active": s.v2x_coordination_active,
        "av_penetration_rate": s.av_penetration_rate,
        "emission_scale": round(s.emission_scale(), 3),
        "speed_smoothing": round(s.speed_smoothing(), 3),
    }
