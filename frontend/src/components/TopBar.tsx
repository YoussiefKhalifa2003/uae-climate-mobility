import { useEffect, useState } from "react";
import { useStore, AppMode } from "../store/useStore";
import { api } from "../api/client";
import { aqiColor } from "../lib/colors";

const MODES: { id: AppMode; label: string; icon: string }[] = [
  { id: "navigate", label: "Navigate", icon: "🧭" },
  { id: "simulate", label: "Simulate", icon: "🏙️" },
];

function envAgeLabel(fetchedAt?: number): string {
  if (!fetchedAt) return "";
  const s = Math.floor(Date.now() / 1000 - fetchedAt);
  if (s < 60) return `updated ${s}s ago`;
  return `updated ${Math.floor(s / 60)}m ago`;
}

export default function TopBar() {
  const mode = useStore((s) => s.mode);
  const setMode = useStore((s) => s.setMode);
  const env = useStore((s) => s.env);
  const sector = useStore((s) => s.sector);
  const [backend, setBackend] = useState<string>("");

  useEffect(() => {
    api
      .health()
      .then((h) => setBackend(`${h.compute.device}${h.compute.gpu ? " (GPU)" : ""}`))
      .catch(() => setBackend("unknown"));
  }, []);

  return (
    <div className="pointer-events-none absolute left-0 right-0 top-0 z-10 flex items-start justify-between p-3">
      <div className="pointer-events-auto rounded-xl border border-edge bg-panel/90 px-4 py-2 shadow-xl backdrop-blur">
        <div className="flex items-center gap-2">
          <span className="text-lg">🌇</span>
          <div>
            <h1 className="text-sm font-semibold tracking-wide text-white">
              UAE Climate Mobility
            </h1>
            <p className="text-[10px] text-violet-300/90">
              {mode === "simulate" ? "Counterfactual Twin · Phase 3" : "Exposure Engine · World Model v2"}
            </p>
          </div>
        </div>
        <p className="mt-0.5 text-[11px] text-slate-400">
          {sector ? sector.place : "loading sector…"}
        </p>
      </div>

      <div className="pointer-events-auto flex gap-1 rounded-xl border border-edge bg-panel/90 p-1 shadow-xl backdrop-blur">
        {MODES.map((m) => (
          <button
            key={m.id}
            type="button"
            onClick={() => setMode(m.id)}
            className={`rounded-lg px-4 py-1.5 text-xs font-semibold transition ${
              mode === m.id ? "bg-violet-600 text-white" : "text-slate-300 hover:bg-panel2"
            }`}
          >
            <span className="mr-1">{m.icon}</span>
            {m.label}
          </button>
        ))}
      </div>

      <div className="pointer-events-auto rounded-xl border border-edge bg-panel/90 px-4 py-2 text-right shadow-xl backdrop-blur">
        {env ? (
          <div className="flex items-center gap-4 text-xs">
            <Stat label="Air" value={`${env.air_temp_c.toFixed(1)}°C`} />
            <Stat label="RH" value={`${env.relative_humidity.toFixed(0)}%`} />
            <div>
              <div className="text-[10px] uppercase text-slate-500">AQI</div>
              <div className="font-mono font-semibold" style={{ color: aqiColor(env.aqi ?? 0) }}>
                {env.aqi ?? "-"}
              </div>
            </div>
          </div>
        ) : (
          <span className="text-xs text-slate-500">env…</span>
        )}
        <p className="mt-0.5 text-[10px] text-slate-500">
          {env?.source ?? "…"}
          {env?.fetched_at ? ` · ${envAgeLabel(env.fetched_at)}` : ""}
          {" · "}{backend}
        </p>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase text-slate-500">{label}</div>
      <div className="font-mono font-semibold text-slate-200">{value}</div>
    </div>
  );
}
