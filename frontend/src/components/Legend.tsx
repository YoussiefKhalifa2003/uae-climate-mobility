import { useEffect, useState } from "react";
import { useStore } from "../store/useStore";
import { heatBandColor, refugeColor } from "../lib/colors";
import CollapsibleCornerPanel from "./CollapsibleCornerPanel";
import { api } from "../api/client";

const LAYER_META: {
  key: keyof ReturnType<typeof useStore.getState>["layers"];
  label: string;
  hint: string;
  provKey?: string;
  simulateOnly?: boolean;
}[] = [
  { key: "buildings", label: "3D Buildings", hint: "Building heights & shadows", provKey: "buildings" },
  { key: "worstSegments", label: "Hot streets", hint: "Simulate: click to select for upgrade", simulateOnly: true },
  { key: "humidity", label: "Humidity fog", hint: "Trapped coastal moisture (purple = worst)", simulateOnly: true },
  { key: "comfort", label: "Heat map", hint: "UTCI comfort field", provKey: "utci" },
  { key: "air", label: "Air pollution", hint: "Traffic + PM2.5 plume", provKey: "air_map" },
  { key: "traffic", label: "Traffic", hint: "Agent sim by default; add TOMTOM_API_KEY in .env for live flow", provKey: "traffic" },
  { key: "refuges", label: "Cool spots", hint: "Malls, metro, parks", provKey: "refuges" },
  { key: "routes", label: "Routes", hint: "Navigate mode only" },
  { key: "wind", label: "Wind flow", hint: "Flowing breeze streaks (live wind + canyon model)", simulateOnly: true },
];

export default function Legend() {
  const layers = useStore((s) => s.layers);
  const mode = useStore((s) => s.mode);
  const toggleLayer = useStore((s) => s.toggleLayer);
  const provenance = useStore((s) => s.provenance);
  const [trafficStatus, setTrafficStatus] = useState<Awaited<ReturnType<typeof api.trafficStatus>> | null>(null);

  useEffect(() => {
    if (!layers.traffic) {
      setTrafficStatus(null);
      return;
    }
    let cancelled = false;
    const load = () => {
      api.trafficStatus().then((s) => {
        if (!cancelled) setTrafficStatus(s);
      }).catch(() => {});
    };
    load();
    const id = setInterval(load, 30_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [layers.traffic]);

  const liveFor = (key?: string) =>
    key ? provenance?.layers.find((l) => l.layer === key)?.live : undefined;

  const trafficProv = provenance?.layers.find((l) => l.layer === "traffic");

  const visible = LAYER_META.filter((m) => !m.simulateOnly || mode === "simulate");

  return (
    <CollapsibleCornerPanel
      title="Layers"
      side="right"
      className="max-w-[280px]"
      defaultOpen={mode !== "simulate"}
      positionClass={mode === "simulate" ? "bottom-24 right-3" : undefined}
    >
      <div className="grid grid-cols-1 gap-1">
        {visible.map(({ key, label, hint, provKey }) => {
          const live = liveFor(provKey);
          return (
            <label
              key={key}
              className="flex cursor-pointer items-start gap-1.5 rounded-lg px-1 py-0.5 hover:bg-panel2/40"
            >
              <input
                type="checkbox"
                checked={layers[key]}
                onChange={() => toggleLayer(key)}
                className="mt-0.5 accent-accent"
              />
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-1.5 text-[11px] text-slate-200">
                  {label}
                  {live === true && (
                    <span className="rounded bg-accent/15 px-1 text-[8px] text-accent">LIVE</span>
                  )}
                  {live === false && (
                    <span className="rounded bg-warn/15 px-1 text-[8px] text-warn">SIM</span>
                  )}
                </span>
                <span className="block text-[9px] text-slate-500">{hint}</span>
              </span>
            </label>
          );
        })}
      </div>

      {layers.traffic && (trafficStatus?.ready || trafficProv) && (
        <div className="mt-2 rounded-lg border border-edge/80 bg-panel2/40 px-2 py-1.5">
          <p className="text-[9px] font-semibold uppercase tracking-wide text-slate-500">Traffic source</p>
          <p className="mt-0.5 text-[10px] text-slate-200">
            {(trafficStatus?.live ?? trafficProv?.live) ? (
              <>
                <span className="font-semibold text-accent">Live</span>
                {" — "}
                {trafficStatus?.detail ?? trafficProv?.detail ?? "TomTom Flow API"}
              </>
            ) : (
              <>
                <span className="font-semibold text-warn">Simulated</span>
                {" — agent model (add TOMTOM_API_KEY for live)"}
              </>
            )}
          </p>
          {trafficStatus?.tomtom_regional_congestion != null && (
            <p className="mt-0.5 font-mono text-[9px] text-slate-400">
              TomTom regional congestion: {(trafficStatus.tomtom_regional_congestion * 100).toFixed(0)}%
            </p>
          )}
        </div>
      )}

      {mode !== "simulate" && (
        <>
          <div className="mt-3 border-t border-edge pt-2">
            <div className="mb-1 text-[9px] font-semibold uppercase text-slate-500">Refuge colors</div>
            <div className="space-y-0.5 text-[9px] text-slate-400">
              <div className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full" style={{ background: `rgb(${refugeColor.railway.slice(0, 3).join(",")})` }} />
                Blue — transit / metro stations
              </div>
              <div className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full" style={{ background: `rgb(${refugeColor.shop.slice(0, 3).join(",")})` }} />
                Purple — malls & indoor amenities
              </div>
              <div className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full" style={{ background: `rgb(${refugeColor.leisure.slice(0, 3).join(",")})` }} />
                Green — parks & shaded leisure
              </div>
            </div>
          </div>

          <div className="mt-2 border-t border-edge pt-2">
            <div className="mb-1 text-[9px] font-semibold uppercase text-slate-500">UTCI heat bands</div>
            <div className="flex flex-wrap gap-1 text-[8px]">
              {Object.entries(heatBandColor).map(([band, color]) => (
                <span key={band} style={{ color }}>{band}</span>
              ))}
            </div>
          </div>
        </>
      )}
    </CollapsibleCornerPanel>
  );
}
