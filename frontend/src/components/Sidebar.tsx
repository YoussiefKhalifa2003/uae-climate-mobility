import { useState } from "react";
import { useStore } from "../store/useStore";
import { UserProfile, RouteOption, RouteRealtimeMeta, RouteRiskOption } from "../api/client";
import { heatBandColor, cvsBandColor } from "../lib/colors";
import { BandBars, CompareBandBars } from "./charts";
import { partitionRouteOptions, ROUTE_INTENT, findRouteIndex } from "../lib/routes";

const PROFILE_LABELS: Record<UserProfile, string> = {
  default: "Adult",
  child: "Child",
  elderly: "Elderly",
  asthma: "Asthma",
  athlete: "Athlete",
  wheelchair: "Wheelchair",
};

const PROFILES_WALK: UserProfile[] = ["default", "child", "elderly", "asthma", "athlete", "wheelchair"];
const PROFILES_DRIVE: UserProfile[] = ["default", "elderly", "asthma"];

export default function Sidebar() {
  const mode = useStore((s) => s.mode);
  return (
    <div className="absolute left-3 top-20 z-10 flex max-h-[calc(100vh-9rem)] w-[300px] flex-col gap-3 overflow-y-auto pb-2">
      {mode === "simulate" ? <SimulatePanel /> : <NavigatePanel />}
    </div>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-edge bg-panel/90 p-3 shadow-xl backdrop-blur">
      <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500">{title}</div>
      {children}
    </div>
  );
}

function NavigatePanel() {
  const store = useStore();
  const {
    origin,
    destination,
    profile,
    pickMode,
    route,
    routing,
    selectedRouteIdx,
    travelMode,
    routeUpdatedAt,
    routeRisk,
    routeRiskLoading,
  } = store;

  const riskByLabel = new Map(routeRisk?.options.map((o) => [o.label, o]) ?? []);

  const [showExtraRoutes, setShowExtraRoutes] = useState(false);
  const [showDetails, setShowDetails] = useState(false);
  const allowedProfiles = travelMode === "drive" ? PROFILES_DRIVE : PROFILES_WALK;
  const selectedOpt = route?.options[selectedRouteIdx];
  const { primary, extra } = route ? partitionRouteOptions(route.options) : { primary: [], extra: [] };
  const visible = showExtraRoutes ? route?.options ?? [] : primary;

  return (
    <>
      <Card title="Navigate">
        <div className="mb-2 flex gap-1 rounded-lg bg-panel2 p-0.5">
          <button
            type="button"
            onClick={() => store.setTravelMode("walk")}
            className={`flex-1 rounded-md py-1.5 text-[11px] font-semibold ${
              travelMode === "walk" ? "bg-accent text-ink" : "text-slate-400"
            }`}
          >
            🚶 Walk
          </button>
          <button
            type="button"
            onClick={() => store.setTravelMode("drive")}
            className={`flex-1 rounded-md py-1.5 text-[11px] font-semibold ${
              travelMode === "drive" ? "bg-accent text-ink" : "text-slate-400"
            }`}
          >
            🚗 Drive
          </button>
        </div>

        <div className="flex gap-2">
          <PointButton
            label="From"
            active={pickMode === "origin"}
            set={() => store.setPickMode("origin")}
            value={origin}
            dotClass="bg-accent"
          />
          <PointButton
            label="To"
            active={pickMode === "destination"}
            set={() => store.setPickMode("destination")}
            value={destination}
            dotClass="bg-accent2"
          />
        </div>

        <div className="mt-3">
          <div className="mb-1 text-[10px] uppercase text-slate-500">Profile</div>
          <div className="flex flex-wrap gap-1">
            {allowedProfiles.map((id) => (
              <button
                key={id}
                type="button"
                onClick={() => store.setProfile(id)}
                className={`rounded-md px-2 py-1 text-[11px] ${
                  profile === id ? "bg-violet-600 text-white" : "bg-panel2 text-slate-300 hover:bg-edge"
                }`}
              >
                {PROFILE_LABELS[id]}
              </button>
            ))}
          </div>
        </div>

        <button
          type="button"
          onClick={() => store.computeRoute({ full: true })}
          disabled={routing || !origin || !destination}
          className="mt-3 w-full rounded-lg bg-accent px-3 py-2.5 text-xs font-bold text-ink disabled:opacity-40"
        >
          {routing ? "Computing exposure…" : "Find route"}
        </button>
        <p className="mt-2 text-[10px] text-slate-500">
          Use the <strong className="text-violet-300">X-Ray</strong> panel below the map to scrub time &amp; exposure.
        </p>
      </Card>

      {route && route.options.length === 0 && (
        <Card title="No route">
          <p className="text-[11px] text-slate-300">Could not connect points on the {travelMode} network.</p>
        </Card>
      )}

      {route && visible.length > 0 && (
        <Card title="Routes">
          {routeRisk?.advisory && (
            <RiskAdvisory
              advisory={routeRisk.advisory}
              recommended={routeRisk.recommended_label}
              selectedLabel={selectedOpt?.label}
              onSelectRecommended={() => {
                const idx = findRouteIndex(route.options, routeRisk.recommended_label ?? "");
                if (idx >= 0) store.selectRoute(idx);
              }}
            />
          )}
          {routeRiskLoading && !routeRisk && (
            <p className="mb-2 text-[10px] text-slate-500 animate-pulse">Scoring routes under P95 weather…</p>
          )}
          {route.realtime && (
            <RealtimeBadge rt={route.realtime} updatedAt={routeUpdatedAt} routing={routing} />
          )}
          <div className="space-y-2">
            {visible.map((opt) => {
              const i = route.options.indexOf(opt);
              return (
                <RouteRow
                  key={`${opt.label}-${i}`}
                  opt={opt}
                  risk={riskByLabel.get(opt.label)}
                  recommended={routeRisk?.recommended_label === opt.label}
                  selected={i === selectedRouteIdx}
                  onClick={() => store.selectRoute(i)}
                />
              );
            })}
          </div>
          {extra.length > 0 && (
            <button
              type="button"
              onClick={() => setShowExtraRoutes(!showExtraRoutes)}
              className="mt-2 text-[10px] text-slate-400 hover:text-white"
            >
              {showExtraRoutes ? "Hide alternate routes ▴" : `Show ${extra.length} more routes ▾`}
            </button>
          )}
        </Card>
      )}

      {selectedOpt && (
        <div>
          <button
            type="button"
            onClick={() => setShowDetails(!showDetails)}
            className="mb-1 w-full text-left text-[10px] text-slate-500 hover:text-slate-300"
          >
            {showDetails ? "Hide route details ▴" : "Route details ▾"}
          </button>
          {showDetails && <CompactDetail opt={selectedOpt} />}
        </div>
      )}
    </>
  );
}

