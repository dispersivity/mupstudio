import type { FeatureCollection } from "geojson";

/**
 * Talking to the Data step's endpoints.
 *
 * Layers come back as GeoJSON already in longitude and latitude: the server
 * knows the project's coordinate system and has pyproj, so it converts once
 * rather than shipping a projection library to the browser to do it again.
 */

export interface Basemap {
  id: string;
  label: string;
  url: string;
  attribution: string;
  maxZoom: string;
}

export interface DataSource {
  id: string;
  kind: "vector" | "raster" | "points";
  label: string;
  path: string;
  crs: string | null;
  visible: boolean;
  colour: string;
  bounds: [number, number, number, number] | null;
  /** Vector only. */
  geometry?: "polygon" | "line" | "point" | "mixed";
  feature_count?: number;
  /** Raster only. */
  width?: number;
  height?: number;
  band_count?: number;
  /** Points only. */
  row_count?: number;
  x_column?: string;
  y_column?: string;
}

export interface DataState {
  sources: DataSource[];
  basemap: string | null;
  crs: string | null;
  /** West, south, east, north, in degrees, of everything imported. */
  extent: [number, number, number, number] | null;
}

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

const project = (path: string) => `path=${encodeURIComponent(path)}`;

export async function fetchBasemaps(): Promise<{ basemaps: Basemap[]; note: string }> {
  return json("/api/v1/basemaps");
}

export async function fetchData(path: string): Promise<DataState> {
  return json(`/api/v1/projects/data?${project(path)}`);
}

export async function fetchLayer(path: string, source: string): Promise<FeatureCollection> {
  return json(
    `/api/v1/projects/data/geojson?${project(path)}&source=${encodeURIComponent(source)}`,
  );
}

export async function uploadLayer(
  path: string,
  file: File,
): Promise<{ source: DataSource; warnings: string[] }> {
  const form = new FormData();
  form.append("file", file);
  return json(`/api/v1/projects/data/upload?${project(path)}`, { method: "POST", body: form });
}

export async function importPath(
  path: string,
  filePath: string,
): Promise<{ source: DataSource; warnings: string[] }> {
  return json(`/api/v1/projects/data/import?${project(path)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path: filePath }),
  });
}

export async function updateSource(
  path: string,
  source: string,
  change: Partial<Pick<DataSource, "label" | "colour" | "visible">>,
): Promise<{ source: DataSource }> {
  return json(
    `/api/v1/projects/data/source?${project(path)}&source=${encodeURIComponent(source)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(change),
    },
  );
}

export async function setBasemap(path: string, basemap: string | null): Promise<void> {
  const query = basemap ? `&basemap=${encodeURIComponent(basemap)}` : "";
  await json(`/api/v1/projects/data/basemap?${project(path)}${query}`, { method: "PUT" });
}

export async function removeSource(path: string, source: string): Promise<void> {
  await json(`/api/v1/projects/data/source?${project(path)}&source=${encodeURIComponent(source)}`, {
    method: "DELETE",
  });
}

export interface GeneratedGrid {
  cellSize: number;
  nrow: number;
  ncol: number;
  nlay: number;
  activeCells: number;
  totalCells: number;
  summary: string;
  warnings: string[];
  applied: boolean;
}

/**
 * Cover an imported boundary with cells.
 *
 * With `apply` false nothing is saved and only the counts come back, which is
 * what makes trying a cell size cheap enough to do three times.
 */
export async function gridFromBoundary(
  path: string,
  body: { source: string; cellSize?: number; margin?: number; apply: boolean },
): Promise<GeneratedGrid> {
  return json(`/api/v1/projects/grid/from-boundary?${project(path)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
