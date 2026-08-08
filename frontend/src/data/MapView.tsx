import type { FeatureCollection } from "geojson";
import {
  Map as MapLibreMap,
  NavigationControl,
  ScaleControl,
  type MapMouseEvent,
  type StyleSpecification,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef, useState } from "react";
import type { Basemap, DataSource } from "./dataClient";

/**
 * The imported data, on a map.
 *
 * Only the Data step has a map. Everything downstream works on the grid, where
 * a basemap would be a distraction at best: the question on the Flow step is
 * which cells a boundary is in, and satellite imagery cannot help with it.
 *
 * The map is deliberately not the WebGPU viewport. Tiles, pan and zoom in a
 * geographic projection are a solved problem with a lot of fiddly detail in it,
 * and the viewport's job — extruded prisms at a hundred frames a second — is a
 * different one. They share nothing but the screen.
 *
 * Nothing is fetched from the network until a basemap is chosen. With none, the
 * map is an empty dark canvas with the data drawn on it, which is a perfectly
 * good way to look at a catchment and involves telling nobody where it is.
 */

const EMPTY_STYLE: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [{ id: "background", type: "background", paint: { "background-color": "#0a0a0c" } }],
};

function styleFor(basemap: Basemap | null): StyleSpecification {
  if (!basemap) return EMPTY_STYLE;
  return {
    version: 8,
    sources: {
      basemap: {
        type: "raster",
        tiles: [basemap.url],
        tileSize: 256,
        maxzoom: Number(basemap.maxZoom) || 19,
        attribution: basemap.attribution,
      },
    },
    layers: [
      { id: "background", type: "background", paint: { "background-color": "#0a0a0c" } },
      { id: "basemap", type: "raster", source: "basemap" },
    ],
  };
}

export function MapView({
  sources,
  layers,
  basemap,
  extent,
  onSelect,
  selected,
  className = "",
}: {
  sources: DataSource[];
  /** Each layer's GeoJSON, already in longitude and latitude. */
  layers: Record<string, FeatureCollection>;
  basemap: Basemap | null;
  extent: [number, number, number, number] | null;
  onSelect?: (id: string) => void;
  selected?: string | null;
  className?: string;
}) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<MapLibreMap | null>(null);
  const fitted = useRef(false);
  // Bumped whenever a style finishes loading. Drawing the data is an effect of
  // this rather than a listener on the map, because adding a layer is itself a
  // style change: a handler that redrew on every style event would trigger
  // itself for ever.
  const [styleEpoch, setStyleEpoch] = useState(0);

  useEffect(() => {
    if (!container.current) return;

    const instance = new MapLibreMap({
      container: container.current,
      style: EMPTY_STYLE,
      center: [0, 0],
      zoom: 1,
      attributionControl: { compact: true },
    });
    instance.addControl(new NavigationControl({ showCompass: false }), "top-right");
    instance.addControl(new ScaleControl({ unit: "metric" }), "bottom-right");
    map.current = instance;

    return () => {
      instance.remove();
      map.current = null;
      fitted.current = false;
    };
  }, []);

  // Switching basemap replaces the style, which drops every layer with it, so
  // the data is put back once the new style has been parsed.
  //
  // The signal is `style.load`, not `isStyleLoaded()`. The latter reports
  // whether everything the style needs has finished arriving, which for a
  // raster basemap means every visible tile — it stays false for as long as
  // the map is fetching, and gating a draw on it means never drawing at all.
  // `style.load` fires once the style itself is ready to take layers, which is
  // the question actually being asked.
  useEffect(() => {
    const instance = map.current;
    if (!instance) return;

    const ready = () => setStyleEpoch((value) => value + 1);
    instance.once("style.load", ready);
    instance.setStyle(styleFor(basemap));

    return () => {
      instance.off("style.load", ready);
    };
  }, [basemap]);

  useEffect(() => {
    const instance = map.current;
    if (!instance) return;

    // Nothing to draw on until a style has been parsed; the epoch says when
    // one has, and changes again whenever the basemap is swapped.
    if (styleEpoch === 0) return;
    drawLayers(instance, sources, layers, selected ?? null);
  }, [sources, layers, selected, styleEpoch]);

  // Move to the data the first time there is any. Only once: refitting on every
  // import would yank the view away while someone is looking at something.
  useEffect(() => {
    const instance = map.current;
    if (!instance || !extent || fitted.current) return;
    const [west, south, east, north] = extent;
    if (west === east || south === north) {
      instance.jumpTo({ center: [west, south], zoom: 13 });
    } else {
      instance.fitBounds([west, south, east, north], { padding: 48, duration: 0 });
    }
    fitted.current = true;
  }, [extent]);

  // Clicking a feature selects its layer, which is how you find out what
  // something is when several overlap.
  useEffect(() => {
    const instance = map.current;
    if (!instance || !onSelect) return;

    const click = (event: MapMouseEvent) => {
      const hits = instance.queryRenderedFeatures(event.point);
      const layer = hits.find((hit) => hit.layer?.id?.startsWith("data:"));
      if (layer) onSelect(layer.layer.id.split(":")[1]);
    };
    instance.on("click", click);
    return () => {
      instance.off("click", click);
    };
  }, [onSelect]);

  return <div ref={container} className={`min-h-0 ${className}`} />;
}

