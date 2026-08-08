import { useEffect, useState } from "react";
import { Hint } from "./Hint";
import type { FieldProblem } from "./useProjectDocument";

/** The frame every editor step shares: a title, a save button, and problems. */
export function EditorShell({
  title,
  blurb,
  dirty,
  saving,
  problems,
  error,
  savedSummary,
  onSave,
  onRevert,
  children,
  preview,
  aside,
}: {
  title: string;
  blurb: string;
  dirty: boolean;
  saving: boolean;
  problems: FieldProblem[];
  error: string | null;
  savedSummary: string | null;
  onSave: () => void;
  onRevert: () => void;
  children: React.ReactNode;
  /**
   * The model drawn.
   *
   * Given a preview, it becomes the centre of the screen and the form moves to
   * a column beside it. That is the arrangement the whole app is built around:
   * the figure is the thing being worked on, and the controls sit next to it.
   * A picture in a corner is a picture nobody looks at.
   */
  preview?: React.ReactNode;
  /** Rendered above the form, for a step whose form is a list of things. */
  aside?: React.ReactNode;
}) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-start justify-between gap-4 border-b border-zinc-800 px-6 py-4">
        <div className="flex items-center gap-1.5">
          <h2 className="text-sm font-medium text-zinc-100">{title}</h2>
          <Hint>{blurb}</Hint>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {savedSummary && !dirty && <span className="text-[10px] text-emerald-400">saved</span>}
          {dirty && <span className="text-[10px] text-amber-300">unsaved</span>}
          <button
            type="button"
            onClick={onRevert}
            disabled={!dirty || saving}
            className="rounded border border-zinc-700 px-2 py-1 text-[10px] text-zinc-400 hover:border-zinc-600 disabled:opacity-40"
          >
            Revert
          </button>
          <button
            type="button"
            onClick={onSave}
            disabled={!dirty || saving}
            className="rounded bg-sky-600 px-3 py-1 text-xs font-medium text-white hover:bg-sky-500 disabled:opacity-40"
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>

      {/* What the save produced, said where the action was. A button that
          reports nothing leaves you to go and check whether it worked. */}
      {savedSummary && !dirty && !error && problems.length === 0 && (
        <p className="border-b border-zinc-800 px-6 py-1.5 text-[10px] text-sky-400">
          {savedSummary}
        </p>
      )}

      {(error || problems.length > 0) && (
        <div className="border-b border-red-900 bg-red-950/30 px-6 py-2">
          {error && <p className="text-xs text-red-300">{error}</p>}
          {problems.map((problem) => (
            <p key={`${problem.field}-${problem.message}`} className="text-[11px] text-red-300">
              <span className="font-mono text-red-400">{problem.field || "project"}</span>{" "}
              {problem.message}
            </p>
          ))}
        </div>
      )}

      {preview ? (
        <div className="flex min-h-0 flex-1">
          <div className="min-h-0 min-w-0 flex-1 p-3">{preview}</div>
          <div className="flex min-h-0 w-96 shrink-0 flex-col border-l border-zinc-800 2xl:w-[28rem]">
            {aside}
            <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">{children}</div>
          </div>
        </div>
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">{children}</div>
      )}
    </div>
  );
}

export function Section({
  title,
  hint,
  field,
  onShow,
  children,
}: {
  title: string;
  hint?: string;
  /**
   * The drawable field this section is about, if any.
   *
   * Clicking into one of its inputs draws that field. Focus rather than a
   * button beside every control: the gesture that says "I am looking at this"
   * is already the one that starts editing it.
   */
  field?: string;
  onShow?: (field: string) => void;
  children: React.ReactNode;
}) {
  return (
    <section className="mb-7" onFocusCapture={field && onShow ? () => onShow(field) : undefined}>
      <div className="flex items-center gap-1.5">
        <h3 className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
          {title}
        </h3>
        {hint && <Hint>{hint}</Hint>}
      </div>
      <div className="mt-2">{children}</div>
    </section>
  );
}

export function Labelled({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 flex items-center gap-1 text-[10px] text-zinc-500">
        {label}
        {hint && <Hint>{hint}</Hint>}
      </span>
      {children}
    </label>
  );
}

/**
 * A number field that commits on blur or Enter.
 *
 * Not per keystroke: typing "1e-" or clearing a field to retype it would
 * otherwise be rejected mid-edit, and scientific notation is how these values
 * are usually written.
 */
export function NumberInput({
  value,
  onCommit,
  label,
  min,
  step,
  disabled,
  wide,
}: {
  value: number;
  onCommit: (value: number) => void;
  label?: string;
  min?: number;
  step?: number;
  disabled?: boolean;
  wide?: boolean;
}) {
  const [draft, setDraft] = useState<string | null>(null);

  useEffect(() => setDraft(null), [value]);

  const commit = () => {
    if (draft === null) return;
    const parsed = Number(draft);
    if (Number.isFinite(parsed)) onCommit(parsed);
    setDraft(null);
  };

  return (
    <input
      type="text"
      inputMode="decimal"
      aria-label={label}
      disabled={disabled}
      value={draft ?? format(value)}
      min={min}
      step={step}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={commit}
      onKeyDown={(event) => {
        if (event.key === "Enter") commit();
        if (event.key === "Escape") setDraft(null);
      }}
      className={`rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs tabular-nums text-zinc-100 disabled:opacity-40 ${
        wide ? "w-full" : "w-28"
      }`}
    />
  );
}

export function TextInput({
  value,
  onCommit,
  label,
  placeholder,
}: {
  value: string;
  onCommit: (value: string) => void;
  label?: string;
  placeholder?: string;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  useEffect(() => setDraft(null), [value]);

  return (
    <input
      type="text"
      aria-label={label}
      placeholder={placeholder}
      value={draft ?? value}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={() => {
        if (draft !== null) onCommit(draft);
        setDraft(null);
      }}
      onKeyDown={(event) => {
        if (event.key === "Enter") {
          if (draft !== null) onCommit(draft);
          setDraft(null);
        }
      }}
      className="w-full rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs text-zinc-100"
    />
  );
}

export function Select({
  value,
  options,
  onChange,
  label,
}: {
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
  label?: string;
}) {
  return (
    <select
      value={value}
      aria-label={label}
      onChange={(event) => onChange(event.target.value)}
      className="w-full rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs text-zinc-100"
    >
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}

export function NoProject({ onGo }: { onGo: () => void }) {
  return (
    <div className="flex h-full items-center justify-center p-8">
      <div className="max-w-md space-y-3 text-center">
        <p className="text-sm text-zinc-300">No project open.</p>
        <button
          type="button"
          onClick={onGo}
          className="rounded border border-zinc-700 px-3 py-1.5 text-xs text-zinc-300 hover:border-zinc-600"
        >
          Go to Project
        </button>
      </div>
    </div>
  );
}

function format(value: number): string {
  if (value === 0) return "0";
  const magnitude = Math.abs(value);
  if (magnitude < 1e-4 || magnitude >= 1e6) return value.toExponential(3);
  return String(Number(value.toPrecision(6)));
}
