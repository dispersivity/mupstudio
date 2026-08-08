import { CellSelector } from "./CellSelector";
import { TextInput } from "./controls";
import type { Limits } from "./grid";
import { describeSelection, type CellSelection } from "./selection";

/**
 * The model's named regions.
 *
 * A modeller does not think in three independent property maps — they think
 * "this is the sand and that is the clay", and then give each its properties.
 * So the region is drawn once here and every property refers to it by name.
 *
 * Order is paint order, later winning where two overlap. That is what a layer
 * list means in every GIS, and the only rule that can be predicted without
 * reading anything.
 */

// Enough distinct hues to tell a dozen units apart, in the order they are
// handed out, so two zones created in a row never look alike.
const COLOURS = [
  "#c8a95a",
  "#6ba3c8",
  "#c87f6b",
  "#7fc86b",
  "#a96bc8",
  "#c86ba9",
  "#6bc8b4",
  "#c8b46b",
];

export interface Zone {
  id: string;
  label?: string;
  color?: string | null;
  cells: CellSelection;
}

export function ZoneList({
  zones,
  limits,
  sources,
  path,
  pickingZone,
  onPick,
  onChange,
}: {
  zones: Zone[];
  limits: Limits;
  sources: { id: string; name: string; geometry?: string }[];
  path: string | null;
  /** Index of the zone whose cells clicks are going into, or null. */
  pickingZone: number | null;
  onPick: (index: number | null) => void;
  onChange: (change: (zones: Zone[]) => void) => void;
}) {
  return (
    <div className="space-y-2">
      {zones.length === 0 && (
        <p className="text-[11px] leading-relaxed text-zinc-600">
          No zones yet. A zone is a named part of the grid — a stratigraphic unit, a fault block,
          a contaminated area — that properties can be given per zone instead of one value for the
          whole model.
        </p>
      )}

      <ul className="space-y-2">
        {zones.map((zone, index) => (
          <li key={index} className="rounded border border-zinc-800">
            <div className="flex items-center gap-2 px-2 py-1.5">
              <span
                className="h-3 w-3 shrink-0 rounded-sm"
                style={{ backgroundColor: zone.color ?? COLOURS[index % COLOURS.length] }}
              />
              <TextInput
                value={zone.label ?? ""}
                label={`${zone.id} name`}
                placeholder={zone.id}
                onCommit={(value) => onChange((draft) => void (draft[index].label = value))}
              />
              <span className="shrink-0 text-[10px] text-zinc-600">
                {describeSelection(zone.cells)}
              </span>
              <div className="ml-auto flex shrink-0 items-center gap-1">
                {index > 0 && (
                  <button
                    type="button"
                    title="Move up: earlier zones are painted over by later ones"
                    onClick={() =>
                      onChange((draft) => {
                        [draft[index - 1], draft[index]] = [draft[index], draft[index - 1]];
                      })
                    }
                    className="px-1 text-[10px] text-zinc-600 hover:text-zinc-300"
                  >
                    ↑
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => {
                    if (pickingZone === index) onPick(null);
                    onChange((draft) => void draft.splice(index, 1));
                  }}
                  className="px-1 text-[10px] text-zinc-500 hover:text-red-400"
                >
                  remove
                </button>
              </div>
            </div>

            <div className="border-t border-zinc-800 p-2">
              <CellSelector
                selection={zone.cells}
                limits={limits}
                sources={sources}
                path={path}
                picking={pickingZone === index}
                onPick={(on) => onPick(on ? index : null)}
                onChange={(selection) => onChange((draft) => void (draft[index].cells = selection))}
              />
            </div>
          </li>
        ))}
      </ul>

      <button
        type="button"
        onClick={() =>
          onChange((draft) => {
            const used = new Set(draft.map((zone) => zone.id));
            let number = draft.length + 1;
            while (used.has(`zone${number}`)) number++;
            draft.push({
              id: `zone${number}`,
              label: "",
              color: COLOURS[draft.length % COLOURS.length],
              // A new zone starts empty and picked, since drawing it is the
              // next thing anyone does after creating one.
              cells: { kind: "list", indices: [] },
            });
          })
        }
        className="rounded border border-zinc-700 px-2 py-1 font-mono text-[10px] text-zinc-300 hover:border-zinc-600 hover:text-zinc-100"
      >
        + zone
      </button>
    </div>
  );
}
