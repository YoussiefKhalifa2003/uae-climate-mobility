// Typed REST client for the backend gateway.

export const API_BASE = (import.meta as any).env?.VITE_API_BASE ?? "http://localhost:8000";
export const WS_BASE = API_BASE.replace(/^http/, "ws");

export type LatLon = { lat: number; lon: number };
export type TravelMode = "walk" | "drive" | "bike";
export type UserProfile = "default" | "child" | "elderly" | "asthma" | "athlete" | "wheelchair";

export interface RouteMetrics {
  distance_m: number;
  duration_min: number;
  shade_pct: number;
  avg_utci_c: number;
  max_heat_risk: string;
  heat_risk_score: number;
  inhaled_pm25_ug: number;
  aqi: number;
  co2_ice_g: number;
  co2_ev_g: number;
  fuel_cost_aed: number;
  hydration_ml: number;
  calories_kcal: number;
  refuge_stops: number;
  base_duration_min?: number;
  traffic_delay_min?: number;
  heat_delay_min?: number;
  avg_speed_kph?: number;
  cvs_score?: number;
  cvs_band?: string;
  cvs_components?: Record<string, number>;
  transfer_min?: number;
}

export interface RouteLeg {
  mode: string;
  label: string;
  path: [number, number][];
  metrics: RouteMetrics;
  transfer?: { name: string; type: string; lat: number; lon: number };
}

export interface ThermalAlert {
  type: string;
  severity: string;
  message: string;
  at_min: number;
  at_km: number;
}

export interface ThermalHorizonPoint {
  t_min: number;
  utci: number;
  shade_pct: number;
  pm25: number;
  aqi: number;
  band: string;
  lat: number;
  lon: number;
  color: [number, number, number, number];
}

export interface ThermalHorizon {
  points: ThermalHorizonPoint[];
  alerts: ThermalAlert[];
  peak_utci: number;
  peak_at_min: number;
  total_min: number;
  safe_window_min: number;
  thresholds: { warn: number; critical: number };
  timeline?: ExposureTimelineFrame[];
  intersections?: ExposureIntersection[];
  departure_hour?: number;
}

export interface ExposureTimelineFrame {
  t_min: number;
  city_hour: number;
  lat: number;
  lon: number;
  utci: number;
  utci_delta: number;
  pm25: number;
  aqi: number;
  shade_pct: number;
  band: string;
  overlap_score: number;
  intersection: boolean;
}

export interface ExposureIntersection {
  t_min: number;
  city_hour: number;
  lat: number;
  lon: number;
  utci: number;
  pm25: number;
  overlap_score: number;
  message: string;
}

export interface ForecastDelta {
  peak_utci: number;
  mean_utci: number;
  stress_score: number;
}

export interface ExposureForecastSlot {
  delay_minutes: number;
  departure_hour: number;
  env: EnvSnapshot;
  peak_utci: number;
  mean_utci: number;
  shade_pct: number;
  mean_pm25: number;
  safe_window_min: number;
  stress_score: number;
  peak_at_min: number;
  total_min: number;
  delta_vs_now: ForecastDelta;
  timeline: ExposureTimelineFrame[];
}

export interface ExposureForecast {
  label: string;
  base_hour: number;
  forecast_minutes: number;
  step_minutes: number;
  assimilated: boolean;
  model: string;
  slots: ExposureForecastSlot[];
  realtime?: RouteRealtimeMeta;
}

export interface RouteOption {
  label: string;
  description: string;
  color: [number, number, number, number];
  path: [number, number][];
  metrics: RouteMetrics;
  refuges: { lon: number; lat: number; type: string }[];
  legs?: RouteLeg[];
  multimodal?: boolean;
  thermal_horizon?: ThermalHorizon;
  path_colors?: [number, number, number, number][];
}

export interface RouteRealtimeMeta {
  computed_at: number;
  hour: number;
  env_source: string;
  env_live: boolean;
  aqi_live: boolean;
  air_source: string;
  traffic_source: string;
  traffic_live: boolean;
  tomtom_blend: boolean;
}

export interface RouteResponse {
  options: RouteOption[];
  comparison: Record<string, number | string>;
  realtime?: RouteRealtimeMeta;
}

export interface SectorMeta {
  place: string;
  synthetic: boolean;
  utm_epsg: number;
  n_buildings: number;
  n_refuges: number;
  raster_shape: number[] | null;
  bounds_wgs84: { west: number; south: number; east: number; north: number };
  center: LatLon;
}

export interface EnvSnapshot {
  source: string;
  air_temp_c: number;
  relative_humidity: number;
  wind_speed_ms: number;
  wind_dir_deg: number;
  aqi?: number;
  pm25_ug_m3?: number;
  fetched_at?: number;
}

