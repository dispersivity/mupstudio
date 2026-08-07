import { useEffect, useState } from "react";
import type { DatabaseIndex, RateDetail } from "./database";
import { fetchRate } from "./database";
import { AddFromDatabase, Cell, Chooser, RowButton } from "./pickers";
import { uniqueId } from "./edits";
import { Empty } from "./Empty";

/* eslint-disable @typescript-eslint/no-explicit-any */
type Chemistry = Record<string, any>;
type Edit = (change: (draft: Chemistry) => void) => void;

interface PanelProps {
  chemistry: Chemistry;
  index: DatabaseIndex | null;
  edit: Edit;
}

/**
 * The solid and sorbed phases a solution can react with.
 *
 * Each of these tabs edits one list of named assemblages. A cell gets one of
 * each through a composition, so the assemblage is the unit of reuse: "calcite
 * sand" is defined once and applied wherever that material is.
 */

/** A frame shared by the assemblage tabs: a list on the left, an editor per item. */
function AssemblageList({
  items,
  kind,
  onAdd,
  onRemove,
  onRename,
  hint,
  emptyMessage,
  children,
}: {
  items: { id: string; label?: string }[];
  kind: string;
  onAdd: () => void;
  onRemove: (index: number) => void;
  onRename: (index: number, name: string) => void;
  hint: string;
  emptyMessage: string;
  children: (item: any, index: number) => React.ReactNode;
}) {
  if (items.length === 0) {
    return <Empty message={emptyMessage} action={`Add ${kind}`} onAction={onAdd} />;
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <RowButton onClick={onAdd} title={`Add ${kind}`}>
          + {kind}
        </RowButton>
        <span className="max-w-2xl text-[10px] leading-relaxed text-zinc-600">{hint}</span>
      </div>

      {items.map((item, position) => (
        <div key={position} className="rounded border border-zinc-800 p-3">
          <div className="mb-2 flex items-center gap-2">
            <input
              value={item.id}
              aria-label={`Name of ${kind} ${position + 1}`}
              onChange={(event) => onRename(position, event.target.value)}
              className="w-40 rounded border border-transparent bg-transparent px-1 py-0.5 font-mono text-xs text-zinc-100 hover:border-zinc-700 focus:border-sky-600 focus:outline-none"
            />
            <span className="text-[10px] text-zinc-600">#{position + 1}</span>
            <div className="ml-auto">
              <RowButton danger title={`Delete ${item.id}`} onClick={() => onRemove(position)}>
                delete
              </RowButton>
            </div>
          </div>
          {children(item, position)}
        </div>
      ))}
    </div>
  );
}

/** Renaming an assemblage carries the compositions that point at it. */
function renameIn(draft: Chemistry, list: string, slot: string, position: number, next: string) {
  const previous = draft[list][position].id;
  draft[list][position].id = next;
  if (previous === next) return;
  for (const composition of draft.compositions ?? []) {
    if (composition[slot] === previous) composition[slot] = next;
  }
}

/** Deleting one clears it from the compositions rather than dangling. */
function removeFrom(draft: Chemistry, list: string, slot: string, position: number) {
  const [removed] = draft[list].splice(position, 1);
  for (const composition of draft.compositions ?? []) {
    if (composition[slot] === removed.id) composition[slot] = null;
  }
}

// --- Equilibrium phases -----------------------------------------------------

