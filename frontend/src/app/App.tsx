import { useEffect, useState } from "react";
import { detectWebGPU, type GpuSupport } from "@/lib/webgpu";
import { AppShell } from "./AppShell";
import { PerfPage } from "@/perf/PerfPage";
import { UnsupportedPage } from "./UnsupportedPage";

/** Grid size comes from the URL, which is how the perf harness scales it. */
function settingsFromQuery() {
  const params = new URLSearchParams(location.search);
  const read = (key: string, fallback: number) => {
    const value = Number(params.get(key));
    return Number.isFinite(value) && value > 0 ? value : fallback;
  };
  return {
    perf: params.get("perf") === "1",
    ncpl: read("ncpl", 20_000),
    nlay: read("nlay", 6),
    ntimes: read("ntimes", 40),
    frames: read("frames", 600),
  };
}

export function App() {
  const [support, setSupport] = useState<GpuSupport | null>(null);
  const [settings] = useState(settingsFromQuery);

  useEffect(() => {
    detectWebGPU().then(setSupport);
  }, []);

  if (support === null) {
    return <Centered>Checking GPU support…</Centered>;
  }

  if (!support.supported) {
    return <UnsupportedPage support={support} />;
  }

  if (settings.perf) {
    return (
      <PerfPage
        ncpl={settings.ncpl}
        nlay={settings.nlay}
        ntimes={settings.ntimes}
        frames={settings.frames}
      />
    );
  }

  return <AppShell ncpl={settings.ncpl} nlay={settings.nlay} ntimes={settings.ntimes} />;
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <main className="flex min-h-full items-center justify-center bg-white p-8 text-zinc-600 dark:bg-zinc-900 dark:text-zinc-400">
      {children}
    </main>
  );
}
