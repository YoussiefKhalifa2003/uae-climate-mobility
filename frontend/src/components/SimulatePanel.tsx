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
    selectingInView,
  } = store;

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
        <p className="mt-1.5 text-[9px] text-slate-400">
          Temp, humidity &amp; AQI refresh live from Open-Meteo (Downtown Dubai). Heat, fog &amp; wind layers
          are physics models driven by that live weather + OSM buildings. Traffic is simulated unless you add a
          TomTom API key to <span className="font-mono">.env</span> (see Data sources panel).
        </p>
      </div>

      <Step n={1} title="Pick streets to upgrade">
        <p className="mb-2 text-[10px] text-slate-400">
          Pan/zoom first, then tap a button below. Selected streets turn into a{" "}
          <span className="font-bold text-amber-300">bright gold glow</span> you can&apos;t miss.
        </p>
        <div className="flex flex-col gap-1.5">
          <button
            type="button"
            onClick={() => void store.selectInterventionInView("replace")}
            disabled={selectingInView}
            className="w-full rounded-lg bg-amber-500 px-3 py-2.5 text-xs font-bold text-ink shadow-md hover:bg-amber-400 disabled:opacity-60"
          >
            {selectingInView ? "Finding hot streets in view…" : "★ Select hot streets in this view (spread out)"}
          </button>
          <button
            type="button"
            onClick={() => store.seedInterventionFromWorst(10)}
            className="w-full rounded-lg bg-violet-700 px-3 py-2 text-xs font-semibold text-white hover:bg-violet-600"
          >
            City-wide top 10 hottest
          </button>
          <button
            type="button"
            onClick={() => store.clearIntervention()}
            className="rounded-lg bg-panel2 px-3 py-1.5 text-[10px] text-slate-400 hover:bg-edge"
          >
            Clear selection
          </button>
        </div>

        {interventionEdgeUids.length > 0 ? (
          <div className="mt-3 rounded-lg border-2 border-amber-400 bg-amber-500/20 px-3 py-2.5">
            <p className="text-lg font-bold text-amber-200">{interventionEdgeUids.length} streets selected</p>
            <p className="text-[10px] text-amber-100/90">Look for the pulsing gold lines on the map ↑</p>
          </div>
        ) : (
          <p className="mt-2 text-[10px] text-slate-500">Nothing selected yet — pan somewhere, then use a button above.</p>
        )}
        <p className="mt-2 text-[9px] text-slate-500">Or click individual red streets on the map to toggle them.</p>
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
                store.setMapMoment("Edit selection — click red streets or use Select in view");
              }}
              className="text-[10px] text-amber-300 hover:text-amber-200"
            >
              Edit selection
            </button>
          </div>
        </div>
      )}

      {he && !counterfactual && (
        <p className="mt-3 text-[10px] text-slate-500">
          Network: {he.summary.dangerous_network_pct}% of walkable streets in dangerous heat bands.
        </p>
      )}
    </div>
  );
}
