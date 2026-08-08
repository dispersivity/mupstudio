import type { PackageTab } from "./packages";

/**
 * One tab per package, named the way the engine names it.
 *
 * The acronym is the label because that is what the written file is called and
 * what an error in a listing file mentions. Hovering gives the full name and
 * what the package decides, so the shorthand does not have to be memorised
 * first.
 *
 * A package with nothing in it is dimmed rather than hidden. A model with no
 * RIV still has a RIV tab, because "is there a river in this model?" is a
 * question the screen should answer without being clicked through.
 */
export function PackageTabs({
  groups,
  active,
  counts,
  onSelect,
}: {
  groups: { label: string; tabs: PackageTab[] }[];
  active: string;
  /** How many instances each package has, where the notion applies. */
  counts?: Record<string, number>;
  onSelect: (id: string) => void;
}) {
  return (
    <nav className="mb-5 border-b border-zinc-800 pb-2">
      {groups.map((group) => (
        <div key={group.label} className="flex items-center gap-2 py-0.5">
          <span className="w-16 shrink-0 text-[9px] uppercase tracking-wider text-zinc-600">
            {group.label}
          </span>
          <div className="flex flex-wrap gap-1">
            {group.tabs.map((tab) => {
              const count = counts?.[tab.id];
              const empty =
                counts !== undefined && count === undefined && group.label !== "Aquifer";

              return (
                <button
                  key={tab.id}
                  type="button"
                  title={`${tab.label} — ${tab.purpose}`}
                  onClick={() => onSelect(tab.id)}
                  className={`rounded px-2 py-1 font-mono text-[10px] ${
                    active === tab.id
                      ? "bg-zinc-800 text-sky-300"
                      : empty
                        ? "text-zinc-700 hover:text-zinc-500"
                        : "text-zinc-400 hover:text-zinc-200"
                  }`}
                >
                  {tab.id}
                  {count ? <span className="ml-1 text-zinc-500">{count}</span> : null}
                </button>
              );
            })}
          </div>
        </div>
      ))}
    </nav>
  );
}
