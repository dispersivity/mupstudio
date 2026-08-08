import { useEffect, useState } from "react";
import { projects, type ProjectDetail, type ProjectSummary } from "@/net/projectClient";

export interface ActiveProject {
  summary: ProjectSummary;
  detail: ProjectDetail;
}

/**
 * Create a project or reopen one.
 *
 * New projects start as a 1D column because that is the shape a reactive
 * transport benchmark takes, and it is the only shape that can be described
 * before the map-based builder exists.
 */
export function ProjectStep({
  active,
  onOpen,
}: {
  active: ActiveProject | null;
  onOpen: (project: ActiveProject) => void;
}) {
  const [known, setKnown] = useState<ProjectSummary[]>([]);
  const [defaultParent, setDefaultParent] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = () => {
    projects
      .list()
      .then((body) => {
        setKnown(body.projects);
        setDefaultParent(body.defaultParent ?? "");
      })
      .catch((problem: Error) => setError(problem.message));
  };

  useEffect(refresh, []);

  const open = async (path: string) => {
    setBusy(true);
    setError(null);
    try {
      const { project, detail } = await projects.open(path);
      onOpen({ summary: project, detail });
      refresh();
    } catch (problem) {
      setError((problem as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-3xl space-y-8 overflow-y-auto p-8">
      {error && (
        <div className="rounded border border-red-900 bg-red-950/40 p-3 text-xs text-red-300">
          {error}
        </div>
      )}

      {active && <ActiveSummary project={active} />}

      <NewProjectForm
        busy={busy}
        defaultParent={defaultParent}
        onCreated={(created) => {
          onOpen(created);
          refresh();
        }}
        onError={setError}
        setBusy={setBusy}
      />

      <RecentProjects
        known={known}
        busy={busy}
        onOpen={open}
        onForget={async (path) => {
          await projects.forget(path);
          refresh();
        }}
      />

      <OpenByPath busy={busy} onOpen={open} />
    </div>
  );
}

function ActiveSummary({ project }: { project: ActiveProject }) {
  const { detail } = project;
  return (
    <section className="rounded border border-sky-900 bg-sky-950/30 p-4">
      <h2 className="text-sm font-medium text-zinc-100">{detail.name}</h2>
      <p className="mt-1 text-xs text-zinc-400">{detail.summary}</p>
      <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 text-xs">
        <Row label="Engine" value={detail.engine} />
        <Row
          label="Simulated time"
          value={`${detail.time.total} ${detail.timeUnit} in ${detail.time.nper} period${
            detail.time.nper === 1 ? "" : "s"
          }`}
        />
        <Row label="Cells" value={detail.grid.ncells.toLocaleString()} />
        <Row
          label="Boundaries"
          value={
            detail.boundaries.length === 0
              ? "none"
              : detail.boundaries.map((item) => item.id).join(", ")
          }
        />
      </dl>
      <p className="mt-3 truncate text-[10px] text-zinc-600">{project.summary.path}</p>
    </section>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt className="text-zinc-500">{label}</dt>
      <dd className="text-zinc-200">{value}</dd>
    </>
  );
}

function NewProjectForm({
  busy,
  defaultParent,
  onCreated,
  onError,
  setBusy,
}: {
  busy: boolean;
  /** Where the server would put it, shown so the path is never a surprise. */
  defaultParent: string;
  onCreated: (project: ActiveProject) => void;
  onError: (message: string) => void;
  setBusy: (busy: boolean) => void;
}) {
  const [name, setName] = useState("");
  const [engine, setEngine] = useState("mf6rtm");
  const [parent, setParent] = useState("");
  // Off by default: most reactive transport starts as a column or a box that is
  // nowhere in particular, and a coordinate system is a claim about the model
  // that should be made deliberately.
  const [georeferenced, setGeoreferenced] = useState(false);
  const [crs, setCrs] = useState("EPSG:32719");

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    try {
      const { project, detail } = await projects.create({
        name: name.trim(),
        engine,
        parent: parent.trim() || undefined,
        crs: georeferenced ? crs.trim() || null : null,
      });
      onCreated({ summary: project, detail });
    } catch (problem) {
      onError((problem as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-3">
      <h2 className="text-sm font-medium text-zinc-100">New project</h2>
      <p className="text-xs text-zinc-500">
        Starts as a 1D column: one row, one layer, cells along x. Width and thickness are 1, so cell
        volume equals cell length.
      </p>

      <div className="grid grid-cols-2 gap-3">
        <Field label="Name">
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Maipo valley"
            aria-label="Project name"
            required
            className="w-full rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs text-zinc-100"
          />
        </Field>
        <Field label="Engine">
          <select
            value={engine}
            onChange={(event) => setEngine(event.target.value)}
            className="w-full rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs text-zinc-100"
          >
            <option value="mf6rtm">MF6RTM</option>
            <option value="pht3d">PHT3D</option>
          </select>
        </Field>
      </div>

      <p className="text-[10px] leading-relaxed text-zinc-600">
        A new project starts as a 50-cell column half a metre long, with inflow at one end and
        outflow at the other, so it runs immediately. Change the discretisation in Grid, the stress
        periods in Time, and the boundaries in Flow.
      </p>

      {/* Asked here rather than later because the next step is Data, and where
          a shapefile belongs on Earth cannot be answered without it. */}
      <div className="rounded border border-zinc-800 p-3">
        <label className="flex items-center gap-2 text-xs text-zinc-300">
          <input
            type="checkbox"
            checked={georeferenced}
            onChange={(event) => setGeoreferenced(event.target.checked)}
            className="accent-sky-600"
          />
          This model is somewhere real
        </label>

        {georeferenced ? (
          <div className="mt-2 max-w-xs">
            <Field label="Coordinate reference system">
              <input
                value={crs}
                onChange={(event) => setCrs(event.target.value)}
                placeholder="EPSG:32719"
                aria-label="Coordinate reference system"
                className="w-full rounded border border-zinc-700 bg-zinc-900 px-2 py-1 font-mono text-xs text-zinc-100"
              />
            </Field>
            <p className="mt-1 text-[10px] leading-relaxed text-zinc-600">
              Use a projected system in metres. Degrees make a cell size meaningless, and every
              length in the model is a cell size.
            </p>
          </div>
        ) : (
          <p className="mt-1.5 text-[10px] leading-relaxed text-zinc-600">
            A benchmark column belongs nowhere, and nothing is lost by saying so. Turn this on for a
            model of a real place: it is what lets data be imported and drawn on a map.
          </p>
        )}
      </div>

      <Field label="Create in">
        <input
          value={parent}
          onChange={(event) => setParent(event.target.value)}
          placeholder={defaultParent || "…"}
          aria-label="Where to create the project"
          className="w-full rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs text-zinc-100"
        />
      </Field>
      {name.trim() && (
        <p className="text-[10px] text-zinc-600">
          Creates{" "}
          <span className="font-mono text-zinc-500">
            {(parent.trim() || defaultParent).replace(/\/$/, "")}/{slugify(name)}.mup
          </span>
        </p>
      )}

      <button
        type="submit"
        disabled={busy}
        className="rounded bg-sky-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-sky-500 disabled:opacity-40"
      >
        {busy ? "Working…" : "Create project"}
      </button>
    </form>
  );
}

function OpenByPath({ busy, onOpen }: { busy: boolean; onOpen: (path: string) => void }) {
  const [path, setPath] = useState("");

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        if (path.trim()) onOpen(path.trim());
      }}
      className="space-y-2"
    >
      <h2 className="text-sm font-medium text-zinc-100">Open by path</h2>
      <div className="flex gap-2">
        <input
          value={path}
          onChange={(event) => setPath(event.target.value)}
          placeholder="/path/to/column.mup"
          className="flex-1 rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs text-zinc-100"
        />
        <button
          type="submit"
          disabled={busy || !path.trim()}
          className="rounded border border-zinc-700 px-3 py-1 text-xs text-zinc-300 hover:border-zinc-600 disabled:opacity-40"
        >
          Open
        </button>
      </div>
    </form>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-[10px] text-zinc-500">{label}</span>
      {children}
    </label>
  );
}

/** The directory name the server derives from a project's name. */
function slugify(name: string): string {
  return name.replace(/[^A-Za-z0-9\-_]/g, "-");
}

/**
 * Projects opened before.
 *
 * Scrolled and forgettable. The list is a convenience, and one that grows
 * without bound turns the first screen of the app into a wall of paths — most
 * of them experiments that were never meant to be kept.
 */
function RecentProjects({
  known,
  busy,
  onOpen,
  onForget,
}: {
  known: ProjectSummary[];
  busy: boolean;
  onOpen: (path: string) => void;
  onForget: (path: string) => Promise<void>;
}) {
  const missing = known.filter((entry) => !entry.exists);

  if (known.length === 0) {
    return (
      <section>
        <h2 className="text-sm font-medium text-zinc-100">Recent projects</h2>
        <p className="mt-2 text-xs text-zinc-500">
          None yet. Create one above, or open one below by path.
        </p>
      </section>
    );
  }

  return (
    <section>
      <div className="flex items-baseline justify-between">
        <h2 className="text-sm font-medium text-zinc-100">
          Recent projects <span className="text-[10px] text-zinc-600">({known.length})</span>
        </h2>
        {missing.length > 0 && (
          <button
            type="button"
            onClick={() => void Promise.all(missing.map((entry) => onForget(entry.path)))}
            className="text-[10px] text-zinc-500 hover:text-zinc-300"
          >
            Forget {missing.length} missing
          </button>
        )}
      </div>

      <ul className="mt-2 max-h-72 space-y-0.5 overflow-y-auto pr-1">
        {known.map((entry) => (
          <li key={entry.path} className="group flex items-center gap-1">
            <button
              type="button"
              disabled={!entry.exists || busy}
              onClick={() => onOpen(entry.path)}
              className="min-w-0 flex-1 rounded px-2 py-1.5 text-left hover:bg-zinc-900 disabled:opacity-40"
            >
              <div className="flex items-baseline gap-2">
                <span className="truncate text-xs text-zinc-200">{entry.name}</span>
                <span className="shrink-0 text-[10px] text-zinc-600">{entry.engine}</span>
                {!entry.exists && (
                  <span className="shrink-0 text-[10px] text-amber-500">missing</span>
                )}
              </div>
              <div className="truncate text-[10px] text-zinc-600">{entry.path}</div>
            </button>
            <button
              type="button"
              onClick={() => void onForget(entry.path)}
              aria-label={`Forget ${entry.name}`}
              title="Remove from this list. Nothing on disk is touched."
              className="shrink-0 px-1.5 text-[10px] text-zinc-700 hover:text-red-400"
            >
              ×
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
