"use client";

import { useEffect, useState } from "react";
import type { DataSource } from "./types";
import { api } from "./api";
import { clampRefreshSecs, isLiveDataDisabled, providerDisplayName } from "./liveFormat";

/** R-701/R-703: the live state a component renders from. `asOf` is the
 * camelCase mapping of the wire payload's `as_of`. `disabled` is set only when
 * the backend returns its `TRUS_LIVE_DATA=off` marker — renderers treat that
 * as "no live chrome at all" (fall back to the plain manual field), which is
 * distinct from `stale`/`error` (render the last value, badge it, stay
 * editable — R-703). */
export interface LiveValueState {
  value: number | null;
  unit: string | null;
  asOf: string | null;
  source: string;
  stale: boolean;
  error: string | null;
  loading: boolean;
  disabled: boolean;
}

const INERT_STATE: LiveValueState = {
  value: null,
  unit: null,
  asOf: null,
  source: "",
  stale: false,
  error: null,
  loading: false,
  disabled: false,
};

/**
 * Fetches `GET /api/live/{provider}` on mount and every `refresh_secs`
 * seconds, for as long as `dataSource` is present. Returns an inert state (no
 * fetch, no timer) when it's null/undefined. Cleans up its interval on
 * unmount or whenever the data source changes.
 *
 * A failure to reach OUR OWN route (network down, rate-limited, etc.) keeps
 * the last good value in place and marks `stale`/`error` — the route itself
 * already degrades gracefully (a dead provider returns the last-cached value
 * marked `stale`, or a null value with `error` if nothing was ever cached),
 * so this hook only needs its own fallback for the "couldn't even reach the
 * route" case.
 */
export function useLiveValue(dataSource: DataSource | null | undefined): LiveValueState {
  const [state, setState] = useState<LiveValueState>(INERT_STATE);

  useEffect(() => {
    if (!dataSource) {
      setState(INERT_STATE);
      return;
    }
    let cancelled = false;
    const refreshSecs = clampRefreshSecs(dataSource.refresh_secs);
    const source = providerDisplayName(dataSource.provider);

    setState({ ...INERT_STATE, source, loading: true });

    const tick = async () => {
      try {
        const payload = await api.liveValue(dataSource.provider, dataSource.query, refreshSecs);
        if (cancelled) return;
        setState({
          value: payload.value,
          unit: payload.unit,
          asOf: payload.as_of,
          source,
          stale: Boolean(payload.stale),
          error: payload.error,
          loading: false,
          disabled: isLiveDataDisabled(payload.error),
        });
      } catch {
        if (cancelled) return;
        setState((prev) => ({
          ...prev,
          source,
          loading: false,
          disabled: false,
          stale: prev.value !== null,
          error:
            prev.value !== null
              ? "Couldn't reach the live value — showing the last known reading."
              : "Live value unavailable right now.",
        }));
      }
    };

    tick();
    const id = window.setInterval(tick, refreshSecs * 1000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
    // dataSource's identity may change every render (a fresh object literal
    // from the parsed config); key the effect off its actual content instead.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dataSource?.provider, dataSource ? JSON.stringify(dataSource.query) : null, dataSource?.refresh_secs]);

  return state;
}
