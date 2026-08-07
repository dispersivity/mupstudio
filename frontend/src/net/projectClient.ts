/** REST calls for projects and runs. */

export interface ProjectSummary {
  path: string;
  name: string;
  engine: string;
  exists: boolean;
  lastOpened: string | null;
}

export interface ProjectDetail {
  name: string;
  engine: string;
  description: string;
  summary: string;
  lengthUnit: string;
  timeUnit: string;
  grid: { kind: string; nlay: number; nrow: number | null; ncol: number | null; ncells: number };
  time: { nper: number; total: number; periods: { perlen: number; nstp: number }[] };
  boundaries: { id: string; kind: string }[];
  transport: { advection: string; dispersion: boolean; dualPorosity: boolean };
}

export interface ValidationResult {
  ok: boolean;
  errors: string[];
  warnings: string[];
  cells?: number;
  boundaries?: { id: string; kind: string; cells: number }[];
}

export interface WriteResult {
  workdir: string;
  files: string[];
  warnings: string[];
}

export interface RunState {
  runId: string;
  engine: string;
  label: string | null;
  state: "queued" | "running" | "succeeded" | "failed" | "cancelled" | "unknown";
  exitCode: number | null;
  message: string | null;
  hasResults: boolean;
  workdir: string;
  progress: {
    kper: number | null;
    kstp: number | null;
    phase: string;
    fraction: number | null;
    warnings: string[];
  } | null;
}

export const TERMINAL_STATES = new Set(["succeeded", "failed", "cancelled", "unknown"]);

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/v1${path}`, init);
  if (!response.ok) {
    // FastAPI reports the reason in `detail`; surfacing it beats a bare status.
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `${init?.method ?? "GET"} ${path} failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

function json(body: unknown): RequestInit {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

export const projects = {
  list: () => request<{ projects: ProjectSummary[] }>("/projects"),

  create: (body: { name: string; engine: string; parent?: string }) =>
    request<{ project: ProjectSummary; detail: ProjectDetail }>("/projects", json(body)),

  open: (path: string) =>
    request<{ project: ProjectSummary; detail: ProjectDetail }>("/projects/open", json({ path })),

  forget: (path: string) =>
    request<{ status: string }>(`/projects?path=${encodeURIComponent(path)}`, {
      method: "DELETE",
    }),

  detail: (path: string) =>
    request<ProjectDetail>(`/projects/detail?path=${encodeURIComponent(path)}`),

  validate: (path: string) =>
    request<ValidationResult>(`/projects/validate?path=${encodeURIComponent(path)}`, {
      method: "POST",
    }),

  write: (path: string) =>
    request<WriteResult>(`/projects/write?path=${encodeURIComponent(path)}`, { method: "POST" }),

  file: (path: string, name: string) =>
    request<{ name: string; bytes: number; truncated: boolean; content: string }>(
      `/projects/file?path=${encodeURIComponent(path)}&name=${encodeURIComponent(name)}`,
    ),

  run: (path: string) =>
    request<{ runId: string; workdir: string; files: string[]; warnings: string[] }>(
      `/projects/run?path=${encodeURIComponent(path)}`,
      { method: "POST" },
    ),
};

export const runs = {
  status: (runId: string) => request<RunState>(`/runs/${runId}`),

  log: (runId: string) => request<{ lines: string[]; truncated?: boolean }>(`/runs/${runId}/log`),

  cancel: (runId: string) => request<RunState>(`/runs/${runId}/cancel`, { method: "POST" }),

  collect: (runId: string) =>
    request<{ components: string[]; times: number; cells: number; warnings: string[] }>(
      `/runs/${runId}/collect`,
      { method: "POST" },
    ),
};

/**
 * Watch a run until it ends.
 *
 * A websocket rather than polling: a reactive run reports per timestep, and the
 * socket also sends current state on connect so a late subscriber is not blank.
 */
export function watchRun(
  runId: string,
  handlers: {
    onState?: (state: RunState) => void;
    /** Every engine output line arrives as kind "log"; parsed events as the rest. */
    onProgress?: (progress: {
      kind: "step" | "finished" | "failed" | "warning" | "log";
      kper: number | null;
      kstp: number | null;
      phase: string;
      message: string;
    }) => void;
    onClose?: () => void;
  },
): () => void {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const socket = new WebSocket(`${protocol}//${location.host}/api/v1/ws/runs/${runId}`);

  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data as string);
    if (message.op === "state") handlers.onState?.(message as RunState);
    else if (message.op === "progress") handlers.onProgress?.(message);
  });
  socket.addEventListener("close", () => handlers.onClose?.());

  return () => socket.close();
}
