import { useMemo, useRef, useState } from "react";
import { format } from "./edits";

/**
 * Choosing from a database.
 *
 * A database holds hundreds of phases and dozens of species, so every one of
 * these is a search box rather than a dropdown. The list is filtered as you
 * type and shows what is already chosen, because adding the same mineral twice
 * is the mistake these are here to prevent.
 */

export function AddFromDatabase({
  label,
  options,
  chosen,
  onAdd,
  describe,
  placeholder,
}: {
  label: string;
  options: string[];
  chosen: readonly string[];
  onAdd: (name: string) => void;
  describe?: (name: string) => string | null;
  placeholder?: string;
}) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  const taken = useMemo(() => new Set(chosen), [chosen]);
  const matches = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const available = options.filter((name) => !taken.has(name));
    if (!needle) return available.slice(0, 40);
    // Names that start with the query first: typing "Cal" should reach Calcite
    // before Hydroxylapatite, which merely contains the letters.
    const starts: string[] = [];
    const contains: string[] = [];
    for (const name of available) {
      const lower = name.toLowerCase();
      if (lower.startsWith(needle)) starts.push(name);
      else if (lower.includes(needle)) contains.push(name);
    }
    return [...starts, ...contains].slice(0, 40);
  }, [options, query, taken]);

  const pick = (name: string) => {
    onAdd(name);
    setQuery("");
    setOpen(false);
  };

  return (
    <div ref={box} className="relative w-64">
      <input
        value={query}
        aria-label={label}
        placeholder={placeholder ?? label}
        onChange={(event) => {
          setQuery(event.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => window.setTimeout(() => setOpen(false), 150)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && matches.length > 0) {
            event.preventDefault();
            pick(matches[0]);
          }
          if (event.key === "Escape") setOpen(false);
        }}
        className="w-full rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs text-zinc-100 focus:border-sky-600 focus:outline-none"
      />

      {open && (
        <ul className="absolute z-20 mt-1 max-h-64 w-full overflow-y-auto rounded border border-zinc-700 bg-zinc-900 py-1 shadow-xl">
          {matches.length === 0 && (
            <li className="px-2 py-1.5 text-[11px] text-zinc-600">
              {options.length === 0 ? "The database has none of these." : "Nothing matches."}
            </li>
          )}
          {matches.map((name) => (
            <li key={name}>
              <button
                type="button"
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => pick(name)}
                className="block w-full px-2 py-1 text-left hover:bg-zinc-800"
              >
                <span className="font-mono text-[11px] text-zinc-200">{name}</span>
                {describe?.(name) && (
                  <span className="ml-2 text-[10px] text-zinc-500">{describe(name)}</span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * Choosing one of the project's own things: a solution, an assemblage, a zone.
 *
 * Short lists that people name themselves, so a plain select is right here
 * where a search box would be overkill.
 */
export function Chooser({
  value,
  options,
  onChange,
  allowNone,
  noneLabel = "none",
  label,
}: {
  value: string | null;
  options: { id: string; label?: string }[];
  onChange: (value: string | null) => void;
  allowNone?: boolean;
  noneLabel?: string;
  label: string;
}) {
  return (
    <select
      value={value ?? ""}
      aria-label={label}
      onChange={(event) => onChange(event.target.value || null)}
      className="w-full rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs text-zinc-100 focus:border-sky-600 focus:outline-none"
    >
      {allowNone && <option value="">{noneLabel}</option>}
      {options.map((option) => (
        <option key={option.id} value={option.id}>
          {option.label ? `${option.id} · ${option.label}` : option.id}
        </option>
      ))}
    </select>
  );
}

/**
 * A number cell that commits on blur or Enter.
 *
 * Not per keystroke: concentrations are written in scientific notation, and
 * "1e-" is not a number until the exponent arrives.
 */
export function Cell({
  value,
  onCommit,
  label,
  placeholder,
}: {
  value: number | null;
  onCommit: (value: number) => void;
  label: string;
  placeholder?: string;
}) {
  const [text, setText] = useState<string | null>(null);
  const shown = text ?? (value === null ? "" : format(value));

  const commit = () => {
    if (text === null) return;
    const parsed = Number(text);
    if (text.trim() !== "" && Number.isFinite(parsed)) onCommit(parsed);
    setText(null);
  };

  return (
    <input
      value={shown}
      aria-label={label}
      placeholder={placeholder}
      inputMode="decimal"
      onChange={(event) => setText(event.target.value)}
      onBlur={commit}
      onKeyDown={(event) => {
        if (event.key === "Enter") event.currentTarget.blur();
        if (event.key === "Escape") setText(null);
      }}
      className="w-full rounded border border-transparent bg-zinc-900/60 px-1.5 py-1 text-right font-mono text-[11px] tabular-nums text-zinc-100 hover:border-zinc-700 focus:border-sky-600 focus:outline-none"
    />
  );
}

/** A small button for adding and removing rows, used across the chemistry tabs. */
export function RowButton({
  onClick,
  title,
  danger,
  children,
}: {
  onClick: () => void;
  title: string;
  danger?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-label={title}
      className={`rounded px-1.5 py-0.5 text-[10px] ${
        danger
          ? "text-zinc-600 hover:bg-red-950 hover:text-red-400"
          : "border border-zinc-700 text-zinc-400 hover:border-zinc-600 hover:text-zinc-200"
      }`}
    >
      {children}
    </button>
  );
}