/**
 * Put the data on the map, replacing whatever was there.
 *
 * Rebuilt rather than diffed: these are a handful of layers whose GeoJSON is
 * already in memory, and the bookkeeping to work out what changed would be
 * more code than the work it saves.
 */
function drawLayers(
  map: MapLibreMap,
  sources: DataSource[],
  layers: Record<string, FeatureCollection>,
  selected: string | null,
): void {
  const style = map.getStyle();
  for (const layer of style.layers ?? []) {
    if (layer.id.startsWith("data:") && map.getLayer(layer.id)) map.removeLayer(layer.id);
  }
  for (const id of Object.keys(style.sources ?? {})) {
    if (id.startsWith("data:") && map.getSource(id)) map.removeSource(id);
  }

  // Drawn back to front: polygons first so lines and points sit on top of them
  // rather than under.
  const order = { polygon: 0, raster: 1, line: 2, point: 3, mixed: 2 } as const;
  const drawable = sources
    .filter((source) => source.visible && layers[source.id])
    .sort((left, right) => rank(left, order) - rank(right, order));

  for (const source of drawable) {
    const id = `data:${source.id}`;
    map.addSource(id, { type: "geojson", data: layers[source.id] });

    const emphasis = source.id === selected;
    const width = emphasis ? 3 : 1.6;

    if (source.kind === "raster") {
      // A raster shows as its footprint. The pixels are the Grid step's
      // business; here the question is only where it covers.
      map.addLayer({
        id,
        type: "line",
        source: id,
        paint: {
          "line-color": source.colour,
          "line-width": width,
          "line-dasharray": [3, 2],
        },
      });
      continue;
    }

    const geometry = source.kind === "points" ? "point" : (source.geometry ?? "polygon");

    if (geometry === "point") {
      map.addLayer({
        id,
        type: "circle",
        source: id,
        paint: {
          "circle-radius": emphasis ? 6 : 4,
          "circle-color": source.colour,
          "circle-stroke-width": 1,
          "circle-stroke-color": "#0a0a0c",
        },
      });
    } else if (geometry === "line") {
      map.addLayer({
        id,
        type: "line",
        source: id,
        paint: { "line-color": source.colour, "line-width": width },
      });
    } else {
      // Outlined and barely filled: a solid polygon over satellite imagery
      // hides the thing you imported it to sit against.
      map.addLayer({
        id,
        type: "fill",
        source: id,
        paint: {
          "fill-color": source.colour,
          "fill-opacity": emphasis ? 0.25 : 0.12,
          "fill-outline-color": source.colour,
        },
      });
    }
  }
}

function rank(source: DataSource, order: Record<string, number>): number {
  if (source.kind === "raster") return order.raster;
  if (source.kind === "points") return order.point;
  return order[source.geometry ?? "polygon"] ?? 0;
}
