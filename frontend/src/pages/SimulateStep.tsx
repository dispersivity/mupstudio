import { useEffect, useState } from "react";
import { projects } from "@/net/projectClient";
import {
  TERMINAL_STATES,
  type RunState,
  type ValidationResult,
  type WriteResult,
} from "@/net/projectClient";
import { useRunSession } from "@/state/runSession";
import { prerequisitesFor } from "@/sim/checks";
import { Outcome, Prerequisites } from "@/sim/Prerequisites";
import { NoProject } from "./editor/controls";
import type { ActiveProject } from "./ProjectStep";

/**
 * Validate, write, run.
 *
 * The written files are shown, not just listed: a modeller checking whether the
 * app understood their intent reads the input MODFLOW will read, and a summary
 * of what we believe we wrote is exactly the thing they cannot trust.
 *
 * Run state lives in a store rather than here, so leaving this screen while a
 * model is running does not lose the output.
 */
export function SimulateStep({
  project,
  onFinished,
  onGoToProject,
}: {
  project: ActiveProject | null;
  onFinished: (runId: string) => void;
  onGoToProject: () => void;
}) {
  const session = useRunSession();
  // Only to distinguish "written just now" from "written earlier in this
  // session", so the outcome line does not claim credit for an old write.
  const [wroteAt, setWroteAt] = useState<number | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [preview, setPreview] = useState<{
    name: string;
    content: string;
    truncated: boolean;
  } | null>(null);

  const path = project?.summary.path ?? null;

  useEffect(() => {
    session.setProject(path);
  }, [path, session]);

  if (!project || !path) return <NoProject onGo={onGoToProject} />;

  const running = session.run !== null && !TERMINAL_STATES.has(session.run.state);

  const guard = async (label: string, action: () => Promise<void>) => {
    session.setBusy(label);
    session.setError(null);
    try {
      await action();
    } catch (problem) {
      session.setError((problem as Error).message);
    } finally {
      session.setBusy(null);
    }
  };

  const openFile = async (name: string) => {
    setSelected(name);
    try {
      const body = await projects.file(path, name);
      setPreview({ name, content: body.content, truncated: body.truncated });
    } catch (problem) {
      session.setError((problem as Error).message);
    }
  };

  const validate = () =>
    guard("validate", async () => session.setValidation(await projects.validate(path)));

  const write = () =>
    guard("write", async () => {
      const result = await projects.write(path);
      setWroteAt(Date.now());
      session.setWritten(result);
      // The discretisation file is what people check first.
      const first = result.files.find((name) => name.endsWith(".dis")) ?? result.files[0];
      if (first) void openFile(first);
    });

  const start = () =>
    guard("run", async () => {
      const started = await projects.run(path);
      session.setWritten({
        workdir: started.workdir,
        files: started.files,
        warnings: started.warnings,
        components: started.components,
      });
      setWroteAt(Date.now());
      session.start(started.runId);
    });

  return (
    <div className="flex h-full min-h-0">
      <div className="flex w-72 shrink-0 flex-col gap-4 overflow-y-auto border-r border-zinc-800 p-4">
        <div>
          <h2 className="text-sm font-medium text-zinc-100">{project.detail.name}</h2>
          <p className="mt-0.5 text-[10px] text-zinc-500">{project.detail.summary}</p>
        </div>

        <Prerequisites checks={prerequisitesFor(project.detail, session.written)} />

        <div className="space-y-2">
          <div>
            <Action
              label="Validate"
              busy={session.busy === "validate"}
              disabled={running}
              onClick={validate}
            />
            <Outcome>{validationOutcome(session.validation)}</Outcome>
          </div>

          <div>
            <Action
              label="Write input"
              busy={session.busy === "write"}
              disabled={running}
              onClick={write}
            />
            <Outcome>{writeOutcome(session.written, wroteAt)}</Outcome>
          </div>

          <Action
            label={running ? "Running…" : "Write and run"}
            primary
            busy={session.busy === "run" || running}
            disabled={running}
            onClick={start}
          />
          {running && (
            <button
              type="button"
              onClick={() => void session.cancel()}
              className="w-full rounded border border-red-900 px-3 py-1.5 text-xs text-red-300 hover:border-red-700"
            >
              Cancel run
            </button>
          )}
        </div>

        {session.error && (
          <div className="rounded border border-red-900 bg-red-950/40 p-2 text-[10px] leading-relaxed text-red-300">
            {session.error}
          </div>
        )}

        {session.finishedRunId && (
          <button
            type="button"
            onClick={() => {
              const runId = session.finishedRunId;
              session.clearFinished();
              if (runId) onFinished(runId);
            }}
            className="w-full rounded bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-500"
          >
            View results
          </button>
        )}

        {session.validation && <ValidationPanel result={session.validation} />}
        {session.run && <RunPanel run={session.run} />}

        {session.written && (
          <div className="min-h-0">
            <h3 className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
              Written files ({session.written.files.length})
            </h3>
            <ul className="mt-1 space-y-0.5">
              {session.written.files.map((name) => (
                <li key={name}>
                  <button
                    type="button"
                    onClick={() => void openFile(name)}
                    className={`w-full truncate rounded px-2 py-0.5 text-left font-mono text-[10px] ${
                      selected === name
                        ? "bg-sky-500/15 text-sky-200"
                        : "text-zinc-400 hover:bg-white/5"
                    }`}
                  >
                    {name}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex min-h-0 flex-1 flex-col">
          {preview ? (
            <>
              <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-2">
                <span className="font-mono text-xs text-zinc-300">{preview.name}</span>
                {preview.truncated && (
                  <span className="text-[10px] text-amber-300">truncated for preview</span>
                )}
              </div>
              <pre className="min-h-0 flex-1 overflow-auto p-4 font-mono text-[11px] leading-relaxed text-zinc-300">
                {preview.content}
              </pre>
            </>
          ) : (
            <div className="flex flex-1 items-center justify-center p-8 text-center">
              <p className="max-w-sm text-xs text-zinc-500">
                Write the input to see the files MODFLOW will read. Nothing here is a summary of
                what we think we wrote; it is the file itself.
              </p>
            </div>
          )}
        </div>

        <EngineOutput lines={session.log} running={running} />
      </div>
    </div>
  );
}

/**
 * The engine's own words, as they arrive.
 *
 * Follows the tail while a run is going, but stops following the moment you
 * scroll up: scrolling back to read something and being yanked to the bottom
 * makes a log unusable.
 */
function EngineOutput({ lines, running }: { lines: string[]; running: boolean }) {
  const [follow, setFollow] = useState(true);
  const [element, setElement] = useState<HTMLPreElement | null>(null);

  useEffect(() => {
    if (follow && element) element.scrollTop = element.scrollHeight;
  }, [lines, follow, element]);

  if (lines.length === 0 && !running) return null;

  return (
    <div className="flex h-52 shrink-0 flex-col border-t border-zinc-800 bg-zinc-950">
      <div className="flex items-center justify-between px-3 py-1">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
          Engine output {running && <span className="ml-1 text-sky-400">live</span>}
        </span>
        <label className="flex items-center gap-1 text-[10px] text-zinc-500">
          <input
            type="checkbox"
            checked={follow}
            onChange={(event) => setFollow(event.target.checked)}
          />
          follow
        </label>
      </div>
      <pre
        ref={setElement}
        onScroll={(event) => {
          const target = event.currentTarget;
          const atBottom = target.scrollHeight - target.scrollTop - target.clientHeight < 24;
          if (follow !== atBottom) setFollow(atBottom);
        }}
        className="min-h-0 flex-1 overflow-auto px-3 pb-2 font-mono text-[10px] leading-relaxed text-zinc-400"
      >
        {lines.length === 0 ? "waiting for output…" : lines.join("\n")}
      </pre>
    </div>
  );
}

function Action({
  label,
  onClick,
  busy,
  disabled,
  primary,
}: {
  label: string;
  onClick: () => void;
  busy?: boolean;
  disabled?: boolean;
  primary?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy || disabled}
      className={`w-full rounded px-3 py-1.5 text-xs font-medium disabled:opacity-40 ${
        primary
          ? "bg-sky-600 text-white hover:bg-sky-500"
          : "border border-zinc-700 text-zinc-300 hover:border-zinc-600"
      }`}
    >
      {busy ? "Working…" : label}
    </button>
  );
}

function ValidationPanel({
  result,
}: {
  result: {
    ok: boolean;
    cells?: number;
    errors: string[];
    warnings: string[];
    boundaries?: { id: string; kind: string; cells: number }[];
  };
}) {
  return (
    <div className="space-y-1 text-[10px]">
      <h3 className="font-semibold uppercase tracking-wider text-zinc-500">Validation</h3>
      <p className={result.ok ? "text-emerald-400" : "text-red-400"}>
        {result.ok ? `ok — ${result.cells?.toLocaleString()} cells` : "problems found"}
      </p>
      {result.errors.map((message) => (
        <p key={message} className="leading-relaxed text-red-300">
          {message}
        </p>
      ))}
      {result.warnings.map((message) => (
        <p key={message} className="leading-relaxed text-amber-300">
          {message}
        </p>
      ))}
      {result.boundaries?.map((boundary) => (
        <p key={boundary.id} className="text-zinc-500">
          {boundary.id}: {boundary.cells} cell{boundary.cells === 1 ? "" : "s"}
        </p>
      ))}
    </div>
  );
}

const STATE_COLOUR: Record<string, string> = {
  running: "text-sky-400",
  queued: "text-zinc-400",
  succeeded: "text-emerald-400",
  failed: "text-red-400",
  cancelled: "text-amber-400",
  unknown: "text-amber-400",
};

function RunPanel({ run }: { run: RunState }) {
  const fraction = run.progress?.fraction;
  return (
    <div className="space-y-1 text-[10px]">
      <h3 className="font-semibold uppercase tracking-wider text-zinc-500">Run</h3>
      <p className={STATE_COLOUR[run.state] ?? "text-zinc-400"}>
        {run.state}
        {run.exitCode !== null && run.exitCode !== 0 ? ` (exit ${run.exitCode})` : ""}
      </p>
      {run.progress?.kper != null && (
        <p className="tabular-nums text-zinc-400">
          stress period {run.progress.kper}
          {run.progress.kstp != null ? `, step ${run.progress.kstp}` : ""} — {run.progress.phase}
        </p>
      )}
      {fraction != null && (
        <div className="h-1 overflow-hidden rounded bg-zinc-800">
          <div className="h-full bg-sky-500" style={{ width: `${fraction * 100}%` }} />
        </div>
      )}
      {run.message && <p className="leading-relaxed text-amber-300">{run.message}</p>}
      {run.progress?.warnings.map((warning) => (
        <p key={warning} className="leading-relaxed text-amber-300">
          {warning}
        </p>
      ))}
      <p className="truncate text-zinc-600">{run.runId}</p>
    </div>
  );
}

/** What validation found, in one line. */
function validationOutcome(result: ValidationResult | null): string {
  if (!result) return "";
  if (!result.ok) {
    return `${result.errors.length} problem${result.errors.length === 1 ? "" : "s"} to fix`;
  }

  const cells = result.cells ? `${result.cells.toLocaleString()} cells` : "";
  const boundaries = result.boundaries?.length
    ? `${result.boundaries.reduce((total, item) => total + item.cells, 0)} boundary cells`
    : "no boundaries";
  const warnings = result.warnings.length
    ? ` · ${result.warnings.length} warning${result.warnings.length === 1 ? "" : "s"}`
    : "";

  return `valid · ${[cells, boundaries].filter(Boolean).join(" · ")}${warnings}`;
}

/** What writing produced. */
function writeOutcome(written: WriteResult | null, at: number | null): string {
  if (!written || at === null) return "";
  const parts = [`${written.files.length} files`];
  const components = written.components;
  if (components?.length) parts.push(`${components.length} components`);
  if (written.warnings.length) {
    parts.push(`${written.warnings.length} warning${written.warnings.length === 1 ? "" : "s"}`);
  }
  return parts.join(" · ");
}
