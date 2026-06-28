import { useEffect, useRef, useState } from "react";
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

function syncAgeLabel(at?: number): string {
  if (!at) return "syncing…";
  const s = Math.max(0, Math.floor((Date.now() - at) / 1000));
  if (s < 2) return "just now";
  if (s < 60) return `${s}s ago`;
  return `${Math.floor(s / 60)}m ago`;
}

export default function TimeBar() {
  const hour = useStore((s) => s.hour);
  const playing = useStore((s) => s.playing);
  const tripPlaying = useStore((s) => s.tripPlaying);
  const layerSyncAt = useStore((s) => s.layerSyncAt);
  const env = useStore((s) => s.env);
  const togglePlay = useStore((s) => s.togglePlay);
  const setHourLight = useStore((s) => s.setHourLight);
  const scheduleLayerRefresh = useStore((s) => s.scheduleLayerRefresh);
  const syncToNow = useStore((s) => s.syncToNow);
  const counterfactual = useStore((s) => s.counterfactual);
  const layers = useStore((s) => s.layers);
  const humidityRaster = useStore((s) => s.humidityRaster);
  const interventionEdgeUids = useStore((s) => s.interventionEdgeUids);
  const [, clockTick] = useState(0);

  const [dragHour, setDragHour] = useState<number | null>(null);
  const dragging = useRef(false);

  const maxHour = getMaxSelectableUAEHour();
  const sliderHour = dragHour ?? hour;
  const atLiveEdge = sliderHour >= maxHour - 0.01;
  const displayHour = playing && atLiveEdge && !dragging.current ? getCurrentUAEHour() : sliderHour;
  const live = isNearNow(displayHour);

  useEffect(() => {
    if (!playing) return;
    const id = setInterval(() => clockTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, [playing]);

  const onSliderInput = (raw: number) => {
    const h = snapUAEHour(raw);
    setDragHour(h);
    setHourLight(h);
    scheduleLayerRefresh(h);
  };

  const onSliderCommit = (raw: number) => {
    const h = snapUAEHour(raw);
    setDragHour(null);
    dragging.current = false;
    setHourLight(h);
    scheduleLayerRefresh(h, { immediate: true });
  };

  return (
    <div className="absolute bottom-3 left-1/2 z-10 w-[min(640px,92vw)] -translate-x-1/2 rounded-xl border border-edge bg-panel/90 px-3 py-2 shadow-xl backdrop-blur">
      <div className="mb-1 flex items-center gap-3">
        <button
          type="button"
          onClick={togglePlay}
          className="shrink-0 rounded-lg bg-accent2 px-2.5 py-1 text-[11px] font-semibold text-ink hover:opacity-90"
        >
          {playing ? (atLiveEdge ? "⏸ Live" : "⏸ Pause") : "▶ Play"}
        </button>

        <div className="flex shrink-0 flex-col">
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-lg font-bold text-white">{fmtHour(displayHour)}</span>
            {live && !tripPlaying && (
              <span className="rounded-full bg-accent/20 px-1.5 py-0.5 text-[9px] font-semibold text-accent">
                LIVE
              </span>
            )}
          </div>
          {(playing || dragging.current) && (
            <span className="text-[8px] text-slate-500">
              Layers {syncAgeLabel(layerSyncAt)}
              {env?.air_temp_c != null && (
                <span className="ml-1 text-slate-400">
                  · {env.air_temp_c.toFixed(1)}°C · RH {env.relative_humidity.toFixed(0)}%
                </span>
              )}
            </span>
          )}
        </div>

        <input
          type="range"
          min={0}
          max={maxHour}
          step={0.5}
          value={Math.min(sliderHour, maxHour)}
          onPointerDown={() => {
            dragging.current = true;
            if (playing) useStore.setState({ playing: false });
          }}
          onPointerUp={(e) => onSliderCommit(parseFloat(e.currentTarget.value))}
          onPointerCancel={() => {
            dragging.current = false;
            setDragHour(null);
          }}
          onInput={(e) => onSliderInput(parseFloat(e.currentTarget.value))}
          className="min-w-0 flex-1 accent-accent"
        />

        <button
          type="button"
          onClick={syncToNow}
          title="Snap to current UAE time"
          className="shrink-0 rounded-lg bg-panel2 px-2 py-1 text-[10px] font-medium text-slate-300 hover:bg-edge"
        >
          Now
        </button>
      </div>

      <p className="truncate text-center text-[9px] text-slate-500">
        {playing && (
          <span className="mr-1 font-semibold text-accent">
            {atLiveEdge ? "● Live sync" : "▶ Scrubbing"}
          </span>
        )}
        {!counterfactual ? (
          <>
            <span className="text-red-300">Red</span> = hot streets ·{" "}
            <span className="font-semibold text-amber-300">Gold glow</span> = your picks
            {interventionEdgeUids.length > 0 && (
              <span className="font-semibold text-amber-200"> ({interventionEdgeUids.length} selected)</span>
            )}
            {layers.humidity && humidityRaster && (
              <>
                {" · "}
                <span className="text-fuchsia-300">Purple fog</span> = trapped humidity
              </>
            )}
          </>
        ) : (
          <>
            <span className="text-red-300">Red inner</span> = before ·{" "}
            <span className="text-emerald-300">Green outer</span> = after fix
            {layers.humidity && humidityRaster && (
              <>
                {" · "}
                <span className="text-fuchsia-300">Purple</span> = humidity traps
              </>
            )}
          </>
        )}
      </p>
    </div>
  );
}
