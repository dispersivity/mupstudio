import { useEffect, useState } from "react";
import { detectWebGPU, type GpuSupport } from "@/lib/webgpu";
import { UnsupportedPage } from "./UnsupportedPage";

type Health = { status: string; version: string };

/**
 * M0 shell: prove the browser can run the viewport and that the backend the
 * frontend was served from is reachable. Replaced by the real app shell in M1.
 */
export function App() {
  const [support, setSupport] = useState<GpuSupport | null>(null);
  const [health, setHealth] = useState<Health | "unreachable" | null>(null);

  useEffect(() => {
    detectWebGPU().then(setSupport);
  }, []);

  useEffect(() => {
    fetch("/api/v1/health")
      .then((response) => (response.ok ? response.json() : Promise.reject(response.status)))
      .then(setHealth)
      .catch(() => setHealth("unreachable"));
  }, []);

  if (support === null) {
    return <Centered>Checking GPU support…</Centered>;
  }

  if (!support.supported) {
    return <UnsupportedPage support={support} />;
  }

  return (
    <Centered>
      <div className="space-y-3 text-center">
        <h1 className="text-2xl font-semibold text-zinc-900 dark:text-zinc-50">MUP Studio</h1>
        <dl className="space-y-1 text-sm text-zinc-600 dark:text-zinc-400">
          <Row label="WebGPU" value={support.adapterInfo?.vendor || "adapter ready"} />
          <Row
            label="Backend"
            value={
              health === null
                ? "connecting…"
                : health === "unreachable"
                  ? "unreachable"
                  : `v${health.version}`
            }
          />
        </dl>
      </div>
    </Centered>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-center gap-2">
      <dt className="text-zinc-500">{label}</dt>
      <dd data-testid={`status-${label.toLowerCase()}`}>{value}</dd>
    </div>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <main className="flex min-h-full items-center justify-center bg-white p-8 text-zinc-600 dark:bg-zinc-900 dark:text-zinc-400">
      {children}
    </main>
  );
}
