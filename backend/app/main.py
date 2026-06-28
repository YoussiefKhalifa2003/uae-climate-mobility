"""FastAPI gateway: REST endpoints + the traffic WebSocket stream.

The server starts immediately and warms up geo/comfort/sim in a background
thread so the frontend loading overlay stays responsive.  All data-dependent
endpoints check _ready before serving; they return 202 while loading.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.core import air_quality, analytics, compute, geo_engine, router as router_engine, solar_comfort
from app.core.traffic_sim import get_sim
from app.data import provenance as provenance_mod
from app.data.traffic_adapter import apply_tomtom_to_congestion, traffic_provenance
from app.models.schemas import (
    BestDepartureResponse,
    EnvSnapshot,
    ExposureForecastRequest,
    ExposureForecastResponse,
    ExposureTimelineRequest,
    ExposureTimelineResponse,
    IsochroneRequest,
    RouteRequest,
    RouteResponse,
    RouteRiskRequest,
    RouteRiskResponse,
    CounterfactualRequest,
    CounterfactualResponse,
    WhatIfRequest,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("app.main")

# ------------------------------------------------------------ startup state

_ready = False
_loading_error: str | None = None


def _sim_tick_loop() -> None:
    """Keeps the traffic sim stepping at ~20 fps independently of WebSocket clients."""
    import time
    while True:
        try:
            if _ready:
                get_sim().step(dt=0.05)
        except Exception:
            pass
        time.sleep(0.05)


def _warm() -> None:
    """Background geo + sim warm-up. Runs in a daemon thread after server starts."""
    global _ready, _loading_error
    try:
        from app.data.adapters import get_environment
        from app.core.solar_comfort import get_field
        import datetime, math

        logger.info("Background warm-up starting …")
        geo_engine.get_geo()
        logger.info("Geo loaded. Building comfort field …")

        # Current UAE hour for the initial field
        utc = datetime.datetime.utcnow()
        uae_hour = (utc.hour + 4) % 24 + utc.minute / 60
        get_field(uae_hour)

        # Unblock the frontend as soon as geo + comfort exist; traffic/air finish in background.
        _ready = True
        logger.info("Core geo ready — API accepting requests.")

        logger.info("Starting traffic sim …")
        sim = get_sim()

        logger.info("Traffic sim ready (%d agents). Computing air field …", sim.n)
        air_quality.compute_field()

        logger.info("Warm-up complete — platform is ready.")

        # Precompute the full day of comfort fields in the background so the
        # time-slider / Play feature is instant (no per-hour CPU stall).
        try:
            solar_comfort.precompute_day()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Day precompute skipped: %s", exc)
    except Exception as exc:  # noqa: BLE001
        _loading_error = str(exc)
        _ready = True  # allow frontend to proceed (will show degraded state)
        logger.error("Warm-up failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Compute backend: %s", compute.backend_info())
    t = threading.Thread(target=_warm, daemon=True, name="geo-warmup")
    t.start()
    tick = threading.Thread(target=_sim_tick_loop, daemon=True, name="sim-tick")
    tick.start()
    logger.info("Server accepting requests — geo loading in background.")
    yield
    logger.info("Shutting down.")


app = FastAPI(title="UAE Climate Mobility Platform", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins + ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------- loading guard

def _require_ready(response: Response) -> bool:
    """Returns True if ready, sets 202 on response if not."""
    if not _ready:
        response.status_code = 202
        return False
    return True


# --------------------------------------------------------------- status / meta


@app.get("/api/status")
def status():
    return {
        "ready": _ready,
        "error": _loading_error,
        "compute": compute.backend_info(),
    }


@app.get("/api/health")
def health(response: Response):
    if not _require_ready(response):
        return {"ready": False, "api_features": ["exposure_forecast", "exposure_timeline", "route_risk", "counterfactual_twin"]}
    return {
        "status": "ok",
        "compute": compute.backend_info(),
        "sector": geo_engine.sector_meta(),
        "api_version": "world_model_v2",
        "api_features": ["exposure_forecast", "exposure_timeline", "route_risk", "counterfactual_twin"],
    }


@app.get("/api/sector")
def sector(response: Response):
    if not _require_ready(response):
        return {"ready": False}
    return geo_engine.sector_meta()


@app.get("/api/buildings")
def buildings(response: Response):
    if not _require_ready(response):
        return {"type": "FeatureCollection", "features": []}
    return geo_engine.buildings_geojson()


@app.get("/api/refuges")
def refuges(response: Response):
    if not _require_ready(response):
        return {"type": "FeatureCollection", "features": []}
    return geo_engine.refuges_geojson()


# --------------------------------------------------- environment + comfort


@app.get("/api/environment", response_model=EnvSnapshot)
def environment(
    response: Response,
    hour: float = Query(14.0, ge=0, le=24),
    refresh: bool = Query(False, description="Bypass cache and fetch live data"),
):
    from app.data.adapters import get_environment
    return get_environment(hour, force_refresh=refresh)


@app.get("/api/provenance")
def data_provenance(response: Response):
    """Per-layer data source registry — live vs simulated, with timestamps."""
    if not _require_ready(response):
        return {"layers": [], "server_time": 0}
    meta = geo_engine.sector_meta()
    provenance_mod.set_source(
        "buildings",
        "3D Buildings",
        "live:openstreetmap" if not meta.get("synthetic") else "simulated",
        not meta.get("synthetic", True),
        f"{meta.get('n_buildings', 0)} buildings from OSM",
    )
    provenance_mod.set_source(
        "utci",
        "Heat (UTCI)",
        "physics:pvlib+osm-shadows",
        True,
        "Solar geometry + building shadow casting + pythermalcomfort UTCI",
    )
    provenance_mod.set_source(
        "refuges",
        "Cool Refuges",
        "live:openstreetmap",
        not meta.get("synthetic", True),
        f"{meta.get('n_refuges', 0)} POIs (stations, malls, parks)",
    )
    try:
        stats = get_sim().stats()
        traffic_provenance(float(stats.get("congested_pct", 0)))
    except Exception:
        pass
    provenance_mod.set_source(
        "cvs",
        "Climate Vulnerability Score",
        "computed:live-fusion",
        True,
        "Profile-weighted fusion of live UTCI, hybrid air, traffic delay & shade",
    )
    provenance_mod.set_source(
        "thermal_horizon",
        "Thermal Horizon",
        "physics:predictive-utci",
        True,
        "Minute-by-minute UTCI along route using moving sun + live weather",
    )
    provenance_mod.set_source(
        "exposure_4d",
        "4D Exposure Playback",
        "physics:spatiotemporal-fusion",
        True,
        "Trip timeline fusing moving sun, shadows, hybrid air, profile speed",
    )
    return provenance_mod.snapshot()


@app.get("/api/comfort")
def comfort(response: Response, hour: float = Query(14.0, ge=0, le=24)):
    if not _require_ready(response):
        return {"ready": False}
    return solar_comfort.comfort_raster_payload(hour)


@app.get("/api/solar")
def solar(hour: float = Query(14.0, ge=0, le=24)):
    az, el = solar_comfort.solar_position(hour)
    return {"hour": hour, "azimuth_deg": round(az, 2), "elevation_deg": round(el, 2)}


@app.get("/api/air")
def air(response: Response):
    if not _require_ready(response):
        return {"shape": [0, 0], "pm25_min": 38.0, "pm25_max": 38.0, "baseline_pm25": 38.0, "values": [], "bounds_wgs84": {"west": 0, "south": 0, "east": 0, "north": 0}}
    air_quality.compute_field()
    return air_quality.air_raster_payload()


# --------------------------------------------------------------- routing


@app.post("/api/route", response_model=RouteResponse)
def route(req: RouteRequest, response: Response):
    if not _require_ready(response):
        return {"options": [], "comparison": {}, "realtime": None}
    return router_engine.route(
        origin=req.origin.model_dump(),
        destination=req.destination.model_dump(),
        mode=req.mode.value,
        profile=req.profile.value,
        hour=req.hour,
        live=req.live,
        include_horizon=req.include_horizon,
        include_multimodal=req.include_multimodal,
    )


@app.post("/api/exposure-timeline", response_model=ExposureTimelineResponse)
def exposure_timeline(req: ExposureTimelineRequest, response: Response):
    """4D exposure timeline for one route label — used when switching route options."""
    if not _require_ready(response):
        return {"label": req.label, "thermal_horizon": None}
    result = router_engine.exposure_for_label(
        origin=req.origin.model_dump(),
        destination=req.destination.model_dump(),
        mode=req.mode.value,
        profile=req.profile.value,
        hour=req.hour,
        label=req.label,
        live=req.live,
    )
    if not result:
        return {"label": req.label, "thermal_horizon": None}
    return result


@app.post("/api/route-risk", response_model=RouteRiskResponse)
def route_risk(req: RouteRiskRequest, response: Response):
    """Probabilistic P50/P95 exposure risk + confidence per route option."""
    if not _require_ready(response):
        return {"hour": req.hour, "profile": req.profile.value, "temp_spread_c": 0, "options": []}
    return router_engine.route_risk(
        origin=req.origin.model_dump(),
        destination=req.destination.model_dump(),
        mode=req.mode.value,
        profile=req.profile.value,
        hour=req.hour,
        label=req.label,
    )


@app.post("/api/exposure-forecast", response_model=ExposureForecastResponse)
def exposure_forecast(req: ExposureForecastRequest, response: Response):
    """World-model roll-forward: exposure if departure is delayed 0–N minutes."""
    if not _require_ready(response):
        return {
            "label": req.label,
            "base_hour": req.hour,
            "forecast_minutes": req.forecast_minutes,
            "step_minutes": req.step_minutes,
            "slots": [],
            "realtime": None,
        }
    result = router_engine.exposure_forecast_for_label(
        origin=req.origin.model_dump(),
        destination=req.destination.model_dump(),
        mode=req.mode.value,
        profile=req.profile.value,
        hour=req.hour,
        label=req.label,
        forecast_minutes=req.forecast_minutes,
        step_minutes=req.step_minutes,
    )
    if not result:
        return {
            "label": req.label,
            "base_hour": req.hour,
            "forecast_minutes": req.forecast_minutes,
            "step_minutes": req.step_minutes,
            "slots": [],
            "realtime": None,
        }
    provenance_mod.set_source(
        "exposure_forecast",
        "Exposure world model",
        "world_model_v2_ensemble + open-meteo-hourly",
        True,
        f"{len(result.get('slots', []))} slots · {req.forecast_minutes} min horizon",
    )
    return result


@app.post("/api/best-departure", response_model=BestDepartureResponse)
def best_departure(req: RouteRequest, response: Response):
    if not _require_ready(response):
        return {"recommended_hour": 6.0, "reason": "Loading…", "slots": []}
    return router_engine.best_departure(
        origin=req.origin.model_dump(),
        destination=req.destination.model_dump(),
        mode=req.mode.value,
        profile=req.profile.value,
    )


# ------------------------------------------------------------- analytics


@app.post("/api/isochrone")
def isochrone(req: IsochroneRequest, response: Response):
    if not _require_ready(response):
        return {"type": "FeatureCollection", "features": []}
    return analytics.comfort_isochrone(
        origin=req.origin.model_dump(),
        minutes=req.minutes,
        hour=req.hour,
        profile=req.profile.value,
        comfort_aware=req.comfort_aware,
    )


@app.get("/api/heat-exposure")
def heat_exposure(response: Response, hour: float = Query(14.0, ge=0, le=24)):
    if not _require_ready(response):
        return {"summary": {}, "worst_segments": {"type": "FeatureCollection", "features": []}}
    return analytics.heat_exposure_summary(hour)


@app.post("/api/whatif")
def whatif(req: WhatIfRequest, response: Response):
    if not _require_ready(response):
        return {"error": "loading"}
    return analytics.what_if(req.edge_uids, req.added_shade_fraction, req.hour)


@app.post("/api/counterfactual", response_model=CounterfactualResponse)
def counterfactual(req: CounterfactualRequest, response: Response):
    if not _require_ready(response):
        return {"error": "loading"}
    origin = req.origin.model_dump() if req.origin else None
    return analytics.counterfactual_twin(
        req.edge_uids,
        req.added_shade_fraction,
        req.hour,
        origin=origin,
        isochrone_minutes=req.isochrone_minutes,
        profile=req.profile.value,
    )


# ------------------------------------------------------------- traffic WS


@app.websocket("/ws/traffic")
async def traffic_ws(ws: WebSocket):
    await ws.accept()
    # Wait up to 90 s for geo to be ready before streaming
    waited = 0
    while not _ready and waited < 90:
        await asyncio.sleep(1)
        waited += 1
    if not _ready:
        await ws.close(code=1013)
        return
    sim = get_sim()
    interval = 1.0 / max(1, settings.sim_fps)
    frame_no = 0
    try:
        await ws.send_json({"type": "header", "agents": sim.n, "stride": 4, "fps": settings.sim_fps})
        while True:
            frame = sim.frame_bytes(dt=interval)
            await ws.send_bytes(frame)
            frame_no += 1
            if frame_no % (settings.sim_fps * 2) == 0:
                air_quality.compute_field()
            await asyncio.sleep(interval)
    except WebSocketDisconnect:
        logger.info("traffic client disconnected")
    except Exception as exc:  # noqa: BLE001
        logger.warning("traffic stream error: %s", exc)


@app.get("/api/traffic/stats")
def traffic_stats(response: Response):
    if not _require_ready(response):
        return {}
    return get_sim().stats()


@app.get("/api/traffic/roads")
def traffic_roads(response: Response):
    """Drive-network road geometries (static, cached).  Fetch once at startup."""
    if not _require_ready(response):
        return {"type": "FeatureCollection", "features": []}
    return geo_engine.drive_roads_geojson()


@app.get("/api/traffic/congestion")
def traffic_congestion(response: Response):
    """Per-edge congestion 0–1, polled every 2 s by the frontend."""
    if not _require_ready(response):
        return {}
    base = get_sim().segment_congestion()
    return apply_tomtom_to_congestion(base)
