import { useState } from "react";
import {
  ExchangePanel,
  GasesPanel,
  KineticsPanel,
  MineralsPanel,
  SurfacePanel,
} from "@/chem/AssemblagePanels";
import { useChemistryCheck, useDatabaseIndex, useDatabaseList } from "@/chem/database";
import { DatabasePanel } from "@/chem/DatabasePanel";
import { SolutionsPanel } from "@/chem/SolutionsPanel";
import { BoundaryPanel, OutputPanel, ZonesPanel } from "@/chem/ZonesPanel";
import { EditorShell, NoProject } from "./editor/controls";
import { cellCount, gridLimits } from "./editor/grid";
import { useProjectDocument } from "./editor/useProjectDocument";

type Tab =
  | "database"
  | "solutions"
  | "minerals"
  | "exchange"
  | "surface"
  | "kinetics"
  | "gases"
  | "zones"
  | "boundaries"
  | "output";

const TABS: { id: Tab; label: string }[] = [
  { id: "database", label: "Database" },
  { id: "solutions", label: "Solutions" },
  { id: "minerals", label: "Minerals" },
  { id: "exchange", label: "Exchange" },
  { id: "surface", label: "Surface" },
  { id: "kinetics", label: "Kinetics" },
  { id: "gases", label: "Gases" },
  { id: "zones", label: "Zones" },
  { id: "boundaries", label: "Boundaries" },
  { id: "output", label: "Output" },
];

/**
 * The chemistry a reactive model runs.
 *
 * Split into tabs because the parts are edited at different times and by
 * different reasoning: the database is chosen once, solutions come from
 * analyses, assemblages from what the aquifer is made of, and zones say where
 * each applies. Keeping them on one screen would mean scrolling past nine
 * tables to change a pH.
 *
 * Everything is checked against the selected database as it is edited, because
 * a species the database does not have is a failure three minutes into a run
 * otherwise.
 */
