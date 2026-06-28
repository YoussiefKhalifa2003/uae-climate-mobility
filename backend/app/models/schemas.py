"""Pydantic request/response models for the API surface."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class TravelMode(str, Enum):
    walk = "walk"
    drive = "drive"
    bike = "bike"


class UserProfile(str, Enum):
    """Vulnerable-group profiles that reweight routing objectives."""

    default = "default"
    child = "child"
    elderly = "elderly"
    asthma = "asthma"
    athlete = "athlete"
    wheelchair = "wheelchair"


class LatLon(BaseModel):
    lat: float
    lon: float


class RouteRequest(BaseModel):
    origin: LatLon
    destination: LatLon
    mode: TravelMode = TravelMode.walk
    profile: UserProfile = UserProfile.default
    hour: float = Field(default=14.0, ge=0, le=24, description="Local hour of day")
    live: bool = Field(default=True, description="Refresh live env/air/traffic before compute")
    include_horizon: bool = Field(default=True, description="Compute thermal horizon (expensive)")
    include_multimodal: bool = Field(default=True, description="Include park-and-walk option in drive mode")


class RouteMetrics(BaseModel):
    distance_m: float
    duration_min: float
    shade_pct: float
    avg_utci_c: float
    max_heat_risk: str
    heat_risk_score: float
    inhaled_pm25_ug: float
    aqi: int
    co2_ice_g: float
    co2_ev_g: float
    fuel_cost_aed: float
    hydration_ml: float
    calories_kcal: float
    refuge_stops: int
    base_duration_min: float | None = None
    traffic_delay_min: float | None = None
    heat_delay_min: float | None = None
    avg_speed_kph: float | None = None
    cvs_score: float | None = None
    cvs_band: str | None = None
    cvs_components: dict | None = None
    transfer_min: float | None = None


class RouteLeg(BaseModel):
    mode: str
    label: str
    path: list[list[float]]
    metrics: RouteMetrics
    transfer: dict | None = None


class ThermalHorizonPoint(BaseModel):
    t_min: float
    utci: float
    shade_pct: float
    pm25: float
    aqi: int
    band: str
    lat: float
    lon: float
    color: list[int]


class ThermalAlert(BaseModel):
    type: str
    severity: str
    message: str
    at_min: float
    at_km: float


class ThermalHorizon(BaseModel):
    points: list[ThermalHorizonPoint]
    alerts: list[ThermalAlert]
    peak_utci: float
    peak_at_min: float
    total_min: float
    safe_window_min: float
    thresholds: dict
    timeline: list[dict] = Field(default_factory=list)
    intersections: list[dict] = Field(default_factory=list)
    departure_hour: float | None = None


class RouteOption(BaseModel):
    label: str
    description: str
    color: list[int]  # RGBA for the frontend PathLayer
    path: list[list[float]]  # [[lon, lat], ...]
    metrics: RouteMetrics
    refuges: list[dict] = Field(default_factory=list)
    legs: list[RouteLeg] = Field(default_factory=list)
    multimodal: bool = False
    thermal_horizon: ThermalHorizon | None = None
    path_colors: list[list[int]] | None = None


class RouteRealtimeMeta(BaseModel):
    computed_at: float
    hour: float
    env_source: str
    env_live: bool
    aqi_live: bool
    air_source: str
    traffic_source: str
    traffic_live: bool
    tomtom_blend: bool


class RouteResponse(BaseModel):
    options: list[RouteOption]
    comparison: dict
    realtime: RouteRealtimeMeta | None = None


class ExposureTimelineRequest(RouteRequest):
    """Fetch 4D exposure timeline for a single route label without recomputing all options."""

    label: str = Field(..., description="Route preset label, e.g. 'Balanced', 'Fastest'")


class ExposureTimelineResponse(BaseModel):
    label: str
    thermal_horizon: ThermalHorizon | None = None


class EnvSnapshot(BaseModel):
    source: str
    air_temp_c: float
    relative_humidity: float
    wind_speed_ms: float
    wind_dir_deg: float
    aqi: int | None = None
    pm25_ug_m3: float | None = None
    fetched_at: float | None = None


class ForecastDelta(BaseModel):
    peak_utci: float = 0.0
    mean_utci: float = 0.0
    stress_score: float = 0.0


class ExposureForecastSlot(BaseModel):
    delay_minutes: int
    departure_hour: float
    env: EnvSnapshot
    peak_utci: float
    mean_utci: float
    shade_pct: float
    mean_pm25: float
    safe_window_min: float
    stress_score: float
    peak_at_min: float
    total_min: float
    delta_vs_now: ForecastDelta = Field(default_factory=ForecastDelta)
    timeline: list[dict] = Field(default_factory=list)
    peak_utci_p50: float | None = None
    peak_utci_p95: float | None = None
    mean_utci_p95: float | None = None
    confidence_pct: float | None = None


class ExposureForecastRequest(ExposureTimelineRequest):
    forecast_minutes: int = Field(default=60, ge=15, le=120)
    step_minutes: int = Field(default=10, ge=5, le=30)
    ensemble: bool = Field(default=True, description="Attach P50/P95 uncertainty bands")


class ExposureForecastResponse(BaseModel):
    label: str
    base_hour: float
    forecast_minutes: int
    step_minutes: int
    assimilated: bool = True
    model: str = "world_model_v2_ensemble"
    slots: list[ExposureForecastSlot]
    realtime: RouteRealtimeMeta | None = None


class RouteRiskOption(BaseModel):
    label: str
    avg_utci_p50: float
    avg_utci_p95: float
    peak_utci_p95: float
    inhaled_pm25_p95: float
    confidence_pct: float
    duration_min: float | None = None
    shade_pct: float | None = None


class RouteRiskRequest(RouteRequest):
    label: str | None = Field(default=None, description="Optional single route label filter")


class RouteRiskResponse(BaseModel):
    hour: float
    profile: str
    temp_spread_c: float = 0.0
    options: list[RouteRiskOption]
    recommended_label: str | None = None
    advisory: str | None = None


class BestDepartureSlot(BaseModel):
    hour: float
    label: str
    heat_risk_score: float
    max_heat_risk: str
    shade_pct: float
    avg_utci_c: float


class BestDepartureResponse(BaseModel):
    recommended_hour: float
    reason: str
    slots: list[BestDepartureSlot]


class IsochroneRequest(BaseModel):
    origin: LatLon
    minutes: float = Field(default=10.0, gt=0, le=60)
    hour: float = Field(default=14.0, ge=0, le=24)
    profile: UserProfile = UserProfile.default
    comfort_aware: bool = True


class WhatIfRequest(BaseModel):
    """Planner scenario: shade a set of street edges (e.g. add awnings/trees)."""

    edge_uids: list[str] = Field(default_factory=list)
    added_shade_fraction: float = Field(default=0.7, ge=0, le=1)
    hour: float = Field(default=14.0, ge=0, le=24)


class CounterfactualRequest(BaseModel):
    """Phase 3 — shade intervention twin with before/after city metrics."""

    edge_uids: list[str] = Field(default_factory=list)
    added_shade_fraction: float = Field(default=0.7, ge=0, le=1)
    hour: float = Field(default=14.0, ge=0, le=24)
    origin: LatLon | None = None
    isochrone_minutes: float | None = Field(default=None, gt=0, le=60)
    profile: UserProfile = UserProfile.default


class CounterfactualSummary(BaseModel):
    avg_utci_c: float
    avg_shade_pct: float
    dangerous_network_pct: float
    band_pct: dict[str, float]
    equity_note: str


class CounterfactualDelta(BaseModel):
    avg_utci_reduction_c: float
    dangerous_network_pct_reduction: float
    network_km_upgraded_band: float
    edges_targeted: int
    target_km: float = 0.0
    target_avg_utci_reduction_c: float = 0.0
    target_dangerous_pct_reduction: float = 0.0


class CounterfactualIsochroneDelta(BaseModel):
    baseline_area_km2: float
    scenario_area_km2: float
    area_gain_pct: float


class CounterfactualResponse(BaseModel):
    hour: float
    added_shade_fraction: float
    baseline: CounterfactualSummary
    scenario: CounterfactualSummary
    target_baseline: CounterfactualSummary | None = None
    target_scenario: CounterfactualSummary | None = None
    delta: CounterfactualDelta
    affected_segments: dict
    isochrone: CounterfactualIsochroneDelta | None = None
