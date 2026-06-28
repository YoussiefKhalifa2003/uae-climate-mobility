import { useState } from "react";
import { useStore } from "../store/useStore";
import type { InterventionType } from "../api/client";
import { CompareBandBars } from "./charts";

const INTERVENTIONS: { id: InterventionType; label: string; plain: string; resultHint: string }[] = [
  {
    id: "SolidCanopy",
    label: "Canopy",
    plain: "Shade structures — blocks sun, best for open sidewalks",
    resultHint: "Shade-only fix — lowers radiant heat, not air temperature",
  },
  {
    id: "ActiveMisting",
    label: "Misting",
    plain: "Water mist — cools air fast, adds humidity nearby",
    resultHint: "Strongest cooling — drops air temp, but raises local humidity",
  },
  {
    id: "XeriscapeForestry",
    label: "Ghaf trees",
    plain: "Native trees — steady shade + small air cooling",
    resultHint: "Balanced fix — moderate shade plus transpiration cooling",
  },
];

const INTERVENTION_LABEL: Record<InterventionType, string> = {
  SolidCanopy: "Canopy",
  ActiveMisting: "Misting",
  XeriscapeForestry: "Ghaf trees",
  LegacyShade: "Generic shade",
};

function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-edge bg-panel p-3 shadow-md">
      <div className="mb-2 flex items-center gap-2">
        <span className="flex h-5 w-5 items-center justify-center rounded-full bg-violet-600 text-[10px] font-bold text-white">
          {n}
        </span>
        <span className="text-xs font-semibold text-slate-100">{title}</span>
      </div>
      {children}
    </div>
  );
}

