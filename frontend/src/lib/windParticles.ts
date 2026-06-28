import type { WindRaster } from "../api/client";

export interface WindParticle {
  /** Tail → head polyline in WGS84 (iOS Weather–style flowing streak). */
  trail: [number, number][];
  speed: number;
  /** 0–1 lifecycle for fade-in / fade-out before respawn. */
  life: number;
}

const TRAIL_LEN = 22;

function clamp(v: number, lo: number, hi: number) {
  return Math.max(lo, Math.min(hi, v));
}

/** Bilinear sample of wind vector at WGS84 point. */
export function sampleWindAt(
  lon: number,
  lat: number,
  raster: WindRaster,
): { u: number; v: number; speed: number } {
  const [h, w] = raster.shape;
  const b = raster.bounds_wgs84;
  const fx = ((lon - b.west) / Math.max(b.east - b.west, 1e-9)) * (w - 1);
  const fy = ((b.north - lat) / Math.max(b.north - b.south, 1e-9)) * (h - 1);
  const c0 = clamp(Math.floor(fx), 0, w - 1);
  const r0 = clamp(Math.floor(fy), 0, h - 1);
  const c1 = Math.min(c0 + 1, w - 1);
  const r1 = Math.min(r0 + 1, h - 1);
  const tx = fx - c0;
  const ty = fy - r0;

  const sample = (r: number, c: number) => {
    const i = r * w + c;
    return {
      u: raster.u_ms[i] ?? 0,
      v: raster.v_ms[i] ?? 0,
      speed: raster.speed_ms[i] ?? 0,
    };
  };
  const a = sample(r0, c0);
  const b0 = sample(r0, c1);
  const c = sample(r1, c0);
  const d = sample(r1, c1);
  const u = a.u * (1 - tx) * (1 - ty) + b0.u * tx * (1 - ty) + c.u * (1 - tx) * ty + d.u * tx * ty;
  const v = a.v * (1 - tx) * (1 - ty) + b0.v * tx * (1 - ty) + c.v * (1 - tx) * ty + d.v * tx * ty;
  const speed = Math.hypot(u, v);
  return { u, v, speed };
}

function spawnParticle(raster: WindRaster): WindParticle {
  const b = raster.bounds_wgs84;
  const lon = b.west + Math.random() * (b.east - b.west);
  const lat = b.south + Math.random() * (b.north - b.south);
  return { trail: [[lon, lat]], speed: 0, life: Math.random() * 0.35 };
}

export function createWindParticles(raster: WindRaster, count = 200): WindParticle[] {
  const out: WindParticle[] = [];
  for (let i = 0; i < count; i += 1) {
    out.push(spawnParticle(raster));
  }
  return out;
}

/** Fade 0→1→0 over particle lifetime (soft appear / disappear like iOS Weather). */
export function particleFade(life: number): number {
  return Math.sin(clamp(life, 0, 1) * Math.PI);
}

/** Advect particles along the wind field with trailing streaks. */
export function stepWindParticles(particles: WindParticle[], raster: WindRaster, dtSec: number): WindParticle[] {
  const b = raster.bounds_wgs84;
  const mPerDegLat = 111_320;
  const lifeStep = dtSec * 0.07;

  return particles.map((p) => {
    let { trail, life } = p;
    const head = trail[trail.length - 1];
    if (!head) return spawnParticle(raster);

    const { u, v, speed } = sampleWindAt(head[0], head[1], raster);
    const mPerDegLon = 111_320 * Math.cos((head[1] * Math.PI) / 180);
    const scale = 0.000038 * (0.45 + speed * 0.55) * dtSec * 60;
    const lon = head[0] + (u / Math.max(mPerDegLon, 1e-6)) * scale;
    const lat = head[1] + (v / Math.max(mPerDegLat, 1e-6)) * scale;

    life += lifeStep;
    const outOfBounds = lon < b.west || lon > b.east || lat < b.south || lat > b.north;
    if (outOfBounds || life >= 1) {
      return spawnParticle(raster);
    }

    trail = [...trail, [lon, lat]];
    if (trail.length > TRAIL_LEN) trail = trail.slice(trail.length - TRAIL_LEN);

    return { trail, speed, life };
  });
}
