import { useStore } from "../store/useStore";
import { heatBandColor } from "../lib/colors";

/** Live city-wide metrics — sun, heat network, air (Simulate mode). */
export default function CityAnalytics() {
  const comfort = useStore((s) => s.comfort);
  const env = useStore((s) => s.env);
  const he = useStore((s) => s.heatExposure);
  const hour = useStore((s) => s.hour);

  const sunEl = comfort?.elevation ?? 0;
  const sunAz = comfort?.azimuth;
  const networkUtci = he?.summary?.avg_utci_c;
  const dangerousPct = he?.summary?.dangerous_network_pct;
  const band = networkUtci != null ? comfortBand(networkUtci) : null;

  return (
    <div className="rounded-xl border border-edge bg-panel/95 p-3 shadow-xl backdrop-blur">
      <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
        City analytics
      </div>
      <div className="grid grid-cols-2 gap-2">
        <Stat
          label="Sun"
          value={sunEl > 0 ? `${sunEl.toFixed(0)}° up` : "Below horizon"}
          hint={sunAz != null ? `az ${sunAz.toFixed(0)}°` : undefined}
          accent={sunEl > 15 ? "text-amber-300" : "text-slate-400"}
        />
        <Stat
          label="Network heat"
          value={networkUtci != null ? `${networkUtci.toFixed(1)}°C` : "…"}
          hint={band ?? undefined}
          color={band ? heatBandColor[band] : undefined}
        />
        <Stat
          label="Air temp"
          value={env ? `${env.air_temp_c.toFixed(1)}°C` : "…"}
          hint={env?.wx_live ? "Live weather" : "Model"}
        />
        <Stat
          label="Humidity"
          value={env ? `${env.relative_humidity.toFixed(0)}%` : "…"}
        />
      </div>
      {dangerousPct != null && dangerousPct > 5 && (
        <p className="mt-2 rounded-lg border border-red-500/40 bg-red-950/50 px-2 py-1.5 text-[10px] text-red-200">
          <strong>Dangerous streets:</strong> {dangerousPct}% of the walkable network is in very strong
          or extreme heat at {fmtHour(hour)}.
        </p>
      )}
    </div>
  );
}

function comfortBand(utci: number): string {
  if (utci < 26) return "Comfortable";
  if (utci < 32) return "Moderate";
  if (utci < 38) return "Strong";
  if (utci < 46) return "Very Strong";
  return "Extreme";
}

function fmtHour(h: number): string {
  const hh = Math.floor(h) % 24;
  const mm = Math.round((h % 1) * 60);
  return `${hh.toString().padStart(2, "0")}:${mm.toString().padStart(2, "0")}`;
}

function Stat({
  label,
  value,
  hint,
  accent = "text-slate-100",
  color,
}: {
  label: string;
  value: string;
  hint?: string;
  accent?: string;
  color?: string;
}) {
  return (
    <div className="rounded-lg bg-panel2/60 px-2 py-1.5">
      <div className="text-[9px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`font-mono text-sm font-semibold ${accent}`} style={color ? { color } : undefined}>
        {value}
      </div>
      {hint && <div className="text-[9px] text-slate-500">{hint}</div>}
    </div>
  );
}