function SimulatePanel() {
  const store = useStore();
  const {
    heatExposure: he,
    hour,
    origin,
    interventionEdgeUids,
    interventionShade,
    counterfactual,
    counterfactualLoading,
    twinMapView,
    isochroneMinutes,
  } = store;
  const [reachMin, setReachMin] = useState(isochroneMinutes);

  return (
    <>
      <Card title="Counterfactual twin">
        <p className="mb-2 text-[11px] leading-snug text-slate-400">
          Model shade trees or awnings on hot streets. Compare baseline vs upgraded city exposure and
          see how far you can comfortably walk.
        </p>
        {he ? (
          <>
            <div className="mb-2 grid grid-cols-3 gap-2">
              <MiniStat label="Avg UTCI" value={`${he.summary.avg_utci_c}°`} />
              <MiniStat label="Dangerous" value={`${he.summary.dangerous_network_pct}%`} />
              <MiniStat label="Network" value={`${he.summary.network_km} km`} />
            </div>
            {!counterfactual ? (
              <>
                <BandBars bandPct={he.summary.band_pct} />
                <p className="mt-2 text-[10px] text-slate-400">{he.summary.equity_note}</p>
              </>
            ) : (
              <>
                {counterfactual.target_baseline && counterfactual.target_scenario && (
                  <div className="mb-2 rounded-lg border border-emerald-500/40 bg-emerald-950/40 px-2.5 py-2">
                    <div className="text-[9px] font-semibold uppercase tracking-wide text-emerald-300">
                      On selected streets ({counterfactual.delta.edges_targeted})
                    </div>
                    <div className="mt-1 font-mono text-lg font-bold text-white">
                      {counterfactual.target_baseline.avg_utci_c}° → {counterfactual.target_scenario.avg_utci_c}° UTCI
                    </div>
                    <p className="mt-0.5 text-[10px] text-emerald-200">
                      −{(counterfactual.delta.target_avg_utci_reduction_c ?? 0).toFixed(1)}°C avg on{" "}
                      {(counterfactual.delta.target_km ?? 0).toFixed(2)} km of upgraded streets
                    </p>
                  </div>
                )}
                <div className="mb-1 text-[9px] uppercase text-slate-500">Heat bands — selected streets</div>
                <CompareBandBars
                  baseline={counterfactual.target_baseline?.band_pct ?? counterfactual.baseline.band_pct}
                  scenario={counterfactual.target_scenario?.band_pct ?? counterfactual.scenario.band_pct}
                />
                <div className="mt-2 grid grid-cols-2 gap-2 text-[10px]">
                  <div className="rounded-lg bg-panel2/60 px-2 py-1.5">
                    <div className="text-slate-500">City-wide UTCI</div>
                    <div className="font-mono text-slate-400">
                      {counterfactual.baseline.avg_utci_c}° → {counterfactual.scenario.avg_utci_c}°
                      <span className="ml-1 text-[9px]">(whole network)</span>
                    </div>
                  </div>
                  <div className="rounded-lg bg-panel2/60 px-2 py-1.5">
                    <div className="text-slate-500">Band upgrades</div>
                    <div className="font-mono text-emerald-300">
                      {counterfactual.delta.network_km_upgraded_band} km improved
                    </div>
                  </div>
                </div>
                <p className="mt-2 text-[10px] text-slate-400">
                  City-wide numbers move slowly when only a few streets change — look at the{" "}
                  <strong className="text-emerald-300">thick colored lines on the map</strong> and toggle
                  Baseline / After upgrade below.
                </p>
              </>
            )}
          </>
        ) : (
          <p className="text-xs text-slate-500">Loading city exposure…</p>
        )}
      </Card>

      <Card title="Intervention">
        <p className="mb-2 text-[10px] text-slate-500">
          Click red hotspots on the map to add/remove streets. Gold = selected for upgrade.
        </p>
        <div className="mb-2 flex flex-wrap gap-1">
          <button
            type="button"
            onClick={() => store.seedInterventionFromWorst(10)}
            className="rounded-md bg-panel2 px-2 py-1 text-[10px] text-slate-200 hover:bg-edge"
          >
            Top 10 hottest
          </button>
          <button
            type="button"
            onClick={() => store.seedInterventionFromWorst(25)}
            className="rounded-md bg-panel2 px-2 py-1 text-[10px] text-slate-200 hover:bg-edge"
          >
            Top 25
          </button>
          <button
            type="button"
            onClick={() => store.clearIntervention()}
            className="rounded-md bg-panel2 px-2 py-1 text-[10px] text-slate-400 hover:bg-edge"
          >
            Clear
          </button>
        </div>
        <p className="mb-2 font-mono text-[10px] text-amber-300">{interventionEdgeUids.length} streets selected</p>

        <div className="mb-1 text-[10px] uppercase text-slate-500">Added shade cover</div>
        <div className="flex items-center gap-2">
          <input
            type="range"
            min={0.2}
            max={1}
            step={0.1}
            value={interventionShade}
            onChange={(e) => store.setInterventionShade(parseFloat(e.target.value))}
            className="flex-1 accent-accent"
          />
          <span className="w-12 font-mono text-xs text-slate-300">{(interventionShade * 100).toFixed(0)}%</span>
        </div>

        <button
          type="button"
          onClick={() => void store.runCounterfactual()}
          disabled={!he || counterfactualLoading || interventionEdgeUids.length === 0}
          className="mt-3 w-full rounded-lg bg-accent px-3 py-2.5 text-xs font-bold text-ink disabled:opacity-40"
        >
          {counterfactualLoading ? "Running twin…" : "Apply counterfactual twin"}
        </button>

        {counterfactual && (
          <div className="mt-2 space-y-2">
            <div className="rounded-lg bg-panel2/60 p-2 text-[11px]">
              <Row label="Streets upgraded" value={`${counterfactual.delta.edges_targeted}`} />
              <Row
                label="Selected streets UTCI ↓"
                value={`${(counterfactual.delta.target_avg_utci_reduction_c ?? 0).toFixed(1)}°C`}
                good
              />
              <Row label="City UTCI ↓" value={`${counterfactual.delta.avg_utci_reduction_c}°C`} />
              <Row label="Band upgrades" value={`${counterfactual.delta.network_km_upgraded_band} km`} good />
            </div>
            <div className="flex gap-1">
              <button
                type="button"
                onClick={() => store.setTwinMapView("baseline")}
                className={`flex-1 rounded-md py-1 text-[10px] font-semibold ${
                  twinMapView === "baseline" ? "bg-panel2 text-white" : "text-slate-500"
                }`}
              >
                Baseline map
              </button>
              <button
                type="button"
                onClick={() => store.setTwinMapView("scenario")}
                className={`flex-1 rounded-md py-1 text-[10px] font-semibold ${
                  twinMapView === "scenario" ? "bg-emerald-700/60 text-white" : "text-slate-500"
                }`}
              >
                After upgrade
              </button>
            </div>
            <button
              type="button"
              onClick={() => store.clearCounterfactual()}
              className="w-full text-[10px] text-slate-500 hover:text-slate-300"
            >
              Reset twin results
            </button>
          </div>
        )}
      </Card>

      <Card title="Reachability">
        <p className="mb-2 text-[10px] text-slate-500">
          Comfort-aware walk radius from origin — included in twin when origin is set.
        </p>
        <PointButton
          label="Origin"
          active={store.pickMode === "origin"}
          set={() => store.setPickMode("origin")}
          value={origin}
          dotClass="bg-accent"
        />
        <div className="mt-2 flex items-center gap-2">
          <input
            type="range"
            min={5}
            max={30}
            step={5}
            value={reachMin}
            onChange={(e) => setReachMin(parseInt(e.target.value, 10))}
            className="flex-1 accent-accent"
          />
          <span className="font-mono text-xs text-slate-300">{reachMin} min</span>
        </div>
        <button
          type="button"
          onClick={() => store.computeIsochrone(reachMin)}
          disabled={!origin}
          className="mt-2 w-full rounded-lg bg-panel2 px-3 py-2 text-xs font-semibold text-slate-200 disabled:opacity-40"
        >
          Refresh isochrone
        </button>
        {counterfactual?.isochrone && (
          <div className="mt-2 rounded-lg border border-emerald-500/30 bg-emerald-950/30 px-2.5 py-2 text-[10px]">
            <div className="font-semibold text-emerald-300">Walkable area gain</div>
            <p className="mt-1 text-slate-200">
              {counterfactual.isochrone.baseline_area_km2} km² → {counterfactual.isochrone.scenario_area_km2} km²
              <span className="ml-1 font-mono text-emerald-300">
                (+{counterfactual.isochrone.area_gain_pct}%)
              </span>
            </p>
            <p className="mt-0.5 text-slate-500">At {fmtSimHour(hour)} with intervention applied city-wide.</p>
          </div>
        )}
      </Card>
    </>
  );
}

