// Shared color ramps and helpers for map layers and UI.

export type RGBA = [number, number, number, number];

// UTCI heat-stress ramp (deg C -> color). Calibrated for UAE extremes.
export function utciColor(utci: number, alpha = 200): RGBA {
  const stops: [number, RGBA][] = [
    [20, [56, 189, 248, alpha]], // cool blue
    [26, [74, 222, 128, alpha]], // comfortable green
    [32, [250, 204, 21, alpha]], // moderate yellow
    [38, [251, 146, 60, alpha]], // strong orange
    [46, [248, 113, 113, alpha]], // very strong red
    [54, [190, 24, 93, alpha]], // extreme magenta
  ];
  if (utci <= stops[0][0]) return stops[0][1];
  if (utci >= stops[stops.length - 1][0]) return stops[stops.length - 1][1];
  for (let i = 0; i < stops.length - 1; i++) {
    const [a, ca] = stops[i];
    const [b, cb] = stops[i + 1];
    if (utci >= a && utci <= b) {
      const t = (utci - a) / (b - a);
      return [
        Math.round(ca[0] + (cb[0] - ca[0]) * t),
        Math.round(ca[1] + (cb[1] - ca[1]) * t),
        Math.round(ca[2] + (cb[2] - ca[2]) * t),
        alpha,
      ];
    }
  }
  return stops[stops.length - 1][1];
}

// Traffic agent color: green (free-flow) -> amber -> red (congested).
export function speedColor(speedNorm: number): RGBA {
  const t = Math.max(0, Math.min(1, speedNorm));
  // t=1 free flow (green), t=0 jammed (red)
  const r = Math.round(255 * (1 - t) + 52 * t);
  const g = Math.round(80 * (1 - t) + 230 * t);
  const b = Math.round(80 * (1 - t) + 120 * t);
  return [r, g, b, 230];
}

export const heatBandColor: Record<string, string> = {
  Comfortable: "#4ade80",
  Moderate: "#facc15",
  Strong: "#fb923c",
  "Very Strong": "#f87171",
  Extreme: "#be185d",
  Unknown: "#64748b",
};

export const cvsBandColor: Record<string, string> = {
  Excellent: "#34d399",
  Good: "#4ade80",
  Fair: "#facc15",
  Poor: "#fb923c",
  Critical: "#f87171",
};

export const refugeColor: Record<string, RGBA> = {
  railway: [56, 189, 248, 255],
  public_transport: [56, 189, 248, 255],
  amenity: [167, 139, 250, 255],
  shop: [167, 139, 250, 255],
  leisure: [74, 222, 128, 255],
  station: [56, 189, 248, 255],
};

// Building fill by height — low buildings stay dark/neutral, towers read
// brighter and slightly cool, so the skyline is legible without clutter.
export function buildingColor(height: number): RGBA {
  const stops: [number, RGBA][] = [
    [0,   [34, 44, 60, 230]],    // low-rise: dark slate
    [30,  [44, 58, 80, 232]],    // mid-rise
    [80,  [58, 78, 105, 235]],   // tall
    [180, [78, 104, 138, 238]],  // high-rise
    [350, [104, 140, 178, 242]], // supertall: cool steel
  ];
  if (height <= stops[0][0]) return stops[0][1];
  if (height >= stops[stops.length - 1][0]) return stops[stops.length - 1][1];
  for (let i = 0; i < stops.length - 1; i++) {
    const [a, ca] = stops[i];
    const [b, cb] = stops[i + 1];
    if (height >= a && height <= b) {
      const t = (height - a) / (b - a);
      return [
        Math.round(ca[0] + (cb[0] - ca[0]) * t),
        Math.round(ca[1] + (cb[1] - ca[1]) * t),
        Math.round(ca[2] + (cb[2] - ca[2]) * t),
        ca[3],
      ];
    }
  }
  return stops[stops.length - 1][1];
}

// Road-segment congestion: green (free) → amber → red (jammed), like Waze.
export function congestionColor(c: number): RGBA {
  if (c < 0.25) return [34, 197, 94,  230];  // green   — free flow
  if (c < 0.50) return [234, 179, 8,   235];  // yellow  — slowing
  if (c < 0.75) return [249, 115, 22,  245];  // orange  — heavy
  return           [239, 68,  68,  255];  // red     — jammed
}

// Classic warm pollution ramp (blue haze → yellow → orange → deep red).
// `t` is normalized intensity 0–1 relative to baseline / peak.
export function pm25HeatColor(t: number): RGBA {
  const x = Math.max(0, Math.min(1, t));
  const stops: [number, RGBA][] = [
    [0.0,  [33, 102, 172, 255]],
    [0.12, [103, 169, 207, 255]],
    [0.30, [253, 219, 120, 255]],
    [0.50, [253, 174, 97, 255]],
    [0.72, [244, 109, 67, 255]],
    [0.88, [220, 53, 53, 255]],
    [1.0,  [178, 24, 43, 255]],
  ];
  if (x <= stops[0][0]) return stops[0][1];
  if (x >= stops[stops.length - 1][0]) return stops[stops.length - 1][1];
  for (let i = 0; i < stops.length - 1; i++) {
    const [a, ca] = stops[i];
    const [b, cb] = stops[i + 1];
    if (x >= a && x <= b) {
      const f = (x - a) / (b - a);
      return [
        Math.round(ca[0] + (cb[0] - ca[0]) * f),
        Math.round(ca[1] + (cb[1] - ca[1]) * f),
        Math.round(ca[2] + (cb[2] - ca[2]) * f),
        255,
      ];
    }
  }
  return stops[stops.length - 1][1];
}

/** Deck.gl HeatmapLayer palette — matches the warm field ramp. */
export const AIR_HEATMAP_COLORS: RGBA[] = [
  [33, 102, 172, 0],
  [103, 169, 207, 90],
  [253, 219, 120, 150],
  [253, 174, 97, 190],
  [244, 109, 67, 230],
  [178, 24, 43, 255],
];

// PM2.5 µg/m³ → warm heat color (kept for any numeric call sites).
export function pm25Color(pm: number, baseline = 38, peak = 90): RGBA {
  const span = Math.max(peak - baseline, 8);
  const t = Math.pow(Math.max(0, Math.min(1, (pm - baseline) / span)), 0.6);
  return pm25HeatColor(t);
}

export function aqiColor(aqi: number): string {
  if (aqi <= 50) return "#4ade80";
  if (aqi <= 100) return "#facc15";
  if (aqi <= 150) return "#fb923c";
  if (aqi <= 200) return "#f87171";
  if (aqi <= 300) return "#a855f7";
  return "#7f1d1d";
}
