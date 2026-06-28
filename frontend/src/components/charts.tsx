import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { BestDeparture } from "../api/client";
import { heatBandColor } from "../lib/colors";

export function BestDepartureChart({ data, onPick }: { data: BestDeparture; onPick: (h: number) => void }) {
  const chartData = data.slots.map((s) => ({
    label: s.label,
    risk: s.heat_risk_score,
    band: s.max_heat_risk,
    hour: s.hour,
    recommended: s.hour === data.recommended_hour,
  }));
  return (
    <div className="h-36 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={chartData} margin={{ top: 4, right: 4, left: -22, bottom: 0 }}>
          <XAxis dataKey="label" tick={{ fontSize: 9, fill: "#94a3b8" }} interval={1} />
          <YAxis tick={{ fontSize: 9, fill: "#94a3b8" }} domain={[0, 100]} />
          <Tooltip
            contentStyle={{ background: "#111722", border: "1px solid #243044", fontSize: 11 }}
            labelStyle={{ color: "#e5edf5" }}
            formatter={(v: any, _n, p: any) => [`risk ${v} · ${p.payload.band}`, "Heat"]}
          />
          <Bar dataKey="risk" onClick={(d: any) => onPick(d.hour)} cursor="pointer">
            {chartData.map((d, i) => (
              <Cell
                key={i}
                fill={d.recommended ? "#34d399" : heatBandColor[d.band] ?? "#64748b"}
                opacity={d.recommended ? 1 : 0.65}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function BandBars({ bandPct }: { bandPct: Record<string, number> }) {
  const order = ["Comfortable", "Moderate", "Strong", "Very Strong", "Extreme"];
  return (
    <div className="space-y-1">
      {order.map((b) => (
        <div key={b} className="flex items-center gap-2 text-[11px]">
          <span className="w-20 text-slate-400">{b}</span>
          <div className="h-2.5 flex-1 overflow-hidden rounded bg-panel2">
            <div
              className="h-full rounded"
              style={{ width: `${bandPct[b] ?? 0}%`, background: heatBandColor[b] }}
            />
          </div>
          <span className="w-9 text-right font-mono text-slate-300">{(bandPct[b] ?? 0).toFixed(0)}%</span>
        </div>
      ))}
    </div>
  );
}
