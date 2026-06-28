import { useEffect, useMemo, useRef } from "react";
import LiveMap from "./LiveMap";
import { useStore, getCurrentUAEHour, getMaxSelectableUAEHour, isRouteRefreshBlocked, snapUAEHour } from "./store/useStore";
import { getActiveExposureContext } from "./lib/tripExposure";
import TopBar from "./components/TopBar";
import Sidebar from "./components/Sidebar";
import TimeBar from "./components/TimeBar";
import UrbanXRay from "./components/UrbanXRay";
import MapMoment from "./components/MapMoment";
import Legend from "./components/Legend";
import DataProvenance from "./components/DataProvenance";

export default function App() {
  const init               = useStore((s) => s.init);
  const appLoading         = useStore((s) => s.appLoading);
  const playing            = useStore((s) => s.playing);
  const hour               = useStore((s) => s.hour);
  const refreshAllLayers   = useStore((s) => s.refreshAllLayers);
  const refreshAir         = useStore((s) => s.refreshAir);
  const refreshCongestion  = useStore((s) => s.refreshCongestion);
  const refreshEnvironment = useStore((s) => s.refreshEnvironment);
  const refreshProvenance  = useStore((s) => s.refreshProvenance);
  const syncToNow          = useStore((s) => s.syncToNow);
  const error              = useStore((s) => s.error);
  const origin             = useStore((s) => s.origin);
  const destination        = useStore((s) => s.destination);
  const profile            = useStore((s) => s.profile);
  const travelMode         = useStore((s) => s.travelMode);
  const route              = useStore((s) => s.route);
  const computeRoute       = useStore((s) => s.computeRoute);
  const routing            = useStore((s) => s.routing);
  const tripPlaying        = useStore((s) => s.tripPlaying);
  const tripMinute         = useStore((s) => s.tripMinute);
  const setTripMinute      = useStore((s) => s.setTripMinute);
  const stopTrip           = useStore((s) => s.stopTrip);
  const selectedRouteIdx   = useStore((s) => s.selectedRouteIdx);
  const mode               = useStore((s) => s.mode);
  const focusMode          = useStore((s) => s.focusMode);
  const departureLoading   = useStore((s) => s.departureLoading);
  const demoPlaying        = useStore((s) => s.demoPlaying);
  const skipNextRouteRefresh = useStore((s) => s.skipNextRouteRefresh);
  const exposureForecast = useStore((s) => s.exposureForecast);
  const forecastDelayMin = useStore((s) => s.forecastDelayMin);

  const tripDuration = useMemo(() => {
    const opt = route?.options[selectedRouteIdx];
    return getActiveExposureContext(exposureForecast, forecastDelayMin, opt?.thermal_horizon).duration;
  }, [route, selectedRouteIdx, exposureForecast, forecastDelayMin]);

  // Boot
  useEffect(() => { init(); }, [init]);

  // Live weather/AQI: refresh every 45 s (bypass backend cache, refresh overlays).
  useEffect(() => {
    const ms = mode === "simulate" ? 45_000 : 60_000;
    const id = setInterval(() => refreshEnvironment(true), ms);
    return () => clearInterval(id);
  }, [refreshEnvironment, mode]);

  // Data provenance registry: every 30 s.
  useEffect(() => {
    refreshProvenance();
    const id = setInterval(() => refreshProvenance(), 30_000);
    return () => clearInterval(id);
  }, [refreshProvenance]);

  // Real-time sync: every 60 s drift back to current UAE time.
  useEffect(() => {
    const id = setInterval(() => syncToNow(), 60_000);
    return () => clearInterval(id);
  }, [syncToNow]);

  // Air-quality refresh: every 5 s.
  useEffect(() => {
    const id = setInterval(() => refreshAir(), 5_000);
    return () => clearInterval(id);
  }, [refreshAir]);

  // Road congestion refresh: every 2 s — fast enough to show traffic pulse.
  useEffect(() => {
    const id = setInterval(() => refreshCongestion(), 2_000);
    return () => clearInterval(id);
  }, [refreshCongestion]);

  // Recompute routes when trip inputs change — Navigate mode only, never during X-Ray.
  useEffect(() => {
    if (mode !== "navigate") return;
    if (!origin || !destination || playing || tripPlaying || demoPlaying) return;
    if (departureLoading || isRouteRefreshBlocked(useStore.getState())) return;
    if (skipNextRouteRefresh) {
      useStore.setState({ skipNextRouteRefresh: false });
      return;
    }
    const t = setTimeout(() => computeRoute({ full: false }), 1200);
    return () => clearTimeout(t);
  }, [mode, hour, profile, travelMode, origin, destination, playing, tripPlaying, demoPlaying, departureLoading, skipNextRouteRefresh, computeRoute]);

  // Light route refresh — Navigate mode only, paused during X-Ray.
  useEffect(() => {
    const id = setInterval(() => {
      const s = useStore.getState();
      if (s.mode !== "navigate") return;
      if (isRouteRefreshBlocked(s) || s.focusMode) return;
      if (route?.options?.length && origin && destination && !routing && !tripPlaying) {
        computeRoute({ full: false });
      }
    }, 45_000);
    return () => clearInterval(id);
  }, [route?.options?.length, origin, destination, routing, tripPlaying, computeRoute]);

  // 4D trip playback — advances trip clock, syncs city layers to frame city_hour.
  const tripMinRef = useRef(tripMinute);
  tripMinRef.current = tripMinute;
  useEffect(() => {
    if (!tripPlaying) return;
    if (tripDuration <= 0) return;

    const id = setInterval(() => {
      const next = tripMinRef.current + 0.25;
      if (next >= tripDuration) {
        setTripMinute(tripDuration);
        stopTrip();
        return;
      }
      setTripMinute(next);
    }, 200);
    return () => clearInterval(id);
  }, [tripPlaying, tripDuration, setTripMinute, stopTrip]);

  // Playback: advance the slider on a fixed clock; refresh every layer in parallel (non-blocking).
  const hourRef = useRef(hour);
  hourRef.current = hour;
  useEffect(() => {
    if (!playing) return;

    const tick = () => {
      const nowH = getCurrentUAEHour();
      const maxH = getMaxSelectableUAEHour();
      const current = hourRef.current;
      const atLive = current >= maxH - 0.01;
      const targetH = atLive
        ? nowH
        : Math.min(maxH, Math.round((current + 0.5) * 2) / 2);

      const snapped = snapUAEHour(targetH);
      hourRef.current = snapped;
      useStore.setState({ hour: snapped });

      void refreshAllLayers(snapped, { forceEnv: atLive || snapped >= maxH - 0.01 });
    };

    tick();
    const id = setInterval(tick, 1_500);
    return () => clearInterval(id);
  }, [playing, refreshAllLayers]);

  return (
    <div className="relative h-full w-full">
      <LiveMap />
      <TopBar />
      {!focusMode && <Sidebar />}
      {mode === "simulate" ? <TimeBar /> : <UrbanXRay />}
      {!focusMode && mode === "simulate" && <Legend />}
      {!focusMode && <DataProvenance />}
      <MapMoment />

      {/* Loading overlay */}
      {appLoading && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-ink/85 backdrop-blur-sm">
          <div className="flex flex-col items-center gap-5 rounded-2xl border border-edge bg-panel/90 p-8 shadow-2xl">
            <div className="h-12 w-12 animate-spin rounded-full border-4 border-edge border-t-accent" />
            <div className="text-center">
              <p className="text-base font-semibold text-white">
                🌇 UAE Climate Mobility Platform
              </p>
              <p className="mt-1 text-sm text-slate-300">
                Loading city data — please wait…
              </p>
            </div>
            <div className="space-y-1 text-[11px] text-slate-500">
              <p>• Downloading real Dubai street network (OpenStreetMap)</p>
              <p>• Computing solar position &amp; building shadows</p>
              <p>• Initialising 20,000-agent traffic simulation</p>
            </div>
            <p className="text-[10px] text-slate-600">
              First run takes 30–60 s · subsequent starts are instant (cached)
            </p>
          </div>
        </div>
      )}

      {/* Toast error */}
      {error && !appLoading && (
        <div className="absolute bottom-48 left-1/2 z-40 -translate-x-1/2 rounded-md bg-danger/90 px-4 py-2 text-sm text-white shadow-lg">
          {error}
        </div>
      )}
    </div>
  );
}
