"""In-process data-source registry — tracks live vs simulated per layer."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class SourceRecord:
    layer: str
    label: str
    source: str          # e.g. "live:open-meteo", "simulated", "hybrid"
    live: bool
    detail: str = ""
    updated_at: float = field(default_factory=time.time)


_registry: dict[str, SourceRecord] = {}


def set_source(
    layer: str,
    label: str,
    source: str,
    live: bool,
    detail: str = "",
) -> None:
    _registry[layer] = SourceRecord(
        layer=layer,
        label=label,
        source=source,
        live=live,
        detail=detail,
        updated_at=time.time(),
    )


def get_all() -> list[dict]:
    return [
        {
            "layer": r.layer,
            "label": r.label,
            "source": r.source,
            "live": r.live,
            "detail": r.detail,
            "updated_at": r.updated_at,
            "age_s": round(time.time() - r.updated_at),
        }
        for r in _registry.values()
    ]


def snapshot() -> dict:
    return {"layers": get_all(), "server_time": time.time()}
