import { useMemo, useState } from "react";
import type { DatabaseIndex, DatabaseListing, RateDetail } from "./database";
import { fetchRate } from "./database";

/**
 * Which database, and what is in it.
 *
 * The database is chosen before anything else because it decides what every
 * other tab can offer. Showing its contents here is not decoration: a chemist
 * picks between phreeqc.dat and pht3d_datab.dat by what they hold, and needs to
 * confirm a mineral exists before building a model around it.
 */
export function DatabasePanel({
  databases,
  index,
  selected,
  loading,
  error,
  onSelect,
}: {
  databases: DatabaseListing[];
  index: DatabaseIndex | null;
  selected: string;
  loading: boolean;
  error: string | null;
  onSelect: (name: string) => void;
}) {
  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
          Database
        </h3>
        <p className="mt-1 max-w-xl text-[11px] leading-relaxed text-zinc-600">
          Everything the other tabs offer comes from here. Changing it after the chemistry is built
          may leave species behind; they are flagged rather than deleted.
        </p>

        <ul className="mt-3 grid max-w-3xl gap-2 sm:grid-cols-2">
          {databases.map((entry) => (
            <li key={entry.path}>
              <button
                type="button"
                onClick={() => onSelect(entry.name)}
                className={`w-full rounded border px-3 py-2 text-left ${
                  entry.name === selected
                    ? "border-sky-600 bg-sky-950/30"
                    : "border-zinc-800 hover:border-zinc-700"
                }`}
              >
                <div className="font-mono text-xs text-zinc-100">{entry.name}</div>
                {entry.error ? (
                  <div className="mt-0.5 text-[10px] text-red-400">{entry.error}</div>
                ) : (
                  <div className="mt-0.5 text-[10px] text-zinc-500">
                    {entry.summary?.masterSpecies} species · {entry.summary?.phases} minerals ·{" "}
                    {entry.summary?.gases} gases · {entry.summary?.rates} rate laws
                  </div>
                )}
              </button>
            </li>
          ))}
          {databases.length === 0 && (
            <li className="text-[11px] text-zinc-600">
              No databases found. mupstudio ships several; if none appear, the install is
              incomplete.
            </li>
          )}
        </ul>
      </div>

      {loading && <p className="text-[11px] text-zinc-500">Reading {selected}…</p>}
      {error && <p className="text-[11px] text-red-300">{error}</p>}
      {index && <Explorer index={index} />}
    </div>
  );
}

type Tab = "species" | "minerals" | "gases" | "exchange" | "surface" | "rates";

const TABS: { id: Tab; label: string }[] = [
  { id: "species", label: "Species" },
  { id: "minerals", label: "Minerals" },
  { id: "gases", label: "Gases" },
  { id: "exchange", label: "Exchange" },
  { id: "surface", label: "Surface" },
  { id: "rates", label: "Rate laws" },
];

function Explorer({ index }: { index: DatabaseIndex }) {
  const [tab, setTab] = useState<Tab>("species");
  const [query, setQuery] = useState("");

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 border-b border-zinc-800 pb-2">
        {TABS.map((entry) => (
          <button
            key={entry.id}
            type="button"
            onClick={() => setTab(entry.id)}
            className={`rounded px-2 py-1 text-[11px] ${
              tab === entry.id ? "bg-zinc-800 text-zinc-100" : "text-zinc-500 hover:text-zinc-300"
            }`}
          >
            {entry.label}
          </button>
        ))}
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search"
          aria-label="Search the database"
          className="ml-auto w-48 rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-[11px] text-zinc-100 focus:border-sky-600 focus:outline-none"
        />
      </div>

      <div className="mt-3 max-h-96 overflow-y-auto">
        {tab === "species" && <SpeciesList index={index} query={query} />}
        {tab === "minerals" && <PhaseList phases={index.phases} query={query} />}
        {tab === "gases" && <PhaseList phases={index.gases} query={query} />}
        {tab === "exchange" && (
          <NameList
            names={[...index.exchangeSites, ...index.exchangeSpecies]}
            query={query}
            empty="This database has no exchange species."
          />
        )}
        {tab === "surface" && (
          <NameList
            names={index.surfaceSites}
            query={query}
            empty="This database has no surface sites."
          />
        )}
        {tab === "rates" && <RateList index={index} query={query} />}
      </div>
    </div>
  );
}

function matches(text: string, query: string): boolean {
  return !query.trim() || text.toLowerCase().includes(query.trim().toLowerCase());
}

