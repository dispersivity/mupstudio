import { useEffect, useState } from "react";
import { ViewportHost } from "@/viewport-host/ViewportHost";
import { fetchDatasetListing } from "@/net/viewportClient";
import type { DatasetListing } from "@/results/DatasetPicker";
import { StepPlaceholder } from "./StepPlaceholder";
import { WorkflowRail } from "./WorkflowRail";
import { IMPLEMENTED, type StepId, type StepStatus } from "./workflow";

export interface AppShellProps {
  ncpl: number;
  nlay: number;
  ntimes: number;
}

/**
 * The application frame: rail on the left, work area in the middle, whatever
 * the active step wants to put in the inspector on the right.
 *
 * The Results step mounts the viewport, which supplies its own inspector
 * contents. Steps that do not exist yet say so.
 */
export function AppShell({ ncpl, nlay, ntimes }: AppShellProps) {
  const [active, setActive] = useState<StepId>("results");
  const [railExpanded, setRailExpanded] = useState(true);
  const [inspector, setInspector] = useState<React.ReactNode>(null);
  const [listing, setListing] = useState<DatasetListing | null>(null);
  const [datasetId, setDatasetId] = useState("demo");

  // Prefer a real run over the synthetic demo when one is available: seeing
  // your own model beats seeing a fabricated one.
  useEffect(() => {
    fetchDatasetListing()
      .then((found) => {
        setListing(found);
        const usable = found.runs.find((run) => run.hasResults);
        if (usable) setDatasetId((current) => (current === "demo" ? usable.id : current));
      })
      .catch(() => setListing(null));
  }, []);

  // Only Results has data behind it today; the rest are honestly empty.
  const statuses: Partial<Record<StepId, StepStatus>> = {
    results: "complete",
  };

  return (
    <div className="flex h-full w-full bg-zinc-950 text-zinc-200">
      <WorkflowRail
        active={active}
        statuses={statuses}
        expanded={railExpanded}
        onSelect={setActive}
        onToggleExpanded={() => setRailExpanded((value) => !value)}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar step={active} datasetId={datasetId} listing={listing} />

        <div className="flex min-h-0 flex-1">
          <main className="min-w-0 flex-1">
            {active === "results" ? (
              <ViewportHost
                datasetId={datasetId}
                ncpl={ncpl}
                nlay={nlay}
                ntimes={ntimes}
                onInspector={setInspector}
                listing={listing}
                onSelectDataset={setDatasetId}
              />
            ) : (
              <StepPlaceholder step={active} onGoToResults={() => setActive("results")} />
            )}
          </main>

          <aside className="hidden w-72 shrink-0 border-l border-zinc-800 bg-zinc-900 lg:block xl:w-80">
            {active === "results" && inspector ? (
              inspector
            ) : (
              <div className="p-4 text-xs text-zinc-600">
                Nothing to configure on this step yet.
              </div>
            )}
          </aside>
        </div>
      </div>
    </div>
  );
}

function TopBar({
  step,
  datasetId,
  listing,
}: {
  step: StepId;
  datasetId: string;
  listing: DatasetListing | null;
}) {
  const run = listing?.runs.find((entry) => entry.id === datasetId);
  const showing = datasetId === "demo" ? "Synthetic demo" : (run?.label ?? datasetId);

  return (
    <header className="flex h-12 shrink-0 items-center justify-between border-b border-zinc-800 bg-zinc-900 px-4">
      <div className="flex items-center gap-3">
        <span className="text-sm font-medium capitalize text-zinc-100">{step}</span>
        {!IMPLEMENTED.has(step) && (
          <span className="rounded bg-zinc-800 px-2 py-0.5 text-[10px] text-zinc-400">
            not built yet
          </span>
        )}
      </div>

      <div className="flex items-center gap-3 text-[10px]">
        <span className="text-zinc-400">{showing}</span>
        {datasetId === "demo" ? (
          <span className="rounded bg-amber-500/15 px-2 py-0.5 text-amber-300">demo data</span>
        ) : (
          <span className="rounded bg-emerald-500/15 px-2 py-0.5 text-emerald-300">
            {run?.engine ?? "run"}
          </span>
        )}
      </div>
    </header>
  );
}
