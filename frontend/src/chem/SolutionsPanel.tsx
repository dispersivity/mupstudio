import { useMemo } from "react";
import type { DatabaseIndex } from "./database";
import { uniqueId } from "./edits";
import { allSpecies } from "./database";
import { Empty } from "./Empty";
import { AddFromDatabase, Cell, RowButton } from "./pickers";

/* eslint-disable @typescript-eslint/no-explicit-any */
type Chemistry = Record<string, any>;
type Solution = Record<string, any>;

const EMPTY: Solution[] = [];

/**
 * Solutions as a spreadsheet: species down, waters across.
 *
 * Cards per solution would be the obvious layout and the wrong one. The tasks
 * here are comparing one species across every water and pasting a block from
 * Excel, and a table is what makes both possible. It is also how the analyses
 * arrive in the first place.
 */
export function SolutionsPanel({
  chemistry,
  index,
  edit,
}: {
  chemistry: Chemistry;
  index: DatabaseIndex | null;
  edit: (change: (draft: Chemistry) => void) => void;
}) {
  // Read once: `chemistry.solutions ?? []` would be a fresh array on every
  // render, and the memo below keys on it.
  const solutions: Solution[] = chemistry.solutions ?? EMPTY;

  // Every species any solution mentions becomes a row, so a value entered for
  // one water leaves a visible blank in the others rather than hiding.
  const species = useMemo(() => {
    const seen = new Set<string>();
    for (const solution of solutions) {
      for (const name of Object.keys(solution.concentrations ?? {})) seen.add(name);
    }
    return [...seen].sort();
  }, [solutions]);

  const addSolution = () =>
    edit((draft) => {
      const id = uniqueId(
        "water",
        draft.solutions.map((item: Solution) => item.id),
      );
      draft.solutions.push({
        id,
        label: "",
        ph: 7,
        pe: 4,
        temperature: 25,
        units: "mol/kgw",
        concentrations: Object.fromEntries(species.map((name) => [name, 0])),
        charge_balance: null,
      });
    });

  if (solutions.length === 0) {
    return (
      <Empty
        message="No solutions yet. A reactive model needs at least one water: the pore water the model starts with."
        action="Add a solution"
        onAction={addSolution}
      />
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <AddFromDatabase
          label="Add a species"
          placeholder="Add a species…"
          options={allSpecies(index)}
          chosen={species}
          onAdd={(name) =>
            edit((draft) => {
              for (const solution of draft.solutions) {
                solution.concentrations[name] = solution.concentrations[name] ?? 0;
              }
            })
          }
        />
        <RowButton onClick={addSolution} title="Add a solution">
          + solution
        </RowButton>
        <span className="text-[10px] text-zinc-600">
          Concentrations in mol/kgw unless the row says otherwise. Zero is a value; a species you do
          not want is removed, not zeroed.
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="text-[11px]">
          <thead>
            <tr>
              <th className="sticky left-0 z-10 bg-zinc-950 pb-1 pr-3 text-left text-[10px] uppercase tracking-wider text-zinc-600">
                Species
              </th>
              {solutions.map((solution, column) => (
                <th key={solution.id} className="min-w-32 px-1 pb-1 text-left">
                  <input
                    value={solution.id}
                    aria-label={`Name of solution ${column + 1}`}
                    onChange={(event) =>
                      edit((draft) => {
                        renameSolution(draft, column, event.target.value);
                      })
                    }
                    className="w-full rounded border border-transparent bg-transparent px-1 py-0.5 font-mono text-[11px] text-zinc-100 hover:border-zinc-700 focus:border-sky-600 focus:outline-none"
                  />
                  <input
                    value={solution.label ?? ""}
                    placeholder="description"
                    aria-label={`Description of ${solution.id}`}
                    onChange={(event) =>
                      edit((draft) => {
                        draft.solutions[column].label = event.target.value;
                      })
                    }
                    className="w-full rounded border border-transparent bg-transparent px-1 text-[10px] font-normal text-zinc-500 hover:border-zinc-800 focus:border-sky-600 focus:outline-none"
                  />
                </th>
              ))}
              <th className="pb-1" />
            </tr>
          </thead>

          <tbody>
            <MetaRow
              label="pH"
              field="ph"
              solutions={solutions}
              edit={edit}
              hint="Set by the water, or adjusted to balance charge."
            />
            <MetaRow
              label="pe"
              field="pe"
              solutions={solutions}
              edit={edit}
              hint="Redox potential as an electron activity."
            />
            <MetaRow
              label="Temperature"
              field="temperature"
              solutions={solutions}
              edit={edit}
              hint="Degrees Celsius."
            />

            <tr>
              <td className="sticky left-0 z-10 bg-zinc-950 py-1 pr-3 text-[10px] text-zinc-500">
                Charge balance
              </td>
              {solutions.map((solution, column) => (
                <td key={solution.id} className="px-1">
                  <select
                    value={solution.charge_balance ?? ""}
                    aria-label={`Charge balance for ${solution.id}`}
                    onChange={(event) =>
                      edit((draft) => {
                        draft.solutions[column].charge_balance = event.target.value || null;
                      })
                    }
                    className="w-full rounded border border-transparent bg-zinc-900/60 px-1 py-1 text-[10px] text-zinc-300 hover:border-zinc-700 focus:border-sky-600 focus:outline-none"
                  >
                    <option value="">none</option>
                    {Object.keys(solution.concentrations ?? {})
                      .sort()
                      .map((name) => (
                        <option key={name} value={name}>
                          {name}
                        </option>
                      ))}
                  </select>
                </td>
              ))}
              <td />
            </tr>

            <tr>
              <td colSpan={solutions.length + 2} className="pt-3">
                <span className="text-[10px] uppercase tracking-wider text-zinc-600">
                  Concentrations
                </span>
              </td>
            </tr>

            {species.map((name) => (
              <tr key={name} className="hover:bg-zinc-900/40">
                <td className="sticky left-0 z-10 bg-zinc-950 py-0.5 pr-3 font-mono text-zinc-300">
                  {name}
                </td>
                {solutions.map((solution, column) => (
                  <td key={solution.id} className="px-1">
                    <Cell
                      value={solution.concentrations?.[name] ?? null}
                      label={`${name} in ${solution.id}`}
                      onCommit={(value) =>
                        edit((draft) => {
                          draft.solutions[column].concentrations[name] = value;
                        })
                      }
                    />
                  </td>
                ))}
                <td className="pl-1">
                  <RowButton
                    danger
                    title={`Remove ${name} from every solution`}
                    onClick={() =>
                      edit((draft) => {
                        for (const solution of draft.solutions) {
                          delete solution.concentrations[name];
                          if (solution.charge_balance === name) solution.charge_balance = null;
                        }
                      })
                    }
                  >
                    ×
                  </RowButton>
                </td>
              </tr>
            ))}

            {species.length === 0 && (
              <tr>
                <td
                  colSpan={solutions.length + 2}
                  className="py-2 text-[11px] leading-relaxed text-zinc-600"
                >
                  No species yet. Add the ones the analysis reports; the database above says which
                  names it knows.
                </td>
              </tr>
            )}

            <tr>
              <td className="sticky left-0 z-10 bg-zinc-950 pt-2" />
              {solutions.map((solution, column) => (
                <td key={solution.id} className="px-1 pt-2 text-center">
                  <RowButton
                    danger
                    title={`Delete solution ${solution.id}`}
                    onClick={() =>
                      edit((draft) => {
                        removeSolution(draft, column);
                      })
                    }
                  >
                    delete
                  </RowButton>
                </td>
              ))}
              <td />
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}

function MetaRow({
  label,
  field,
  solutions,
  edit,
  hint,
}: {
  label: string;
  field: string;
  solutions: Solution[];
  edit: (change: (draft: Chemistry) => void) => void;
  hint: string;
}) {
  return (
    <tr className="hover:bg-zinc-900/40">
      <td className="sticky left-0 z-10 bg-zinc-950 py-0.5 pr-3 text-zinc-300" title={hint}>
        {label}
      </td>
      {solutions.map((solution, column) => (
        <td key={solution.id} className="px-1">
          <Cell
            value={solution[field] ?? null}
            label={`${label} of ${solution.id}`}
            onCommit={(value) =>
              edit((draft) => {
                draft.solutions[column][field] = value;
              })
            }
          />
        </td>
      ))}
      <td />
    </tr>
  );
}

/**
 * Renaming a solution carries every reference with it.
 *
 * Compositions and boundaries point at solutions by name, so a rename that left
 * them behind would break the project the moment it was saved. Doing it here
 * rather than warning about it is what makes the name feel like a label.
 */
function renameSolution(draft: Chemistry, column: number, next: string): void {
  const previous = draft.solutions[column].id;
  draft.solutions[column].id = next;
  if (previous === next) return;

  for (const composition of draft.compositions ?? []) {
    if (composition.solution === previous) composition.solution = next;
  }
  for (const assemblage of [...(draft.exchange ?? []), ...(draft.surface ?? [])]) {
    if (assemblage.equilibrate_with === previous) assemblage.equilibrate_with = next;
  }
  for (const [pack, solution] of Object.entries(draft.boundary_solutions ?? {})) {
    if (solution === previous) draft.boundary_solutions[pack] = next;
  }
}

/** Deleting drops the references too, rather than leaving them dangling. */
function removeSolution(draft: Chemistry, column: number): void {
  const [removed] = draft.solutions.splice(column, 1);

  draft.compositions = (draft.compositions ?? []).filter(
    (composition: Record<string, unknown>) => composition.solution !== removed.id,
  );
  const survivors = new Set(draft.compositions.map((item: { id: string }) => item.id));
  draft.zones = (draft.zones ?? []).filter((zone: { composition: string }) =>
    survivors.has(zone.composition),
  );
  if (!survivors.has(draft.background)) draft.background = draft.compositions[0]?.id ?? null;

  for (const assemblage of [...(draft.exchange ?? []), ...(draft.surface ?? [])]) {
    if (assemblage.equilibrate_with === removed.id) assemblage.equilibrate_with = null;
  }
  for (const [pack, solution] of Object.entries(draft.boundary_solutions ?? {})) {
    if (solution === removed.id) delete draft.boundary_solutions[pack];
  }
}
