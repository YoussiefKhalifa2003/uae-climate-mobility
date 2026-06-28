import type { GeoJSON } from "geojson";
import { WebMercatorViewport } from "@deck.gl/core";

export interface GeoBounds {
  west: number;
  south: number;
  east: number;
  north: number;
}

export interface MapViewport {
  longitude: number;
  latitude: number;
  zoom: number;
  pitch: number;
  bearing: number;
  width: number;
  height: number;
}

export function normalizeBounds(b: GeoBounds): GeoBounds {
  return {
    west: Math.min(b.west, b.east),
    east: Math.max(b.west, b.east),
    south: Math.min(b.south, b.north),
    north: Math.max(b.south, b.north),
  };
}

/** Accurate geographic bounds for the current deck.gl viewport (handles pitch & bearing). */
export function boundsFromViewState(vp: MapViewport): GeoBounds | null {
  const { width, height } = vp;
  if (width < 20 || height < 20) return null;
  const viewport = new WebMercatorViewport({
    longitude: vp.longitude,
    latitude: vp.latitude,
    zoom: vp.zoom,
    pitch: vp.pitch,
    bearing: vp.bearing,
    width,
    height,
  });
  const [minLon, minLat, maxLon, maxLat] = viewport.getBounds();
  return normalizeBounds({ west: minLon, south: minLat, east: maxLon, north: maxLat });
}

/** Slightly expand bounds so edge-visible streets still match. */
export function expandBounds(b: GeoBounds, paddingPct = 0.06): GeoBounds {
  const norm = normalizeBounds(b);
  const w = norm.east - norm.west;
  const h = norm.north - norm.south;
  return normalizeBounds({
    west: norm.west - w * paddingPct,
    east: norm.east + w * paddingPct,
    south: norm.south - h * paddingPct,
    north: norm.north + h * paddingPct,
  });
}

function pointInBounds(lon: number, lat: number, b: GeoBounds): boolean {
  return lon >= b.west && lon <= b.east && lat >= b.south && lat <= b.north;
}

/** True if any vertex of a LineString lies inside the bounds. */
export function featureIntersectsBounds(feat: GeoJSON.Feature, bounds: GeoBounds): boolean {
  const g = feat.geometry;
  if (!g) return false;
  if (g.type === "LineString") {
    return g.coordinates.some(([lon, lat]) => pointInBounds(lon, lat, bounds));
  }
  if (g.type === "MultiLineString") {
    return g.coordinates.some((line) => line.some(([lon, lat]) => pointInBounds(lon, lat, bounds)));
  }
  return false;
}

export function uidsInBounds(
  bounds: GeoBounds,
  worstSegments?: GeoJSON.FeatureCollection | null,
): string[] {
  const uids = new Set<string>();
  if (!worstSegments?.features?.length) return [];
  for (const feat of worstSegments.features) {
    const uid = (feat.properties as { uid?: string })?.uid;
    if (!uid || !featureIntersectsBounds(feat, bounds)) continue;
    uids.add(uid);
  }
  return [...uids];
}

export function selectedSegmentFeatures(
  uids: string[],
  worstSegments?: GeoJSON.FeatureCollection | null,
  roadSegments?: GeoJSON.FeatureCollection | null,
): GeoJSON.Feature[] {
  const want = new Set(uids);
  const out: GeoJSON.Feature[] = [];
  const seen = new Set<string>();
  const scan = (fc?: GeoJSON.FeatureCollection | null) => {
    if (!fc?.features?.length) return;
    for (const feat of fc.features) {
      const uid = (feat.properties as { uid?: string })?.uid;
      if (!uid || !want.has(uid) || seen.has(uid)) continue;
      seen.add(uid);
      out.push(feat);
    }
  };
  scan(worstSegments);
  scan(roadSegments);
  return out;
}

type ScoredStreet = { uid: string; utci: number; feat: GeoJSON.Feature; lon: number; lat: number };

function scoredStreets(worstSegments?: GeoJSON.FeatureCollection | null): ScoredStreet[] {
  if (!worstSegments?.features?.length) return [];
  const out: ScoredStreet[] = [];
  for (const feat of worstSegments.features) {
    const uid = (feat.properties as { uid?: string; utci_c?: number })?.uid;
    const utci = Number((feat.properties as { utci_c?: number })?.utci_c ?? 0);
    if (!uid) continue;
    const mid = featureMidpoint(feat);
    if (!mid) continue;
    out.push({ uid, utci, feat, lon: mid[0], lat: mid[1] });
  }
  return out;
}

function cellBounds(bounds: GeoBounds, col: number, row: number, cols: number, rows: number): GeoBounds {
  const w = (bounds.east - bounds.west) / cols;
  const h = (bounds.north - bounds.south) / rows;
  return {
    west: bounds.west + col * w,
    east: bounds.west + (col + 1) * w,
    south: bounds.south + row * h,
    north: bounds.south + (row + 1) * h,
  };
}

