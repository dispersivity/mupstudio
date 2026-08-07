import { create } from "zustand";
import {
  runs,
  watchRun,
  TERMINAL_STATES,
  type RunState,
  type ValidationResult,
  type WriteResult,
} from "@/net/projectClient";

/**
 * The state of the current run, held outside the Simulate step.
 *
 * A run outlives the screen you started it from. Keeping this in the step's
 * own state meant navigating to Results and back lost the log, the file list
 * and the progress — while the model was still running.
 */

/** Lines kept in memory. A long reactive run prints far more than anyone reads. */
const LOG_LIMIT = 5000;

interface RunSession {
  projectPath: string | null;
  validation: ValidationResult | null;
  written: WriteResult | null;
  run: RunState | null;
  log: string[];
  error: string | null;
  busy: string | null;

  setProject: (path: string | null) => void;
  setValidation: (result: ValidationResult | null) => void;
  setWritten: (result: WriteResult | null) => void;
  setError: (message: string | null) => void;
  setBusy: (label: string | null) => void;
  /** Run id whose results are ready but not yet opened. */
  finishedRunId: string | null;
  clearFinished: () => void;
  start: (runId: string) => void;
  cancel: () => Promise<void>;
}

let unwatch: (() => void) | null = null;

export const useRunSession = create<RunSession>((set, get) => ({
  projectPath: null,
  validation: null,
  written: null,
  run: null,
  log: [],
  error: null,
  busy: null,
  finishedRunId: null,

  setProject: (path) => {
    if (get().projectPath === path) return;
    // Everything shown belongs to one project, so switching clears it. A run
    // already going keeps running; it is simply no longer what is on screen.
    unwatch?.();
    unwatch = null;
    set({
      projectPath: path,
      validation: null,
      written: null,
      run: null,
      log: [],
      error: null,
      busy: null,
      finishedRunId: null,
    });
  },

  clearFinished: () => set({ finishedRunId: null }),

  setValidation: (validation) => set({ validation }),
  setWritten: (written) => set({ written }),
  setError: (error) => set({ error }),
  setBusy: (busy) => set({ busy }),

  start: (runId) => {
    unwatch?.();
    // A placeholder state so the output panel appears at once, rather than
    // when the first message happens to arrive.
    set({
      log: [],
      error: null,
      finishedRunId: null,
      run: {
        runId,
        engine: "",
        label: null,
        state: "queued",
        exitCode: null,
        message: null,
        hasResults: false,
        workdir: "",
        progress: null,
      },
    });

    unwatch = watchRun(runId, {
      onState: (state) => {
        set({ run: state });
        if (TERMINAL_STATES.has(state.state)) {
          void finish(state, set);
        }
      },
      onProgress: (progress) => {
        if (progress.kind === "log") {
          set((current) => ({
            log: [...current.log, progress.message].slice(-LOG_LIMIT),
          }));
          return;
        }
        set((current) =>
          current.run
            ? {
                run: {
                  ...current.run,
                  progress: {
                    kper: progress.kper,
                    kstp: progress.kstp,
                    phase: progress.phase,
                    fraction: current.run.progress?.fraction ?? null,
                    warnings: current.run.progress?.warnings ?? [],
                  },
                },
              }
            : current,
        );
      },
    });
  },

  cancel: async () => {
    const { run } = get();
    if (!run) return;
    try {
      set({ run: await runs.cancel(run.runId) });
    } catch (problem) {
      set({ error: (problem as Error).message });
    }
  },
}));

async function finish(state: RunState, set: (partial: Partial<RunSession>) => void): Promise<void> {
  try {
    // Collect even a failed run: partial output is usually the most useful
    // thing to look at when a model dies partway.
    await runs.collect(state.runId);
    set({ finishedRunId: state.runId });
  } catch (problem) {
    set({ error: (problem as Error).message });
  }
}
