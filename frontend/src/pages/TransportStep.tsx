import { useState } from "react";
import { transportPackages } from "./editor/packages";
import { PackageTabs } from "./editor/PackageTabs";
import { EditorShell, Labelled, NoProject, NumberInput, Section, Select } from "./editor/controls";
import { ModelPreview } from "@/preview/ModelPreview";
import { useProjectDocument, type ProjectDocument } from "./editor/useProjectDocument";

const SCHEMES = [
  { value: "tvd", label: "TVD (least numerical dispersion)" },
  { value: "upstream", label: "Upstream (robust, more smearing)" },
  { value: "central", label: "Central (can oscillate)" },
];

/**
 * How solutes move, before any chemistry acts on them.
 *
 * Transverse dispersivities are optional here because MODFLOW requires them
 * whenever a longitudinal value is given, and the compiler supplies the
 * conventional ratios when they are left unset. Leaving them blank is a choice
 * with a defined meaning, not an omission.
 */
export function TransportStep({
  path,
  onGoToProject,
  onSaved,
}: {
  path: string | null;
  onGoToProject: () => void;
  onSaved: () => void;
}) {
  const editor = useProjectDocument(path);
  // The field drawn beside the form. Focusing an input points the viewport at
  // that property, so a value and its distribution are read together.
  const [drawn, setDrawn] = useState("transport_porosity");
  const [tab, setTab] = useState<string | null>(null);

  if (!path) return <NoProject onGo={onGoToProject} />;
  if (!editor.document) return <div className="p-6 text-xs text-zinc-500">Loading…</div>;

  const transport = editor.document.transport;
  const dispersion = transport.dispersion;
  const flowPorosity = editor.document.flow.properties.porosity?.value ?? 0;
  const engine = editor.document.meta.engine;
  const longitudinal = dispersion.longitudinal?.value ?? 0;
  const tabs = transportPackages(engine);
  const active = tab ?? tabs[0].id;

  return (
    <EditorShell
      title="Transport"
      blurb="Advection is driven by the flow solution. These control how much a plume spreads on top of it."
      dirty={editor.dirty}
      saving={editor.saving}
      problems={editor.problems}
      error={editor.error}
      savedSummary={editor.savedSummary}
      onSave={async () => {
        if (await editor.save()) onSaved();
      }}
      onRevert={() => void editor.reload()}
      preview={
        <ModelPreview
          path={path}
          revision={editor.revision}
          field={drawn}
          onFieldChange={setDrawn}
          className="h-full"
        />
      }
    >
      <PackageTabs
        groups={[{ label: "Transport", tabs }]}
        active={active}
        onSelect={(id) => {
          setTab(id);
          const field = { MST: "transport_porosity", BTN: "transport_porosity", DSP: "alh" }[id];
          if (field) setDrawn(field);
        }}
      />

      {(active === "MST" || active === "BTN") && (
        <Section
          field="transport_porosity"
          onShow={setDrawn}
          title={active === "BTN" ? "BTN — Basic transport" : "MST — Mobile storage"}
          hint="Transport can use a different porosity from flow, for instance an effective porosity that excludes dead-end pores."
        >
          <div className="flex max-w-md items-end gap-3">
            <Labelled label="Transport porosity">
              <NumberInput
                value={transport.porosity?.value ?? flowPorosity}
                disabled={transport.porosity === null}
                label="Transport porosity"
                onCommit={(value) =>
                  editor.edit((draft) => {
                    draft.transport.porosity = { kind: "constant", value };
                  })
                }
              />
            </Labelled>
            <label className="flex items-center gap-1 pb-1 text-[10px] text-zinc-500">
              <input
                type="checkbox"
                checked={transport.porosity === null}
                onChange={(event) =>
                  editor.edit((draft) => {
                    draft.transport.porosity = event.target.checked
                      ? null
                      : { kind: "constant", value: flowPorosity };
                  })
                }
              />
              follow flow ({flowPorosity})
            </label>
          </div>
        </Section>
      )}

      {active === "DSP" && (
        <Section
          field="alh"
          onShow={setDrawn}
          title="DSP — Dispersion"
          hint="Leave everything at zero for a pure-advection test; the dispersion package is then not written at all."
        >
          <div className="grid max-w-2xl grid-cols-2 gap-x-8 gap-y-4">
            <Labelled
              label="Longitudinal dispersivity"
              hint="Along the flow direction. Often a fraction of the travel distance."
            >
              <NumberInput
                value={longitudinal}
                label="Longitudinal dispersivity"
                onCommit={(value) =>
                  editor.edit((draft) => {
                    draft.transport.dispersion.longitudinal = { kind: "constant", value };
                  })
                }
              />
            </Labelled>

            <Labelled label="Molecular diffusion" hint="Independent of flow velocity.">
              <NumberInput
                value={dispersion.diffusion?.value ?? 0}
                label="Molecular diffusion"
                onCommit={(value) =>
                  editor.edit((draft) => {
                    draft.transport.dispersion.diffusion = { kind: "constant", value };
                  })
                }
              />
            </Labelled>

            <OptionalRatio
              label="Transverse horizontal"
              field="transverse_horizontal"
              ratio={0.1}
              longitudinal={longitudinal}
              value={dispersion.transverse_horizontal}
              onEdit={editor.edit}
            />
            <OptionalRatio
              label="Transverse vertical"
              field="transverse_vertical"
              ratio={0.01}
              longitudinal={longitudinal}
              value={dispersion.transverse_vertical}
              onEdit={editor.edit}
            />
          </div>
        </Section>
      )}

      {active === "ADV" && (
        <Section
          title="ADV — Advection"
          hint="How the solute front is carried between cells. TVD keeps a sharp front at some cost in solve time."
        >
          <div className="max-w-md">
            <Select
              value={transport.advection_scheme}
              label="Advection scheme"
              options={SCHEMES}
              onChange={(value) =>
                editor.edit((draft) => void (draft.transport.advection_scheme = value))
              }
            />
          </div>
        </Section>
      )}

      {(active === "MST" || active === "BTN") && (
        <Section
          title="Dual porosity"
          hint="A mobile and an immobile domain exchanging mass. PHT3D only for now; MF6RTM will accept it once upstream supports it."
        >
          {engine === "mf6rtm" ? (
            <p className="text-[11px] text-zinc-500">
              Not available for MF6RTM yet. A project targeting PHT3D can use it, and the model does
              not need rebuilding when support lands.
            </p>
          ) : transport.dual_porosity === null ? (
            <button
              type="button"
              onClick={() =>
                editor.edit((draft) => {
                  draft.transport.dual_porosity = {
                    immobile_porosity: { kind: "constant", value: 0.05 },
                    transfer_rate: { kind: "constant", value: 1e-3 },
                  };
                })
              }
              className="rounded border border-zinc-700 px-2 py-1 text-[10px] text-zinc-300 hover:border-zinc-600"
            >
              Enable dual porosity
            </button>
          ) : (
            <div className="flex max-w-lg items-end gap-4">
              <Labelled label="Immobile porosity">
                <NumberInput
                  value={transport.dual_porosity.immobile_porosity.value}
                  label="Immobile porosity"
                  onCommit={(value) =>
                    editor.edit((draft) => {
                      draft.transport.dual_porosity.immobile_porosity = {
                        kind: "constant",
                        value,
                      };
                    })
                  }
                />
              </Labelled>
              <Labelled label="Transfer rate">
                <NumberInput
                  value={transport.dual_porosity.transfer_rate.value}
                  label="Transfer rate"
                  onCommit={(value) =>
                    editor.edit((draft) => {
                      draft.transport.dual_porosity.transfer_rate = { kind: "constant", value };
                    })
                  }
                />
              </Labelled>
              <button
                type="button"
                onClick={() => editor.edit((draft) => void (draft.transport.dual_porosity = null))}
                className="pb-1 text-[10px] text-zinc-500 hover:text-red-400"
              >
                disable
              </button>
            </div>
          )}
        </Section>
      )}

      {(active === "SSM" || active === "GCG") && (
        <Section title={active === "SSM" ? "SSM — Source mixing" : "GCG — Solver"}>
          <p className="max-w-lg text-[11px] leading-relaxed text-zinc-500">
            {active === "SSM"
              ? "Written from the flow boundaries and the chemistry each one carries. Set the water a boundary brings in on the Chemistry step, under Boundaries."
              : "Written with settings that suit every model this builds. It becomes editable if a run ever fails to converge on them."}
          </p>
        </Section>
      )}
    </EditorShell>
  );
}

