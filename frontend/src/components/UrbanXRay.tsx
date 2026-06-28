import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useStore, getCurrentUAEHour, getMaxSelectableUAEHour, snapUAEHour } from "../store/useStore";
import {
  activeTimeline,
  computeSafeWindows,
  fmtCityHour,
  fmtTripClock,
  combinedStressNorm,
  getActiveExposureContext,
  horizonTimeline,
  pickForecastSlot,
  sampleTimeline,
  tripDurationMin,
} from "../lib/tripExposure";
import { heatBandColor } from "../lib/colors";

function fmtHour(h: number): string {
  return fmtCityHour(h);
}

function ForecastSection({
  forecastPreview,
  onForecastScrub,
  onLoad,
}: {
  forecastPreview: number;
  onForecastScrub: (min: number) => void;
  onLoad: () => void;
}) {
  const exposureForecast = useStore((s) => s.exposureForecast);
  const forecastDelayMin = useStore((s) => s.forecastDelayMin);
  const forecastLoading = useStore((s) => s.forecastLoading);
  const forecastError = useStore((s) => s.forecastError);
  const forecastSlot = useMemo(
    () => pickForecastSlot(exposureForecast?.slots, forecastDelayMin),
    [exposureForecast, forecastDelayMin],
  );

  return (
    <div className="rounded-lg border border-sky-500/20 bg-sky-950/30 p-2.5">
      <div className="mb-1 flex items-center justify-between">
        <span className="text-[9px] font-semibold uppercase tracking-wider text-sky-400">
          World model · Leave in…
        </span>
        {exposureForecast && (
          <span className="text-[9px] text-slate-500">{exposureForecast.slots.length} slots</span>
        )}
      </div>

      {forecastLoading && (
        <p className="py-2 text-center text-[11px] text-amber-300 animate-pulse">
          Rolling forward 60 min (weather + sun + traffic)… ~30–90 s
        </p>
      )}

      {forecastError && !forecastLoading && (
        <div className="space-y-2">
          <p className="text-[11px] text-red-300">{forecastError}</p>
          <button
            type="button"
            onClick={onLoad}
            className="text-[10px] text-sky-400 hover:underline"
          >
            Retry forecast
          </button>
        </div>
      )}

      {!forecastLoading && !exposureForecast && !forecastError && (
        <button
          type="button"
          onClick={onLoad}
          className="w-full rounded-lg border border-sky-500/40 bg-sky-500/10 py-2 text-[11px] font-semibold text-sky-200 hover:bg-sky-500/20"
        >
          Load 60-min exposure forecast
        </button>
      )}

      {exposureForecast && !forecastLoading && (
        <>
          <input
            type="range"
            min={0}
            max={60}
            step={10}
            value={forecastPreview}
            onChange={(e) => onForecastScrub(parseInt(e.target.value, 10))}
            className="h-2 w-full cursor-pointer accent-sky-400"
          />
          <div className="mt-1 flex justify-between text-[10px] text-slate-500">
            <span>Now</span>
            <span className="font-mono text-sky-300">
              {forecastPreview === 0 ? "Leave now" : `+${forecastPreview} min`}
            </span>
            <span>+60 min</span>
          </div>
          {forecastSlot && forecastDelayMin > 0 && (
            <p className="mt-1.5 text-[10px] text-slate-300">
              vs leaving now:{" "}
              <span className={forecastSlot.delta_vs_now.mean_utci >= 0 ? "text-red-300" : "text-emerald-300"}>
                {forecastSlot.delta_vs_now.mean_utci >= 0 ? "+" : ""}
                {forecastSlot.delta_vs_now.mean_utci.toFixed(1)}°C avg UTCI
              </span>
              {" · "}
              peak {forecastSlot.peak_utci.toFixed(0)}°C
            </p>
          )}
          {forecastDelayMin === 0 && (
            <p className="mt-1 text-[10px] text-slate-500">Scrub right to see how waiting changes your exposure.</p>
          )}
        </>
      )}
    </div>
  );
}

