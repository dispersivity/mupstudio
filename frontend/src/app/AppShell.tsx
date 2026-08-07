import { useEffect, useState } from "react";
import { ViewportHost } from "@/viewport-host/ViewportHost";
import { fetchDatasetListing } from "@/net/viewportClient";
import { projects } from "@/net/projectClient";
import type { DatasetListing } from "@/results/DatasetPicker";
import { ProjectStep, type ActiveProject } from "@/pages/ProjectStep";
import { GridStep } from "@/pages/GridStep";
import { TimeStep } from "@/pages/TimeStep";
import { FlowStep } from "@/pages/FlowStep";
import { ChemistryStep } from "@/pages/ChemistryStep";
import { TransportStep } from "@/pages/TransportStep";
import { SimulateStep } from "@/pages/SimulateStep";
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
  const [project, setProject] = useState<ActiveProject | null>(null);

  const refreshDatasets = () =>
    fetchDatasetListing()
      .then(setListing)
      .catch(() => setListing(null));

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

  const open = project !== null;
  const statuses: Partial<Record<StepId, StepStatus>> = {
    project: open ? "complete" : "empty",
    grid: open ? "complete" : "locked",
    time: open ? "complete" : "locked",
    flow: open ? (project.detail.boundaries.length > 0 ? "complete" : "partial") : "locked",
    transport: open ? "complete" : "locked",
    simulate: open ? "partial" : "locked",
    results: "complete",
  };

  // The Project step's summary is stale after an edit elsewhere, so it is
  // refetched rather than left showing the old grid or period count.
  const refreshProject = async () => {
    if (!project) return;
    const detail = await projects.detail(project.summary.path).catch(() => null);
    if (detail) setProject({ ...project, detail });
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
        <TopBar
          step={active}
          datasetId={datasetId}
          listing={listing}
          projectName={project?.detail.name ?? null}
        />

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
            ) : active === "project" ? (
              <ProjectStep active={project} onOpen={setProject} />
            ) : active === "grid" ? (
              <GridStep
                path={project?.summary.path ?? null}
                onGoToProject={() => setActive("project")}
                onSaved={refreshProject}
              />
            ) : active === "time" ? (
              <TimeStep
                path={project?.summary.path ?? null}
                onGoToProject={() => setActive("project")}
                onSaved={refreshProject}
              />
            ) : active === "flow" ? (
              <FlowStep
                path={project?.summary.path ?? null}
                onGoToProject={() => setActive("project")}
                onSaved={refreshProject}
              />
            ) : active === "transport" ? (
              <TransportStep
                path={project?.summary.path ?? null}
                onGoToProject={() => setActive("project")}
                onSaved={refreshProject}
              />
            ) : active === "chemistry" ? (
              <ChemistryStep
                path={project?.summary.path ?? null}
                onGoToProject={() => setActive("project")}
                onSaved={refreshProject}
              />
            ) : active === "simulate" ? (
              <SimulateStep
                project={project}
                onGoToProject={() => setActive("project")}
                onFinished={(runId) => {
                  // Show the run that just finished, so a completed model is
                  // one click from the picture of it.
                  void refreshDatasets();
                  setDatasetId(runId);
                  setActive("results");
                }}
              />
            ) : (
              <StepPlaceholder step={active} onGoToResults={() => setActive("results")} />
            )}
          </main>

          {/* Only the results view puts its controls here. The builder steps
              carry their own column beside their viewport, so an empty pane
              would just be 320px of nothing next to a form that needs room. */}
          {active === "results" && inspector && (
            <aside className="hidden w-72 shrink-0 border-l border-zinc-800 bg-zinc-900 lg:block xl:w-80">
              {inspector}
            </aside>
          )}
        </div>
      </div>
    </div>
  );
}

function TopBar({
  step,
  datasetId,
  listing,
  projectName,
}: {
  step: StepId;
  datasetId: string;
  listing: DatasetListing | null;
  projectName: string | null;
}) {
  const run = listing?.runs.find((entry) => entry.id === datasetId);
  const showing = datasetId === "demo" ? "Synthetic demo" : (run?.label ?? datasetId);

  return (
    <header className="flex h-12 shrink-0 items-center justify-between border-b border-zinc-800 bg-zinc-900 px-4">
      <div className="flex items-center gap-3">
        <span className="text-sm font-medium capitalize text-zinc-100">{step}</span>
        {projectName && <span className="text-xs text-zinc-500">{projectName}</span>}
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
