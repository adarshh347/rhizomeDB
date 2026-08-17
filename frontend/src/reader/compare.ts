// Reading /connect/compare against the engine the reader has selected.
import type { CompareResponse } from "../api/types";

export interface CompareBasis {
  // The selected engine has a row in the results — it was compared at all.
  inComparison: boolean;
  // Its label as the server names it (null when it was not compared).
  label: string | null;
  // Its pick set, for "shared with mine" marking.
  ids: Set<string>;
  // How many picks it returned — the denominator of the shared badge.
  total: number;
  // Show shared badges at all: only when there is a real pick set to share.
  showShared: boolean;
}

// /connect/compare is called without `engines`, so the server compares the
// engines that are *ready*. The selected engine can be missing from the results
// (marks with no marks yet, structural unbuilt) — and then there is no pick set
// to compare against: every "0/1 shared" badge would be a number the comparison
// never computed. Say the engine is not in the comparison instead of inventing
// a denominator.
export function compareBasis(data: CompareResponse, selected: string): CompareBasis {
  const mine = data.results.find((r) => r.key === selected);
  const items = mine?.items ?? [];
  return {
    inComparison: !!mine,
    label: mine?.label ?? null,
    ids: new Set(items.map((i) => i.chunk_id)),
    total: items.length,
    showShared: !!mine && items.length > 0,
  };
}
