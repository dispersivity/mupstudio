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
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = () => {
    projects
      .list()
      .then((body) => setKnown(body.projects))
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
        onCreated={(created) => {
          onOpen(created);
          refresh();
        }}
        onError={setError}
        setBusy={setBusy}
      />

      <section>
        <h2 className="text-sm font-medium text-zinc-100">Recent projects</h2>
        {known.length === 0 ? (
          <p className="mt-2 text-xs text-zinc-500">
            None yet. Create one above, or open a directory made by{" "}
            <code className="text-zinc-400">mupstudio new</code>.
          </p>
        ) : (
          <ul className="mt-2 space-y-1">
            {known.map((entry) => (
              <li key={entry.path}>
                <button
                  type="button"
                  disabled={!entry.exists || busy}
                  onClick={() => open(entry.path)}
                  className="w-full rounded border border-zinc-800 px-3 py-2 text-left hover:border-zinc-700 disabled:opacity-40"
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="truncate text-xs text-zinc-200">{entry.name}</span>
                    <span className="shrink-0 text-[10px] text-zinc-500">{entry.engine}</span>
                  </div>
                  <div className="truncate text-[10px] text-zinc-600">
                    {entry.exists ? entry.path : `${entry.path} — missing`}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

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
  onCreated,
  onError,
  setBusy,
}: {
  busy: boolean;
  onCreated: (project: ActiveProject) => void;
  onError: (message: string) => void;
  setBusy: (busy: boolean) => void;
}) {
  const [name, setName] = useState("column");
  const [engine, setEngine] = useState("mf6rtm");
  const [parent, setParent] = useState("");

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    try {
      const { project, detail } = await projects.create({
        name,
        engine,
        parent: parent.trim() || undefined,
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
            <option value="pht3d">PHT3D (writing not implemented)</option>
          </select>
        </Field>
      </div>

      <p className="text-[10px] leading-relaxed text-zinc-600">
        A new project starts as a 50-cell column half a metre long, with inflow at one end and
        outflow at the other, so it runs immediately. Change the discretisation in Grid, the stress
        periods in Time, and the boundaries in Flow.
      </p>

      <Field label="Create in (blank uses the server's working directory)">
        <input
          value={parent}
          onChange={(event) => setParent(event.target.value)}
          placeholder="/path/to/models"
          className="w-full rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs text-zinc-100"
        />
      </Field>

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
