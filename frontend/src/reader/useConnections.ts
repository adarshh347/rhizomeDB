import { useEffect, useState } from "react";

import { type ConnSeed, sse } from "../api/client";
import { exploreUrl } from "../api/explore";
import type { EngineRef, ExploreCandidate, ExploreSeed, ExploreVerdict } from "../api/types";

// Streams the connection engine seeded by a passage or a piece of text (SSE
// /api/v2/explore). The chosen retrieval engine's picks arrive first and are
// useful on their own — geometry-only, no API key. When an LLM is configured
// the genuine-vs-forced verdicts and a synthesized reading follow.
export type ConnStatus =
  | "geometry"
  | "judging"
  | "synthesizing"
  | "done"
  | "error";

export interface ConnectionsState {
  seed: ExploreSeed | null;
  engine: EngineRef | null;
  candidates: ExploreCandidate[];
  verdicts: Record<number, ExploreVerdict>;
  exploration: string | null;
  notes: string[];
  status: ConnStatus;
  error: string | null;
}

const initial = (): ConnectionsState => ({
  seed: null,
  engine: null,
  candidates: [],
  verdicts: {},
  exploration: null,
  notes: [],
  status: "geometry",
  error: null,
});

export function useConnections(seed: ConnSeed | null, engineKey: string): ConnectionsState {
  const [state, setState] = useState<ConnectionsState>(initial);
  const mode = seed?.mode ?? null;
  const value = seed?.value ?? null;
  const kind = seed?.kind ?? null;

  useEffect(() => {
    if (!mode || !value) return;
    setState(initial());

    const url = exploreUrl({ mode, value, ...(kind ? { kind } : {}) }, engineKey);
    const control = sse(
      url,
      {
        seed: (d) => setState((s) => ({ ...s, seed: d })),
        engine: (d) => setState((s) => ({ ...s, engine: d })),
        candidates: (d) => setState((s) => ({ ...s, candidates: d.items ?? [] })),
        stage: (d) =>
          setState((s) => ({
            ...s,
            status:
              d.name === "judge" ? "judging" : d.name === "synthesize" ? "synthesizing" : s.status,
          })),
        verdicts: (d) =>
          setState((s) => ({
            ...s,
            verdicts: Object.fromEntries(
              (d.items ?? []).map((v: ExploreVerdict) => [v.index, v]),
            ),
          })),
        exploration: (d) => setState((s) => ({ ...s, exploration: d.text })),
        note: (d) => setState((s) => ({ ...s, notes: [...s.notes, d.text] })),
        error: (d) => {
          control.stop();
          setState((s) => ({ ...s, status: "error", error: d.text }));
        },
        done: () => {
          control.stop();
          setState((s) => ({ ...s, status: "done" }));
        },
      },
      (message) => setState((s) => ({ ...s, status: "error", error: s.error ?? message })),
    );

    return () => control.stop();
  }, [mode, value, kind, engineKey]);

  return state;
}