/** Pick hot streets spread across the viewport grid (not one congested cluster). */
export function uidsSpreadInBounds(
  bounds: GeoBounds,
  worstSegments?: GeoJSON.FeatureCollection | null,
  maxTotal = 16,
  gridCols = 5,
  gridRows = 4,
): string[] {
  const norm = normalizeBounds(bounds);
  const pool = scoredStreets(worstSegments).filter((s) => featureIntersectsBounds(s.feat, norm));
  if (!pool.length) return [];

  const cols = pool.length < 10 ? 2 : pool.length < 24 ? 3 : gridCols;
  const rows = pool.length < 10 ? 2 : pool.length < 24 ? 3 : gridRows;

  const picked: string[] = [];
  const seen = new Set<string>();
  const perCell = Math.max(1, Math.ceil(maxTotal / (cols * rows)));

  for (let row = 0; row < rows; row += 1) {
    for (let col = 0; col < cols; col += 1) {
      const cell = cellBounds(norm, col, row, cols, rows);
      const inCell = pool
        .filter((s) => featureIntersectsBounds(s.feat, cell))
        .sort((a, b) => b.utci - a.utci);
      for (const s of inCell.slice(0, perCell)) {
        if (seen.has(s.uid)) continue;
        seen.add(s.uid);
        picked.push(s.uid);
        if (picked.length >= maxTotal) return picked;
      }
    }
  }

  for (const s of pool.sort((a, b) => b.utci - a.utci)) {
    if (seen.has(s.uid)) continue;
    seen.add(s.uid);
    picked.push(s.uid);
    if (picked.length >= maxTotal) break;
  }
  return picked;
}

/** City-wide pick — hottest streets but spatially separated. */
export function uidsSpreadGlobal(
  worstSegments?: GeoJSON.FeatureCollection | null,
  maxTotal = 10,
  minSepDeg = 0.0028,
): string[] {
  const pool = scoredStreets(worstSegments).sort((a, b) => b.utci - a.utci);
  if (!pool.length) return [];

  const picked: ScoredStreet[] = [];
  for (const s of pool) {
    const tooClose = picked.some(
      (p) => Math.hypot(p.lon - s.lon, p.lat - s.lat) < minSepDeg,
    );
    if (tooClose) continue;
    picked.push(s);
    if (picked.length >= maxTotal) break;
  }

  if (picked.length < maxTotal) {
    for (const s of pool) {
      if (picked.some((p) => p.uid === s.uid)) continue;
      picked.push(s);
      if (picked.length >= maxTotal) break;
    }
  }
  return picked.map((s) => s.uid);
}

/** Bounding box of GeoJSON line features. */
export function boundsFromFeatures(features: GeoJSON.Feature[]): GeoBounds | null {
  let minLon = Infinity;
  let minLat = Infinity;
  let maxLon = -Infinity;
  let maxLat = -Infinity;
  for (const feat of features) {
    const g = feat.geometry;
    if (!g) continue;
    const lines = g.type === "LineString" ? [g.coordinates] : g.type === "MultiLineString" ? g.coordinates : [];
    for (const line of lines) {
      for (const [lon, lat] of line as [number, number][]) {
        minLon = Math.min(minLon, lon);
        maxLon = Math.max(maxLon, lon);
        minLat = Math.min(minLat, lat);
        maxLat = Math.max(maxLat, lat);
      }
    }
  }
  if (!Number.isFinite(minLon)) return null;
  return { west: minLon, south: minLat, east: maxLon, north: maxLat };
}

/** Midpoint of a line feature for marker placement. */
export function featureMidpoint(feat: GeoJSON.Feature): [number, number] | null {
  const g = feat.geometry;
  if (!g) return null;
  let coords: [number, number][] = [];
  if (g.type === "LineString") {
    coords = g.coordinates as [number, number][];
  } else if (g.type === "MultiLineString") {
    const lines = g.coordinates as [number, number][][];
    const longest = lines.reduce((a, b) => (a.length >= b.length ? a : b), lines[0] ?? []);
    coords = longest;
  }
  if (!coords.length) return null;
  return coords[Math.floor(coords.length / 2)];
}

/** Sleek animated wind streak (2-point line). */
export function windStreamline(
  lon: number,
  lat: number,
  u: number,
  v: number,
  speed: number,
  phase: number,
  lengthM = 110,
): [number, number][] {
  const mag = Math.max(speed, 0.12);
  const mPerDegLat = 111_320;
  const mPerDegLon = 111_320 * Math.cos((lat * Math.PI) / 180);
  const drift = phase * lengthM * 0.45;
  const lon0 = lon + (u / mag) * (drift / mPerDegLon);
  const lat0 = lat + (v / mag) * (drift / mPerDegLat);
  const lon1 = lon0 + (u / mag) * (lengthM / mPerDegLon);
  const lat1 = lat0 + (v / mag) * (lengthM / mPerDegLat);
  return [
    [lon0, lat0],
    [lon1, lat1],
  ];
}
