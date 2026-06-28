import type { ExposureTimelineFrame, ExposureForecastSlot, ThermalHorizon } from "../api/client";

/** Interpolate exposure frame at fractional trip minute. */
export function sampleTimeline(
  timeline: ExposureTimelineFrame[],
  tripMin: number,
): ExposureTimelineFrame | null {
  if (!timeline.length) return null;
  if (tripMin <= timeline[0].t_min) return timeline[0];
  const last = timeline[timeline.length - 1];
  if (tripMin >= last.t_min) return last;

  for (let i = 0; i < timeline.length - 1; i++) {
    const a = timeline[i];
    const b = timeline[i + 1];
    if (tripMin >= a.t_min && tripMin <= b.t_min) {
      const span = b.t_min - a.t_min || 1;
      const t = (tripMin - a.t_min) / span;
      return {
        t_min: tripMin,
        city_hour: a.city_hour + (b.city_hour - a.city_hour) * t,
        lat: a.lat + (b.lat - a.lat) * t,
        lon: a.lon + (b.lon - a.lon) * t,
        utci: a.utci + (b.utci - a.utci) * t,
        utci_delta: b.utci - a.utci,
        pm25: a.pm25 + (b.pm25 - a.pm25) * t,
        aqi: Math.round(a.aqi + (b.aqi - a.aqi) * t),
        shade_pct: a.shade_pct + (b.shade_pct - a.shade_pct) * t,
        overlap_score: a.overlap_score + (b.overlap_score - a.overlap_score) * t,
        intersection: a.intersection || b.intersection,
        band: a.band,
      };
    }
  }
  return last;
}

export function horizonTimeline(horizon?: ThermalHorizon): ExposureTimelineFrame[] {
  return horizon?.timeline ?? [];
}

/** Nearest forecast slot for a delay offset (minutes). */
export function pickForecastSlot(
  slots: ExposureForecastSlot[] | undefined,
  delayMin: number,
): ExposureForecastSlot | null {
  if (!slots?.length) return null;
  let best = slots[0];
  for (const s of slots) {
    if (Math.abs(s.delay_minutes - delayMin) < Math.abs(best.delay_minutes - delayMin)) best = s;
  }
  return best;
}

/** Active trip timeline — forecast slot when delay > 0, else route horizon. */
export function activeTimeline(
  forecast: { slots: ExposureForecastSlot[] } | null | undefined,
  forecastDelayMin: number,
  horizon?: ThermalHorizon,
): ExposureTimelineFrame[] {
  if (forecastDelayMin > 0 && forecast?.slots?.length) {
    const slot = pickForecastSlot(forecast.slots, forecastDelayMin);
    if (slot?.timeline?.length) return slot.timeline;
  }
  return horizonTimeline(horizon);
}

/** Unified trip context — use everywhere playback/scrub touches the timeline. */
export function getActiveExposureContext(
  exposureForecast: { slots: ExposureForecastSlot[] } | null | undefined,
  forecastDelayMin: number,
  horizon?: ThermalHorizon,
) {
  const timeline = activeTimeline(exposureForecast, forecastDelayMin, horizon);
  const duration = timeline.length
    ? timeline[timeline.length - 1].t_min
    : tripDurationMin(horizon);
  return {
    timeline,
    duration,
    thresholds: horizon?.thresholds ?? { warn: 38, critical: 46 },
  };
}

export function tripDurationMin(horizon?: ThermalHorizon): number {
  if (!horizon) return 0;
  return horizon.total_min ?? horizon.timeline?.length ?? 0;
}