export default function UrbanXRay() {
  const store = useStore();
  const {
    mode,
    hour,
    profile,
    route,
    selectedRouteIdx,
    tripMinute,
    tripPlaying,
    tripExposureLoading,
    departureLoading,
    xrayExpanded,
    bestDeparture,
    focusMode,
    demoPlaying,
    exposureForecast,
    forecastDelayMin,
    forecastLoading,
  } = store;

  const opt = route?.options[selectedRouteIdx];
  const horizon = opt?.thermal_horizon;
  const timeline = useMemo(
    () => getActiveExposureContext(exposureForecast, forecastDelayMin, horizon).timeline,
    [exposureForecast, forecastDelayMin, horizon],
  );
  const forecastSlot = useMemo(
    () => pickForecastSlot(exposureForecast?.slots, forecastDelayMin),
    [exposureForecast, forecastDelayMin],
  );
  const duration = timeline.length ? (timeline[timeline.length - 1]?.t_min ?? tripDurationMin(horizon)) : tripDurationMin(horizon);
  const frame = useMemo(
    () => (timeline.length ? sampleTimeline(timeline, tripMinute) : null),
    [timeline, tripMinute],
  );

  const thresholds = horizon?.thresholds ?? { warn: 38, critical: 46 };
  const { safe, hazards } = useMemo(
    () => computeSafeWindows(timeline, thresholds),
    [timeline, thresholds],
  );

  const maxDeparture = getMaxSelectableUAEHour();
  const minDeparture = 6;

  useEffect(() => {
    if (timeline.length > 0 && !store.layers.comfort) {
      store.toggleLayer("comfort");
    }
  }, [timeline.length, store]);

  const departureTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [departurePreview, setDeparturePreview] = useState(hour);
  const [forecastPreview, setForecastPreview] = useState(forecastDelayMin);
  const [showDetails, setShowDetails] = useState(false);

  useEffect(() => {
    setDeparturePreview(hour);
  }, [hour]);

  useEffect(() => {
    setForecastPreview(forecastDelayMin);
  }, [forecastDelayMin]);

  const onForecastScrub = useCallback(
    (min: number) => {
      const clamped = Math.max(0, Math.min(60, Math.round(min)));
      setForecastPreview(clamped);
      store.setForecastDelay(clamped);
    },
    [store],
  );

  const onDepartureScrub = useCallback(
    (h: number) => {
      const snapped = snapUAEHour(h);
      setDeparturePreview(snapped);
      store.setMapMoment(`Leaving at ${fmtHour(snapped)} — shadows & exposure recalculating…`);
      if (departureTimer.current) clearTimeout(departureTimer.current);
      departureTimer.current = setTimeout(() => {
        void store.setDepartureHour(snapped);
      }, 600);
    },
    [store],
  );

  if (mode === "simulate") return null;

  const hasRoute = Boolean(route?.options?.length);
  const loading = tripExposureLoading || departureLoading || forecastLoading;
  const activeHazard = hazards.find((h) => tripMinute >= h.startMin && tripMinute <= h.endMin);
  const activeSafe = safe.find((s) => tripMinute >= s.startMin && tripMinute <= s.endMin);

  const panelClass = focusMode
    ? "absolute bottom-4 left-1/2 z-20 w-[min(720px,92vw)] -translate-x-1/2 rounded-2xl border border-violet-400/50 bg-ink/90 shadow-2xl backdrop-blur-xl"
    : "absolute bottom-3 left-1/2 z-20 w-[min(960px,96vw)] -translate-x-1/2 rounded-xl border border-violet-500/30 bg-panel/95 shadow-2xl backdrop-blur-md";

  if (!hasRoute) {
    return (
      <div className={panelClass + " px-4 py-3"}>
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-widest text-violet-400">
              4D Urban X-Ray
            </div>
            <p className="text-[11px] text-slate-400">Find routes to walk through time, heat &amp; shade.</p>
          </div>
          <span className="font-mono text-lg font-bold text-white">{fmtHour(hour)}</span>
        </div>
      </div>
    );
  }

  return (
    <div className={panelClass}>
      {/* Focus mode — cinematic minimal UI */}
      {focusMode ? (
        <div className="px-5 py-4 space-y-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-violet-300">
                4D Urban X-Ray
              </div>
              <h2 className="mt-1 text-lg font-semibold text-white">
                When do you leave?
              </h2>
              <p className="text-[11px] text-slate-400">
                Drag to shift departure — watch shadow &amp; heat move on your path.
              </p>
            </div>
            <button
              type="button"
              onClick={() => store.toggleFocusMode()}
              className="shrink-0 rounded-lg border border-edge bg-panel2 px-3 py-1.5 text-[11px] text-slate-300 hover:text-white"
            >
              Exit focus
            </button>
          </div>

          {!timeline.length && !loading && (
            <button
              type="button"
              onClick={() => store.ensureTripExposure()}
              className="w-full rounded-xl bg-gradient-to-r from-violet-600 to-indigo-500 py-3 text-sm font-bold text-white"
            >
              Start X-Ray
            </button>
          )}

          {timeline.length > 0 && (
            <>
              <div>
                <div className="mb-2 flex items-baseline justify-between">
                  <span className="font-mono text-3xl font-bold text-white">{fmtHour(departurePreview)}</span>
                  {frame && (
                    <span className="text-[11px] text-slate-400">
                      {frame.shade_pct >= 50 ? "☁ In shadow" : "☀ In sun"} · UTCI {frame.utci.toFixed(0)}°C
                      {forecastSlot && forecastDelayMin > 0 && (
                        <span className={forecastSlot.delta_vs_now.mean_utci >= 0 ? " text-red-300" : " text-emerald-300"}>
                          {" "}({forecastSlot.delta_vs_now.mean_utci >= 0 ? "+" : ""}
                          {forecastSlot.delta_vs_now.mean_utci.toFixed(1)}° vs now)
                        </span>
                      )}
                    </span>
                  )}
                </div>
                <input
                  type="range"
                  min={minDeparture}
                  max={Math.max(minDeparture + 0.5, maxDeparture)}
                  step={0.25}
                  value={departurePreview}
                  onChange={(e) => onDepartureScrub(parseFloat(e.target.value))}
                  className="h-2 w-full cursor-pointer accent-violet-400"
                />
                <div className="mt-1 flex justify-between text-[10px] text-slate-500">
                  <span>Earlier</span>
                  <span>Now {fmtHour(getCurrentUAEHour())}</span>
                </div>
              </div>

              <ForecastSection
                forecastPreview={forecastPreview}
                onForecastScrub={onForecastScrub}
                onLoad={() => void store.fetchExposureForecast()}
              />

              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => store.toggleTripPlay()}
                  disabled={loading}
                  className="rounded-xl bg-violet-600 px-5 py-2.5 text-sm font-bold text-white disabled:opacity-40"
                >
                  {tripPlaying || demoPlaying ? "⏸ Pause walk" : "▶ Play your trip"}
                </button>
                <span className="font-mono text-xs text-slate-400">
                  {fmtTripClock(tripMinute)} / {fmtTripClock(duration)}
                </span>
                {activeSafe && (
                  <span className="rounded-full bg-emerald-500/20 px-2 py-0.5 text-[10px] text-emerald-300">
                    Safe zone
                  </span>
                )}
                {activeHazard && (
                  <span className="rounded-full bg-red-500/20 px-2 py-0.5 text-[10px] text-red-300">
                    Exposure peak
                  </span>
                )}
              </div>

              <input
                type="range"
                min={0}
                max={duration}
                step={0.05}
                value={Math.min(tripMinute, duration)}
                onChange={(e) => store.setTripMinute(parseFloat(e.target.value))}
                className="w-full accent-emerald-500"
              />

              {bestDeparture && (
                <button
                  type="button"
                  onClick={() => void store.setDepartureHour(bestDeparture.recommended_hour)}
                  className="text-[11px] text-emerald-400 hover:underline"
                >
                  Suggested: leave at {fmtHour(bestDeparture.recommended_hour)} (lower heat)
                </button>
              )}
            </>
          )}

          {loading && (
            <p className="text-center text-[11px] text-amber-300 animate-pulse">Syncing exposure field…</p>
          )}
          {demoPlaying && (
            <p className="text-center text-[11px] text-violet-300">Auto-demo — camera follows your exposure</p>
          )}
        </div>
      ) : (
        /* Standard panel */
        <>
          <div className="flex items-center justify-between gap-2 border-b border-edge/60 px-4 py-2">
            <div className="flex items-center gap-2">
              <span className="text-sm">🌪</span>
              <div>
                <div className="text-[10px] font-bold uppercase tracking-widest text-violet-300">
                  4D Urban X-Ray
                </div>
                <div className="text-[10px] text-slate-500">{opt?.label} · {profile}</div>
              </div>
            </div>
            <div className="flex items-center gap-2">
              {timeline.length > 0 && (
                <button
                  type="button"
                  onClick={() => store.toggleFocusMode()}
                  className="rounded-lg bg-violet-600/80 px-3 py-1 text-[11px] font-semibold text-white"
                >
                  Focus
                </button>
              )}
              {loading && <span className="text-[10px] text-amber-300 animate-pulse">Syncing…</span>}
              <button
                type="button"
                onClick={() => store.setXrayExpanded(!xrayExpanded)}
                className="rounded-lg bg-panel2 px-2 py-1 text-[10px] text-slate-400"
              >
                {xrayExpanded ? "▾" : "▸"}
              </button>
            </div>
          </div>

          {xrayExpanded && (
            <div className="px-4 py-3 space-y-3">
              {!timeline.length && !loading && (
                <button
                  type="button"
                  onClick={() => store.ensureTripExposure()}
                  className="w-full rounded-lg bg-gradient-to-r from-violet-600 to-accent2 px-4 py-2.5 text-xs font-bold text-white"
                >
                  Activate X-Ray
                </button>
              )}

              {timeline.length > 0 && (
                <>
                  <div>
                    <div className="mb-1 text-[9px] uppercase text-slate-500">When do you leave?</div>
                    <input
                      type="range"
                      min={minDeparture}
                      max={Math.max(minDeparture + 0.5, maxDeparture)}
                      step={0.25}
                      value={departurePreview}
                      onChange={(e) => onDepartureScrub(parseFloat(e.target.value))}
                      className="w-full accent-violet-500"
                    />
                    <div className="mt-0.5 text-right font-mono text-xs text-violet-300">{fmtHour(departurePreview)}</div>
                  </div>

                  <ForecastSection
                    forecastPreview={forecastPreview}
                    onForecastScrub={onForecastScrub}
                    onLoad={() => void store.fetchExposureForecast()}
                  />

                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => store.toggleTripPlay()}
                      className="rounded-lg bg-violet-600 px-3 py-1.5 text-xs font-semibold text-white"
                    >
                      {tripPlaying ? "⏸ Pause" : "▶ Play"}
                    </button>
                    <input
                      type="range"
                      min={0}
                      max={duration}
                      step={0.05}
                      value={Math.min(tripMinute, duration)}
                      onChange={(e) => store.setTripMinute(parseFloat(e.target.value))}
                      className="flex-1 accent-violet-500"
                    />
                  </div>

                  <button
                    type="button"
                    onClick={() => setShowDetails(!showDetails)}
                    className="text-[10px] text-slate-500 hover:text-slate-300"
                  >
                    {showDetails ? "Hide details ▴" : "Show details ▾"}
                  </button>

                  {showDetails && frame && (
                    <div className="grid grid-cols-4 gap-2 text-[10px]">
                      <Stat label="UTCI" value={`${frame.utci.toFixed(1)}°C`} color={heatBandColor[frame.band] ?? "#fff"} />
                      <Stat label="PM2.5" value={`${frame.pm25.toFixed(0)}`} color="#fdba74" />
                      <Stat label="Shade" value={frame.shade_pct >= 50 ? "Yes" : "No"} color="#94a3b8" />
                      <Stat label="Risk" value={`${(frame.overlap_score * 100).toFixed(0)}%`} color="#f87171" />
                    </div>
                  )}

                  {!bestDeparture && (
                    <button
                      type="button"
                      onClick={() => store.computeBestDeparture()}
                      className="text-[10px] text-slate-400 hover:text-white"
                    >
                      ⏰ Find best departure time
                    </button>
                  )}
                </>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function Stat({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="rounded-lg bg-panel2/70 px-2 py-1.5">
      <div className="text-slate-500">{label}</div>
      <div className="font-mono font-semibold" style={{ color }}>{value}</div>
    </div>
  );
}
