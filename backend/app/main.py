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
from app.data.traffic_adapter import congestion_for_hour, current_uae_hour, get_live_traffic_hint, traffic_provenance, traffic_provenance_for_hour
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
    V2XScenarioRequest,
    V2XScenarioResponse,
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

        # Cache road GeoJSON during warm-up so the first frontend request
        # doesn't block the event loop for tens of seconds.
        try:
            geo_engine.drive_roads_geojson()
            logger.info("Road network GeoJSON cached.")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Road GeoJSON cache skipped: %s", exc)

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

        # Precompute comfort fields in a separate thread so heavy CPU work
        # never blocks the warm-up thread or stalls live API requests.
        def _precompute() -> None:
            try:
                solar_comfort.precompute_day()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Day precompute skipped: %s", exc)

        threading.Thread(target=_precompute, daemon=True, name="comfort-precompute").start()
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
        return {"ready": False, "api_features": [
            "exposure_forecast", "exposure_timeline", "route_risk", "counterfactual_twin",
            "dubai_walk_planner", "humidity_field", "wind_field", "indoor_routing", "v2x_scenario",
        ]}
    return {
        "status": "ok",
        "compute": compute.backend_info(),
        "sector": geo_engine.sector_meta(),
        "api_version": "world_model_v3",
        "api_features": [
            "exposure_forecast", "exposure_timeline", "route_risk", "counterfactual_twin",
            "dubai_walk_planner", "humidity_field", "wind_field", "indoor_routing", "v2x_scenario",
        ],
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

    snap = get_environment(hour, force_refresh=refresh)
    if refresh:
        from app.core.wind_cfd import invalidate_wind_cache

        invalidate_wind_cache()
    return snap


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


@app.get("/api/humidity")
def humidity_field(response: Response, hour: float = Query(14.0, ge=0, le=24)):
    if not _require_ready(response):
        return {"ready": False}
    from app.core.humidity_physics import humidity_raster_payload
    from app.core.wind_cfd import wind_speed_grid

    wgrid = wind_speed_grid(hour)
    return humidity_raster_payload(hour, wind_speed_grid=wgrid)


@app.get("/api/wind")
def wind_field(response: Response, hour: float = Query(14.0, ge=0, le=24)):
    if not _require_ready(response):
        return {"ready": False}
    from app.core.wind_cfd import wind_raster_payload

    return wind_raster_payload(hour)


@app.get("/api/airlocks")
def airlocks(response: Response):
    if not _require_ready(response):
        return {"gates": []}
    from app.core.indoor_network import get_airlocks

    return {"gates": get_airlocks()}


@app.post("/api/v2x-scenario", response_model=V2XScenarioResponse)
def v2x_scenario(req: V2XScenarioRequest, response: Response):
    if not _require_ready(response):
        return V2XScenarioResponse(
            v2x_coordination_active=False,
            av_penetration_rate=0.0,
            emission_scale=1.0,
            speed_smoothing=1.0,
        )
    from app.core.v2x_optimizer import set_v2x_scenario
    from app.core import air_quality

    snap = set_v2x_scenario(active=req.v2x_coordination_active, penetration=req.av_penetration_rate)
    air_quality.compute_field()
    from app.core.v2x_optimizer import v2x_snapshot

    return V2XScenarioResponse(**v2x_snapshot())


@app.get("/api/v2x-scenario", response_model=V2XScenarioResponse)
def v2x_scenario_get(response: Response):
    if not _require_ready(response):
        return V2XScenarioResponse(
            v2x_coordination_active=False,
            av_penetration_rate=0.0,
            emission_scale=1.0,
            speed_smoothing=1.0,
        )
    from app.core.v2x_optimizer import v2x_snapshot

    return V2XScenarioResponse(**v2x_snapshot())


@app.get("/api/comfort")
def comfort(response: Response, hour: float = Query(14.0, ge=0, le=24)):
    if not _require_ready(response):
        return {"ready": False}
    from app.data.adapters import get_environment
    from app.core import solar_comfort

    snapped = round(hour * 2) / 2.0
    env = get_environment(hour)
    solar_comfort.compute_hour(snapped, env=env)
    return solar_comfort.comfort_raster_payload(hour)


@app.get("/api/solar")
def solar(hour: float = Query(14.0, ge=0, le=24)):
    az, el = solar_comfort.solar_position(hour)
    return {"hour": hour, "azimuth_deg": round(az, 2), "elevation_deg": round(el, 2)}


@app.get("/api/air")
def air(response: Response, hour: float | None = Query(None, ge=0, le=24)):
    if not _require_ready(response):
        return {"shape": [0, 0], "pm25_min": 38.0, "pm25_max": 38.0, "baseline_pm25": 38.0, "values": [], "bounds_wgs84": {"west": 0, "south": 0, "east": 0, "north": 0}}
    from app.data.adapters import get_environment
    from app.data.traffic_adapter import diurnal_emission_scale

    h = hour if hour is not None else current_uae_hour()
    env = get_environment(h)
    air_quality.compute_field(env=env, hour=h, emission_scale=diurnal_emission_scale(h))
    payload = air_quality.air_raster_payload()
    payload["hour"] = h
    return payload


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
def heat_exposure(
    response: Response,
    hour: float = Query(14.0, ge=0, le=24),
    worst_n: int = Query(25, ge=5, le=500),
    west: float | None = None,
    south: float | None = None,
    east: float | None = None,
    north: float | None = None,
):
    if not _require_ready(response):
        return {"summary": {}, "worst_segments": {"type": "FeatureCollection", "features": []}}
    bbox = None
    if west is not None and south is not None and east is not None and north is not None:
        bbox = (west, south, east, north)
    return analytics.heat_exposure_summary(hour, worst_n=worst_n, bbox=bbox)


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
    edge_int = None
    if req.edge_interventions:
        edge_int = {k: v.value for k, v in req.edge_interventions.items()}
    return analytics.counterfactual_twin(
        req.edge_uids,
        req.added_shade_fraction,
        req.hour,
        origin=origin,
        isochrone_minutes=req.isochrone_minutes,
        profile=req.profile.value,
        intervention_type=req.intervention_type.value,
        edge_interventions=edge_int,
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


@app.get("/api/traffic/status")
def traffic_status(response: Response):
    """Whether traffic is live (TomTom) or simulated — for UI verification."""
    if not _require_ready(response):
        return {"ready": False, "live": False, "source": "loading"}
    from app.data import provenance

    stats = get_sim().stats()
    traffic_provenance(float(stats.get("congested_pct", 0)))
    hint = get_live_traffic_hint()
    rec = next((r for r in provenance.get_all() if r["layer"] == "traffic"), None)
    return {
        "ready": True,
        "live": bool(hint),
        "source": rec["source"] if rec else ("live:tomtom" if hint else "unknown"),
        "detail": rec["detail"] if rec else "",
        "tomtom_regional_congestion": hint.get("__tomtom_avg__") if hint else None,
        "sim_congested_pct": float(stats.get("congested_pct", 0)),
        "updated_age_s": rec["age_s"] if rec else None,
    }


@app.get("/api/traffic/roads")
def traffic_roads(response: Response):
    """Drive-network road geometries (static, cached).  Fetch once at startup."""
    if not _require_ready(response):
        return {"type": "FeatureCollection", "features": []}
    try:
        return geo_engine.drive_roads_geojson()
    except Exception as exc:  # noqa: BLE001
        logger.exception("traffic/roads failed")
        response.status_code = 500
        return {"type": "FeatureCollection", "features": [], "error": str(exc)}


@app.get("/api/traffic/congestion")
def traffic_congestion(response: Response, hour: float | None = Query(None, ge=0, le=24)):
    """Per-edge congestion 0–1 for the selected UAE hour."""
    if not _require_ready(response):
        return {}
    h = hour if hour is not None else current_uae_hour()
    stats = get_sim().stats()
    traffic_provenance_for_hour(h, float(stats.get("congested_pct", 0)))
    return congestion_for_hour(h)
