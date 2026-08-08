import type { Check } from "./checks";

export function Prerequisites({ checks }: { checks: Check[] }) {
  const blocked = checks.filter((check) => check.state === "blocked");

  return (
    <div>
      <h3 className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
        Before running
      </h3>

      <ul className="mt-1.5 space-y-1">
        {checks.map((check) => (
          <li key={check.label} className="flex items-start gap-2">
            <Mark state={check.state} />
            <div className="min-w-0">
              <div className="text-[11px] text-zinc-300">{check.label}</div>
              <div className="text-[10px] leading-snug text-zinc-500">{check.detail}</div>
            </div>
          </li>
        ))}
      </ul>

      {blocked.length > 0 && (
        <p className="mt-2 text-[10px] text-red-300">
          {blocked.map((check) => check.label).join(" and ")} must be sorted out first.
        </p>
      )}
    </div>
  );
}

function Mark({ state }: { state: Check["state"] }) {
  const colour =
    state === "ok" ? "text-emerald-400" : state === "warn" ? "text-amber-400" : "text-red-400";
  const glyph = state === "ok" ? "✓" : state === "warn" ? "!" : "×";

  return (
    <span
      aria-label={state}
      className={`mt-0.5 w-3 shrink-0 text-center text-[10px] leading-none ${colour}`}
    >
      {glyph}
    </span>
  );
}

/**
 * What an action produced, said immediately beneath it.
 *
 * A button that reports nothing leaves you to go and check whether it worked.
 * One line closes the loop: how many files, how many components, how many
 * cells.
 */
export function Outcome({ children }: { children: React.ReactNode }) {
  if (!children) return null;
  return <p className="mt-1.5 text-[10px] leading-relaxed text-sky-400">{children}</p>;
}
