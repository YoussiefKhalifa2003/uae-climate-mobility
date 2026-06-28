import { useEffect, useMemo, useState } from "react";
import DeckGL from "@deck.gl/react";
import { GeoJsonLayer, PathLayer, ScatterplotLayer, BitmapLayer } from "@deck.gl/layers";
import { HeatmapLayer } from "@deck.gl/aggregation-layers";
import { Map } from "react-map-gl/maplibre";
import { AmbientLight, DirectionalLight, LightingEffect } from "@deck.gl/core";
import type { MapViewState, PickingInfo } from "@deck.gl/core";
import { useStore } from "./store/useStore";
import { utciColor, pm25HeatColor, AIR_HEATMAP_COLORS, congestionColor, refugeColor, buildingColor } from "./lib/colors";
import type { RouteOption } from "./api/client";
import type { Layer } from "@deck.gl/core";
import { activeTimeline, getActiveExposureContext, horizonTimeline, pmStressNorm, sampleTimeline, buildExposureRibbon, findShadeCrossings } from "./lib/tripExposure";

const MAP_STYLE = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";

/** Draw a route path in its preset color — glow + core, matched to the sidebar dot. */
function pushRouteColorLayers(
  layers: Layer[],
  opt: RouteOption,
  id: string,
  selected: boolean,
) {
  if (!opt.path?.length) return;
  const [r, g, b] = opt.color;
  const data = [{ path: opt.path }];
  const onTop = { depthTest: false as const };
  const rounded = { capRounded: true, jointRounded: true, parameters: onTop };

  if (selected) {
    layers.push(
      new PathLayer({
        id: `${id}-outer`,
        data,
        getPath: (d: { path: [number, number][] }) => d.path,
        getColor: [r, g, b, 85],
        getWidth: 30,
        widthMinPixels: 16,
        widthMaxPixels: 34,
        ...rounded,
      }),
      new PathLayer({
        id: `${id}-mid`,
        data,
        getPath: (d: { path: [number, number][] }) => d.path,
        getColor: [Math.min(255, r + 35), Math.min(255, g + 35), Math.min(255, b + 35), 210],
        getWidth: 14,
        widthMinPixels: 8,
        widthMaxPixels: 18,
        ...rounded,
      }),
      new PathLayer({
        id: `${id}-core`,
        data,
        getPath: (d: { path: [number, number][] }) => d.path,
        getColor: [255, 255, 255, 255],
        getWidth: 5,
        widthMinPixels: 4,
        widthMaxPixels: 8,
        ...rounded,
      }),
    );
  } else {
    layers.push(
      new PathLayer({
        id: `${id}-glow`,
        data,
        getPath: (d: { path: [number, number][] }) => d.path,
        getColor: [r, g, b, 120],
        getWidth: 14,
        widthMinPixels: 5,
        widthMaxPixels: 12,
        ...rounded,
      }),
      new PathLayer({
        id: `${id}-line`,
        data,
        getPath: (d: { path: [number, number][] }) => d.path,
        getColor: [r, g, b, 235],
        getWidth: 6,
        widthMinPixels: 3,
        widthMaxPixels: 8,
        ...rounded,
      }),
    );
  }
}

/** Lighting tied to the real solar azimuth/elevation for accurate skyline shading. */
function makeLighting(azimuth: number, elevation: number): LightingEffect {
  const ambient = new AmbientLight({ color: [255, 255, 255], intensity: 1.4 });
  // Convert sun az/el to a downward-pointing direction vector.
  const el = Math.max(5, elevation) * (Math.PI / 180);
  const az = azimuth * (Math.PI / 180);
  const dir: [number, number, number] = [
    -Math.sin(az) * Math.cos(el),
    -Math.cos(az) * Math.cos(el),
    -Math.sin(el),
  ];
  const sun = new DirectionalLight({
    color: [255, 245, 225],
    intensity: elevation > 0 ? 2.0 : 0.3,
    direction: dir,
  });
  const fill = new DirectionalLight({
    color: [180, 200, 230],
    intensity: 0.7,
    direction: [0.3, 0.5, -1],
  });
  return new LightingEffect({ ambient, sun, fill });
}