export function ChemistryStep({
  path,
  onGoToProject,
  onSaved,
}: {
  path: string | null;
  onGoToProject: () => void;
  onSaved: () => void;
}) {
  const editor = useProjectDocument(path);
  const [tab, setTab] = useState<Tab>("solutions");

  const chemistry = editor.document?.chemistry ?? null;
  const enabled = Boolean(chemistry?.enabled);
  const databaseName = chemistry?.database?.name ?? "phreeqc.dat";

  const { databases } = useDatabaseList();
  const { index, loading, error } = useDatabaseIndex(enabled ? databaseName : null);
  const check = useChemistryCheck(chemistry, enabled);

  if (!path) return <NoProject onGo={onGoToProject} />;
  if (!editor.document || !chemistry) {
    return <div className="p-6 text-xs text-zinc-500">Loading…</div>;
  }

  const grid = editor.document.grid;
  const limits = gridLimits(grid);
  const cells = cellCount(grid);
  const times = (editor.document.time.periods as { nstp: number }[]).reduce(
    (total, period) => total + period.nstp,
    0,
  );
  const packages = (editor.document.flow.packages ?? []) as { id: string; kind: string }[];

  const edit = (change: (draft: Record<string, unknown>) => void) =>
    editor.edit((draft) => change(draft.chemistry));

  return (
    <EditorShell
      title="Chemistry"
      blurb="What is in the water, what it can react with, and where. Every name here has to exist in the selected PHREEQC database, so the tables only offer what it holds."
      dirty={editor.dirty}
      saving={editor.saving}
      problems={editor.problems}
      error={editor.error}
      savedSummary={editor.savedSummary}
      onSave={async () => {
        if (await editor.save()) onSaved();
      }}
      onRevert={() => void editor.reload()}
    >
      <label className="mb-4 flex items-center gap-2 text-xs text-zinc-300">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(event) =>
            editor.edit((draft) => {
              draft.chemistry.enabled = event.target.checked;
            })
          }
          className="accent-sky-600"
        />
        Run this model reactively
        <span className="text-[10px] text-zinc-600">
          Off, the model transports a conservative tracer and the chemistry is kept but not written.
        </span>
      </label>

      {!enabled ? (
        <p className="max-w-xl text-[11px] leading-relaxed text-zinc-500">
          Chemistry is off. Turn it on to define the waters and the solids they react with; the
          model will run through PHREEQC instead of transporting a single tracer.
        </p>
      ) : (
        <>
          <nav className="mb-4 flex flex-wrap gap-1 border-b border-zinc-800 pb-2">
            {TABS.map((entry) => (
              <button
                key={entry.id}
                type="button"
                onClick={() => setTab(entry.id)}
                className={`rounded px-2 py-1 text-[11px] ${
                  tab === entry.id
                    ? "bg-zinc-800 text-zinc-100"
                    : "text-zinc-500 hover:text-zinc-300"
                }`}
              >
                {entry.label}
                <Count tab={entry.id} chemistry={chemistry} />
              </button>
            ))}
          </nav>

          {check && check.problems.length > 0 && (
            <ul className="mb-4 space-y-0.5 rounded border border-zinc-800 bg-zinc-900/40 p-2">
              {check.problems.slice(0, 12).map((problem, position) => (
                <li
                  key={position}
                  className={`text-[11px] ${
                    problem.severity === "error" ? "text-red-300" : "text-amber-300"
                  }`}
                >
                  <span className="text-zinc-500">{problem.where}:</span> {problem.message}
                  {problem.suggestion && (
                    <span className="text-zinc-500"> Did you mean {problem.suggestion}?</span>
                  )}
                </li>
              ))}
              {check.problems.length > 12 && (
                <li className="text-[10px] text-zinc-600">and {check.problems.length - 12} more</li>
              )}
            </ul>
          )}

          {tab === "database" && (
            <DatabasePanel
              databases={databases}
              index={index}
              selected={databaseName}
              loading={loading}
              error={error}
              onSelect={(name) =>
                editor.edit((draft) => {
                  draft.chemistry.database = { name, path: null, sha256: null };
                })
              }
            />
          )}
          {tab === "solutions" && (
            <SolutionsPanel chemistry={chemistry} index={index} edit={edit} />
          )}
          {tab === "minerals" && <MineralsPanel chemistry={chemistry} index={index} edit={edit} />}
          {tab === "exchange" && <ExchangePanel chemistry={chemistry} index={index} edit={edit} />}
          {tab === "surface" && <SurfacePanel chemistry={chemistry} index={index} edit={edit} />}
          {tab === "kinetics" && <KineticsPanel chemistry={chemistry} index={index} edit={edit} />}
          {tab === "gases" && <GasesPanel chemistry={chemistry} index={index} edit={edit} />}
          {tab === "zones" && <ZonesPanel chemistry={chemistry} limits={limits} edit={edit} />}
          {tab === "boundaries" && (
            <BoundaryPanel chemistry={chemistry} packages={packages} edit={edit} />
          )}
          {tab === "output" && (
            <OutputPanel
              chemistry={chemistry}
              index={index}
              cells={cells}
              times={times}
              edit={edit}
            />
          )}
        </>
      )}
    </EditorShell>
  );
}

/** How many things a tab holds, so an empty one is visible without opening it. */
function Count({ tab, chemistry }: { tab: Tab; chemistry: Record<string, unknown> }) {
  const lists: Partial<Record<Tab, string>> = {
    solutions: "solutions",
    minerals: "equilibrium_phases",
    exchange: "exchange",
    surface: "surface",
    kinetics: "kinetics",
    gases: "gas_phases",
    zones: "compositions",
  };

  const key = lists[tab];
  if (!key) return null;
  const total = (chemistry[key] as unknown[] | undefined)?.length ?? 0;
  if (total === 0) return null;

  return <span className="ml-1 text-[9px] text-zinc-600">{total}</span>;
}
