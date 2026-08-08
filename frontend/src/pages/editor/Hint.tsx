/**
 * An explanation, kept out of the way until it is wanted.
 *
 * These screens had a paragraph under every heading. Each one was worth saying
 * once and worth reading once, and after that it was a third of the window
 * spent on text nobody was looking at any more — pushing the thing being edited
 * further down the page every time.
 *
 * A hover rather than a click: reading it should cost less than deciding to
 * read it. Positioned to the right and below, because these sit beside titles
 * near the top of a panel where there is room underneath.
 */
export function Hint({ children, className = "" }: { children: string; className?: string }) {
  if (!children) return null;

  return (
    <span className={`group relative inline-flex align-middle ${className}`}>
      <button
        type="button"
        aria-label={children}
        // A button so it is reachable by keyboard; focus shows the same panel
        // hover does.
        className="flex h-3.5 w-3.5 items-center justify-center rounded-full border border-zinc-700 text-[8px] leading-none text-zinc-500 hover:border-zinc-500 hover:text-zinc-300 focus:outline-none focus-visible:border-sky-500"
      >
        ?
      </button>

      <span
        role="tooltip"
        className="pointer-events-none absolute left-0 top-5 z-50 w-72 rounded border border-zinc-700 bg-zinc-900 p-2 text-[11px] font-normal leading-relaxed text-zinc-300 opacity-0 shadow-xl transition-opacity group-hover:opacity-100 group-focus-within:opacity-100"
      >
        {children}
      </span>
    </span>
  );
}