export function MineralsPanel({ chemistry, index, edit }: PanelProps) {
  const items = chemistry.equilibrium_phases ?? [];

  return (
    <AssemblageList
      items={items}
      kind="assemblage"
      hint="Minerals held at equilibrium every step. Zero moles is meaningful: the mineral can precipitate but there is none there to dissolve."
      emptyMessage="No mineral assemblages. Add one to let the water react with the solids it flows through."
      onAdd={() =>
        edit((draft) => {
          draft.equilibrium_phases.push({
            id: uniqueId(
              "minerals",
              draft.equilibrium_phases.map((item: any) => item.id),
            ),
            label: "",
            phases: [],
          });
        })
      }
      onRemove={(position) =>
        edit((draft) => removeFrom(draft, "equilibrium_phases", "equilibrium_phases", position))
      }
      onRename={(position, name) =>
        edit((draft) => renameIn(draft, "equilibrium_phases", "equilibrium_phases", position, name))
      }
    >
      {(item, position) => (
        <div className="space-y-2">
          <AddFromDatabase
            label="Add a mineral"
            placeholder="Add a mineral…"
            options={(index?.phases ?? []).map((phase) => phase.name)}
            chosen={item.phases.map((target: any) => target.phase)}
            onAdd={(phase) =>
              edit((draft) => {
                draft.equilibrium_phases[position].phases.push({
                  phase,
                  saturation_index: 0,
                  moles: 0,
                });
              })
            }
          />

          {item.phases.length > 0 && (
            <table className="text-[11px]">
              <thead>
                <tr className="text-left text-[10px] uppercase tracking-wider text-zinc-600">
                  <th className="pb-1 pr-4 font-medium">Mineral</th>
                  <th className="pb-1 pr-2 font-medium">Saturation index</th>
                  <th className="pb-1 pr-2 font-medium">Moles</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {item.phases.map((target: any, row: number) => (
                  <tr key={target.phase}>
                    <td className="py-0.5 pr-4 font-mono text-zinc-200">{target.phase}</td>
                    <td className="w-28 pr-2">
                      <Cell
                        value={target.saturation_index}
                        label={`Saturation index of ${target.phase}`}
                        onCommit={(value) =>
                          edit((draft) => {
                            draft.equilibrium_phases[position].phases[row].saturation_index = value;
                          })
                        }
                      />
                    </td>
                    <td className="w-28 pr-2">
                      <Cell
                        value={target.moles}
                        label={`Moles of ${target.phase}`}
                        onCommit={(value) =>
                          edit((draft) => {
                            draft.equilibrium_phases[position].phases[row].moles = value;
                          })
                        }
                      />
                    </td>
                    <td>
                      <RowButton
                        danger
                        title={`Remove ${target.phase}`}
                        onClick={() =>
                          edit((draft) => {
                            draft.equilibrium_phases[position].phases.splice(row, 1);
                          })
                        }
                      >
                        ×
                      </RowButton>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </AssemblageList>
  );
}

// --- Exchange ---------------------------------------------------------------

export function ExchangePanel({ chemistry, index, edit }: PanelProps) {
  const items = chemistry.exchange ?? [];
  const solutions = (chemistry.solutions ?? []).map((item: any) => ({
    id: item.id,
    label: item.label,
  }));

  return (
    <AssemblageList
      items={items}
      kind="exchanger"
      hint="Cation exchange capacity by site. Equilibrating with a solution fills the sites from that water rather than from the numbers given."
      emptyMessage="No exchangers. Add one where clays or organic matter hold exchangeable cations."
      onAdd={() =>
        edit((draft) => {
          draft.exchange.push({
            id: uniqueId(
              "exchanger",
              draft.exchange.map((item: any) => item.id),
            ),
            label: "",
            sites: {},
            equilibrate_with: draft.solutions[0]?.id ?? null,
          });
        })
      }
      onRemove={(position) => edit((draft) => removeFrom(draft, "exchange", "exchange", position))}
      onRename={(position, name) =>
        edit((draft) => renameIn(draft, "exchange", "exchange", position, name))
      }
    >
      {(item, position) => (
        <div className="space-y-2">
          <div className="flex flex-wrap items-end gap-3">
            <AddFromDatabase
              label="Add an exchange site"
              placeholder="Add a site…"
              options={[...(index?.exchangeSites ?? []), ...(index?.exchangeSpecies ?? [])]}
              chosen={Object.keys(item.sites)}
              onAdd={(site) =>
                edit((draft) => {
                  draft.exchange[position].sites[site] = 0;
                })
              }
            />
            <label className="block w-56">
              <span className="mb-1 block text-[10px] text-zinc-500">Equilibrate with</span>
              <Chooser
                label={`Equilibrating solution for ${item.id}`}
                value={item.equilibrate_with}
                options={solutions}
                allowNone
                noneLabel="use the amounts below"
                onChange={(value) =>
                  edit((draft) => {
                    draft.exchange[position].equilibrate_with = value;
                  })
                }
              />
            </label>
          </div>

          <SiteTable
            sites={item.sites}
            unit="moles of sites"
            onSet={(site, value) =>
              edit((draft) => {
                draft.exchange[position].sites[site] = value;
              })
            }
            onRemove={(site) =>
              edit((draft) => {
                delete draft.exchange[position].sites[site];
              })
            }
          />
        </div>
      )}
    </AssemblageList>
  );
}

function SiteTable({
  sites,
  unit,
  onSet,
  onRemove,
}: {
  sites: Record<string, number>;
  unit: string;
  onSet: (site: string, value: number) => void;
  onRemove: (site: string) => void;
}) {
  const names = Object.keys(sites).sort();
  if (names.length === 0) return null;

  return (
    <table className="text-[11px]">
      <thead>
        <tr className="text-left text-[10px] uppercase tracking-wider text-zinc-600">
          <th className="pb-1 pr-4 font-medium">Site</th>
          <th className="pb-1 pr-2 font-medium">{unit}</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {names.map((site) => (
          <tr key={site}>
            <td className="py-0.5 pr-4 font-mono text-zinc-200">{site}</td>
            <td className="w-28 pr-2">
              <Cell
                value={sites[site]}
                label={`${unit} for ${site}`}
                onCommit={(value) => onSet(site, value)}
              />
            </td>
            <td>
              <RowButton danger title={`Remove ${site}`} onClick={() => onRemove(site)}>
                ×
              </RowButton>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// --- Surface ----------------------------------------------------------------

const EDL_MODELS = [
  { value: "no_edl", label: "No double layer" },
  { value: "diffuse_layer", label: "Diffuse layer" },
  { value: "donnan", label: "Donnan" },
];

export function SurfacePanel({ chemistry, index, edit }: PanelProps) {
  const items = chemistry.surface ?? [];

  return (
    <AssemblageList
      items={items}
      kind="surface"
      hint="Sorption sites on a solid. A diffuse or Donnan layer is calculated from the specific area and mass, so both are needed once either is chosen."
      emptyMessage="No surfaces. Add one where iron oxides or organic coatings sorb metals."
      onAdd={() =>
        edit((draft) => {
          draft.surface.push({
            id: uniqueId(
              "surface",
              draft.surface.map((item: any) => item.id),
            ),
            label: "",
            sites: [],
            edl_model: "no_edl",
            donnan_thickness: null,
            equilibrate_with: null,
          });
        })
      }
      onRemove={(position) => edit((draft) => removeFrom(draft, "surface", "surface", position))}
      onRename={(position, name) =>
        edit((draft) => renameIn(draft, "surface", "surface", position, name))
      }
    >
      {(item, position) => (
        <div className="space-y-2">
          <div className="flex flex-wrap items-end gap-3">
            <AddFromDatabase
              label="Add a surface site"
              placeholder="Add a site…"
              options={index?.surfaceSites ?? []}
              chosen={item.sites.map((site: any) => site.site)}
              onAdd={(site) =>
                edit((draft) => {
                  draft.surface[position].sites.push({
                    site,
                    moles: 0,
                    specific_area: 0,
                    mass: 0,
                  });
                })
              }
            />
            <label className="block w-48">
              <span className="mb-1 block text-[10px] text-zinc-500">Electrical double layer</span>
              <select
                value={item.edl_model}
                aria-label={`Double layer model for ${item.id}`}
                onChange={(event) =>
                  edit((draft) => {
                    draft.surface[position].edl_model = event.target.value;
                  })
                }
                className="w-full rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs text-zinc-100 focus:border-sky-600 focus:outline-none"
              >
                {EDL_MODELS.map((model) => (
                  <option key={model.value} value={model.value}>
                    {model.label}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {item.sites.length > 0 && (
            <table className="text-[11px]">
              <thead>
                <tr className="text-left text-[10px] uppercase tracking-wider text-zinc-600">
                  <th className="pb-1 pr-4 font-medium">Site</th>
                  <th className="pb-1 pr-2 font-medium">Sites (mol)</th>
                  <th className="pb-1 pr-2 font-medium">Area (m²/g)</th>
                  <th className="pb-1 pr-2 font-medium">Mass (g)</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {item.sites.map((site: any, row: number) => (
                  <tr key={site.site}>
                    <td className="py-0.5 pr-4 font-mono text-zinc-200">{site.site}</td>
                    {(["moles", "specific_area", "mass"] as const).map((field) => (
                      <td key={field} className="w-24 pr-2">
                        <Cell
                          value={site[field]}
                          label={`${field} of ${site.site}`}
                          onCommit={(value) =>
                            edit((draft) => {
                              draft.surface[position].sites[row][field] = value;
                            })
                          }
                        />
                      </td>
                    ))}
                    <td>
                      <RowButton
                        danger
                        title={`Remove ${site.site}`}
                        onClick={() =>
                          edit((draft) => {
                            draft.surface[position].sites.splice(row, 1);
                          })
                        }
                      >
                        ×
                      </RowButton>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </AssemblageList>
  );
}

// --- Kinetics ---------------------------------------------------------------

export function KineticsPanel({ chemistry, index, edit }: PanelProps) {
  const items = chemistry.kinetics ?? [];

  return (
    <AssemblageList
      items={items}
      kind="rate set"
      hint="Reactions that proceed at a rate rather than reaching equilibrium each step. The parameters are positional; hover a heading to see the line of BASIC that uses it."
      emptyMessage="No kinetics. Add a rate set where a mineral dissolves too slowly to assume equilibrium."
      onAdd={() =>
        edit((draft) => {
          draft.kinetics.push({
            id: uniqueId(
              "rates",
              draft.kinetics.map((item: any) => item.id),
            ),
            label: "",
            reactions: [],
          });
        })
      }
      onRemove={(position) => edit((draft) => removeFrom(draft, "kinetics", "kinetics", position))}
      onRename={(position, name) =>
        edit((draft) => renameIn(draft, "kinetics", "kinetics", position, name))
      }
    >
      {(item, position) => (
        <div className="space-y-2">
          <AddFromDatabase
            label="Add a rate law"
            placeholder="Add a rate law…"
            options={(index?.rates ?? []).map((rate) => rate.name)}
            chosen={item.reactions.map((reaction: any) => reaction.rate)}
            describe={(name) => {
              const rate = index?.rates.find((entry) => entry.name === name);
              if (!rate) return null;
              return `${rate.parmCount} parm${rate.parmCount === 1 ? "" : "s"}${
                rate.isMineral ? " · mineral" : ""
              }`;
            }}
            onAdd={(rate) =>
              edit((draft) => {
                const known = index?.rates.find((entry) => entry.name === rate);
                draft.kinetics[position].reactions.push({
                  rate,
                  m0: 0,
                  parms: Array<number>(known?.parmCount ?? 0).fill(0),
                  formula: null,
                  steps: null,
                });
              })
            }
          />

          {item.reactions.map((reaction: any, row: number) => (
            <KineticRow
              key={reaction.rate}
              reaction={reaction}
              database={index?.name ?? null}
              onSet={(field, value) =>
                edit((draft) => {
                  draft.kinetics[position].reactions[row][field] = value;
                })
              }
              onSetParm={(parm, value) =>
                edit((draft) => {
                  const parms = draft.kinetics[position].reactions[row].parms;
                  while (parms.length <= parm) parms.push(0);
                  parms[parm] = value;
                })
              }
              onRemove={() =>
                edit((draft) => {
                  draft.kinetics[position].reactions.splice(row, 1);
                })
              }
            />
          ))}
        </div>
      )}
    </AssemblageList>
  );
}

/**
 * One rate law and its parameters.
 *
 * The parameters are numbered, not named — PHREEQC's rate laws read PARM(1),
 * PARM(2) and so on, and the only statement of what each means is the line of
 * BASIC that reads it. Those lines are fetched and shown as the heading's
 * tooltip, so the meaning is where the value is typed.
 */
function KineticRow({
  reaction,
  database,
  onSet,
  onSetParm,
  onRemove,
}: {
  reaction: any;
  database: string | null;
  onSet: (field: string, value: unknown) => void;
  onSetParm: (index: number, value: number) => void;
  onRemove: () => void;
}) {
  const [detail, setDetail] = useState<RateDetail | null>(null);
  const [showBasic, setShowBasic] = useState(false);

  useEffect(() => {
    if (!database) return;
    let live = true;
    fetchRate(database, reaction.rate)
      .then((found) => live && setDetail(found))
      .catch(() => live && setDetail(null));
    return () => {
      live = false;
    };
  }, [database, reaction.rate]);

  const count = detail?.parmCount ?? reaction.parms.length;
  const mismatch = detail !== null && reaction.parms.length < detail.parmCount;

  return (
    <div className="rounded border border-zinc-900 bg-zinc-900/30 p-2">
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <span className="mb-1 block text-[10px] text-zinc-500">Rate law</span>
          <span className="font-mono text-xs text-zinc-100">{reaction.rate}</span>
          {detail && !detail.isMineral && (
            <span className="ml-2 text-[10px] text-zinc-600">needs a formula</span>
          )}
        </div>

        <label className="block w-24">
          <span
            className="mb-1 block text-[10px] text-zinc-500"
            title="Amount present at the start"
          >
            m0
          </span>
          <Cell
            value={reaction.m0 ?? 0}
            label={`Initial moles of ${reaction.rate}`}
            onCommit={(value) => onSet("m0", value)}
          />
        </label>

        {Array.from({ length: count }, (_, parm) => (
          <label key={parm} className="block w-24">
            <span
              className="mb-1 block cursor-help text-[10px] text-zinc-500 underline decoration-dotted"
              title={
                detail?.parms[parm]?.lines.join("\n") ||
                `PARM(${parm + 1}), used by the ${reaction.rate} rate law`
              }
            >
              parm {parm + 1}
            </span>
            <Cell
              value={reaction.parms[parm] ?? null}
              label={`Parameter ${parm + 1} of ${reaction.rate}`}
              onCommit={(value) => onSetParm(parm, value)}
            />
          </label>
        ))}

        <div className="ml-auto flex items-center gap-2">
          {detail && (
            <RowButton onClick={() => setShowBasic(!showBasic)} title="Show the rate law's BASIC">
              {showBasic ? "hide code" : "code"}
            </RowButton>
          )}
          <RowButton danger title={`Remove ${reaction.rate}`} onClick={onRemove}>
            ×
          </RowButton>
        </div>
      </div>

      <label className="mt-2 block">
        <span className="mb-1 block text-[10px] text-zinc-500">
          Formula {detail?.isMineral ? "(optional; the phase supplies one)" : "(required)"}
        </span>
        <input
          value={reaction.formula ?? ""}
          placeholder={detail?.isMineral ? reaction.rate : "Orgc_sed -1.0 C 1.0"}
          aria-label={`Formula for ${reaction.rate}`}
          onChange={(event) => onSet("formula", event.target.value || null)}
          className="w-full max-w-lg rounded border border-zinc-700 bg-zinc-900 px-2 py-1 font-mono text-[11px] text-zinc-100 focus:border-sky-600 focus:outline-none"
        />
      </label>

      {mismatch && (
        <p className="mt-1 text-[10px] text-amber-300">
          This rate law reads {detail?.parmCount} parameters; {reaction.parms.length} are set.
        </p>
      )}

      {showBasic && detail && (
        <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-zinc-950 p-2 font-mono text-[10px] leading-snug text-zinc-500">
          {detail.basic}
        </pre>
      )}
    </div>
  );
}

// --- Gas phases -------------------------------------------------------------

export function GasesPanel({ chemistry, index, edit }: PanelProps) {
  const items = chemistry.gas_phases ?? [];

  return (
    <AssemblageList
      items={items}
      kind="gas phase"
      hint="A gas phase that exchanges with the water. Fixed pressure holds the total constant, as an open atmosphere does; fixed volume lets pressure build, as a trapped bubble does."
      emptyMessage="No gas phases. Add one where a bubble forms or the water sees the atmosphere."
      onAdd={() =>
        edit((draft) => {
          draft.gas_phases.push({
            id: uniqueId(
              "gas",
              draft.gas_phases.map((item: any) => item.id),
            ),
            label: "",
            partial_pressures: {},
            fixed_pressure: true,
            total_pressure: 1,
            volume: 1,
          });
        })
      }
      onRemove={(position) =>
        edit((draft) => removeFrom(draft, "gas_phases", "gas_phase", position))
      }
      onRename={(position, name) =>
        edit((draft) => renameIn(draft, "gas_phases", "gas_phase", position, name))
      }
    >
      {(item, position) => (
        <div className="space-y-2">
          <div className="flex flex-wrap items-end gap-3">
            <AddFromDatabase
              label="Add a gas"
              placeholder="Add a gas…"
              options={(index?.gases ?? []).map((gas) => gas.name)}
              chosen={Object.keys(item.partial_pressures)}
              onAdd={(gas) =>
                edit((draft) => {
                  draft.gas_phases[position].partial_pressures[gas] = 0;
                })
              }
            />
            <label className="flex items-center gap-2 text-[11px] text-zinc-300">
              <input
                type="checkbox"
                checked={item.fixed_pressure}
                onChange={(event) =>
                  edit((draft) => {
                    draft.gas_phases[position].fixed_pressure = event.target.checked;
                  })
                }
                className="accent-sky-600"
              />
              Fixed pressure
            </label>
            <label className="block w-24">
              <span className="mb-1 block text-[10px] text-zinc-500">
                {item.fixed_pressure ? "Total (atm)" : "Volume (L)"}
              </span>
              <Cell
                value={item.fixed_pressure ? item.total_pressure : item.volume}
                label={item.fixed_pressure ? "Total pressure" : "Volume"}
                onCommit={(value) =>
                  edit((draft) => {
                    const field = item.fixed_pressure ? "total_pressure" : "volume";
                    draft.gas_phases[position][field] = value;
                  })
                }
              />
            </label>
          </div>

          <SiteTable
            sites={item.partial_pressures}
            unit="partial pressure (atm)"
            onSet={(gas, value) =>
              edit((draft) => {
                draft.gas_phases[position].partial_pressures[gas] = value;
              })
            }
            onRemove={(gas) =>
              edit((draft) => {
                delete draft.gas_phases[position].partial_pressures[gas];
              })
            }
          />
        </div>
      )}
    </AssemblageList>
  );
}
