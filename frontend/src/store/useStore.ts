import { create } from "zustand";
import {
  api,
  API_BASE,
  AirRaster,
  BestDeparture,
  ComfortRaster,
  EnvSnapshot,
  ExposureForecast,
  HeatExposure,
  LatLon,
  ProvenanceSnapshot,
  RouteResponse,
  SectorMeta,
  TravelMode,
  UserProfile,
} from "../api/client";
import { activeTimeline, getActiveExposureContext, horizonTimeline, sampleTimeline } from "../lib/tripExposure";

export type AppMode = "navigate" | "simulate";

// ---------------------------------------------------------------- helpers

/** Current hour as a decimal in UAE local time (UTC+4). */
export function getCurrentUAEHour(): number {
  const now = new Date();
  // Shift to UTC, then add 4 h for UAE
  const uaeMs = now.getTime() + (4 * 60 + now.getTimezoneOffset()) * 60_000;
  const d = new Date(uaeMs);
  return d.getHours() + d.getMinutes() / 60;
}

/** Latest selectable half-hour — never into the future. */
export function getMaxSelectableUAEHour(): number {
  return Math.floor(getCurrentUAEHour() * 2) / 2;
}

/** Snap to half-hour and clamp to current UAE time. */
export function snapUAEHour(h: number): number {
  const snapped = Math.round(h * 2) / 2;
  return Math.max(0, Math.min(getMaxSelectableUAEHour(), snapped));
}

// ---------------------------------------------------------------- types

interface LayerToggles {
  buildings: boolean;
  traffic: boolean;
  air: boolean;
  comfort: boolean;
  refuges: boolean;
  routes: boolean;
  isochrone: boolean;
  worstSegments: boolean;
}

interface State {
  mode: AppMode;
  profile: UserProfile;
  travelMode: TravelMode;
  hour: number;
  playing: boolean;
  appLoading: boolean;

  sector?: SectorMeta;
  env?: EnvSnapshot;
  comfort?: ComfortRaster;
  buildings?: GeoJSON.FeatureCollection;
  refuges?: GeoJSON.FeatureCollection;
  roadSegments?: GeoJSON.FeatureCollection;
  congestion: Record<string, number>;
  congestionSeq: number;           // bumped each refresh — tells deck.gl to recolor
  airRaster?: AirRaster;

  origin?: LatLon;
  destination?: LatLon;
  pickMode: "origin" | "destination" | null;

  route?: RouteResponse;
  bestDeparture?: BestDeparture;
  heatExposure?: HeatExposure;
  isochrone?: GeoJSON.FeatureCollection;
  provenance?: ProvenanceSnapshot;
  isochroneMinutes: number;

  routing: boolean;
  layers: LayerToggles;
  selectedRouteIdx: number;
  error?: string;

  routeUpdatedAt?: number;

  /** 4D trip playback — separate from city TimeBar `playing` / `hour`. */
  tripPlaying: boolean;
  tripMinute: number;
  tripExposureLoading: boolean;
  exposure4DEnabled: boolean;
  /** Last city-hour snap synced during trip playback (avoids API spam). */
  tripCityHourSnap: number;
  /** Departure-hour timeline reload (Urban X-Ray). */
  departureLoading: boolean;
  xrayExpanded: boolean;
  /** Full-screen X-Ray: hides sidebar, camera follows traveller. */
  focusMode: boolean;
  demoPlaying: boolean;
  demoCompleted: boolean;
  /** Skip one debounced route refresh after X-Ray hour change. */
  skipNextRouteRefresh: boolean;
  /** Floating map callout (shade crossing, etc.). */
  mapMoment: string | null;

  /** World-model forecast: delayed departure 0–60 min. */
  exposureForecast: ExposureForecast | null;
  forecastDelayMin: number;
  forecastLoading: boolean;
  forecastError: string | null;

  setMode: (m: AppMode) => void;
  setProfile: (p: UserProfile) => void;
  setTravelMode: (m: TravelMode) => void;
  setHour: (h: number) => void;
  togglePlay: () => void;
  toggleLayer: (k: keyof LayerToggles) => void;
  setPickMode: (m: "origin" | "destination" | null) => void;
  setPoint: (p: LatLon) => void;
  selectRoute: (i: number) => void;
  syncToNow: () => void;
  stopTrip: () => void;
  resetTrip: () => void;
  toggleTripPlay: () => void;
  setTripMinute: (m: number) => void;
  setDepartureHour: (h: number, opts?: { recomputeRoute?: boolean }) => Promise<void>;
  ensureTripExposure: () => Promise<void>;
  syncTripCityLayers: (cityHour: number) => void;
  setXrayExpanded: (v: boolean) => void;
  toggleFocusMode: () => void;
  startAutoDemo: () => void;
  stopDemo: () => void;
  setMapMoment: (msg: string | null) => void;
  fetchExposureForecast: () => Promise<void>;
  setForecastDelay: (min: number) => void;

