// node --test src/__tests__/
//
// The compare panel's "shared with the selected engine" arithmetic. /connect/
// compare only runs the *ready* engines, so the selected engine may have no row
// at all — and then there is no denominator to show.
import { test } from "node:test";
import assert from "node:assert/strict";

import { compareBasis } from "../reader/compare.ts";
import type { CompareResponse, ConnectItem, ExploreSeed } from "../api/types.ts";

const item = (chunkId: string): ConnectItem =>
  ({ chunk_id: chunkId, index: 0, author: "", title: "", page: null, text: "" }) as ConnectItem;

const response = (results: CompareResponse["results"]): CompareResponse => ({
  seed: {} as ExploreSeed,
  results,
  overlap: { keys: results.map((r) => r.key), matrix: [] },
});

const data = response([
  { key: "band", label: "Resonance band", items: [item("a#1"), item("b#2")], ms: 1 },
  { key: "plain", label: "Nearest (plain RAG)", items: [item("a#1"), item("c#3")], ms: 1 },
]);

test("the selected engine's picks are the basis for the shared count", () => {
  const basis = compareBasis(data, "band");
  assert.equal(basis.inComparison, true);
  assert.equal(basis.showShared, true);
  assert.equal(basis.total, 2);
  assert.equal(basis.label, "Resonance band");
  assert.deepEqual([...basis.ids].sort(), ["a#1", "b#2"]);
});

test("an engine missing from the results shows no shared badges at all", () => {
  // `marks` with no marks yet, `structural` unbuilt: not ready, so not compared.
  const basis = compareBasis(data, "marks");
  assert.equal(basis.inComparison, false, "it was not compared");
  assert.equal(basis.showShared, false, "so no row may claim '0/1 shared'");
  assert.equal(basis.total, 0, "and there is no fabricated denominator");
  assert.equal(basis.ids.size, 0);
  assert.equal(basis.label, null);
});

test("an engine that was compared but found nothing shares nothing", () => {
  const empty = response([
    ...data.results,
    { key: "echo", label: "Echoes in this book", items: [], ms: 1 },
  ]);
  const basis = compareBasis(empty, "echo");
  assert.equal(basis.inComparison, true);
  assert.equal(basis.showShared, false);
  assert.equal(basis.total, 0);
});
