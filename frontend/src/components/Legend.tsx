import { useStore } from "../store/useStore";
import { heatBandColor, refugeColor } from "../lib/colors";
import CollapsibleCornerPanel from "./CollapsibleCornerPanel";

const LAYER_META: {
  key: keyof ReturnType<typeof useStore.getState>["layers"];
  label: string;
  hint: string;
  provKey?: string;
}[] = [
  { key: "buildings", label: "3D Buildings", hint: "OSM footprints", provKey: "buildings" },
  { key: "traffic", label: "Traffic", hint: "Road congestion lines", provKey: "traffic" },
  { key: "air", label: "Air Quality", hint: "Live baseline + traffic plume", provKey: "air_map" },
  { key: "comfort", label: "Heat (UTCI)", hint: "Solar + shadow physics", provKey: "utci" },
  { key: "refuges", label: "Cool Refuges", hint: "AC / shade POIs", provKey: "refuges" },
  { key: "routes", label: "Routes", hint: "Multi-objective paths", provKey: undefined },
  { key: "isochrone", label: "Reachability", hint: "Comfort isochrone", provKey: undefined },
  { key: "worstSegments", label: "Heat Hotspots", hint: "Hottest street segments", provKey: undefined },
];

export default function Legend() {
  const layers = useStore((s) => s.layers);
  const toggleLayer = useStore((s) => s.toggleLayer);
  const provenance = useStore((s) => s.provenance);

  const liveFor = (key?: string) =>
    key ? provenance?.layers.find((l) => l.layer === key)?.live : undefined;

  return (
    <CollapsibleCornerPanel title="Layers" side="right" className="max-w-[320px]">
      <div className="grid grid-cols-1 gap-1">
        {LAYER_META.map(({ key, label, hint, provKey }) => {
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
    </CollapsibleCornerPanel>
  );
}
