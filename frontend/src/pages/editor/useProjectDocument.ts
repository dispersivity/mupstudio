import { useCallback, useEffect, useState } from "react";

/** The project as JSON. Shaped by the backend schema, so it is not typed here. */
export type ProjectDocument = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

export interface FieldProblem {
  field: string;
  message: string;
}

interface SaveResponse {
  ok: boolean;
  problems: FieldProblem[];
  document?: ProjectDocument;
  detail?: { summary: string };
}

/**
 * Load, edit and save the whole project document.
 *
 * The whole document rather than a section: validation is holistic, since a
 * boundary's cell indices only mean something against the grid and a
 * per-period series only against the stress periods. Editing one part in
 * isolation would let the parts contradict each other.
 *
 * A rejected save leaves the edits in place so they can be corrected. Nothing
 * invalid reaches disk.
 */
export function useProjectDocument(path: string | null) {
  const [document, setDocument] = useState<ProjectDocument | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [problems, setProblems] = useState<FieldProblem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [savedSummary, setSavedSummary] = useState<string | null>(null);

  const reload = useCallback(async () => {
    if (!path) {
      setDocument(null);
      return;
    }
    setError(null);
    try {
      const response = await fetch(`/api/v1/projects/document?path=${encodeURIComponent(path)}`);
      if (!response.ok) throw new Error((await response.json()).detail ?? response.statusText);
      setDocument((await response.json()).document);
      setDirty(false);
      setProblems([]);
    } catch (problem) {
      setError((problem as Error).message);
    }
  }, [path]);

  useEffect(() => {
    void reload();
  }, [reload]);

  /** Apply an edit locally. Nothing is written until save. */
  const edit = useCallback((change: (draft: ProjectDocument) => void) => {
    setDocument((current) => {
      if (!current) return current;
      const draft = structuredClone(current);
      change(draft);
      return draft;
    });
    setDirty(true);
    setSavedSummary(null);
  }, []);

  const save = useCallback(async () => {
    if (!path || !document) return false;
    setSaving(true);
    setError(null);
    try {
      const response = await fetch(`/api/v1/projects/document?path=${encodeURIComponent(path)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ document }),
      });
      if (!response.ok) throw new Error((await response.json()).detail ?? response.statusText);

      const body = (await response.json()) as SaveResponse;
      setProblems(body.problems);
      if (body.ok && body.document) {
        setDocument(body.document);
        setDirty(false);
        setSavedSummary(body.detail?.summary ?? "saved");
      }
      return body.ok;
    } catch (problem) {
      setError((problem as Error).message);
      return false;
    } finally {
      setSaving(false);
    }
  }, [path, document]);

  return {
    document,
    dirty,
    saving,
    problems,
    error,
    savedSummary,
    edit,
    save,
    reload,
    /** Problems that mention a field, so an editor can show them in place. */
    problemsFor: (prefix: string) => problems.filter((item) => item.field.startsWith(prefix)),
  };
}
