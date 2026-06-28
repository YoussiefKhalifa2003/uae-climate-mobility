import { useState, type ReactNode } from "react";

interface CollapsibleCornerPanelProps {
  title: string;
  side: "left" | "right";
  className?: string;
  children: ReactNode;
  defaultOpen?: boolean;
  positionClass?: string;
}

/** Bottom corner panel with minimize / restore. */
export default function CollapsibleCornerPanel({
  title,
  side,
  className = "",
  children,
  defaultOpen = true,
  positionClass,
}: CollapsibleCornerPanelProps) {
  const [open, setOpen] = useState(defaultOpen);
  const pos = positionClass ?? (side === "left" ? "bottom-3 left-3" : "bottom-3 right-3");

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={`absolute ${pos} z-10 flex items-center gap-1.5 rounded-lg border border-edge bg-panel/95 px-3 py-1.5 text-[11px] font-medium text-slate-300 shadow-lg backdrop-blur transition hover:bg-panel2 hover:text-white`}
        title={`Expand ${title}`}
      >
        <span className="text-slate-500">{side === "left" ? "◧" : "◨"}</span>
        {title}
      </button>
    );
  }

  return (
    <div
      className={`absolute ${pos} z-10 rounded-xl border border-edge bg-panel/90 shadow-xl backdrop-blur ${className}`}
    >
      <div className="flex items-center justify-between gap-2 border-b border-edge/60 px-3 py-2">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
          {title}
        </span>
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="rounded-md px-1.5 py-0.5 text-sm leading-none text-slate-400 transition hover:bg-panel2 hover:text-white"
          title={`Minimize ${title}`}
          aria-label={`Minimize ${title}`}
        >
          −
        </button>
      </div>
      <div className="p-3 pt-2">{children}</div>
    </div>
  );
}