function fmtSimHour(h: number): string {
  const hh = Math.floor(h) % 24;
  const mm = Math.round((h % 1) * 60);
  return `${hh.toString().padStart(2, "0")}:${mm.toString().padStart(2, "0")}`;
}

function PointButton({
  label,
  active,
  set,
  value,
  dotClass,
}: {
  label: string;
  active: boolean;
  set: () => void;
  value?: { lat: number; lon: number };
  dotClass: string;
}) {
  return (
    <button
      type="button"
      onClick={set}
      className={`flex-1 rounded-lg border px-2 py-1.5 text-left text-[11px] ${
        active ? "border-accent bg-panel2" : "border-edge bg-panel2/50 hover:bg-panel2"
      }`}
    >
      <div className="flex items-center gap-1.5">
        <span className={`h-2 w-2 rounded-full ${dotClass}`} />
        <span className="text-slate-300">{label}</span>
      </div>
      <div className="mt-0.5 font-mono text-[10px] text-slate-500">
        {value ? `${value.lat.toFixed(4)}, ${value.lon.toFixed(4)}` : "tap map"}
      </div>
    </button>
  );
}

function RiskAdvisory({
  advisory,
  recommended,
  selectedLabel,
  onSelectRecommended,
}: {
  advisory: string;
  recommended?: string | null;
  selectedLabel?: string;
  onSelectRecommended: () => void;
}) {
  const showSwitch = recommended && selectedLabel && recommended !== selectedLabel;
  return (
    <div className="mb-2 rounded-lg border border-violet-500/40 bg-violet-950/40 px-2.5 py-2">
      <div className="text-[9px] font-semibold uppercase tracking-wide text-violet-300">Uncertainty advisory</div>
      <p className="mt-1 text-[10px] leading-snug text-slate-200">{advisory}</p>
      {showSwitch && (
        <button
          type="button"
          onClick={onSelectRecommended}
          className="mt-2 rounded-md bg-violet-600 px-2 py-1 text-[10px] font-semibold text-white hover:bg-violet-500"
        >
          Switch to {recommended}
        </button>
      )}
    </div>
  );
}