// ---------------------------------------------------------------- helpers

function buildComfortImage(
  values: number[],
  shape: [number, number]
): ImageData | null {
  const [h, w] = shape;
  if (!h || !w || values.length !== h * w) return null;
  const img = new ImageData(w, h);
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    const c = utciColor(v, 255);
    // Alpha scales with heat stress: comfortable areas are nearly invisible,
    // dangerous heat is clearly highlighted. Removes the harsh uniform tint.
    let alpha = 0;
    if (v >= 26) alpha = Math.min(180, Math.round((v - 26) / 22 * 180));
    const o = i * 4;
    img.data[o] = c[0];
    img.data[o + 1] = c[1];
    img.data[o + 2] = c[2];
    img.data[o + 3] = alpha;
  }
  return img;
}

/** Warm full-area field — transparent in clean zones, glowing at traffic plumes. */
function buildAirImage(
  values: number[] | undefined,
  shape: [number, number] | undefined,
  baseline: number,
  pm25Max: number
): ImageData | null {
  if (!values?.length || !shape?.length) return null;
  const [h, w] = shape;
  if (!h || !w || values.length !== h * w) return null;
  const img = new ImageData(w, h);
  const span = Math.max(pm25Max - baseline, 10);
  for (let i = 0; i < values.length; i++) {
    const pm = values[i];
    const raw = Math.max(0, (pm - baseline * 0.92) / span);
    const t = Math.pow(raw, 0.58);
    if (t < 0.06) continue; // clean air stays fully transparent
    const c = pm25HeatColor(t);
    const alpha = Math.round(Math.min(215, 18 + t * t * 200));
    const o = i * 4;
    img.data[o] = c[0];
    img.data[o + 1] = c[1];
    img.data[o + 2] = c[2];
    img.data[o + 3] = alpha;
  }
  return img;
}

// ---------------------------------------------------------------- component

