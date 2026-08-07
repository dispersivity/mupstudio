/**
 * Small helpers the chemistry tabs share.
 *
 * Kept apart from the components that use them so each panel file exports only
 * components, which is what lets fast refresh work while editing them.
 */

/** A name not already taken, so adding twice does not collide. */
export function uniqueId(stem: string, taken: string[]): string {
  if (!taken.includes(stem)) return stem;
  let counter = 2;
  while (taken.includes(`${stem}_${counter}`)) counter += 1;
  return `${stem}_${counter}`;
}

/**
 * "1, 3, 5-9" to the indices it names.
 *
 * Ranges because cells come in runs: a lens across twenty columns is written
 * once rather than typed out. Deduplicated and sorted, so overlapping ranges
 * are harmless.
 */
export function parseIndices(text: string): number[] {
  const found: number[] = [];
  for (const part of text.split(",")) {
    const range = part.trim().match(/^(\d+)\s*-\s*(\d+)$/);
    if (range) {
      const [start, end] = [Number(range[1]), Number(range[2])];
      for (let value = Math.min(start, end); value <= Math.max(start, end); value += 1) {
        found.push(value);
      }
      continue;
    }
    const single = Number(part.trim());
    if (Number.isInteger(single) && single > 0) found.push(single);
  }
  return [...new Set(found)].sort((left, right) => left - right);
}

/**
 * A number as text, losslessly.
 *
 * Every digit is kept. These are the numbers in a water analysis, and the text
 * shown here is also what an unedited cell commits back, so rounding for
 * readability would quietly change the model: a rate constant given to seven
 * figures would come back as four.
 *
 * Both branches round-trip exactly. Javascript's default number-to-string and
 * ``toExponential()`` with no argument each produce the shortest text that
 * parses back to the same value; the only choice made here is which of the two
 * reads better at a given magnitude.
 */
export function format(value: number): string {
  if (!Number.isFinite(value)) return "";
  if (value === 0) return "0";
  const magnitude = Math.abs(value);
  if (magnitude < 1e-3 || magnitude >= 1e5) return value.toExponential();
  return String(value);
}

/** Rough, and meant to be: the point is to notice a gigabyte before running. */
export function estimateSize(columns: number, cells: number, times: number): string {
  const bytes = columns * cells * times * 8;
  if (bytes < 1e6) return `${Math.round(bytes / 1e3)} kB`;
  if (bytes < 1e9) return `${(bytes / 1e6).toFixed(1)} MB`;
  return `${(bytes / 1e9).toFixed(1)} GB`;
}
