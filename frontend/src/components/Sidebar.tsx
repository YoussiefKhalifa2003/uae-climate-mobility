import { useState } from "react";
import { useStore } from "../store/useStore";
import { UserProfile, RouteOption, RouteRealtimeMeta, RouteRiskOption } from "../api/client";
import { heatBandColor, cvsBandColor } from "../lib/colors";
import { BandBars } from "./charts";
import { partitionRouteOptions, ROUTE_INTENT, findRouteIndex } from "../lib/routes";
import SimulatePanel from "./SimulatePanel";
import LiveConditionsPanel from "./LiveConditionsPanel";

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
      {mode === "simulate" && <LiveConditionsPanel />}
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
