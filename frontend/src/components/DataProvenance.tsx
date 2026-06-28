import { useStore } from "../store/useStore";
import type { ProvenanceLayer } from "../api/client";
import CollapsibleCornerPanel from "./CollapsibleCornerPanel";

function fmtAge(s: number): string {
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ago`;
}

function Row({ r }: { r: ProvenanceLayer }) {
  return (
    <div className="rounded-lg bg-panel2/50 px-2 py-1.5">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] font-medium text-slate-200">{r.label}</span>
        <span
          className={`shrink-0 rounded-full px-1.5 py-0.5 text-[9px] font-semibold uppercase ${
            r.live ? "bg-accent/20 text-accent" : "bg-warn/15 text-warn"
          }`}
        >
          {r.live ? "Live" : "Sim"}
        </span>
      </div>
      <div className="mt-0.5 font-mono text-[9px] text-slate-500">{r.source}</div>
      {r.detail && <div className="mt-0.5 text-[9px] text-slate-400">{r.detail}</div>}
      <div className="mt-0.5 text-[9px] text-slate-600">Updated {fmtAge(r.age_s)}</div>
    </div>
  );
}

export default function DataProvenance() {
  const provenance = useStore((s) => s.provenance);
  const layers = provenance?.layers ?? [];

  if (!layers.length) return null;

  return (
    <CollapsibleCornerPanel title="Data sources" side="left" className="w-[280px]">
      <div className="max-h-[38vh] space-y-1.5 overflow-y-auto">
        {layers.map((r) => (
          <Row key={r.layer} r={r} />
        ))}
      </div>
    </CollapsibleCornerPanel>
  );
}
