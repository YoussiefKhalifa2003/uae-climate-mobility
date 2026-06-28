import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { aqiColor } from "../lib/colors";
import { useStore } from "../store/useStore";

type TrafficStatus = Awaited<ReturnType<typeof api.trafficStatus>>;

function syncAgeLabel(at?: number): string {
  if (!at) return "syncing…";
  const s = Math.max(0, Math.floor((Date.now() - at) / 1000));
  if (s < 2) return "just now";
  if (s < 60) return `${s}s ago`;
  return `${Math.floor(s / 60)}m ago`;
}

function avgCongestion(c: Record<string, number>): number | null {
  const vals = Object.values(c);
  if (!vals.length) return null;
  return vals.reduce((a, b) => a + b, 0) / vals.length;
}

function LiveBadge({ live }: { live: boolean }) {
  return (
    <span
      className={`rounded px-1 py-0.5 text-[8px] font-bold uppercase ${
        live ? "bg-accent/20 text-accent" : "bg-warn/15 text-warn"
      }`}
    >
      {live ? "Live" : "Sim"}
    </span>
  );
}

function MetricRow({
  label,
  value,
  live,
  sub,
}: {
  label: string;
  value: React.ReactNode;
  live?: boolean;
  sub?: string;
}) {
  return (
    <div className="rounded-lg bg-panel2/60 px-2.5 py-2">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[10px] font-medium uppercase tracking-wide text-slate-500">{label}</span>
        {live !== undefined && <LiveBadge live={live} />}
      </div>
      <div className="mt-0.5 font-mono text-sm font-semibold text-slate-100">{value}</div>
      {sub && <p className="mt-0.5 text-[9px] leading-snug text-slate-500">{sub}</p>}
    </div>
  );
}

export default function LiveConditionsPanel() {
  const playing = useStore((s) => s.playing);
  const env = useStore((s) => s.env);
  const airRaster = useStore((s) => s.airRaster);
  const congestion = useStore((s) => s.congestion);
  const layerSyncAt = useStore((s) => s.layerSyncAt);
  const provenance = useStore((s) => s.provenance);

  const [trafficStatus, setTrafficStatus] = useState<TrafficStatus | null>(null);
  const [, tick] = useState(0);

  useEffect(() => {
    if (!playing) {
      setTrafficStatus(null);
      return;
    }
    let cancelled = false;
    const load = () => {
      api.trafficStatus().then((s) => {
        if (!cancelled) setTrafficStatus(s);
      });
    };
    load();
    const id = setInterval(load, 3_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [playing]);

  useEffect(() => {
    if (!playing) return;
    const id = setInterval(() => tick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, [playing]);

  const prov = useMemo(() => {
    const layers = provenance?.layers ?? [];
    const by = (k: string) => layers.find((l) => l.layer === k);
    return {
      weather: by("weather"),
      aqi: by("aqi_point"),
      airMap: by("air_map"),
      traffic: by("traffic"),
    };
  }, [provenance]);

  const streetCongPct = useMemo(() => {
    const avg = avgCongestion(congestion);
    return avg != null ? Math.round(avg * 100) : null;
  }, [congestion]);

  if (!playing) return null;

  const trafficLive = trafficStatus?.live ?? prov.traffic?.live ?? false;
  const tomtomPct =
    trafficStatus?.tomtom_regional_congestion != null
      ? Math.round(trafficStatus.tomtom_regional_congestion * 100)
      : null;

  return (
    <div className="rounded-xl border border-accent/30 bg-panel/95 p-3 shadow-xl backdrop-blur-sm">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wider text-accent">Live conditions</p>
          <p className="text-[9px] text-slate-500">Updates with the time slider · {syncAgeLabel(layerSyncAt)}</p>
        </div>
        <span className="rounded-full bg-accent/15 px-2 py-0.5 text-[9px] font-bold text-accent">▶ PLAY</span>
      </div>

      <div className="space-y-1.5">
        <MetricRow
          label="Weather · Downtown Dubai"
          live={env?.wx_live ?? prov.weather?.live ?? false}
          value={
            env ? (
              <>
                {env.air_temp_c.toFixed(1)}°C · RH {env.relative_humidity.toFixed(0)}% · wind{" "}
                {env.wind_speed_ms.toFixed(1)} m/s
              </>
            ) : (
              "…"
            )
          }
          sub={prov.weather?.source ?? (env?.wx_live ? "Open-Meteo" : env?.source ?? "loading")}
        />

        <MetricRow
          label="Air quality (measured point)"
          live={env?.aq_live ?? prov.aqi?.live ?? false}
          value={
            env?.aqi != null ? (
              <span style={{ color: aqiColor(env.aqi) }}>
                AQI {env.aqi}
                {env.pm25_ug_m3 != null && (
                  <span className="ml-2 text-slate-300">PM2.5 {env.pm25_ug_m3.toFixed(0)} µg/m³</span>
                )}
              </span>
            ) : (
              "…"
            )
          }
          sub={prov.aqi?.detail ?? "Open-Meteo Air Quality API when live"}
        />

        {airRaster && airRaster.shape[0] > 0 && (
          <MetricRow
            label="Pollution map (street plumes)"
            live={prov.airMap?.live ?? env?.aq_live ?? false}
            value={
              <>
                baseline {airRaster.baseline_pm25.toFixed(0)} · peak {airRaster.pm25_max.toFixed(0)} µg/m³
              </>
            }
            sub={
              prov.airMap?.detail ??
              "Live PM2.5 baseline + traffic dispersion model (not a raw sensor grid)"
            }
          />
        )}

        <MetricRow
          label="Road congestion"
          live={trafficLive}
          value={
            tomtomPct != null ? (
              <>TomTom regional {tomtomPct}% busy</>
            ) : streetCongPct != null ? (
              <>Streets avg {streetCongPct}% congested</>
            ) : (
              "…"
            )
          }
          sub={
            trafficLive || tomtomPct != null
              ? (trafficStatus?.detail ?? prov.traffic?.detail ?? "TomTom Flow API blended with street map")
              : trafficStatus?.sim_congested_pct != null
                ? `Agent simulation · ${trafficStatus.sim_congested_pct.toFixed(0)}% of network congested`
                : (prov.traffic?.detail ?? "Agent traffic model on OSM roads")
          }
        />

        {streetCongPct != null && tomtomPct != null && (
          <p className="px-1 text-[9px] text-slate-500">Map streets avg {streetCongPct}% congested (sim + TomTom blend)</p>
        )}
      </div>
    </div>
  );
}
