// node --test src/__tests__/
//
// The engine key the reader carries (?engine= or localStorage) against the
// roster the server actually offers.
import { test } from "node:test";
import assert from "node:assert/strict";

import { DEFAULT_ENGINE, engineFallback } from "../reader/engineChoice.ts";
import { exploreUrl } from "../api/explore.ts";
import type { EngineCard } from "../api/types.ts";

const card = (key: string, ready = true): EngineCard => ({
  key,
  label: key,
  blurb: "",
  needs: [],
  params: {},
  ready,
  reason: ready ? "" : "not built",
});

const roster = [card("band"), card("plain"), card("structural", false)];

test("a key the roster does not offer falls back to the default", () => {
  assert.equal(engineFallback("bogus", roster), DEFAULT_ENGINE);
  assert.equal(engineFallback("", roster), DEFAULT_ENGINE);
});

test("a key the roster offers is left alone — including a not-ready engine", () => {
  assert.equal(engineFallback("plain", roster), null);
  assert.equal(engineFallback("structural", roster), null);
});

test("before the roster arrives nothing is reset", () => {
  assert.equal(engineFallback("concept", []), null);
});

test("a selection seed asks the server for the selection prompt", () => {
  assert.equal(
    exploreUrl({ mode: "theme", value: "the thing itself", kind: "selection" }, "band"),
    "/api/v2/explore?mode=theme&value=the%20thing%20itself&candidates=8&engine=band" +
      "&seed_kind=selection",
  );
});

test("a chunk seed sends no seed_kind", () => {
  const url = exploreUrl({ mode: "chunk", value: "being-and-truth#0036" }, "walk");
  assert.equal(
    url,
    "/api/v2/explore?mode=chunk&value=being-and-truth%230036&candidates=8&engine=walk",
  );
  assert.ok(!url.includes("seed_kind"));
});
