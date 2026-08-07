/**
 * Fetching values through time for the selected cells.
 *
 * Separate from the panel that draws them so the component file exports only
 * components, and so the fetching can be tested without a DOM.
 */

import { useEffect, useState } from "react";
import type { SeriesResponse } from "./TimeSeriesPanel";

export function useCellSeries(
  datasetId: string,
  component: string | null,
  tokens: string[],
  params: URLSearchParams,
) {
  const [data, setData] = useState<SeriesResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const key = tokens.join(",");

  useEffect(() => {
    if (!component || tokens.length === 0) {
      setData(null);
      setError(null);
      return;
    }

    let cancelled = false;
    setLoading(true);
    const query = new URLSearchParams(params);
    query.set("component", component);
    query.set("cells", key);

    fetch(`/api/v1/datasets/${encodeURIComponent(datasetId)}/series?${query}`)
      .then(async (response) => {
        const body = await response.json();
        if (!response.ok) throw new Error(body.detail ?? response.statusText);
        return body as SeriesResponse;
      })
      .then((body) => {
        if (!cancelled) {
          setData(body);
          setError(null);
        }
      })
      .catch((problem: Error) => {
        if (!cancelled) setError(problem.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
    // params is rebuilt each render; its string form is what matters.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datasetId, component, key, params.toString()]);

  return { data, loading, error };
}
