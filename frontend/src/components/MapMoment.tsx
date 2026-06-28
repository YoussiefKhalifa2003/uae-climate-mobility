import { useEffect } from "react";
import { useStore } from "../store/useStore";

/** Large floating callout for shade crossings and demo hints. */
export default function MapMoment() {
  const mapMoment = useStore((s) => s.mapMoment);
  const setMapMoment = useStore((s) => s.setMapMoment);

  useEffect(() => {
    if (!mapMoment) return;
    const t = setTimeout(() => setMapMoment(null), 4000);
    return () => clearTimeout(t);
  }, [mapMoment, setMapMoment]);

  if (!mapMoment) return null;

  return (
    <div className="pointer-events-none absolute left-1/2 top-24 z-30 max-w-md -translate-x-1/2">
      <div className="rounded-2xl border border-violet-400/40 bg-ink/85 px-5 py-3 text-center shadow-2xl backdrop-blur-md">
        <p className="text-sm font-semibold text-white">{mapMoment}</p>
      </div>
    </div>
  );
}
