import type { RouteOption } from "../api/client";

/** Primary routes shown in Navigate mode (Phase 0 consolidation). */
export const PRIMARY_ROUTE_LABELS = ["Balanced", "Fastest", "Coolest"] as const;

export const ROUTE_INTENT: Record<string, string> = {
  Balanced: "Safest overall exposure",
  Fastest: "Quickest path",
  Coolest: "Most shade & lowest heat",
  "Cleanest Air": "Lowest inhaled PM2.5",
  "Cool Refuge": "AC / shade stops along route",
  "Park & Walk Cool": "Drive + shaded walk",
  "Safest (P95)": "Worst case heat & air (95th percentile)",
};

export function partitionRouteOptions(options: RouteOption[]) {
  const primary: RouteOption[] = [];
  const extra: RouteOption[] = [];
  for (const opt of options) {
    if (PRIMARY_ROUTE_LABELS.includes(opt.label as (typeof PRIMARY_ROUTE_LABELS)[number])) {
      primary.push(opt);
    } else {
      extra.push(opt);
    }
  }
  // Preserve backend order within each group.
  const order = ["Balanced", "Fastest", "Coolest"];
  primary.sort((a, b) => order.indexOf(a.label) - order.indexOf(b.label));
  return { primary, extra };
}

export function findRouteIndex(options: RouteOption[], label: string): number {
  return options.findIndex((o) => o.label === label);
}