export interface AirStation {
  name: string;
  lat: number;
  lon: number;
  pm25_ug_m3?: number;
  aqi?: number;
  source: string;
  live: boolean;
  updated_at: number;
}

export interface AirRaster {
  shape: [number, number];
  pm25_min: number;
  pm25_max: number;
  baseline_pm25: number;
  values: number[];
  bounds_wgs84: { west: number; south: number; east: number; north: number };
  hotspots?: [number, number, number][];
  stations?: AirStation[];
  source?: string;
}

export interface ProvenanceLayer {
  layer: string;
  label: string;
  source: string;
  live: boolean;
  detail: string;
  updated_at: number;
  age_s: number;
}

export interface ProvenanceSnapshot {
  layers: ProvenanceLayer[];
  server_time: number;
}

export interface ComfortRaster {
  hour: number;
  azimuth: number;
  elevation: number;
  shape: [number, number];
  utci_min: number;
  utci_max: number;
  values: number[];
  bounds_wgs84: { west: number; south: number; east: number; north: number };
}

export interface BestDeparture {
  recommended_hour: number;
  reason: string;
  slots: {
    hour: number;
    label: string;
    heat_risk_score: number;
    max_heat_risk: string;
    shade_pct: number;
    avg_utci_c: number;
  }[];
}

export interface HeatExposure {
  summary: {
    hour: number;
    avg_utci_c: number;
    avg_shade_pct: number;
    network_km: number;
    band_pct: Record<string, number>;
    dangerous_network_pct: number;
    equity_note: string;
  };
  worst_segments: GeoJSON.FeatureCollection;
}

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${API_BASE}${path}`);
  if (!r.ok) throw new Error(`GET ${path} -> ${r.status}`);
  return r.json();
}

async function post<T>(
  path: string,
  body: unknown,
  opts?: { signal?: AbortSignal; timeoutMs?: number },
): Promise<T> {
  const controller = new AbortController();
  const timeoutMs = opts?.timeoutMs ?? 90_000;
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  if (opts?.signal) {
    opts.signal.addEventListener("abort", () => controller.abort(), { once: true });
  }
  try {
    const r = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    if (!r.ok) throw new Error(`POST ${path} -> ${r.status}`);
    return r.json();
  } catch (e: any) {
    if (e?.name === "AbortError") throw new Error("Route request timed out — try again.");
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

export type RouteRequestBody = {
  origin: LatLon;
  destination: LatLon;
  mode: TravelMode;
  profile: UserProfile;
  hour: number;
  live?: boolean;
  include_horizon?: boolean;
  include_multimodal?: boolean;
};

export const api = {
  health: () => get<any>("/api/health"),
  sector: () => get<SectorMeta>("/api/sector"),
  buildings: () => get<GeoJSON.FeatureCollection>("/api/buildings"),
  refuges: () => get<GeoJSON.FeatureCollection>("/api/refuges"),
  environment: (hour: number, refresh = false) =>
    get<EnvSnapshot>(`/api/environment?hour=${hour}${refresh ? "&refresh=true" : ""}`),
  provenance: () => get<ProvenanceSnapshot>("/api/provenance"),
  comfort: (hour: number) => get<ComfortRaster>(`/api/comfort?hour=${hour}`),
  solar: (hour: number) => get<{ azimuth_deg: number; elevation_deg: number }>(`/api/solar?hour=${hour}`),
  air: () => get<AirRaster>("/api/air"),
  route: (body: RouteRequestBody, opts?: { signal?: AbortSignal; timeoutMs?: number }) =>
    post<RouteResponse>("/api/route", body, opts),
  exposureTimeline: (body: RouteRequestBody & { label: string }, opts?: { signal?: AbortSignal }) =>
    post<{ label: string; thermal_horizon: ThermalHorizon | null }>("/api/exposure-timeline", body, opts),
  exposureForecast: (
    body: RouteRequestBody & { label: string; forecast_minutes?: number; step_minutes?: number },
    opts?: { signal?: AbortSignal; timeoutMs?: number },
  ) => post<ExposureForecast>("/api/exposure-forecast", body, opts),
  bestDeparture: (body: any) => post<BestDeparture>("/api/best-departure", body),
  isochrone: (body: any) => post<GeoJSON.FeatureCollection>("/api/isochrone", body),
  heatExposure: (hour: number) => get<HeatExposure>(`/api/heat-exposure?hour=${hour}`),
  whatif: (body: any) => post<any>("/api/whatif", body),
  trafficStats: () => get<any>("/api/traffic/stats"),
  trafficRoads: () => get<GeoJSON.FeatureCollection>("/api/traffic/roads"),
  trafficCongestion: () => get<Record<string, number>>("/api/traffic/congestion"),
};
