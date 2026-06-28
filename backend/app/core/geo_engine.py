"""Module 1 - Geospatial & Data Layer.

``UAEMapLoader`` fetches real OSM infrastructure for a UAE sector:
  * drive / walk / bike street networks (NetworkX graphs),
  * building footprints with height (or a levels/height heuristic),
  * "cool refuge" POIs (metro, malls, mosques, parks, bus stops).

Everything is reprojected to UTM 40N (EPSG:32640) for metric geometry, a
building-height raster is rasterized for fast GPU shadow casting, and results
are disk-cached. If OSM is unreachable (offline), a deterministic synthetic
grid sector is generated so the entire platform still runs end to end.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.config import settings
from app.data import cache

logger = logging.getLogger(__name__)

# Tags that make a good air-conditioned / shaded refuge in the UAE heat.
_REFUGE_TAGS = {
    "railway": ["station"],
    "station": ["subway"],
    "amenity": ["mall", "marketplace", "place_of_worship", "fountain", "cafe"],
    "shop": ["mall"],
    "leisure": ["park", "garden"],
    "public_transport": ["platform", "station", "stop_position"],
}

# Assumed metres per building level when only `building:levels` is present.
_METERS_PER_LEVEL = 3.2
_DEFAULT_BUILDING_M = 12.0


@dataclass
class GeoData:
    """In-memory container for one loaded sector."""

    place: str
    utm_epsg: int
    graphs: dict[str, Any] = field(default_factory=dict)  # mode -> nx.MultiDiGraph (UTM)
    nodes: Any = None  # GeoDataFrame (UTM) for default mode
    edges: Any = None  # GeoDataFrame (UTM)
    buildings: Any = None  # GeoDataFrame (UTM) with `height_m`
    refuges: Any = None  # GeoDataFrame (UTM, points) with `refuge_type`
    height_raster: np.ndarray | None = None  # 2D float32, metres
    transform: Any = None  # affine.Affine (UTM -> pixel)
    bounds_utm: tuple[float, float, float, float] | None = None  # minx,miny,maxx,maxy
    crs_wgs84: str = "EPSG:4326"
    synthetic: bool = False


_DATA: GeoData | None = None


class UAEMapLoader:
    """Loads and caches geospatial data for a UAE sector."""

    def __init__(self, place: str | None = None, utm_epsg: int | None = None):
        self.place = place or settings.place
        self.utm_epsg = utm_epsg or settings.utm_epsg

    # ------------------------------------------------------------------ load
    def load(self) -> GeoData:
        params = {
            "place": self.place,
            "epsg": self.utm_epsg,
            "res": settings.raster_resolution_m,
            "synthetic": settings.force_synthetic,
        }
        bundle = cache.cached_pickle("geo", params, self._build)
        return bundle

    def _build(self) -> GeoData:
        if settings.force_synthetic:
            logger.info("force_synthetic enabled; building synthetic sector.")
            return self._build_synthetic()
        try:
            return self._build_from_osm()
        except Exception as exc:  # noqa: BLE001
            logger.warning("OSM load failed (%s); generating synthetic sector.", exc)
            return self._build_synthetic()

    # ----------------------------------------------------------- real OSM
    # Uses coordinate-based queries — no Nominatim geocoding, always resolves.
    @property
    def _DIST_M(self) -> int:  # radius around the configured center
        return settings.osm_radius_m

    def _build_from_osm(self) -> GeoData:
        import time

        import geopandas as gpd  # noqa: F401
        import osmnx as ox

        ox.settings.use_cache = True
        ox.settings.log_console = False
        # Hard timeout on each Overpass request so we never hang.
        ox.settings.overpass_settings = "[out:json][timeout:40]"
        ox.settings.requests_timeout = 50

        lat, lon = settings.center_lat, settings.center_lon
        r = self._DIST_M
        logger.info("Downloading OSM data around (%.4f, %.4f) r=%dm", lat, lon, r)

        # Only walk + drive networks (bike aliases drive in the UAE) -> 2 queries.
        graphs: dict[str, Any] = {}
        for mode in ("drive", "walk"):
            t0 = time.time()
            try:
                g = ox.graph_from_point((lat, lon), dist=r, network_type=mode, simplify=True)
                graphs[mode] = ox.project_graph(g, to_crs=f"EPSG:{self.utm_epsg}")
                logger.info("OSM '%s' network: %d nodes (%.1fs)", mode, len(graphs[mode].nodes), time.time() - t0)
            except Exception as exc:  # noqa: BLE001
                logger.info("network '%s' failed: %s", mode, exc)

        if not graphs:
            raise RuntimeError("no OSM street networks returned for point query")
        if "bike" not in graphs:
            graphs["bike"] = graphs.get("drive") or graphs["walk"]

        default_mode = "walk" if "walk" in graphs else next(iter(graphs))
        nodes, edges = ox.graph_to_gdfs(graphs[default_mode])

        # ONE combined features query for buildings + all refuge POIs.
        buildings, refuges = self._load_features_point(ox, lat, lon, r)

        gd = GeoData(
            place=self.place,
            utm_epsg=self.utm_epsg,
            graphs=graphs,
            nodes=nodes,
            edges=edges,
            buildings=buildings,
            refuges=refuges,
        )
        self._finalize(gd)
        return gd

    def _load_features_point(self, ox, lat: float, lon: float, r: int):
        """Single Overpass call for buildings + refuges, then split locally."""
        import time

        import geopandas as gpd
        import pandas as pd

        tags = {
            "building": True,
            "amenity": ["marketplace", "place_of_worship", "cafe", "fountain"],
            "shop": ["mall"],
            "leisure": ["park", "garden"],
            "railway": ["station"],
            "public_transport": ["station", "platform"],
        }
        t0 = time.time()
        feats = ox.features_from_point((lat, lon), dist=r, tags=tags)
        feats = feats.to_crs(epsg=self.utm_epsg)
        logger.info("OSM features: %d rows (%.1fs)", len(feats), time.time() - t0)

        # --- Buildings: polygons with a 'building' tag ---
        is_poly = feats.geometry.type.isin(["Polygon", "MultiPolygon"])
        has_building = feats["building"].notna() if "building" in feats.columns else False
        b = feats[is_poly & has_building].copy()
        b["height_m"] = self._vectorized_heights(b)
        buildings = b[["geometry", "height_m"]].reset_index(drop=True)

        # --- Refuges: tagged POIs (use centroids) ---
        refuge_mask = pd.Series(False, index=feats.index)
        refuge_type = pd.Series("amenity", index=feats.index)
        for col in ("railway", "public_transport", "shop", "leisure", "amenity"):
            if col in feats.columns:
                m = feats[col].notna()
                refuge_mask |= m
                refuge_type[m] = col
        rf = feats[refuge_mask].copy()
        if len(rf):
            rf["refuge_type"] = refuge_type[refuge_mask].values
            rf["geometry"] = rf.geometry.centroid
            refuges = rf[["refuge_type", "geometry"]].reset_index(drop=True)
        else:
            refuges = gpd.GeoDataFrame(
                {"refuge_type": [], "geometry": []}, geometry="geometry", crs=f"EPSG:{self.utm_epsg}"
            )
        return buildings, refuges

    @staticmethod
    def _vectorized_heights(gdf) -> Any:
        """Parse OSM height/levels tags vectorized (fast for many buildings)."""
        import numpy as np
        import pandas as pd

        h = pd.Series(np.nan, index=gdf.index, dtype="float64")
        for col in ("height", "building:height"):
            if col in gdf.columns:
                parsed = pd.to_numeric(
                    gdf[col].astype(str).str.extract(r"([0-9.]+)")[0], errors="coerce"
                )
                h = h.fillna(parsed)
        for col in ("building:levels", "levels"):
            if col in gdf.columns:
                lv = pd.to_numeric(
                    gdf[col].astype(str).str.extract(r"([0-9.]+)")[0], errors="coerce"
                )
                h = h.fillna(lv * _METERS_PER_LEVEL)
        return h.fillna(_DEFAULT_BUILDING_M).clip(2.0, 650.0).to_numpy()

    @staticmethod
    def _estimate_height(row) -> float:
        for key in ("height", "building:height"):
            v = row.get(key)
            if v is not None:
                try:
                    return float(str(v).split()[0])
                except (ValueError, IndexError):
                    pass
        for key in ("building:levels", "levels"):
            v = row.get(key)
            if v is not None:
                try:
                    return float(str(v).split()[0]) * _METERS_PER_LEVEL
                except (ValueError, IndexError):
                    pass
        return _DEFAULT_BUILDING_M

    # ----------------------------------------------------------- synthetic
    def _build_synthetic(self) -> GeoData:
        """Realistic synthetic Downtown Dubai sector (2.5 km × 2.5 km).

        Uses the real center coordinates so buildings land on the correct basemap
        tiles.  Street grid mixes wide arterials every 3 cells with narrower
        side streets.  Building heights are calibrated to Downtown Dubai:
        supertall towers in the CBD core, stepping down toward the edges.
        """
        import geopandas as gpd
        import networkx as nx
        from pyproj import Transformer
        from shapely.geometry import LineString, Point, Polygon

        rng = np.random.default_rng(42)
        transformer = Transformer.from_crs("EPSG:4326", f"EPSG:{self.utm_epsg}", always_xy=True)
        cx, cy = transformer.transform(settings.center_lon, settings.center_lat)

        # 28×28 grid, 90 m spacing → ~2.5 km coverage
        n = 28
        spacing = 90.0
        half = (n - 1) * spacing / 2.0
        xs = cx - half + np.arange(n) * spacing
        ys = cy - half + np.arange(n) * spacing

        # Determine road type: every 3rd line is an arterial (wider, faster).
        def is_arterial(idx: int) -> bool:
            return idx % 3 == 0

        G = nx.MultiDiGraph(crs=f"EPSG:{self.utm_epsg}")
        node_id: dict[tuple[int, int], int] = {}
        nid = 0
        for i, x in enumerate(xs):
            for j, y in enumerate(ys):
                node_id[(i, j)] = nid
                G.add_node(nid, x=float(x), y=float(y))
                nid += 1

        def add_edge(a: int, b: int, arterial: bool = False) -> None:
            xa, ya = G.nodes[a]["x"], G.nodes[a]["y"]
            xb, yb = G.nodes[b]["x"], G.nodes[b]["y"]
            length = float(np.hypot(xb - xa, yb - ya))
            geom = LineString([(xa, ya), (xb, yb)])
            spd = 60.0 if arterial else 30.0
            cap = 3.0 if arterial else 1.5  # used by traffic sim
            G.add_edge(a, b, length=length, geometry=geom, speed_kph=spd, capacity=cap)
            G.add_edge(b, a, length=length, geometry=geom, speed_kph=spd, capacity=cap)

        for i in range(n):
            for j in range(n):
                art_h = is_arterial(i)  # horizontal arterial (E-W)
                art_v = is_arterial(j)  # vertical arterial (N-S)
                if i + 1 < n:
                    add_edge(node_id[(i, j)], node_id[(i + 1, j)], arterial=art_v)
                if j + 1 < n:
                    add_edge(node_id[(i, j)], node_id[(i, j + 1)], arterial=art_h)

        # ---- Buildings ----
        # Calibrated to Downtown Dubai: Burj Khalifa area is ~2 km from the center
        # of our grid, so we replicate the supertall core + stepdown profile.
        polys, heights = [], []
        cx_i, cy_j = n / 2.0, n / 2.0
        for i in range(n - 1):
            for j in range(n - 1):
                # Footprint occupies ~55 % of each block
                pad = spacing * 0.22
                bx, by = xs[i] + pad, ys[j] + pad
                w = spacing - 2 * pad
                # Vary footprint: tall towers are narrower.
                dist = np.hypot(i - cx_i, j - cy_j)  # blocks from center
                if dist < 3:
                    bw = w * 0.45
                elif dist < 6:
                    bw = w * 0.65
                else:
                    bw = w
                # Jitter position slightly for visual variety.
                jx = float(rng.uniform(-pad * 0.3, pad * 0.3))
                jy = float(rng.uniform(-pad * 0.3, pad * 0.3))
                poly = Polygon([
                    (bx + jx, by + jy),
                    (bx + bw + jx, by + jy),
                    (bx + bw + jx, by + bw + jy),
                    (bx + jx, by + bw + jy),
                ])
                # Height profile: supertall core (200-450 m), tower ring (60-180 m),
                # mid-rise (25-65 m), low-rise periphery (8-25 m).
                if dist < 2.5:
                    h = float(np.clip(400.0 * np.exp(-dist / 1.5) + rng.normal(0, 20), 120, 450))
                elif dist < 6:
                    h = float(np.clip(150.0 * np.exp(-dist / 3.0) + rng.normal(0, 15), 40, 180))
                elif dist < 10:
                    h = float(np.clip(50.0 + rng.normal(0, 12), 20, 80))
                else:
                    h = float(np.clip(18.0 + rng.normal(0, 5), 8, 30))
                polys.append(poly)
                heights.append(h)

        buildings = gpd.GeoDataFrame(
            {"height_m": heights, "geometry": polys},
            geometry="geometry",
            crs=f"EPSG:{self.utm_epsg}",
        )

        # ---- Cool refuges ----
        # Approximate real Dubai refuge types: metro stations along arterials,
        # malls at intersections, mosques scattered, parks at edges.
        rtypes = ["railway", "railway", "amenity", "amenity", "leisure", "public_transport"]
        rpts, rt = [], []
        # Metro stops on the main N-S arterial (every ~500 m).
        for j in range(2, n, 6):
            rpts.append(Point(xs[n // 2], ys[j]))
            rt.append("railway")
        # Malls near the center.
        for offset in [(-3, -3), (3, 2), (-2, 4), (4, -2)]:
            i2 = int(np.clip(n // 2 + offset[0], 1, n - 2))
            j2 = int(np.clip(n // 2 + offset[1], 1, n - 2))
            rpts.append(Point(xs[i2], ys[j2]))
            rt.append("amenity")
        # Parks near edges.
        for _ in range(6):
            i2, j2 = int(rng.integers(1, n - 1)), int(rng.integers(1, n - 1))
            rpts.append(Point(xs[i2], ys[j2]))
            rt.append("leisure")

        refuges = gpd.GeoDataFrame(
            {"refuge_type": rt, "geometry": rpts},
            geometry="geometry",
            crs=f"EPSG:{self.utm_epsg}",
        )

        nodes, edges = self._graph_to_gdfs(G)
        gd = GeoData(
            place=self.place + " [synthetic]",
            utm_epsg=self.utm_epsg,
            graphs={"walk": G, "drive": G, "bike": G},
            nodes=nodes,
            edges=edges,
            buildings=buildings,
            refuges=refuges,
            synthetic=True,
        )
        self._finalize(gd)
        return gd

    @staticmethod
    def _graph_to_gdfs(G):
        import geopandas as gpd
        from shapely.geometry import Point

        crs = G.graph.get("crs")
        node_recs = [{"osmid": n, "x": d["x"], "y": d["y"], "geometry": Point(d["x"], d["y"])} for n, d in G.nodes(data=True)]
        nodes = gpd.GeoDataFrame(node_recs, geometry="geometry", crs=crs).set_index("osmid")
        edge_recs = []
        for u, v, k, d in G.edges(keys=True, data=True):
            edge_recs.append({"u": u, "v": v, "key": k, "length": d["length"], "geometry": d["geometry"]})
        edges = gpd.GeoDataFrame(edge_recs, geometry="geometry", crs=crs).set_index(["u", "v", "key"])
        return nodes, edges

    # ------------------------------------------------------------- finalize
    def _finalize(self, gd: GeoData) -> None:
        """Compute bounds, rasterize building heights, attach edge UIDs."""
        minx, miny, maxx, maxy = gd.buildings.total_bounds
        # pad a bit
        pad = 50.0
        gd.bounds_utm = (minx - pad, miny - pad, maxx + pad, maxy + pad)
        gd.height_raster, gd.transform = self._rasterize_heights(gd)
        # Stable edge UID for routing/what-if referencing.
        if gd.edges is not None and len(gd.edges):
            uids = [f"{u}_{v}_{k}" for (u, v, k) in gd.edges.index]
            gd.edges = gd.edges.copy()
            gd.edges["uid"] = uids

    def _rasterize_heights(self, gd: GeoData):
        from affine import Affine
        from rasterio.features import rasterize

        minx, miny, maxx, maxy = gd.bounds_utm
        res = settings.raster_resolution_m
        width = max(1, int(np.ceil((maxx - minx) / res)))
        height = max(1, int(np.ceil((maxy - miny) / res)))
        # North-up affine: row 0 == maxy.
        transform = Affine(res, 0, minx, 0, -res, maxy)
        shapes = ((geom, h) for geom, h in zip(gd.buildings.geometry, gd.buildings.height_m))
        raster = rasterize(
            shapes,
            out_shape=(height, width),
            transform=transform,
            fill=0.0,
            dtype="float32",
        )
        return raster, transform


# ------------------------------------------------------------------ public API


def get_geo() -> GeoData:
    """Return the loaded sector, loading + caching on first access."""
    global _DATA
    if _DATA is None:
        _DATA = UAEMapLoader().load()
        try:
            from app.core.indoor_network import attach_indoor_network

            attach_indoor_network(_DATA)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Indoor network attach skipped: %s", exc)
        logger.info(
            "Geo loaded: %s | buildings=%d refuges=%d raster=%s synthetic=%s",
            _DATA.place,
            len(_DATA.buildings),
            len(_DATA.refuges),
            None if _DATA.height_raster is None else _DATA.height_raster.shape,
            _DATA.synthetic,
        )
    return _DATA


def reset_geo() -> None:
    global _DATA
    _DATA = None


def buildings_geojson(max_features: int = 14000) -> dict:
    """3D building footprints as WGS84 GeoJSON with `height_m` for extrusion."""
    import math

    gd = get_geo()
    b = gd.buildings.copy()
    # Sanitize heights — OSM can have NaN/Inf when tags are malformed.
    b["height_m"] = (
        b["height_m"]
        .fillna(_DEFAULT_BUILDING_M)
        .clip(lower=4.0, upper=650.0)  # 4 m minimum (single storey + parapet)
    )
    b = b[b.geometry.is_valid & ~b.geometry.is_empty].copy()

    # Remove huge flat footprints (parking lots, parks, plazas incorrectly tagged
    # as buildings) — they render as unreadable gray slabs.
    b["_area_m2"] = b.geometry.area
    # Keep: tall buildings regardless of size, OR normal-area buildings.
    b = b[(b["height_m"] > 15) | (b["_area_m2"] < 20_000)].copy()
    b.drop(columns=["_area_m2"], inplace=True)

    if len(b) > max_features:
        b = b.nlargest(max_features, "height_m")
    wgs = b.to_crs(epsg=4326)
    feats = []
    for geom, h in zip(wgs.geometry, wgs.height_m):
        h_val = float(h)
        if not math.isfinite(h_val):
            h_val = _DEFAULT_BUILDING_M
        try:
            geo = geom.__geo_interface__
        except Exception:
            continue
        feats.append(
            {
                "type": "Feature",
                "properties": {"height_m": h_val},
                "geometry": geo,
            }
        )
    return {"type": "FeatureCollection", "features": feats}


def drive_roads_geojson() -> dict:
    """Drive-network road segments as WGS84 GeoJSON.

    Used by the frontend congestion overlay.  Cached in-process after first call
    (the road geometry doesn't change at runtime).
    """
    if drive_roads_geojson._cache is not None:
        return drive_roads_geojson._cache  # type: ignore[attr-defined]

    gd = get_geo()
    if not gd.graphs:
        empty = {"type": "FeatureCollection", "features": []}
        drive_roads_geojson._cache = empty  # type: ignore[attr-defined]
        return empty
    graph = gd.graphs.get("drive") or next(iter(gd.graphs.values()))
    try:
        import osmnx as ox
        _, edges = ox.graph_to_gdfs(graph)
        edges_wgs = edges.to_crs(epsg=4326)
    except Exception:
        edges_wgs = gd.edges.to_crs(epsg=4326)

    feats = []
    for idx, geom in zip(edges_wgs.index, edges_wgs.geometry):
        uid = f"{idx[0]}_{idx[1]}_{idx[2]}"
        try:
            feats.append(
                {"type": "Feature", "properties": {"uid": uid}, "geometry": geom.__geo_interface__}
            )
        except Exception:
            continue
    result = {"type": "FeatureCollection", "features": feats}
    drive_roads_geojson._cache = result  # type: ignore[attr-defined]
    return result

drive_roads_geojson._cache = None  # type: ignore[attr-defined]


def refuges_geojson() -> dict:
    gd = get_geo()
    if gd.refuges is None or not len(gd.refuges):
        return {"type": "FeatureCollection", "features": []}
    wgs = gd.refuges.to_crs(epsg=4326)
    feats = [
        {
            "type": "Feature",
            "properties": {"refuge_type": rt},
            "geometry": geom.__geo_interface__,
        }
        for geom, rt in zip(wgs.geometry, wgs.refuge_type)
    ]
    return {"type": "FeatureCollection", "features": feats}


def sector_meta() -> dict:
    gd = get_geo()
    wgs_bounds = _bounds_to_wgs(gd)
    return {
        "place": gd.place,
        "synthetic": gd.synthetic,
        "utm_epsg": gd.utm_epsg,
        "n_buildings": int(len(gd.buildings)),
        "n_refuges": int(len(gd.refuges)) if gd.refuges is not None else 0,
        "raster_shape": list(gd.height_raster.shape) if gd.height_raster is not None else None,
        "bounds_wgs84": wgs_bounds,
        "center": {"lat": settings.center_lat, "lon": settings.center_lon},
    }


def _bounds_to_wgs(gd: GeoData) -> dict:
    from pyproj import Transformer

    minx, miny, maxx, maxy = gd.bounds_utm
    t = Transformer.from_crs(f"EPSG:{gd.utm_epsg}", "EPSG:4326", always_xy=True)
    west, south = t.transform(minx, miny)
    east, north = t.transform(maxx, maxy)
    return {"west": west, "south": south, "east": east, "north": north}