export default function LiveMap() {
  const store = useStore();
  const {
    sector,
    buildings,
    refuges,
    roadSegments,
    congestion,
    congestionSeq,
    comfort,
    airRaster,
    route,
    isochrone,
    heatExposure,
    layers,
    selectedRouteIdx,
    tripMinute,
    exposure4DEnabled,
    focusMode,
    demoPlaying,
    tripPlaying,
    exposureForecast,
    forecastDelayMin,
  } = store;

  const selRoute = route?.options[selectedRouteIdx];
  const { timeline: activeTl } = useMemo(
    () => getActiveExposureContext(exposureForecast, forecastDelayMin, selRoute?.thermal_horizon),
    [exposureForecast, forecastDelayMin, selRoute],
  );
  const baselineTl = useMemo(
    () => exposureForecast?.slots[0]?.timeline ?? activeTl,
    [exposureForecast, activeTl],
  );

  const tripFrame = useMemo(() => {
    if (!exposure4DEnabled || !activeTl.length) return null;
    return sampleTimeline(activeTl, tripMinute);
  }, [exposure4DEnabled, activeTl, tripMinute]);

  const baselineFrame = useMemo(() => {
    if (!exposure4DEnabled || !baselineTl.length) return null;
    return sampleTimeline(baselineTl, tripMinute);
  }, [exposure4DEnabled, baselineTl, tripMinute]);

  const utciDeltaVsNow =
    tripFrame && baselineFrame && forecastDelayMin > 0
      ? tripFrame.utci - baselineFrame.utci
      : 0;

  const exposureRibbon = useMemo(() => {
    if (!exposure4DEnabled || !activeTl.length) return [];
    return buildExposureRibbon(activeTl);
  }, [exposure4DEnabled, activeTl]);

  const shadeCrossings = useMemo(() => {
    if (!exposure4DEnabled || !activeTl.length) return [];
    return findShadeCrossings(activeTl);
  }, [exposure4DEnabled, activeTl]);

  const [viewState, setViewState] = useState<MapViewState>({
    longitude: 55.2744,
    latitude: 25.1972,
    zoom: 14.5,
    pitch: 52,
    bearing: -10,
  });

  // Fit view to sector on first load (skip when camera is following the trip).
  useEffect(() => {
    if (sector && !focusMode && !demoPlaying && !tripPlaying) {
      setViewState((v) => ({
        ...v,
        longitude: sector.center.lon,
        latitude: sector.center.lat,
        zoom: 14.5,
        pitch: 52,
      }));
    }
  }, [sector?.place, focusMode, demoPlaying, tripPlaying]);

  // Camera follows the exposure bubble during focus / demo / playback.
  const cameraFollow = focusMode || demoPlaying || tripPlaying;
  useEffect(() => {
    if (!cameraFollow || !tripFrame) return;
    setViewState((v) => ({
      ...v,
      longitude: tripFrame.lon,
      latitude: tripFrame.lat,
      zoom: Math.max(v.zoom ?? 14, 16.4),
      pitch: Math.max(v.pitch ?? 52, 60),
      bearing: v.bearing ?? -10,
      transitionDuration: 280,
    }));
  }, [tripFrame?.lat, tripFrame?.lon, cameraFollow]);

  // Road congestion data — merge road geometry with live congestion values.
  // New object reference on every congestionSeq bump so deck.gl redraws colors.
  const trafficRoadsData = useMemo(() => {
    if (!roadSegments) return null;
    return {
      ...roadSegments,
      features: roadSegments.features.map((f: any) => ({
        ...f,
        properties: {
          ...f.properties,
          congestion: congestion[f.properties.uid] ?? 0,
        },
      })),
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roadSegments, congestionSeq]);

  // Comfort bitmap — recompute only when values change.
  const comfortImage = useMemo(
    () => (comfort ? buildComfortImage(comfort.values, comfort.shape as [number, number]) : null),
    [comfort]
  );

  const airImage = useMemo(
    () =>
      airRaster
        ? buildAirImage(
            airRaster.values,
            airRaster.shape as [number, number],
            airRaster.baseline_pm25,
            airRaster.pm25_max
          )
        : null,
    [airRaster]
  );

  // Lighting follows the real sun position for the current hour.
  const lightingEffect = useMemo(
    () => makeLighting(comfort?.azimuth ?? 135, comfort?.elevation ?? 45),
    [comfort?.azimuth, comfort?.elevation]
  );

  const onClick = (info: PickingInfo) => {
    if (store.pickMode && info.coordinate) {
      store.setPoint({ lon: info.coordinate[0], lat: info.coordinate[1] });
    }
  };

  // ---------------------------------------------------------------- layers

  const deckLayers: any[] = [];

  // 1. UTCI comfort raster (behind everything).
  if (layers.comfort && comfortImage && comfort) {
    const b = comfort.bounds_wgs84;
    deckLayers.push(
      new BitmapLayer({
        id: "comfort",
        image: comfortImage,
        bounds: [b.west, b.south, b.east, b.north] as [number, number, number, number],
        opacity: 0.5,
      })
    );
  }

  // 2a. Air quality — warm full-area dispersion field (yellow / orange / red).
  if (layers.air && airImage && airRaster) {
    const b = airRaster.bounds_wgs84;
    deckLayers.push(
      new BitmapLayer({
        id: "air-field",
        image: airImage,
        bounds: [b.west, b.south, b.east, b.north] as [number, number, number, number],
        opacity: 0.92,
      })
    );
  }

  // 2b. Hotspot bloom — incandescent cores at traffic choke points (original heatmap feel).
  if (layers.air && airRaster?.hotspots?.length) {
    deckLayers.push(
      new HeatmapLayer({
        id: "air-hotspots",
        data: airRaster.hotspots,
        getPosition: (d: number[]) => [d[0], d[1]],
        getWeight: (d: number[]) => d[2],
        radiusPixels: 95,
        intensity: 1.35,
        threshold: 0.04,
        aggregation: "SUM",
        colorRange: AIR_HEATMAP_COLORS,
      })
    );
  }

  // 2c. Live air-quality monitor point (Open-Meteo / OpenWeather).
  if (layers.air && airRaster?.stations?.length) {
    deckLayers.push(
      new ScatterplotLayer({
        id: "air-stations",
        data: airRaster.stations,
        getPosition: (d: any) => [d.lon, d.lat],
        getFillColor: (d: any) => (d.live ? [56, 189, 248, 255] : [148, 163, 184, 200]),
        getRadius: 22,
        radiusMinPixels: 8,
        stroked: true,
        getLineColor: [255, 255, 255, 230],
        lineWidthMinPixels: 2,
        pickable: true,
      })
    );
  }

  // 3. 3D buildings.
  if (layers.buildings && buildings) {
    deckLayers.push(
      new GeoJsonLayer({
        id: "buildings",
        data: buildings,
        extruded: true,
        getElevation: (f: any) => f.properties.height_m ?? 12,
        getFillColor: (f: any) => buildingColor(f.properties.height_m ?? 12) as any,
        getLineColor: [90, 115, 150, 60],
        lineWidthMinPixels: 0,
        material: { ambient: 0.55, diffuse: 0.75, shininess: 48, specularColor: [120, 140, 170] },
        pickable: false,
      })
    );
  }

  // 4. Worst heat segments (simulate mode).
  if (layers.worstSegments && heatExposure?.worst_segments) {
    deckLayers.push(
      new GeoJsonLayer({
        id: "worst",
        data: heatExposure.worst_segments as any,
        getLineColor: [248, 113, 113, 230],
        getLineWidth: 7,
        lineWidthMinPixels: 3,
        pickable: true,
      })
    );
  }

  // 5. Comfort isochrone.
  if (layers.isochrone && isochrone) {
    deckLayers.push(
      new GeoJsonLayer({
        id: "isochrone",
        data: isochrone as any,
        getFillColor: [56, 189, 248, 40],
        getLineColor: [56, 189, 248, 210],
        getLineWidth: 3,
        lineWidthMinPixels: 2,
      })
    );
  }

  // 6. Route paths — each option in its own preset color (unselected first).
  if (layers.routes && route) {
    route.options.forEach((opt, i) => {
      if (i === selectedRouteIdx) return;
      pushRouteColorLayers(deckLayers, opt, `route-${i}`, false);
    });
  }

  // 7. Cool refuge POIs.
  if (layers.refuges && refuges) {
    deckLayers.push(
      new GeoJsonLayer({
        id: "refuges",
        data: refuges,
        pointType: "circle",
        getFillColor: (f: any) =>
          refugeColor[f.properties.refuge_type] ?? ([148, 163, 184, 255] as any),
        getPointRadius: 9,
        pointRadiusMinPixels: 3,
        stroked: false,
        pickable: true,
      })
    );
  }

  // 8. Live traffic congestion — road segments colored green → amber → red.
  //    New data reference on every congestionSeq bump triggers deck.gl redraw.
  if (layers.traffic && trafficRoadsData) {
    deckLayers.push(
      new GeoJsonLayer({
        id: "traffic-roads",
        data: trafficRoadsData as any,
        getLineColor: (f: any) => {
          const c: number = f.properties?.congestion ?? 0;
          return congestionColor(c) as any;
        },
        getLineWidth: (f: any) => {
          const c: number = f.properties?.congestion ?? 0;
          return c > 0.65 ? 9 : c > 0.35 ? 6 : 4;
        },
        lineWidthUnits: "meters",
        lineWidthMinPixels: 1,
        lineWidthMaxPixels: 16,
        pickable: false,
        stroked: false,
        filled: false,
      })
    );
  }

  // 9. Origin / destination markers.
  const markers: { lon: number; lat: number; kind: string }[] = [];
  if (store.origin) markers.push({ ...store.origin, kind: "origin" });
  if (store.destination) markers.push({ ...store.destination, kind: "destination" });
  if (markers.length) {
    deckLayers.push(
      new ScatterplotLayer({
        id: "od",
        data: markers,
        getPosition: (d) => [d.lon, d.lat],
        getFillColor: (d) =>
          d.kind === "origin" ? [52, 211, 153, 255] : [56, 189, 248, 255],
        getRadius: 20,
        radiusMinPixels: 9,
        stroked: true,
        getLineColor: [255, 255, 255, 255],
        lineWidthMinPixels: 2,
      })
    );
  }

  // 10. Selected route — exposure ribbon when X-Ray active, else preset neon path.
  if (layers.routes && route) {
    const sel = route.options[selectedRouteIdx];
    if (sel?.path?.length) {
      const onTop = { depthTest: false as const };
      const rounded = { capRounded: true, jointRounded: true, parameters: onTop };

      if (exposure4DEnabled && exposureRibbon.length) {
        // Glow under ribbon
        deckLayers.push(
          new PathLayer({
            id: "xray-ribbon-glow",
            data: exposureRibbon,
            getPath: (d) => d.path,
            getColor: (d) => {
              const c = utciColor(d.utci, 255);
              const active = tripMinute >= d.t_min && tripMinute <= d.t_max + 0.05;
              return [c[0], c[1], c[2], active ? 100 : 55] as [number, number, number, number];
            },
            getWidth: 22,
            widthMinPixels: 10,
            widthMaxPixels: 26,
            ...rounded,
          }),
        );
        deckLayers.push(
          new PathLayer({
            id: "xray-ribbon-core",
            data: exposureRibbon,
            getPath: (d) => d.path,
            getColor: (d) => {
              const c = utciColor(d.utci, 255);
              const active = tripMinute >= d.t_min && tripMinute <= d.t_max + 0.05;
              if (d.intersection) return [248, 113, 113, active ? 255 : 200];
              if (d.shaded) return [56, 189, 248, active ? 255 : 180];
              return [c[0], c[1], c[2], active ? 255 : 210] as [number, number, number, number];
            },
            getWidth: (d) => (tripMinute >= d.t_min && tripMinute <= d.t_max + 0.05 ? 10 : 6),
            widthMinPixels: 4,
            widthMaxPixels: 12,
            ...rounded,
          }),
        );
        // Traveled portion — bright white trail
        const traveled = exposureRibbon.filter((s) => s.t_max <= tripMinute + 0.1);
        if (traveled.length) {
          deckLayers.push(
            new PathLayer({
              id: "xray-traveled",
              data: traveled,
              getPath: (d) => d.path,
              getColor: [255, 255, 255, 140],
              getWidth: 4,
              widthMinPixels: 3,
              ...rounded,
            }),
          );
        }
      } else {
        pushRouteColorLayers(deckLayers, sel, "route-selected", true);
      }

      if (sel.refuges?.length) {
        deckLayers.push(
          new ScatterplotLayer({
            id: "route-refuges",
            data: sel.refuges,
            getPosition: (d: { lon: number; lat: number }) => [d.lon, d.lat],
            getFillColor: sel.multimodal ? [45, 212, 191, 255] : [244, 114, 182, 255],
            getRadius: sel.multimodal ? 22 : 16,
            radiusMinPixels: 8,
            stroked: true,
            getLineColor: [255, 255, 255, 230],
            lineWidthMinPixels: 2,
            parameters: onTop,
          })
        );
      }
    }
  }

  // 11. Shade eclipse crossings — shadow boundary meets the path.
  if (exposure4DEnabled && shadeCrossings.length) {
    const onTop = { depthTest: false as const };
    const nearCrossing = shadeCrossings.find((c) => Math.abs(c.t_min - tripMinute) < 1.2);
    deckLayers.push(
      new ScatterplotLayer({
        id: "shade-crossings",
        data: shadeCrossings,
        getPosition: (d) => [d.lon, d.lat],
        getFillColor: (d) =>
          d.entering_shade ? [56, 189, 248, 230] : [251, 191, 36, 230],
        getRadius: (d) => (nearCrossing === d ? 16 : 10),
        radiusMinPixels: 6,
        stroked: true,
        getLineColor: [255, 255, 255, 220],
        lineWidthMinPixels: 2,
        parameters: onTop,
      }),
    );
  }

  // 12. Exposure intersection sync cones on map.
  if (exposure4DEnabled && selRoute?.thermal_horizon?.intersections?.length) {
    const onTop = { depthTest: false as const };
    deckLayers.push(
      new ScatterplotLayer({
        id: "exposure-intersections",
        data: selRoute.thermal_horizon.intersections,
        getPosition: (d) => [d.lon, d.lat],
        getFillColor: [239, 68, 68, 180],
        getRadius: (d) => (Math.abs(d.t_min - tripMinute) < 1.5 ? 20 : 12),
        radiusMinPixels: 8,
        stroked: true,
        getLineColor: [255, 200, 100, 255],
        lineWidthMinPixels: 3,
        parameters: onTop,
      }),
    );
  }

  // 13. 4D exposure bubble — traveller position + UTCI/PM2.5 pulse (trip timeline).
  if (exposure4DEnabled && tripFrame) {
    const onTop = { depthTest: false as const };
    const [ur, ug, ub] = utciColor(tripFrame.utci, 255);
    const pmRing = (focusMode || demoPlaying ? 28 : 18) + pmStressNorm(tripFrame.pm25) * (focusMode ? 36 : 28);
    const flash = tripFrame.intersection || tripFrame.overlap_score >= 0.55;
    const coreR = focusMode || demoPlaying ? 8 : 5;
    const warming = utciDeltaVsNow >= 1.5;
    const cooling = utciDeltaVsNow <= -1.5;

    deckLayers.push(
      new ScatterplotLayer({
        id: "exposure-bubble-outer",
        data: [tripFrame],
        getPosition: (d) => [d.lon, d.lat],
        getFillColor: [0, 0, 0, 0],
        getRadius: pmRing,
        radiusMinPixels: flash ? 22 : 14,
        stroked: true,
        getLineColor: warming
          ? [248, 113, 113, flash ? 240 : 160]
          : cooling
            ? [74, 222, 128, flash ? 220 : 140]
            : [251, 146, 60, flash ? 220 : 140],
        lineWidthMinPixels: flash ? 4 : 2,
        parameters: onTop,
      }),
      new ScatterplotLayer({
        id: "exposure-bubble-mid",
        data: [tripFrame],
        getPosition: (d) => [d.lon, d.lat],
        getFillColor: [ur, ug, ub, flash ? 200 : 120],
        getRadius: 12,
        radiusMinPixels: 10,
        stroked: true,
        getLineColor: [255, 255, 255, flash ? 255 : 180],
        lineWidthMinPixels: 2,
        parameters: onTop,
      }),
      new ScatterplotLayer({
        id: "exposure-bubble-core",
        data: [tripFrame],
        getPosition: (d) => [d.lon, d.lat],
        getFillColor: [255, 255, 255, 255],
        getRadius: coreR,
        radiusMinPixels: coreR,
        stroked: false,
        parameters: onTop,
      }),
    );

    if (forecastDelayMin > 0 && Math.abs(utciDeltaVsNow) >= 0.5) {
      deckLayers.push(
        new ScatterplotLayer({
          id: "exposure-bubble-delta-halo",
          data: [tripFrame],
          getPosition: (d) => [d.lon, d.lat],
          getFillColor: utciDeltaVsNow >= 0 ? [248, 113, 113, 90] : [74, 222, 128, 90],
          getRadius: pmRing + 14,
          radiusMinPixels: 20,
          stroked: false,
          parameters: onTop,
        }),
      );
    }
  }

  return (
    <DeckGL
      viewState={viewState}
      controller={true}
      onViewStateChange={(e: any) => setViewState(e.viewState)}
      layers={deckLayers}
      effects={[lightingEffect]}
      onClick={onClick}
      getCursor={() => (store.pickMode ? "crosshair" : "grab")}
    >
      <Map mapStyle={MAP_STYLE} attributionControl={false} />
    </DeckGL>
  );
}