/**
 * A dispersivity that follows a ratio of the longitudinal value unless set.
 *
 * The ratio is shown rather than the resulting number alone, so it is clear the
 * value is derived and what it is derived from.
 */
function OptionalRatio({
  label,
  field,
  ratio,
  longitudinal,
  value,
  onEdit,
}: {
  label: string;
  field: string;
  ratio: number;
  longitudinal: number;
  value: ProjectDocument | null;
  onEdit: (change: (draft: ProjectDocument) => void) => void;
}) {
  const derived = longitudinal * ratio;

  return (
    <Labelled
      label={label}
      hint={
        value === null
          ? `following ${ratio} of longitudinal = ${derived.toPrecision(4)}`
          : "set explicitly"
      }
    >
      <div className="flex items-center gap-2">
        <NumberInput
          value={value?.value ?? derived}
          disabled={value === null}
          label={label}
          onCommit={(next) =>
            onEdit((draft) => {
              draft.transport.dispersion[field] = { kind: "constant", value: next };
            })
          }
        />
        <label className="flex items-center gap-1 text-[10px] text-zinc-500">
          <input
            type="checkbox"
            checked={value === null}
            onChange={(event) =>
              onEdit((draft) => {
                draft.transport.dispersion[field] = event.target.checked
                  ? null
                  : { kind: "constant", value: derived };
              })
            }
          />
          auto
        </label>
      </div>
    </Labelled>
  );
}