export function fmtTripClock(min: number): string {
  const m = Math.floor(min);
  const s = Math.round((min - m) * 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function fmtCityHour(h: number): string {
  const hh = Math.floor(h) % 24;
  const mm = Math.round((h % 1) * 60);
  return `${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}`;
}

/** Normalize UTCI / PM2.5 into 0–1 stress for sparkline bars. */
export function heatStressNorm(utci: number, warn = 38): number {
  return Math.max(0, Math.min(1, (utci - 26) / Math.max(1, warn - 26 + 12)));
}

export function pmStressNorm(pm25: number, baseline = 35): number {
  return Math.max(0, Math.min(1, (pm25 - baseline) / 80));
}

export interface ShadeCrossing {
  t_min: number;
  city_hour: number;
  lat: number;
  lon: number;
  entering_shade: boolean;
}

/** Points where the traveller crosses into or out of building shadow. */
export function findShadeCrossings(timeline: ExposureTimelineFrame[]): ShadeCrossing[] {
  const out: ShadeCrossing[] = [];
  for (let i = 1; i < timeline.length; i++) {
    const prevShaded = timeline[i - 1].shade_pct >= 50;
    const currShaded = timeline[i].shade_pct >= 50;
    if (prevShaded === currShaded) continue;
    out.push({
      t_min: timeline[i].t_min,
      city_hour: timeline[i].city_hour,
      lat: timeline[i].lat,
      lon: timeline[i].lon,
      entering_shade: currShaded,
    });
  }
  return out;
}

export interface ExposureRibbonSegment {
  path: [number, number][];
  utci: number;
  pm25: number;
  t_min: number;
  t_max: number;
  shaded: boolean;
  intersection: boolean;
}

/** Heat stress used for safety / ribbon when P95 bands are present. */
export function effectiveHeatUtci(f: ExposureTimelineFrame): number {
  return f.utci_p95 ?? f.utci;
}

export function timelineHasP95Bands(timeline: ExposureTimelineFrame[]): boolean {
  return timeline.some((f) => f.utci_p95 != null);
}

/** Best delayed-departure slot by P95 heat-threshold confidence. */
export function findBestLeaveSlot(slots: ExposureForecastSlot[] | undefined) {
  if (!slots?.length) return null;
  let best = slots[0];
  for (const s of slots) {
    const conf = s.confidence_pct ?? 0;
    const bestConf = best.confidence_pct ?? 0;
    if (conf > bestConf || (conf === bestConf && (s.peak_utci_p95 ?? s.peak_utci) < (best.peak_utci_p95 ?? best.peak_utci))) {
      best = s;
    }
  }
  return best;
}

export interface UncertaintyBucket {
  t_min: number;
  utci_p50: number;
  utci_p95: number;
  band_width_c: number;
}

/** Downsample timeline into buckets for the uncertainty strip (data-driven, not decorative). */
export function buildUncertaintyBuckets(timeline: ExposureTimelineFrame[], maxBuckets = 24): UncertaintyBucket[] {
  if (!timelineHasP95Bands(timeline)) return [];
  const n = Math.min(maxBuckets, timeline.length);
  const step = Math.max(1, Math.floor(timeline.length / n));
  const buckets: UncertaintyBucket[] = [];
  for (let i = 0; i < timeline.length; i += step) {
    const f = timeline[i];
    const p50 = f.utci_p50 ?? f.utci;
    const p95 = f.utci_p95 ?? f.utci;
    buckets.push({
      t_min: f.t_min,
      utci_p50: p50,
      utci_p95: p95,
      band_width_c: f.band_width_c ?? Math.max(0, p95 - p50),
    });
  }
  return buckets;
}

/** Path segments coloured by per-minute exposure along the trip. */
export function buildExposureRibbon(
  timeline: ExposureTimelineFrame[],
  opts?: { worstCase?: boolean },
): ExposureRibbonSegment[] {
  if (timeline.length < 2) return [];
  const worstCase = opts?.worstCase && timelineHasP95Bands(timeline);
  const segs: ExposureRibbonSegment[] = [];
  for (let i = 0; i < timeline.length - 1; i++) {
    const a = timeline[i];
    const b = timeline[i + 1];
    segs.push({
      path: [
        [a.lon, a.lat],
        [b.lon, b.lat],
      ],
      utci: worstCase ? effectiveHeatUtci(a) : a.utci,
      pm25: worstCase && a.pm25_p95 != null ? a.pm25_p95 : a.pm25,
      t_min: a.t_min,
      t_max: b.t_min,
      shaded: a.shade_pct >= 50,
      intersection: a.intersection || b.intersection,
    });
  }
  return segs;
}

export interface SafeWindow {
  startMin: number;
  endMin: number;
  startCityHour: number;
  endCityHour: number;
}

export interface HazardWall {
  startMin: number;
  endMin: number;
  peakUtci: number;
  peakPm25: number;
  kind: "heat" | "air" | "both";
}

function frameIsSafe(f: ExposureTimelineFrame, warn: number, critical: number, useP95: boolean): boolean {
  const heat = useP95 ? effectiveHeatUtci(f) : f.utci;
  const pm = useP95 && f.pm25_p95 != null ? f.pm25_p95 : f.pm25;
  const heatOk = heat < warn;
  const airOk = pm < 55 && f.overlap_score < 0.45;
  const notCritical = heat < critical && !f.intersection;
  return heatOk && airOk && notCritical;
}

/** Biometric-safe trip intervals for the current departure timeline. */
export function computeSafeWindows(
  timeline: ExposureTimelineFrame[],
  thresholds: { warn: number; critical: number },
  opts?: { useP95Envelope?: boolean },
): { safe: SafeWindow[]; hazards: HazardWall[] } {
  if (!timeline.length) return { safe: [], hazards: [] };

  const useP95 = opts?.useP95Envelope ?? timelineHasP95Bands(timeline);
  const safe: SafeWindow[] = [];
  const hazards: HazardWall[] = [];
  let safeStart: ExposureTimelineFrame | null = null;
  let hazardStart: ExposureTimelineFrame | null = null;
  let hazardPeakUtci = 0;
  let hazardPeakPm = 0;
  let hazardHeat = false;
  let hazardAir = false;

  const flushSafe = (end: ExposureTimelineFrame) => {
    if (!safeStart || end.t_min - safeStart.t_min < 1.5) {
      safeStart = null;
      return;
    }
    safe.push({
      startMin: safeStart.t_min,
      endMin: end.t_min,
      startCityHour: safeStart.city_hour,
      endCityHour: end.city_hour,
    });
    safeStart = null;
  };

  const flushHazard = (end: ExposureTimelineFrame) => {
    if (!hazardStart || end.t_min - hazardStart.t_min < 1) {
      hazardStart = null;
      hazardPeakUtci = 0;
      hazardPeakPm = 0;
      hazardHeat = false;
      hazardAir = false;
      return;
    }
    let kind: HazardWall["kind"] = "both";
    if (hazardHeat && !hazardAir) kind = "heat";
    else if (hazardAir && !hazardHeat) kind = "air";
    hazards.push({
      startMin: hazardStart.t_min,
      endMin: end.t_min,
      peakUtci: hazardPeakUtci,
      peakPm25: hazardPeakPm,
      kind,
    });
    hazardStart = null;
    hazardPeakUtci = 0;
    hazardPeakPm = 0;
    hazardHeat = false;
    hazardAir = false;
  };

  for (const f of timeline) {
    const heat = useP95 ? effectiveHeatUtci(f) : f.utci;
    const pm = useP95 && f.pm25_p95 != null ? f.pm25_p95 : f.pm25;
    const isSafe = frameIsSafe(f, thresholds.warn, thresholds.critical, useP95);
    const isHazard =
      f.intersection ||
      heat >= thresholds.critical ||
      f.overlap_score >= 0.55 ||
      (heat >= thresholds.warn && pm >= 50);

    if (isSafe) {
      flushHazard(f);
      if (!safeStart) safeStart = f;
    } else {
      flushSafe(f);
      safeStart = null;
    }

    if (isHazard) {
      if (!hazardStart) hazardStart = f;
      hazardPeakUtci = Math.max(hazardPeakUtci, heat);
      hazardPeakPm = Math.max(hazardPeakPm, pm);
      if (heat >= thresholds.warn) hazardHeat = true;
      if (pm >= 45 || f.intersection) hazardAir = true;
    } else {
      flushHazard(f);
    }
  }

  const last = timeline[timeline.length - 1];
  flushSafe(last);
  flushHazard(last);
  return { safe, hazards };
}

/** Combined 0–1 stress for timeline strip rendering. */
export function combinedStressNorm(
  f: ExposureTimelineFrame,
  warn = 38,
): number {
  return Math.min(1, heatStressNorm(f.utci, warn) * 0.55 + pmStressNorm(f.pm25) * 0.45 + (f.intersection ? 0.2 : 0));
}
