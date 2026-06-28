import { useStore, getCurrentUAEHour, getMaxSelectableUAEHour, snapUAEHour } from "../store/useStore";

function fmtHour(h: number): string {
  const hh = Math.floor(h) % 24;
  const mm = Math.round((h % 1) * 60);
  return `${hh.toString().padStart(2, "0")}:${mm.toString().padStart(2, "0")}`;
}

function isNearNow(h: number): boolean {
  const nowH = getCurrentUAEHour();
  const diff = Math.abs(h - nowH);
  return Math.min(diff, 24 - diff) < 0.5;
}

export default function TimeBar() {
  const hour       = useStore((s) => s.hour);
  const playing    = useStore((s) => s.playing);
  const tripPlaying = useStore((s) => s.tripPlaying);
  const togglePlay = useStore((s) => s.togglePlay);
  const refreshHour = useStore((s) => s.refreshHour);
  const syncToNow  = useStore((s) => s.syncToNow);
  const comfort    = useStore((s) => s.comfort);
  const live       = isNearNow(hour);
  const maxHour    = getMaxSelectableUAEHour();
  const atLiveEdge = hour >= maxHour - 0.01;

  return (
    <div className="absolute bottom-3 left-1/2 z-10 w-[720px] max-w-[94vw] -translate-x-1/2 rounded-xl border border-edge bg-panel/90 px-4 py-3 shadow-xl backdrop-blur">
      <div className="mb-1.5 flex items-center justify-between gap-3">
        {/* Play / pause — replays up to now, then stays live */}
        <button
          onClick={togglePlay}
          className="rounded-lg bg-accent2 px-3 py-1 text-xs font-semibold text-ink hover:opacity-90"
        >
          {playing ? (atLiveEdge ? "⏸ Live" : "⏸ Pause") : "▶ Play to now"}
        </button>

        {/* Current time + LIVE badge */}
        <div className="flex items-center gap-2">
          <span className="font-mono text-xl font-bold text-white">{fmtHour(hour)}</span>
          {live && !tripPlaying && (
            <span className="flex items-center gap-1 rounded-full bg-accent/20 px-2 py-0.5 text-[10px] font-semibold text-accent">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
              LIVE
            </span>
          )}
          {tripPlaying && (
            <span className="rounded-full bg-violet-500/20 px-2 py-0.5 text-[10px] font-semibold text-violet-300">
              4D TRIP
            </span>
          )}
        </div>

        {/* Now button + solar info */}
        <div className="flex items-center gap-3">
          <button
            onClick={syncToNow}
            title="Snap to current UAE time"
            className="rounded-lg bg-panel2 px-2.5 py-1 text-[11px] font-medium text-slate-300 hover:bg-edge"
          >
            ⏱ Now
          </button>
          {comfort && (
            <div className="text-right text-[11px] text-slate-400">
              <div>☀ {comfort.elevation.toFixed(0)}° elev · {comfort.azimuth.toFixed(0)}° az</div>
              <div>UTCI {comfort.utci_min.toFixed(0)}–{comfort.utci_max.toFixed(0)} °C</div>
            </div>
          )}
        </div>
      </div>

      <input
        type="range"
        min={0}
        max={maxHour}
        step={0.5}
        value={Math.min(hour, maxHour)}
        onChange={(e) => refreshHour(snapUAEHour(parseFloat(e.target.value)))}
        className="w-full accent-accent"
      />

      <div className="mt-0.5 flex justify-between text-[10px] text-slate-500">
        <span>00:00</span>
        <span>06:00</span>
        <span>12:00</span>
        <span>18:00</span>
        <span>{fmtHour(maxHour)} now</span>
      </div>
    </div>
  );
}