export default function SimulatePanel() {
  const store = useStore();
  const {
    heatExposure: he,
    origin,
    interventionEdgeUids,
    interventionType,
    counterfactual,
    counterfactualLoading,
    v2xScenario,
    v2xLoading,
    simulateSelectMode,
  } = store;
  const [v2xActive, setV2xActive] = useState(v2xScenario?.v2x_coordination_active ?? false);
  const [v2xPen, setV2xPen] = useState(Math.round((v2xScenario?.av_penetration_rate ?? 0.5) * 100));

  const selectedType = INTERVENTIONS.find((t) => t.id === interventionType);
  const previewType = counterfactual?.intervention_type ?? interventionType;
  const previewLabel = INTERVENTION_LABEL[previewType] ?? previewType;

  return (
    <div className="rounded-xl border border-edge bg-panel/95 p-3 shadow-xl backdrop-blur-sm">
      <div className="mb-3 rounded-lg border border-violet-500/40 bg-violet-950/90 px-3 py-2.5">
        <p className="text-[11px] leading-relaxed text-slate-200">
          <strong className="text-violet-200">City planner mode.</strong> Pan to your area, select streets,
          pick a cooling fix, then preview before &amp; after on the map.
        </p>
      </div>

      <Step n={1} title="Pick streets to upgrade">
        <p className="mb-2 text-[10px] text-slate-400">
          Pan/zoom to the area you care about, then select streets. Selected lines glow{" "}
          <span className="font-semibold text-amber-300">neon gold</span> on the map.
        </p>
        <div className="flex flex-wrap gap-1">
          <button
            type="button"
            onClick={() => store.selectInterventionInView("replace")}
            className="rounded-md bg-violet-700 px-2 py-1 text-[10px] font-semibold text-white hover:bg-violet-600"
          >
            Select in view
          </button>
          <button
            type="button"
            onClick={() => store.setSimulateSelectMode("box")}
            className={`rounded-md px-2 py-1 text-[10px] ${
              simulateSelectMode === "box"
                ? "bg-amber-500 font-bold text-ink"
                : "bg-panel2 text-slate-200 hover:bg-edge"
            }`}
          >
            Draw box
          </button>
          <button
            type="button"
            onClick={() => store.seedInterventionFromWorst(10)}
            className="rounded-md bg-panel2 px-2 py-1 text-[10px] text-slate-200 hover:bg-edge"
          >
            City-wide top 10
          </button>
          <button
            type="button"
            onClick={() => {
              store.clearIntervention();
              store.setSimulateSelectMode("click");
            }}
            className="rounded-md bg-panel2 px-2 py-1 text-[10px] text-slate-400 hover:bg-edge"
          >
            Clear
          </button>
        </div>
        {simulateSelectMode === "box" && (
          <p className="mt-2 text-[10px] font-medium text-amber-300">Box mode active — drag on the map</p>
        )}
        <p className="mt-2 font-mono text-[11px] font-semibold text-amber-300">
          {interventionEdgeUids.length} streets selected
        </p>
        {interventionEdgeUids.length === 0 && (
          <p className="mt-1 text-[9px] text-slate-500">Nothing selected yet — pick an area first.</p>
        )}
      </Step>

      <Step n={2} title="Choose a cooling fix">
        <div className="mb-2 flex flex-wrap gap-1">
          {INTERVENTIONS.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => store.setInterventionType(t.id)}
              className={`rounded-md px-2 py-1 text-[10px] ${
                interventionType === t.id
                  ? "bg-accent font-bold text-ink"
                  : "bg-panel2 text-slate-200 hover:bg-edge"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
        {selectedType && <p className="text-[10px] text-slate-400">{selectedType.plain}</p>}
        <button
          type="button"
          onClick={() => void store.runCounterfactual()}
          disabled={!he || counterfactualLoading || interventionEdgeUids.length === 0}
          className="mt-3 w-full rounded-lg bg-accent px-3 py-2.5 text-xs font-bold text-ink disabled:opacity-40"
        >
          {counterfactualLoading ? "Calculating…" : "Preview before & after"}
        </button>
        <p className="mt-1.5 text-[9px] text-slate-500">
          Red inner line = today · green outer line = after your fix on the same streets.
        </p>
      </Step>

      {counterfactual && (
        <div className="mt-3 space-y-2 rounded-lg border border-emerald-500/50 bg-emerald-950/90 p-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-emerald-300">Preview results</p>
            <span className="rounded-full bg-emerald-500/20 px-2 py-0.5 text-[9px] font-bold text-emerald-200">
              {previewLabel} · {counterfactual.delta.edges_targeted} streets
            </span>
          </div>
          {selectedType && (
            <p className="text-[9px] text-slate-400">
              {INTERVENTIONS.find((t) => t.id === previewType)?.resultHint ?? selectedType.resultHint}
            </p>
          )}
          {counterfactual.target_baseline && counterfactual.target_scenario && (
            <div>
              <div className="font-mono text-xl font-bold text-white">
                {counterfactual.target_baseline.avg_utci_c}° → {counterfactual.target_scenario.avg_utci_c}°C
              </div>
              <p className="text-[10px] text-emerald-200">Average heat on your selected streets (cooler is better)</p>
            </div>
          )}
          {counterfactual.walkability && (
            <p className="text-[11px] text-slate-200">
              Walkability{" "}
              <span className="font-mono font-semibold text-cyan-300">
                {counterfactual.walkability.baseline.score} → {counterfactual.walkability.scenario.score}
              </span>
              <span className="text-emerald-300"> (+{counterfactual.walkability.delta.toFixed(1)})</span>
            </p>
          )}
          {!origin && counterfactual.walkability && Math.abs(counterfactual.walkability.delta) < 0.05 && (
            <p className="text-[9px] text-slate-500">
              Tip: set a start point in Navigate mode to see walkable-area gains here.
            </p>
          )}
          {counterfactual.target_baseline && counterfactual.target_scenario && (
            <CompareBandBars
              baseline={counterfactual.target_baseline.band_pct}
              scenario={counterfactual.target_scenario.band_pct}
            />
          )}
          {counterfactual.isochrone && origin && (
            <p className="text-[10px] text-slate-300">
              From your origin: walkable area{" "}
              {counterfactual.isochrone.baseline_area_km2} → {counterfactual.isochrone.scenario_area_km2} km²
              <span className="text-emerald-300"> (+{counterfactual.isochrone.area_gain_pct}%)</span>
            </p>
          )}
          <div className="flex flex-wrap gap-3 pt-1">
            <button
              type="button"
              onClick={() => store.clearCounterfactual()}
              className="text-[10px] text-slate-400 hover:text-slate-200"
            >
              Clear preview
            </button>
            <button
              type="button"
              onClick={() => {
                store.clearCounterfactual();
                store.setMapMoment("Edit selection — click streets or draw a new box");
              }}
              className="text-[10px] text-amber-300 hover:text-amber-200"
            >
              Edit selection
            </button>
          </div>
        </div>
      )}

      <div className="mt-4 rounded-lg border border-edge bg-panel p-3">
        <p className="mb-1 text-xs font-semibold text-slate-100">Cleaner traffic (optional)</p>
        <p className="mb-2 text-[10px] leading-snug text-slate-400">
          Models smoother self-driving traffic → less exhaust at the curb. Updates the air pollution layer only.
        </p>
        <label className="mb-2 flex cursor-pointer items-center gap-2 text-xs text-slate-200">
          <input
            type="checkbox"
            checked={v2xActive}
            onChange={(e) => setV2xActive(e.target.checked)}
            className="accent-accent"
          />
          Smoother traffic scenario
        </label>
        <div className="flex items-center gap-2">
          <input
            type="range"
            min={0}
            max={100}
            step={10}
            value={v2xPen}
            onChange={(e) => setV2xPen(parseInt(e.target.value, 10))}
            className="flex-1 accent-accent"
            disabled={!v2xActive}
          />
          <span className="w-10 font-mono text-xs text-slate-300">{v2xPen}%</span>
        </div>
        <button
          type="button"
          disabled={v2xLoading}
          onClick={() => void store.setV2xScenario(v2xActive, v2xPen / 100)}
          className="mt-2 w-full rounded-lg bg-panel2 px-3 py-2 text-xs font-semibold text-slate-200 disabled:opacity-40"
        >
          {v2xLoading ? "Updating…" : "Update air pollution map"}
        </button>
        {v2xScenario?.v2x_coordination_active && (
          <p className="mt-2 text-[10px] text-emerald-300">
            Active — exhaust ~{Math.round(v2xScenario.emission_scale * 100)}% on map
          </p>
        )}
      </div>

      {he && !counterfactual && (
        <p className="mt-3 text-[10px] text-slate-500">
          Network: {he.summary.dangerous_network_pct}% of walkable streets in dangerous heat bands.
        </p>
      )}
    </div>
  );
}
