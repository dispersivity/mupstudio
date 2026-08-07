import { useCallback, useEffect, useRef, useState } from "react";
import {
  projects,
  runs,
  watchRun,
  TERMINAL_STATES,
  type RunState,
  type ValidationResult,
  type WriteResult,
} from "@/net/projectClient";
import type { ActiveProject } from "./ProjectStep";

/**
 * Validate, write, run.
 *
 * The written files are shown, not just listed. A modeller checking whether the
 * app understood their intent reads the input MODFLOW will read; a summary of
 * what we think we wrote is exactly the thing they cannot trust.
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
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [written, setWritten] = useState<WriteResult | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [preview, setPreview] = useState<{
    name: string;
    content: string;
    truncated: boolean;
  } | null>(null);
  const [run, setRun] = useState<RunState | null>(null);
  const [log, setLog] = useState<string[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const unwatch = useRef<(() => void) | null>(null);

  const path = project?.summary.path ?? null;

  // A different project invalidates everything shown here.
  useEffect(() => {
    setValidation(null);
    setWritten(null);
    setSelected(null);
    setPreview(null);
    setRun(null);
    setLog([]);
  }, [path]);

  useEffect(() => () => unwatch.current?.(), []);

  const guard = useCallback(async (label: string, action: () => Promise<void>) => {
    setBusy(label);
    setError(null);
    try {
      await action();
    } catch (problem) {
      setError((problem as Error).message);
    } finally {
      setBusy(null);
    }
  }, []);

  const validate = () =>
    guard("validate", async () => {
      if (!path) return;
      setValidation(await projects.validate(path));
    });

  const write = () =>
    guard("write", async () => {
      if (!path) return;
      const result = await projects.write(path);
      setWritten(result);
      // Open the discretisation file first: it is what people check.
      const first = result.files.find((name) => name.endsWith(".dis")) ?? result.files[0];
      if (first) void openFile(first, result);
    });

  const openFile = async (name: string, source: WriteResult | null = written) => {
    if (!path || !source) return;
    setSelected(name);
    try {
      const body = await projects.file(path, name);
      setPreview({ name, content: body.content, truncated: body.truncated });
    } catch (problem) {
      setError((problem as Error).message);
    }
  };

  const start = () =>
    guard("run", async () => {
      if (!path) return;
      const started = await projects.run(path);
      setWritten({ workdir: started.workdir, files: started.files, warnings: started.warnings });
      setLog([]);
      setRun(await runs.status(started.runId));

      unwatch.current?.();
      unwatch.current = watchRun(started.runId, {
        onState: (state) => {
          setRun(state);
          if (TERMINAL_STATES.has(state.state)) {
            void finish(state);
          }
        },
        onProgress: (progress) => {
          setRun((current) =>
            current
              ? {
                  ...current,
                  progress: {
                    kper: progress.kper,
                    kstp: progress.kstp,
                    phase: progress.phase,
                    fraction: current.progress?.fraction ?? null,
                    warnings: current.progress?.warnings ?? [],
                  },
                }
              : current,
          );
        },
      });
    });

  const finish = async (state: RunState) => {
    try {
      setLog((await runs.log(state.runId)).lines);
      // Collect whatever was written, even from a failed run: partial output is
      // usually the most useful thing to look at when a model dies.
      await runs.collect(state.runId);
      onFinished(state.runId);
    } catch (problem) {
      setError((problem as Error).message);
    }
  };

  if (!project) {
    return (
      <div className="flex h-full items-center justify-center p-8">
        <div className="max-w-md space-y-3 text-center">
          <p className="text-sm text-zinc-300">No project open.</p>
          <button
            type="button"
            onClick={onGoToProject}
            className="rounded border border-zinc-700 px-3 py-1.5 text-xs text-zinc-300 hover:border-zinc-600"
          >
            Go to Project
          </button>
        </div>
      </div>
    );
  }

  const running = run !== null && !TERMINAL_STATES.has(run.state);

  return (
    <div className="flex h-full min-h-0">
      <div className="flex w-72 shrink-0 flex-col gap-4 overflow-y-auto border-r border-zinc-800 p-4">
        <div>
          <h2 className="text-sm font-medium text-zinc-100">{project.detail.name}</h2>
          <p className="mt-0.5 text-[10px] text-zinc-500">{project.detail.summary}</p>
        </div>

        <div className="space-y-2">
          <Action
            label="Validate"
            busy={busy === "validate"}
            disabled={running}
            onClick={validate}
          />
          <Action label="Write input" busy={busy === "write"} disabled={running} onClick={write} />
          <Action
            label={running ? "Running…" : "Write and run"}
            primary
            busy={busy === "run" || running}
            disabled={running}
            onClick={start}
          />
          {running && (
            <button
              type="button"
              onClick={() => run && void runs.cancel(run.runId)}
              className="w-full rounded border border-red-900 px-3 py-1.5 text-xs text-red-300 hover:border-red-700"
            >
              Cancel run
            </button>
          )}
        </div>

        {error && (
          <div className="rounded border border-red-900 bg-red-950/40 p-2 text-[10px] leading-relaxed text-red-300">
            {error}
          </div>
        )}

        {validation && <ValidationPanel result={validation} />}
        {run && <RunPanel run={run} />}

        {written && (
          <div className="min-h-0">
            <h3 className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
              Written files ({written.files.length})
            </h3>
            <ul className="mt-1 space-y-0.5">
              {written.files.map((name) => (
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
              Write the input to see the files MODFLOW will read. Nothing here is a summary of what
              we think we wrote; it is the file itself.
            </p>
          </div>
        )}

        {log.length > 0 && (
          <div className="max-h-48 shrink-0 overflow-auto border-t border-zinc-800 bg-zinc-950 p-3">
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
              Engine output
            </div>
            <pre className="font-mono text-[10px] leading-relaxed text-zinc-400">
              {log.join("\n")}
            </pre>
          </div>
        )}
      </div>
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

function ValidationPanel({ result }: { result: ValidationResult }) {
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
          {boundary.id} ({boundary.kind}): {boundary.cells} cell{boundary.cells === 1 ? "" : "s"}
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
