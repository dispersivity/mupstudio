import { useEffect, useState } from "react";

/**
 * The PHREEQC database, as the editor needs it.
 *
 * Everything a chemistry screen offers as a choice comes from here: which
 * species exist, which minerals can precipitate, what a rate law's parameters
 * are. Without it every field is free text and every mistake surfaces as a
 * PHREEQC error three minutes into a run.
 *
 * Fetched whole and kept. llnl.dat is the worst case at a few hundred kilobytes,
 * which is cheaper than paging a list people search rather than scroll.
 */

export interface DatabaseSummary {
  masterSpecies: number;
  phases: number;
  gases: number;
  exchangeSpecies: number;
  surfaceSites: number;
  rates: number;
}

export interface DatabaseListing {
  name: string;
  path: string;
  sha256?: string;
  summary?: DatabaseSummary;
  error?: string;
}

export interface MasterSpecies {
  name: string;
  redox: string | null;
  species: string;
  gramFormulaWeight: number | null;
}

export interface ElementGroup {
  element: string;
  states: MasterSpecies[];
}

export interface PhaseEntry {
  name: string;
  reaction: string;
  logK: number | null;
}

export interface RateEntry {
  name: string;
  parmCount: number;
  isMineral: boolean;
}

export interface DatabaseIndex {
  name: string;
  path: string;
  sha256: string;
  summary: DatabaseSummary;
  elements: ElementGroup[];
  phases: PhaseEntry[];
  gases: PhaseEntry[];
  exchangeSpecies: string[];
  exchangeSites: string[];
  surfaceSites: string[];
  rates: RateEntry[];
  kineticMinerals: string[];
}

export interface RateDetail {
  name: string;
  parmCount: number;
  basic: string;
  isMineral: boolean;
  parms: { index: number; lines: string[] }[];
}

export interface ChemProblem {
  severity: "error" | "warning";
  where: string;
  message: string;
  suggestion: string | null;
}

export interface CheckResult {
  database: string;
  problems: ChemProblem[];
  errors: number;
  warnings: number;
}

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? response.statusText);
  }
  return (await response.json()) as T;
}

export async function listDatabases(): Promise<DatabaseListing[]> {
  return (await json<{ databases: DatabaseListing[] }>("/api/v1/databases")).databases;
}

export async function fetchRate(database: string, rate: string): Promise<RateDetail> {
  return json<RateDetail>(
    `/api/v1/databases/${encodeURIComponent(database)}/rates/${encodeURIComponent(rate)}`,
  );
}

export async function checkChemistry(chemistry: unknown): Promise<CheckResult> {
  return json<CheckResult>("/api/v1/chemistry/check", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(chemistry),
  });
}

/** Every database installed, fetched once. */
export function useDatabaseList(): { databases: DatabaseListing[]; error: string | null } {
  const [databases, setDatabases] = useState<DatabaseListing[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    listDatabases()
      .then((found) => live && setDatabases(found))
      .catch((problem: Error) => live && setError(problem.message));
    return () => {
      live = false;
    };
  }, []);

  return { databases, error };
}

/** One database's contents, refetched when the selected database changes. */
export function useDatabaseIndex(name: string | null): {
  index: DatabaseIndex | null;
  loading: boolean;
  error: string | null;
} {
  const [index, setIndex] = useState<DatabaseIndex | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!name) {
      setIndex(null);
      return;
    }
    let live = true;
    setLoading(true);
    setError(null);

    json<DatabaseIndex>(`/api/v1/databases/${encodeURIComponent(name)}/index`)
      .then((found) => live && setIndex(found))
      .catch((problem: Error) => {
        if (!live) return;
        setIndex(null);
        setError(problem.message);
      })
      .finally(() => live && setLoading(false));

    return () => {
      live = false;
    };
  }, [name]);

  return { index, loading, error };
}

/**
 * Check chemistry against the database as it is edited.
 *
 * Debounced, because it runs on every keystroke in a table and the answer for a
 * half-typed species name is noise. Half a second is long enough to finish a
 * word and short enough that the result still feels attached to the edit.
 */
export function useChemistryCheck(chemistry: unknown, enabled: boolean): CheckResult | null {
  const [result, setResult] = useState<CheckResult | null>(null);
  const serialised = JSON.stringify(chemistry ?? null);

  useEffect(() => {
    if (!enabled) {
      setResult(null);
      return;
    }
    let live = true;
    const timer = setTimeout(() => {
      checkChemistry(JSON.parse(serialised))
        .then((found) => live && setResult(found))
        .catch(() => live && setResult(null));
    }, 500);

    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [serialised, enabled]);

  return result;
}

/** Every master species as a flat list, for pickers and validation hints. */
export function allSpecies(index: DatabaseIndex | null): string[] {
  if (!index) return [];
  return index.elements.flatMap((group) => group.states.map((state) => state.name));
}
