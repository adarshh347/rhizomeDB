// Which retrieval engine the reader is asking, and whether that choice is one
// the server actually offers.
import type { EngineCard } from "../api/types";

export const ENGINE_STORAGE = "rhizome.engine";
export const DEFAULT_ENGINE = "band";

// The retrieval engine choice: ?engine= in the URL (shareable) wins, then the
// last choice remembered in localStorage, then the resonance band.
export function initialEngine(fromUrl: string | null): string {
  if (fromUrl) return fromUrl;
  try {
    return localStorage.getItem(ENGINE_STORAGE) || DEFAULT_ENGINE;
  } catch {
    return DEFAULT_ENGINE;
  }
}

// Neither source is trusted: a hand-edited ?engine=bogus or a key left in
// localStorage by an older build names an engine the server does not have, and
// then every stream is an HTTP 400 the EventSource cannot surface while the
// <select> — matching no <option> — quietly shows the first engine instead, so
// re-picking it fires no change and the reader is stuck.
//
// Returns the key to fall back to, or null when nothing needs to change: the
// roster has not arrived yet (an empty list is "unknown", not "invalid" — a
// valid key must not flash back to the default), or the key is in it. A
// not-ready engine is still a real engine and stays selectable; the panel shows
// its reason.
export function engineFallback(key: string, engines: EngineCard[]): string | null {
  if (engines.length === 0) return null;
  if (engines.some((e) => e.key === key)) return null;
  return DEFAULT_ENGINE;
}
