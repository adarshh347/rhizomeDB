import { useEffect, useState } from "react";

import type { ExploreCandidate, ExploreSeed, ExploreVerdict } from "../api/types";

// Streams the connection engine seeded by a passage (SSE /api/v2/explore). The
// resonance band (cross-book passages related-but-distant) arrives first and is
// useful on its own — geometry-only, no API key. When an LLM is configured the
// genuine-vs-forced verdicts and a synthesized reading follow.
export type ConnStatus =
  | "geometry"
  | "judging"
  | "synthesizing"
  | "done"
  | "error";

export interface ConnectionsState {
  seed: ExploreSeed | null;
  candidates: ExploreCandidate[];
  verdicts: Record<number, ExploreVerdict>;
  exploration: string | null;
  notes: string[];
  status: ConnStatus;
  error: string | null;
}

const initial = (): ConnectionsState => ({
  seed: null,
  candidates: [],
  verdicts: {},
  exploration: null,
  notes: [],
  status: "geometry",
  error: null,
});

export function useConnections(chunkId: string | null): ConnectionsState {
  const [state, setState] = useState<ConnectionsState>(initial);

  useEffect(() => {
    if (!chunkId) return;
    setState(initial());
    let finished = false;

    const url = `/api/v2/explore?mode=chunk&value=${encodeURIComponent(chunkId)}&candidates=8`;
    const es = new EventSource(url);
    const on = (name: string, fn: (data: any) => void) =>
      es.addEventListener(name, (e) => fn(JSON.parse((e as MessageEvent).data)));

    on("seed", (d) => setState((s) => ({ ...s, seed: d })));
    on("candidates", (d) => setState((s) => ({ ...s, candidates: d.items })));
    on("stage", (d) =>
      setState((s) => ({
        ...s,
        status: d.name === "judge" ? "judging" : d.name === "synthesize" ? "synthesizing" : s.status,
      })),
    );
    on("verdicts", (d) =>
      setState((s) => ({
        ...s,
        verdicts: Object.fromEntries(d.items.map((v: ExploreVerdict) => [v.index, v])),
      })),
    );
    on("exploration", (d) => setState((s) => ({ ...s, exploration: d.text })));
    on("note", (d) => setState((s) => ({ ...s, notes: [...s.notes, d.text] })));
    on("error", (d) => {
      finished = true;
      setState((s) => ({ ...s, status: "error", error: d.text }));
      es.close();
    });
    on("done", () => {
      finished = true;
      setState((s) => ({ ...s, status: "done" }));
      es.close();
    });
    // The server closes the stream after "done"; EventSource reads that as an
    // error and would otherwise reconnect (re-running the whole explore).
    es.onerror = () => {
      if (finished) return;
      finished = true;
      setState((s) => ({ ...s, status: "error", error: s.error ?? "Connection lost." }));
      es.close();
    };

    return () => {
      finished = true;
      es.close();
    };
  }, [chunkId]);

  return state;
}
