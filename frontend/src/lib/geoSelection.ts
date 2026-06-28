import type { GeoJSON } from "geojson";

export interface GeoBounds {
  west: number;
  south: number;
  east: number;
  north: number;
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

/** Convert wind u/v (m/s) to a short arrow path in WGS84. */
export function windArrowPath(
  lon: number,
  lat: number,
  u: number,
  v: number,
  speed: number,
  phase: number,
  lengthM = 90,
): [number, number][] {
  const mag = Math.max(speed, 0.15);
  const mPerDegLat = 111_320;
  const mPerDegLon = 111_320 * Math.cos((lat * Math.PI) / 180);
  const flow = phase * 0.35;
  const ox = (u / mag) * flow * (lengthM / mPerDegLon) * 0.15;
  const oy = (v / mag) * flow * (lengthM / mPerDegLat) * 0.15;
  const lon0 = lon + ox;
  const lat0 = lat + oy;
  const lon1 = lon0 + (u / mag) * (lengthM / mPerDegLon);
  const lat1 = lat0 + (v / mag) * (lengthM / mPerDegLat);
  const head = lengthM * 0.28;
  const px = -v / mag;
  const py = u / mag;
  const lon2 = lon1 + (px * head) / mPerDegLon;
  const lat2 = lat1 + (py * head) / mPerDegLat;
  const lon3 = lon1 - (px * head) / mPerDegLon;
  const lat3 = lat1 - (py * head) / mPerDegLat;
  return [
    [lon0, lat0],
    [lon1, lat1],
    [lon2, lat2],
    [lon1, lat1],
    [lon3, lat3],
  ];
}