function RouteRow({
  opt,
  risk,
  recommended,
  selected,
  onClick,
}: {
  opt: RouteOption;
  risk?: RouteRiskOption;
  recommended?: boolean;
  selected: boolean;
  onClick: () => void;
}) {
  const m = opt.metrics;
  const c = `rgb(${opt.color[0]},${opt.color[1]},${opt.color[2]})`;
  const intent = ROUTE_INTENT[opt.label] ?? opt.description;
  return (
    <button
      type="button"
      onClick={onClick}
      className={`w-full rounded-lg border p-2 text-left transition ${
        selected ? "border-2 bg-panel2" : "border border-edge bg-panel2/40 hover:bg-panel2"
      }`}
      style={{ borderColor: selected ? c : undefined }}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: c }} />
          <span className="truncate text-xs font-semibold text-white">{opt.label}</span>
        </div>
        <span className="font-mono text-[11px] text-slate-300">{m.duration_min} min</span>
      </div>
      <p className="mt-0.5 truncate text-[10px] text-slate-500">{intent}</p>
      {risk && (
        <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px]">
          <span className={risk.confidence_pct >= 70 ? "text-emerald-300" : risk.confidence_pct >= 45 ? "text-amber-300" : "text-red-300"}>
            {risk.confidence_pct.toFixed(0)}% safe (P95)
          </span>
          <span className="font-mono text-slate-400">peak {risk.peak_utci_p95.toFixed(0)}°C</span>
          {recommended && (
            <span className="rounded bg-violet-600/60 px-1 py-px text-[9px] font-semibold text-violet-100">Recommended</span>
          )}
        </div>
      )}
      {m.cvs_score != null && (
        <div className="mt-1 text-[10px]" style={{ color: cvsBandColor[m.cvs_band ?? "Fair"] }}>
          CVS {m.cvs_score} · {m.cvs_band}
        </div>
      )}
    </button>
  );
}