/** Redox states shown under their element, which is how PHREEQC organises them. */
function SpeciesList({ index, query }: { index: DatabaseIndex; query: string }) {
  const groups = useMemo(
    () =>
      index.elements.filter(
        (group) =>
          matches(group.element, query) || group.states.some((state) => matches(state.name, query)),
      ),
    [index, query],
  );

  return (
    <ul className="grid gap-x-6 gap-y-1 sm:grid-cols-2 lg:grid-cols-3">
      {groups.map((group) => (
        <li key={group.element} className="text-[11px]">
          <span className="font-mono text-zinc-300">{group.element}</span>
          {group.states.length > 1 || group.states[0]?.name !== group.element ? (
            <span className="ml-2 font-mono text-[10px] text-zinc-600">
              {group.states.map((state) => state.name).join("  ")}
            </span>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

function PhaseList({
  phases,
  query,
}: {
  phases: { name: string; reaction: string; logK: number | null }[];
  query: string;
}) {
  const shown = phases.filter((phase) => matches(phase.name, query)).slice(0, 400);

  return (
    <table className="w-full text-[11px]">
      <thead>
        <tr className="text-left text-[10px] uppercase tracking-wider text-zinc-600">
          <th className="pb-1 font-medium">Name</th>
          <th className="pb-1 font-medium">Reaction</th>
          <th className="pb-1 text-right font-medium">log K</th>
        </tr>
      </thead>
      <tbody>
        {shown.map((phase) => (
          <tr key={phase.name} className="border-t border-zinc-900">
            <td className="py-0.5 pr-3 font-mono text-zinc-200">{phase.name}</td>
            <td className="py-0.5 pr-3 font-mono text-[10px] text-zinc-500">{phase.reaction}</td>
            <td className="py-0.5 text-right font-mono tabular-nums text-zinc-400">
              {phase.logK ?? "—"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function NameList({ names, query, empty }: { names: string[]; query: string; empty: string }) {
  const shown = names.filter((name) => matches(name, query));
  if (shown.length === 0) return <p className="text-[11px] text-zinc-600">{empty}</p>;

  return (
    <ul className="flex flex-wrap gap-1.5">
      {shown.map((name) => (
        <li
          key={name}
          className="rounded bg-zinc-900 px-1.5 py-0.5 font-mono text-[11px] text-zinc-300"
        >
          {name}
        </li>
      ))}
    </ul>
  );
}

/**
 * Rate laws, expandable to their BASIC.
 *
 * A rate law's parameters are positional and otherwise unnamed, so the only
 * statement of what PARM(2) means is the line that reads it. This is where a
 * chemist finds that out without opening the database in an editor.
 */
function RateList({ index, query }: { index: DatabaseIndex; query: string }) {
  const [open, setOpen] = useState<string | null>(null);
  const [detail, setDetail] = useState<RateDetail | null>(null);

  const shown = index.rates.filter((rate) => matches(rate.name, query));

  const toggle = async (name: string) => {
    if (open === name) {
      setOpen(null);
      return;
    }
    setOpen(name);
    setDetail(null);
    try {
      setDetail(await fetchRate(index.name, name));
    } catch {
      setDetail(null);
    }
  };

  return (
    <ul className="space-y-0.5">
      {shown.map((rate) => (
        <li key={rate.name} className="border-t border-zinc-900">
          <button
            type="button"
            onClick={() => void toggle(rate.name)}
            className="flex w-full items-baseline gap-2 py-1 text-left hover:bg-zinc-900/60"
          >
            <span className="font-mono text-[11px] text-zinc-200">{rate.name}</span>
            <span className="text-[10px] text-zinc-500">
              {rate.parmCount} parameter{rate.parmCount === 1 ? "" : "s"}
            </span>
            {rate.isMineral && (
              <span className="rounded bg-zinc-800 px-1 text-[9px] text-zinc-400">mineral</span>
            )}
          </button>

          {open === rate.name && (
            <div className="mb-2 ml-3 border-l border-zinc-800 pl-3">
              {detail === null ? (
                <p className="py-1 text-[10px] text-zinc-600">Reading…</p>
              ) : (
                <>
                  {detail.parms.map((parm) => (
                    <div key={parm.index} className="py-0.5">
                      <span className="font-mono text-[10px] text-sky-400">PARM({parm.index})</span>
                      {parm.lines.map((line) => (
                        <div key={line} className="ml-3 font-mono text-[10px] text-zinc-500">
                          {line}
                        </div>
                      ))}
                    </div>
                  ))}
                  <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap font-mono text-[10px] leading-snug text-zinc-600">
                    {detail.basic}
                  </pre>
                </>
              )}
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}
