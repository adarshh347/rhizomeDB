import type { ConnSeed } from "./client";

// The /explore SSE URL for a seed. `seed_kind` is sent only when the caller
// knows it: a sentence picked out of the text is a `selection`, not a question
// the reader typed, and the server uses that to choose its prompt — a selection
// must not be answered by the long-answer synthesis meant for questions.
export function exploreUrl(seed: ConnSeed, engineKey: string, candidates = 8): string {
  return (
    `/api/v2/explore?mode=${seed.mode}&value=${encodeURIComponent(seed.value)}` +
    `&candidates=${candidates}&engine=${encodeURIComponent(engineKey)}` +
    (seed.kind ? `&seed_kind=${encodeURIComponent(seed.kind)}` : "")
  );
}