function CompactDetail({ opt }: { opt: RouteOption }) {
  const m = opt.metrics;
  return (
    <Card title={`${opt.label}`}>
      <div className="mb-2 rounded-lg border border-accent/30 bg-accent/10 px-3 py-2">
        <div className="text-[10px] uppercase text-accent">Inhaled PM2.5</div>
        <div className="font-mono text-xl font-bold text-white">{m.inhaled_pm25_ug} µg</div>
      </div>
      <div className="grid grid-cols-2 gap-2 text-[10px]">
        <MiniStat label="UTCI" value={`${m.avg_utci_c}°C`} />
        <MiniStat label="Shade" value={`${m.shade_pct}%`} />
        <MiniStat label="Distance" value={`${(m.distance_m / 1000).toFixed(1)} km`} />
        <MiniStat label="Heat risk" value={m.max_heat_risk} />
      </div>
    </Card>
  );
}

function Row({ label, value, good }: { label: string; value: string; good?: boolean }) {
  return (
    <div className="flex justify-between">
      <span className="text-slate-400">{label}</span>
      <span className={`font-mono ${good ? "text-accent" : "text-slate-200"}`}>{value}</span>
    </div>
  );
}

function RealtimeBadge({
  rt,
  updatedAt,
  routing,
}: {
  rt: RouteRealtimeMeta;
  updatedAt?: number;
  routing: boolean;
}) {
  const ageS = updatedAt ? Math.round((Date.now() - updatedAt) / 1000) : 0;
  return (
    <div className="mb-2 flex flex-wrap gap-1 text-[9px]">
      <span className={`rounded px-1.5 py-0.5 ${routing ? "bg-amber-500/20 text-amber-300" : "bg-emerald-500/20 text-emerald-300"}`}>
        {routing ? "Updating…" : `Live · ${ageS}s`}
      </span>
      {rt.env_live && <Tag label="Weather" />}
      {rt.aqi_live && <Tag label="AQI" />}
    </div>
  );
}

function Tag({ label }: { label: string }) {
  return <span className="rounded bg-sky-500/15 px-1.5 py-0.5 text-sky-300">● {label}</span>;
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-panel2/60 px-2 py-1.5">
      <div className="text-[10px] uppercase text-slate-500">{label}</div>
      <div className="font-mono text-sm font-semibold text-slate-100">{value}</div>
    </div>
  );
}
