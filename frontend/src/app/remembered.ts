import type { StepId } from "./workflow";
import { STEP_BY_ID } from "./workflow";

/**
 * The little that should survive a page reload.
 *
 * Building a model means reloading constantly — after a save, after a restart,
 * after a stray refresh. Coming back to a closed project on a step you were not
 * on makes every reload feel like starting over, and the fix is two strings in
 * local storage.
 *
 * Deliberately not the model. What is on disk is the model; this is only where
 * you were looking at it from.
 */

const STEP_KEY = "mupstudio.step";
const PROJECT_KEY = "mupstudio.project";

function read(key: string): string | null {
  try {
    return globalThis.localStorage.getItem(key);
  } catch {
    // Private browsing and some embedded webviews refuse storage outright.
    // Forgetting where you were is a small loss; failing to start is not.
    return null;
  }
}

function write(key: string, value: string | null): void {
  try {
    if (value === null) globalThis.localStorage.removeItem(key);
    else globalThis.localStorage.setItem(key, value);
  } catch {
    // As above: nothing here is worth failing over.
  }
}

export const remembered = {
  /** The step to open on. Project, for a first visit or a forgotten one. */
  step(): StepId {
    const saved = read(STEP_KEY);
    return saved && STEP_BY_ID.has(saved as StepId) ? (saved as StepId) : "project";
  },

  setStep(step: StepId): void {
    write(STEP_KEY, step);
  },

  /** The project that was open, by path. */
  project(): string | null {
    return read(PROJECT_KEY);
  },

  setProject(path: string | null): void {
    write(PROJECT_KEY, path);
  },
};