  init: () => Promise<void>;
  refreshHour: (h: number) => Promise<void>;
  refreshEnvironment: (force?: boolean) => Promise<void>;
  refreshProvenance: () => Promise<void>;
  refreshAir: () => Promise<void>;
  refreshCongestion: () => Promise<void>;
  computeRoute: (opts?: { full?: boolean }) => Promise<void>;
  computeBestDeparture: () => Promise<void>;
  computeIsochrone: (minutes: number) => Promise<void>;
  computeHeatExposure: () => Promise<void>;
}

const modeDefaults: Record<AppMode, { travelMode: TravelMode }> = {
  navigate: { travelMode: "walk" },
  simulate: { travelMode: "walk" },
};

/** True while X-Ray is loading or playing — blocks background route refresh. */
export function isRouteRefreshBlocked(s: State): boolean {
  return s.departureLoading || s.tripExposureLoading || s.forecastLoading || s.tripPlaying || s.demoPlaying;
}


/** Monotonic id so stale route responses never overwrite newer ones. */
let _routeReqSeq = 0;
let _routeAbort: AbortController | null = null;
let _exposureAbort: AbortController | null = null;
let _forecastAbort: AbortController | null = null;

export const useStore = create<State>((set, get) => ({
  mode: "navigate",
  profile: "default",
  travelMode: "walk",
  // Start at current UAE local time, not a hardcoded value.
  hour: getCurrentUAEHour(),
  playing: false,
  appLoading: true,
  airRaster: undefined,
  pickMode: null,
  routing: false,
  selectedRouteIdx: 0,
  isochroneMinutes: 10,
  layers: {
    buildings: true,
    traffic:   true,
    air:       true,    // pollution is the primary environmental overlay
    comfort:   false,   // heat field is a toggle (it's a full-area tint)
    refuges:   true,
    routes:    true,
    isochrone: false,
    worstSegments: false,
  },

  congestion: {},
  congestionSeq: 0,

  tripPlaying: false,
  tripMinute: 0,
  tripExposureLoading: false,
  exposure4DEnabled: true,
  tripCityHourSnap: -1,
  departureLoading: false,
  xrayExpanded: true,
  focusMode: false,
  demoPlaying: false,
  demoCompleted: false,
  skipNextRouteRefresh: false,
  mapMoment: null,
  exposureForecast: null,
  forecastDelayMin: 0,
  forecastLoading: false,
  forecastError: null,

  // ---- mode / ui setters ----

  setMode: (m) => {
    const d = modeDefaults[m];
    set({
      mode: m,
      travelMode: d.travelMode,
      route: undefined,
      bestDeparture: undefined,
      exposureForecast: null,
      forecastDelayMin: 0,
      forecastError: null,
      selectedRouteIdx: 0,
      tripPlaying: false,
      tripMinute: 0,
      focusMode: false,
      demoPlaying: false,
      layers: {
        ...get().layers,
        isochrone: m === "simulate",
        worstSegments: m === "simulate",
        comfort: m === "simulate",
      },
    });
    if (m === "simulate") {
      get().computeHeatExposure();
      if (get().origin) get().computeIsochrone(get().isochroneMinutes);
    }
    const { origin, destination } = get();
    if (m === "navigate" && origin && destination) get().computeRoute({ full: false });
  },
  setProfile: (p) => {
    const { travelMode } = get();
    if (travelMode === "drive" && !["default", "elderly", "asthma"].includes(p)) return;
    set({ profile: p });
    const { origin, destination, mode } = get();
    if (mode === "navigate" && origin && destination) get().computeRoute({ full: false });
  },
  setTravelMode: (m) => {
    const allowed = m === "drive" ? ["default", "elderly", "asthma"] : null;
    const profile = allowed && !allowed.includes(get().profile) ? "default" : get().profile;
    set({ travelMode: m, profile: profile as UserProfile });
    const { origin, destination, mode } = get();
    if (mode === "navigate" && origin && destination) get().computeRoute({ full: false });
  },
  setHour: (h) => set({ hour: snapUAEHour(h) }),
  togglePlay: () => {
    const next = !get().playing;
    if (next && get().tripPlaying) get().stopTrip();
    set({ playing: next });
  },
  toggleLayer: (k) => {
    const s = get();
    const next = !s.layers[k];
    set({ layers: { ...s.layers, [k]: next } });
    if (k === "isochrone" && next) {
      if (s.origin) get().computeIsochrone(s.isochroneMinutes);
      else set({ error: "Set an origin on the map first, then toggle Reachability." });
    }
    if (k === "worstSegments" && next) get().computeHeatExposure();
    if (k === "comfort" && next) {
      get().refreshHour(s.hour);
      get().computeHeatExposure();
    }
  },
  setPickMode: (m) => set({ pickMode: m }),

  stopTrip: () => {
    const wasDemo = get().demoPlaying;
    set({ tripPlaying: false, tripMinute: 0, tripCityHourSnap: -1, demoPlaying: false });
    if (wasDemo) set({ mapMoment: "Your turn — scrub departure time or press Play" });
  },

  resetTrip: () => get().stopTrip(),

  setTripMinute: (m) => {
    const { route, selectedRouteIdx, exposureForecast, forecastDelayMin } = get();
    const opt = route?.options[selectedRouteIdx];
    const { timeline, duration } = getActiveExposureContext(
      exposureForecast,
      forecastDelayMin,
      opt?.thermal_horizon,
    );
    const clamped = Math.max(0, Math.min(duration, m));
    const prevFrame = timeline.length ? sampleTimeline(timeline, get().tripMinute) : null;
    const nextFrame = timeline.length ? sampleTimeline(timeline, clamped) : null;

    set({ tripMinute: clamped, exposure4DEnabled: true });

    if (prevFrame && nextFrame) {
      const wasShaded = prevFrame.shade_pct >= 50;
      const nowShaded = nextFrame.shade_pct >= 50;
      if (wasShaded !== nowShaded) {
        set({
          mapMoment: nowShaded
            ? "☁ Entering shadow — direct sun blocked by buildings"
            : "☀ Leaving shade — heat exposure rising",
        });
      }
    }

    if (timeline.length) {
      const snap = Math.round(timeline[Math.min(Math.floor(clamped), timeline.length - 1)]?.city_hour * 4) / 4;
      get().syncTripCityLayers(snap);
    }
  },

  toggleTripPlay: () => {
    const s = get();
    if (s.tripPlaying) {
      set({ tripPlaying: false });
      return;
    }
    void s.ensureTripExposure().then(() => {
      const opt = get().route?.options[get().selectedRouteIdx];
      const { timeline } = getActiveExposureContext(
        get().exposureForecast,
        get().forecastDelayMin,
        opt?.thermal_horizon,
      );
      if (!timeline.length) return;
      if (get().playing) set({ playing: false });
      set({ tripPlaying: true, exposure4DEnabled: true });
    });
  },

  syncTripCityLayers: (cityHour) => {
    const snap = Math.round(cityHour * 4) / 4;
    if (Math.abs(snap - get().tripCityHourSnap) < 0.01) return;
    set({ tripCityHourSnap: snap });
    void get().refreshHour(snap);
  },

  setXrayExpanded: (v) => set({ xrayExpanded: v }),

  toggleFocusMode: () => {
    const next = !get().focusMode;
    set({ focusMode: next, exposure4DEnabled: true });
    if (next && !get().layers.comfort) get().toggleLayer("comfort");
    if (!next) get().stopDemo();
  },

  startAutoDemo: () => {
    const opt = get().route?.options[get().selectedRouteIdx];
    if (!horizonTimeline(opt?.thermal_horizon).length) return;
    if (get().demoCompleted || get().demoPlaying) return;
    set({
      demoCompleted: true,
      demoPlaying: true,
      focusMode: true,
      exposure4DEnabled: true,
      tripPlaying: false,
      tripMinute: 0,
      mapMoment: "Demo — watch heat & shade change as you walk",
    });
    if (!get().layers.comfort) get().toggleLayer("comfort");
    setTimeout(() => {
      if (get().demoPlaying) set({ tripPlaying: true });
    }, 900);
  },

  stopDemo: () => set({ demoPlaying: false, tripPlaying: false }),

  setMapMoment: (msg) => set({ mapMoment: msg }),

  setForecastDelay: (min) => {
    const clamped = Math.max(0, Math.min(60, Math.round(min)));
    get().stopTrip();
    set({ forecastDelayMin: clamped, tripMinute: 0, exposure4DEnabled: true });
    const { exposureForecast } = get();
    const slot = exposureForecast?.slots.find(
      (s) => s.delay_minutes === clamped,
    ) ?? exposureForecast?.slots.reduce((a, b) =>
      Math.abs(a.delay_minutes - clamped) <= Math.abs(b.delay_minutes - clamped) ? a : b,
    );
    if (slot && clamped > 0) {
      const sign = slot.delta_vs_now.mean_utci >= 0 ? "+" : "";
      get().setMapMoment(
        `Leave in ${clamped} min → ${sign}${slot.delta_vs_now.mean_utci.toFixed(1)}°C avg UTCI vs now`,
      );
    } else {
      get().setMapMoment(null);
    }
  },

  fetchExposureForecast: async () => {
    const { route, selectedRouteIdx, origin, destination, travelMode, profile, hour } = get();
    const opt = route?.options[selectedRouteIdx];
    if (!opt || !origin || !destination) return;
    if (!horizonTimeline(opt.thermal_horizon).length) {
      set({ forecastError: "Activate X-Ray first, then load the forecast." });
      return;
    }

    get().stopTrip();
    _forecastAbort?.abort();
    _forecastAbort = new AbortController();
    set({ forecastLoading: true, forecastError: null, mapMoment: "Building 60-min exposure forecast…" });

    try {
      const res = await api.exposureForecast(
        {
          origin,
          destination,
          mode: travelMode,
          profile,
          hour: getCurrentUAEHour(),
          label: opt.label,
          forecast_minutes: 60,
          step_minutes: 10,
          live: true,
          include_horizon: true,
          include_multimodal: false,
        },
        { signal: _forecastAbort.signal, timeoutMs: 120_000 },
      );
      if (!res.slots?.length) {
        set({ forecastError: "Forecast returned no data — try again in a moment." });
        return;
      }

      const nowSlot = res.slots[0];
      const cur = get().route;
      if (!cur) return;

      const options = cur.options.map((o, i) =>
        i === selectedRouteIdx
          ? {
              ...o,
              thermal_horizon: {
                points: o.thermal_horizon?.points ?? [],
                alerts: o.thermal_horizon?.alerts ?? [],
                peak_utci: nowSlot.peak_utci,
                peak_at_min: nowSlot.peak_at_min,
                total_min: nowSlot.total_min,
                safe_window_min: nowSlot.safe_window_min,
                thresholds: o.thermal_horizon?.thresholds ?? { warn: 38, critical: 46 },
                timeline: nowSlot.timeline?.length ? nowSlot.timeline : o.thermal_horizon?.timeline,
                intersections: o.thermal_horizon?.intersections,
                departure_hour: nowSlot.departure_hour,
              },
            }
          : o,
      );

      set({
        exposureForecast: res,
        forecastDelayMin: 0,
        tripMinute: 0,
        route: { ...cur, options },
        xrayExpanded: true,
        mapMoment: "Forecast ready — scrub “Leave in…” to compare delayed departure",
      });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Forecast failed";
      if (msg.includes("abort")) return;
      if (msg.includes("404")) {
        set({
          forecastError:
            "Backend is missing /api/exposure-forecast — restart the backend (scripts/run_backend.ps1) so Phase 1 routes load.",
        });
        return;
      }
      set({ forecastError: msg.includes("timed out") ? "Forecast timed out — backend may still be warming up." : msg });
    } finally {
      set({ forecastLoading: false });
    }
  },

  setDepartureHour: async (h, opts) => {
    const snapped = snapUAEHour(h);
    const { origin, destination, travelMode, profile, selectedRouteIdx, route } = get();
    const opt = route?.options[selectedRouteIdx];
    if (!origin || !destination || !opt) {
      await get().refreshHour(snapped);
      return;
    }

    get().stopTrip();
    set({
      hour: snapped,
      departureLoading: true,
      exposure4DEnabled: true,
      skipNextRouteRefresh: true,
      exposureForecast: null,
      forecastDelayMin: 0,
    });

    _exposureAbort?.abort();
    _exposureAbort = new AbortController();

    try {
      await get().refreshHour(snapped);
      if (opts?.recomputeRoute) {
        await get().computeRoute({ full: true });
        return;
      }
      const res = await api.exposureTimeline(
        {
          origin,
          destination,
          mode: travelMode,
          profile,
          hour: snapped,
          label: opt.label,
          live: false,
          include_horizon: true,
          include_multimodal: false,
        },
        { signal: _exposureAbort.signal },
      );
      const cur = get().route;
      if (!cur) return;
      const options = cur.options.map((o, i) =>
        i === selectedRouteIdx
          ? { ...o, thermal_horizon: res.thermal_horizon ?? o.thermal_horizon }
          : o,
      );
      set({ route: { ...cur, options } });
    } catch {
      /* aborted or failed */
    } finally {
      set({ departureLoading: false });
    }
  },

  ensureTripExposure: async () => {
    const { route, selectedRouteIdx, origin, destination, travelMode, profile, hour } = get();
    const opt = route?.options[selectedRouteIdx];
    if (!opt || !origin || !destination) return;
    if (horizonTimeline(opt.thermal_horizon).length) {
      get().startAutoDemo();
      return;
    }

    _exposureAbort?.abort();
    _exposureAbort = new AbortController();
    set({ tripExposureLoading: true });
    try {
      const res = await api.exposureTimeline(
        {
          origin,
          destination,
          mode: travelMode,
          profile,
          hour,
          label: opt.label,
          live: false,
          include_horizon: true,
          include_multimodal: false,
        },
        { signal: _exposureAbort.signal },
      );
      const cur = get().route;
      if (!cur) return;
      const options = cur.options.map((o, i) =>
        i === selectedRouteIdx ? { ...o, thermal_horizon: res.thermal_horizon ?? o.thermal_horizon } : o,
      );
      set({ route: { ...cur, options } });
    } catch {
      /* aborted or failed — keep UI usable */
    } finally {
      set({ tripExposureLoading: false });
      if (horizonTimeline(get().route?.options[get().selectedRouteIdx]?.thermal_horizon).length) {
        get().startAutoDemo();
      }
    }
  },

  selectRoute: (i) => {
    get().stopTrip();
    set({ selectedRouteIdx: i, exposureForecast: null, forecastDelayMin: 0, forecastError: null });
    void get().ensureTripExposure();
  },

  syncToNow: () => {
    const h = getCurrentUAEHour();
    void get().refreshEnvironment(true);
    get().refreshHour(h);
  },

  setPoint: (p) => {
    const pm = get().pickMode;
    if (pm === "origin")      set({ origin: p,      pickMode: null });
    else if (pm === "destination") set({ destination: p, pickMode: null });
    // App debounce effect will trigger a light route refresh.
  },

  // ---- async actions ----

  init: async () => {
    set({ appLoading: true });

    // Poll /api/status until the geo warm-up is done (it runs in a background
    // thread so the server accepts requests immediately).
    const waitForReady = async (): Promise<void> => {
      for (let attempt = 0; attempt < 120; attempt++) {
        try {
          const s = await fetch(`${API_BASE}/api/status`);
          const j = await s.json();
          if (j.ready) return;
        } catch { /* server still booting */ }
        await new Promise((r) => setTimeout(r, 1500));
      }
      throw new Error("Backend did not become ready within 3 minutes.");
    };

    try {
      await waitForReady();

      const currentHour = getCurrentUAEHour();
      const [sector, buildings, refuges, roadSegments] = await Promise.all([
        api.sector(),
        api.buildings(),
        api.refuges(),
        api.trafficRoads(),
      ]);
      set({ sector, buildings, refuges, roadSegments });

      // Seed origin/destination on opposite sides of the sector.
      const b = sector.bounds_wgs84;
      const origin      = { lat: b.south + (b.north - b.south) * 0.25, lon: b.west + (b.east - b.west) * 0.25 };
      const destination = { lat: b.south + (b.north - b.south) * 0.75, lon: b.west + (b.east - b.west) * 0.75 };
      set({ origin, destination });

      // Load comfort for right now, then air quality in parallel.
      await get().refreshHour(currentHour);
      await get().refreshAir();
      get().refreshProvenance();

      set({ appLoading: false });

      // Auto-compute a default route straight away.
      get().computeRoute({ full: true });
    } catch (e: any) {
      set({ error: e.message, appLoading: false });
    }
  },

  refreshEnvironment: async (force = false) => {
    try {
      const h = get().hour;
      const env = await api.environment(h, force);
      set({ env });
      // Recompute UTCI raster when live weather refreshes.
      if (force) {
        const comfort = await api.comfort(h);
        set({ comfort });
      }
    } catch {
      /* non-fatal */
    }
  },

  refreshProvenance: async () => {
    try {
      const provenance = await api.provenance();
      set({ provenance });
    } catch {
      /* non-fatal */
    }
  },

  refreshHour: async (h) => {
    const snapped = snapUAEHour(h);
    set({ hour: snapped });
    try {
      const [env, comfort] = await Promise.all([
        api.environment(snapped),
        api.comfort(snapped),
      ]);
      set({ env, comfort });
      if (get().layers.worstSegments || get().mode === "simulate") get().computeHeatExposure();
    } catch {
      /* transient */
    }
  },

  refreshAir: async () => {
    try {
      const data = await api.air();
      // Guard against stale backend responses or malformed payloads.
      if (
        !Array.isArray(data?.values) ||
        !Array.isArray(data?.shape) ||
        data.shape.length !== 2 ||
        data.values.length !== data.shape[0] * data.shape[1] ||
        !data.bounds_wgs84
      ) {
        return;
      }
      set({ airRaster: data });
    } catch {
      /* non-fatal */
    }
  },

  refreshCongestion: async () => {
    try {
      const c = await api.trafficCongestion();
      set((s) => ({ congestion: c, congestionSeq: s.congestionSeq + 1 }));
    } catch {
      /* non-fatal */
    }
  },

  computeRoute: async (opts) => {
    const full = opts?.full ?? false;
    const { origin, destination, travelMode, profile, hour } = get();
    if (!origin || !destination) return;

    const reqId = ++_routeReqSeq;
    _routeAbort?.abort();
    _routeAbort = new AbortController();

    set({ routing: true, error: undefined, tripPlaying: false, tripMinute: 0, tripCityHourSnap: -1, exposureForecast: null, forecastDelayMin: 0, forecastError: null });
    try {
      const route = await api.route(
        {
          origin,
          destination,
          mode: travelMode,
          profile,
          hour,
          live: full,
          include_horizon: full,
          include_multimodal: full || travelMode === "drive",
        },
        { signal: _routeAbort.signal, timeoutMs: full ? 90_000 : 45_000 },
      );
      if (reqId !== _routeReqSeq) return;

      const idx = Math.min(get().selectedRouteIdx, Math.max(0, route.options.length - 1));
      const balancedIdx = route.options.findIndex((o) => o.label === "Balanced");
      const selectedIdx = balancedIdx >= 0 ? balancedIdx : idx;
      set({ route, selectedRouteIdx: selectedIdx, routeUpdatedAt: Date.now(), exposure4DEnabled: full || get().exposure4DEnabled });
      if (full) {
        void get().ensureTripExposure();
      }
      // Best-departure scans 17 hours — only run on explicit user action, not auto-refresh.
    } catch (e: any) {
      if (reqId !== _routeReqSeq) return;
      if (e.message?.includes("timed out")) {
        set({ error: e.message });
      } else if (e.message?.includes("abort")) {
        /* superseded by newer request */
      } else {
        set({ error: e.message, route: undefined });
      }
    } finally {
      if (reqId === _routeReqSeq) set({ routing: false });
    }
  },

  computeBestDeparture: async () => {
    const { origin, destination, travelMode, profile } = get();
    if (!origin || !destination) return;
    try {
      const bd = await api.bestDeparture({ origin, destination, mode: travelMode, profile });
      set({ bestDeparture: bd });
    } catch (e: any) {
      set({ error: e.message });
    }
  },

  computeIsochrone: async (minutes) => {
    const { origin, hour, profile } = get();
    if (!origin) return;
    set({ isochroneMinutes: minutes });
    try {
      const iso = await api.isochrone({ origin, minutes, hour, profile, comfort_aware: true });
      set({ isochrone: iso, layers: { ...get().layers, isochrone: true } });
    } catch (e: any) {
      set({ error: e.message });
    }
  },

  computeHeatExposure: async () => {
    try {
      const he = await api.heatExposure(get().hour);
      set({ heatExposure: he });
    } catch {
      /* non-fatal */
    }
  },
}));
