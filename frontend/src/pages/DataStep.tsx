import type { FeatureCollection } from "geojson";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  fetchBasemaps,
  fetchData,
  fetchLayer,
  removeSource,
  setBasemap,
  updateSource,
  uploadLayer,
  type Basemap,
  type DataSource,
  type DataState,
} from "@/data/dataClient";
import { MapView } from "@/data/MapView";
import { NoProject } from "./editor/controls";

/**
 * Spatial data brought into the project, on a map.
 *
 * The only step with a map. It answers where the model is and what it is being
 * built from — a catchment boundary, a river network, wells, a terrain model —
 * and hands those to the Grid step to be turned into cells. Everything after
 * that works on the grid, where a basemap would be a distraction.
 */
export function DataStep({
  path,
  onGoToProject,
  onSaved,
}: {
  path: string | null;
  onGoToProject: () => void;
  onSaved: () => void;
}) {
  const [state, setState] = useState<DataState | null>(null);
  const [basemaps, setBasemaps] = useState<Basemap[]>([]);
  const [note, setNote] = useState("");
  const [layers, setLayers] = useState<Record<string, FeatureCollection>>({});
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  // Which layers have been asked for. Kept in a ref rather than derived from
  // what has arrived, so that a result landing does not look like a reason to
  // start the others again.
  const requested = useRef(new Set<string>());
  const mounted = useRef(true);

  useEffect(
    () => () => {
      mounted.current = false;
    },
    [],
  );

  const reload = useCallback(async () => {
    if (!path) return;
    try {
      setState(await fetchData(path));
      setError(null);
    } catch (problem) {
      setError((problem as Error).message);
    }
  }, [path]);

  useEffect(() => {
    void reload();
  }, [reload]);

  useEffect(() => {
    fetchBasemaps()
      .then((found) => {
        setBasemaps(found.basemaps);
        setNote(found.note);
      })
      .catch(() => setBasemaps([]));
  }, []);

  // Each layer's geometry is fetched once and kept: reprojecting a catchment
  // boundary every time a checkbox moves would be wasteful and slow.
  //
  // Deliberately not keyed on what has already arrived. Doing that made each
  // result re-run the effect, and the re-run's cleanup cancelled every request
  // still in flight — so importing four layers reliably drew one.
  useEffect(() => {
    if (!path || !state) return;

    for (const source of state.sources) {
      if (requested.current.has(source.id)) continue;
      requested.current.add(source.id);

      fetchLayer(path, source.id)
        .then((geojson) => {
          if (mounted.current) setLayers((current) => ({ ...current, [source.id]: geojson }));
        })
        .catch((problem: Error) => {
          // Dropped from the set so a layer that failed once can be retried
          // when something else changes.
          requested.current.delete(source.id);
          setWarnings((current) => [...current, `${source.label}: ${problem.message}`]);
        });
    }
  }, [path, state]);

  // A different project shares nothing with this one.
  useEffect(() => {
    requested.current = new Set();
    setLayers({});
    setSelected(null);
  }, [path]);

  const importFiles = async (files: FileList | File[]) => {
    if (!path) return;
    setError(null);

    for (const file of Array.from(files)) {
      setBusy(`Reading ${file.name}`);
      try {
        const result = await uploadLayer(path, file);
        setWarnings((current) => [...current, ...result.warnings]);
      } catch (problem) {
        setError(`${file.name}: ${(problem as Error).message}`);
      }
    }

    setBusy(null);
    await reload();
    onSaved();
  };

  if (!path) return <NoProject onGo={onGoToProject} />;

  const active = basemaps.find((item) => item.id === state?.basemap) ?? null;
  const georeferenced = state?.crs != null;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-start justify-between gap-4 border-b border-zinc-800 px-6 py-4">
        <div>
          <h2 className="text-sm font-medium text-zinc-100">Data</h2>
          <p className="mt-0.5 max-w-2xl text-xs leading-relaxed text-zinc-500">
            What the model is built from: a boundary to fill with cells, rivers to refine toward,
            wells to place, terrain to drape over. Shapefiles, GeoJSON, GeoTIFF and CSV.
          </p>
        </div>
      </div>

      {(error || warnings.length > 0) && (
        <div className="border-b border-zinc-800 px-6 py-2">
          {error && <p className="text-[11px] text-red-300">{error}</p>}
          {warnings.slice(-4).map((warning, index) => (
            <p key={index} className="text-[11px] text-amber-300">
              {warning}
            </p>
          ))}
        </div>
      )}

      <div className="flex min-h-0 flex-1">
        <div
          className="relative min-h-0 min-w-0 flex-1 p-3"
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault();
            setDragging(false);
            void importFiles(event.dataTransfer.files);
          }}
        >
          <MapView
            sources={state?.sources ?? []}
            layers={layers}
            basemap={active}
            extent={state?.extent ?? null}
            selected={selected}
            onSelect={setSelected}
            className="h-full overflow-hidden rounded border border-zinc-800"
          />

          {dragging && (
            <div className="pointer-events-none absolute inset-3 flex items-center justify-center rounded border-2 border-dashed border-sky-500 bg-sky-950/40">
              <p className="text-sm text-sky-200">Drop to import</p>
            </div>
          )}

          {busy && (
            <div className="absolute left-6 top-6 rounded bg-black/80 px-3 py-1.5 text-[11px] text-zinc-200 backdrop-blur-sm">
              {busy}…
            </div>
          )}

          {/* Basemap and coordinate system in one place, always visible, so
              where the model is on Earth is never a question you have to go
              looking for the answer to. */}
          <div className="absolute bottom-6 left-6 flex items-center gap-2 rounded-full bg-black/80 px-3 py-1.5 text-[10px] backdrop-blur-sm">
            <select
              value={state?.basemap ?? ""}
              aria-label="Basemap"
              disabled={!georeferenced}
              onChange={async (event) => {
                const chosen = event.target.value || null;
                try {
                  await setBasemap(path, chosen);
                  await reload();
                } catch (problem) {
                  setError((problem as Error).message);
                }
              }}
              className="bg-transparent text-zinc-200 focus:outline-none disabled:opacity-40"
            >
              <option value="">No basemap</option>
              {basemaps.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
            <span className="text-zinc-700">│</span>
            <span className="font-mono text-zinc-400">{state?.crs ?? "no CRS"}</span>
          </div>
        </div>

        <div className="flex min-h-0 w-96 shrink-0 flex-col border-l border-zinc-800">
          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
            {!georeferenced && (
              <p className="mb-4 rounded border border-amber-900 bg-amber-950/30 p-2 text-[11px] leading-relaxed text-amber-200">
                This model has no coordinate system, so it cannot be put on a map. Set one on the
                Grid step, under Domain. Data can still be imported; it just has nowhere to go.
              </p>
            )}

            <button
              type="button"
              onClick={() => fileInput.current?.click()}
              className="w-full rounded border border-dashed border-zinc-700 py-6 text-center hover:border-zinc-600"
            >
              <span className="block text-xs text-zinc-300">Drop files here, or browse</span>
              <span className="mt-0.5 block text-[10px] text-zinc-600">
                Shapefile (.shp or a zip of one) · GeoJSON · GeoTIFF · CSV
              </span>
            </button>
            <input
              ref={fileInput}
              type="file"
              multiple
              hidden
              aria-label="Import spatial data"
              onChange={(event) => {
                if (event.target.files) void importFiles(event.target.files);
                event.target.value = "";
              }}
            />

            <LayerList
              sources={state?.sources ?? []}
              selected={selected}
              onSelect={setSelected}
              onChange={async (id, change) => {
                await updateSource(path, id, change);
                await reload();
              }}
              onRemove={async (id) => {
                await removeSource(path, id);
                requested.current.delete(id);
                setLayers((current) => {
                  const next = { ...current };
                  delete next[id];
                  return next;
                });
                await reload();
              }}
            />

            {note && basemaps.length > 0 && (
              <p className="mt-6 text-[10px] leading-relaxed text-zinc-600">{note}</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

/** What has been imported, grouped by what it is. */
function LayerList({
  sources,
  selected,
  onSelect,
  onChange,
  onRemove,
}: {
  sources: DataSource[];
  selected: string | null;
  onSelect: (id: string) => void;
  onChange: (id: string, change: Partial<DataSource>) => Promise<void>;
  onRemove: (id: string) => Promise<void>;
}) {
  const groups: { kind: string; label: string; members: DataSource[] }[] = [
    {
      kind: "polygon",
      label: "Areas",
      members: sources.filter((item) => item.kind === "vector" && item.geometry === "polygon"),
    },
    {
      kind: "line",
      label: "Lines",
      members: sources.filter((item) => item.kind === "vector" && item.geometry === "line"),
    },
    {
      kind: "point",
      label: "Points",
      members: sources.filter(
        (item) => item.kind === "points" || (item.kind === "vector" && item.geometry === "point"),
      ),
    },
    { kind: "raster", label: "Rasters", members: sources.filter((item) => item.kind === "raster") },
  ];

  if (sources.length === 0) {
    return (
      <p className="mt-6 text-[11px] leading-relaxed text-zinc-600">
        Nothing imported yet. A catchment boundary is the usual first thing: it becomes the outline
        the grid fills.
      </p>
    );
  }

  return (
    <div className="mt-6 space-y-4">
      {groups
        .filter((group) => group.members.length > 0)
        .map((group) => (
          <div key={group.kind}>
            <h3 className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
              {group.label} <span className="text-zinc-700">({group.members.length})</span>
            </h3>
            <ul className="mt-1 space-y-0.5">
              {group.members.map((source) => (
                <li key={source.id}>
                  <div
                    className={`flex items-center gap-2 rounded px-1.5 py-1 ${
                      selected === source.id ? "bg-zinc-800" : "hover:bg-zinc-900"
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={source.visible}
                      aria-label={`Show ${source.label}`}
                      onChange={(event) =>
                        void onChange(source.id, { visible: event.target.checked })
                      }
                      className="accent-sky-600"
                    />
                    <input
                      type="color"
                      value={source.colour}
                      aria-label={`Colour of ${source.label}`}
                      onChange={(event) => void onChange(source.id, { colour: event.target.value })}
                      className="h-3.5 w-3.5 cursor-pointer border-0 bg-transparent p-0"
                    />
                    <button
                      type="button"
                      onClick={() => onSelect(source.id)}
                      className="min-w-0 flex-1 truncate text-left text-[11px] text-zinc-200"
                      title={source.path}
                    >
                      {source.label}
                    </button>
                    <span className="shrink-0 text-[10px] tabular-nums text-zinc-600">
                      {describe(source)}
                    </span>
                    <button
                      type="button"
                      onClick={() => void onRemove(source.id)}
                      aria-label={`Remove ${source.label}`}
                      className="shrink-0 text-[10px] text-zinc-600 hover:text-red-400"
                    >
                      ×
                    </button>
                  </div>

                  {selected === source.id && (
                    <p className="ml-7 pb-1 font-mono text-[10px] text-zinc-600">
                      {source.crs ?? "no CRS — read as the project's"}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          </div>
        ))}
    </div>
  );
}

/** The one number that says how big a layer is. */
function describe(source: DataSource): string {
  if (source.kind === "raster") return `${source.width}×${source.height}`;
  if (source.kind === "points") return `${source.row_count ?? 0}`;
  return `${source.feature_count ?? 0}`;
}
