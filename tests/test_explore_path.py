"""The explore path: what the run decides *before* it spends an LLM call.

Three things are pinned here, all of them about honesty of effort:

  * **the long-answer decision** (`run_explore(long_answer=…)`, `?seed_kind=`) —
    a typed question earns the long synthesis prompt; a sentence the reader
    highlighted arrives as a theme seed too, and must not;
  * **the structural axis** — one `abstract_seed` round-trip, paid only when
    there are candidates to measure it against and only when the engine has not
    already supplied the axis itself;
  * **the band's parity, and its one qualification** — above the context's noise
    floor `band` is byte-identical to `Store.connections()`; below it, band
    returns nothing where `Store.connections()` still answers. That difference
    is the willingness to find nothing (VISION.md, PRD §6c), not a parity break.

The explore run is driven against the in-memory fixture corpus with the LLM
layer stubbed, so no index and no provider key are needed.
"""
import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fixture_corpus import make_corpus  # noqa: E402

from rhizome import config, embed as embed_mod, engines, llm, reader_service as rs
from rhizome.engines import Context
from rhizome.engines.base import best_match


# --------------------------------------------------------------------------- #
# stubs                                                                        #
# --------------------------------------------------------------------------- #
class _Client:
    """Stands in for an LLMClient: run_explore only reads usage off it."""
    provider = "stub"
    last_usage: dict = {}
    total_usage: dict = {}


class _Engine:
    """Stands in for `rhizome.engine.Engine` (the LLM-carrying one)."""
    def __init__(self, client=None):
        self.client = client


def _verdict(i):
    return types.SimpleNamespace(
        candidate_index=i, connected=True, forced_risk="low",
        bridge_concept="bridge", articulation="articulation",
        relation_to_query="relation", unique_shade="shade", confidence=0.9)


def _brainstorm():
    return types.SimpleNamespace(interpretations=[], comparisons=[], follow_ups=[])


class ExploreHarness(unittest.TestCase):
    """A run_explore driver over the fixture corpus with the LLM stubbed out.

    `self.calls` counts what the run actually spent: `abstract_seed` (the
    structural axis) and the `long` flag every `synthesize` was called with.
    """

    def setUp(self):
        self.chunks, self.vecs = make_corpus()
        self.ctx = Context.from_arrays(self.chunks, self.vecs)
        self.theme_vec = self.vecs[self.ctx.index_of("alpha#0005")]

        # process-wide singletons reader_service caches — swapped, then restored
        self._saved = (rs._ENGINE, dict(rs._CONTEXTS))
        rs._ENGINE = _Engine(_Client())
        rs._CONTEXTS.clear()
        rs._CONTEXTS[config.DEFAULT_EMBED] = self.ctx
        self.addCleanup(self._restore)

        self.calls = {"abstract_seed": 0, "synthesize_long": [], "judge": 0}
        p = [
            mock.patch.object(embed_mod, "embed_query",
                              lambda text, key=None: self.theme_vec),
            mock.patch.object(llm, "abstract_seed", self._abstract_seed),
            mock.patch.object(llm, "judge_connections", self._judge),
            mock.patch.object(llm, "synthesize", self._synthesize),
            mock.patch.object(llm, "brainstorm", lambda *a, **kw: _brainstorm()),
        ]
        for patcher in p:
            patcher.start(); self.addCleanup(patcher.stop)

    def _restore(self):
        rs._ENGINE, saved_ctxs = self._saved
        rs._CONTEXTS.clear(); rs._CONTEXTS.update(saved_ctxs)

    # -- stubbed LLM surface ---------------------------------------------------
    def _abstract_seed(self, seed_text, client):
        self.calls["abstract_seed"] += 1
        return "the move beneath the words"

    def _judge(self, seed_text, candidates, client):
        self.calls["judge"] += 1
        return [_verdict(i) for i in range(len(candidates))]

    def _synthesize(self, seed_text, confirmed, client, long=False):
        self.calls["synthesize_long"].append(long)
        return "an exploration"

    # -- driver ----------------------------------------------------------------
    def run_explore(self, **kwargs):
        events = []
        kwargs.setdefault("k", 4)
        rs.run_explore(lambda name, data: events.append((name, data)), **kwargs)
        return events

    @staticmethod
    def names(events):
        return [name for name, _ in events]

    @staticmethod
    def payload(events, name):
        return next(data for n, data in events if n == name)


# --------------------------------------------------------------------------- #
# B1 — the long-answer decision is explicit, not inferred from the seed mode   #
# --------------------------------------------------------------------------- #
class LongAnswerTests(ExploreHarness):

    def test_typed_theme_still_gets_the_long_synthesis(self):
        """The default (`long_answer=None`) keeps today's inference."""
        self.run_explore(theme="what is releasement?")
        self.assertEqual(self.calls["synthesize_long"], [True])

    def test_selection_derived_theme_does_not_get_the_long_synthesis(self):
        """A highlighted sentence is a passage, not a question — even though it
        reaches run_explore as `theme=`."""
        self.run_explore(theme="Thinking is a waiting in the open region.",
                         long_answer=False)
        self.assertEqual(self.calls["synthesize_long"], [False])

    def test_long_answer_true_overrides_a_chunk_seed(self):
        self.run_explore(chunk_id="alpha#0005", long_answer=True)
        self.assertEqual(self.calls["synthesize_long"], [True])

    def test_chunk_seed_stays_short_by_default(self):
        self.run_explore(chunk_id="alpha#0005")
        self.assertEqual(self.calls["synthesize_long"], [False])

    def test_every_sse_event_survives_the_new_parameter(self):
        """The parameter must not disturb the stream the reader listens to."""
        base = self.names(self.run_explore(theme="releasement"))
        with_flag = self.names(self.run_explore(theme="releasement", long_answer=False))
        self.assertEqual(base, with_flag)
        for name in ("seed", "engine", "candidates", "verdicts", "exploration", "done"):
            self.assertIn(name, base)


class SeedKindRouteTests(unittest.TestCase):
    """The API's `?seed_kind=` is what carries the decision from the reader."""

    def _explore(self, **kwargs):
        from rhizome import api
        seen = {}

        def capture(emit, **kw):
            seen.update(kw)

        with mock.patch.object(api.rs, "index_ready", lambda: True), \
             mock.patch.object(api.rs, "run_explore", capture), \
             mock.patch.object(api, "_sse", lambda run: run(lambda *a: None)):
            request = types.SimpleNamespace(query_params={})
            api.explore(request, **kwargs)
        return seen

    def test_default_keeps_a_typed_theme_long(self):
        self.assertIs(self._explore(mode="theme", value="what is truth?")["long_answer"], True)

    def test_seed_kind_question_is_long(self):
        kw = self._explore(mode="theme", value="what is truth?", seed_kind="question")
        self.assertIs(kw["long_answer"], True)

    def test_seed_kind_selection_is_not_long(self):
        kw = self._explore(mode="theme", value="a highlighted sentence",
                           seed_kind="selection")
        self.assertIs(kw["long_answer"], False)

    def test_seed_kind_passage_is_not_long(self):
        kw = self._explore(mode="theme", value="a pasted passage", seed_kind="passage")
        self.assertIs(kw["long_answer"], False)

    def test_chunk_and_random_modes_are_untouched(self):
        for kwargs in ({"mode": "chunk", "value": "alpha#0005"}, {"mode": "random"}):
            with self.subTest(**kwargs):
                self.assertNotIn("long_answer", self._explore(**kwargs))


# --------------------------------------------------------------------------- #
# B2 — the structural axis is paid for only when it buys something            #
# --------------------------------------------------------------------------- #
class StructuralAxisCostTests(ExploreHarness):

    def _empty_run(self):
        # min_sim above every cosine in the fixture → the band finds nothing
        return self.run_explore(theme="releasement",
                                engine_params={"min_sim": 0.999})

    def test_no_llm_call_when_the_seed_finds_nothing(self):
        events = self._empty_run()
        self.assertEqual(self.calls["abstract_seed"], 0,
                         "an empty run must not spend an abstract_seed round-trip")
        self.assertEqual(self.payload(events, "candidates")["items"], [])
        self.assertNotIn("abstraction", self.names(events))
        self.assertIn("note", self.names(events))
        self.assertEqual(self.names(events)[-1], "done")

    def test_one_llm_call_when_candidates_come_back(self):
        events = self.run_explore(theme="releasement")
        self.assertTrue(self.payload(events, "candidates")["items"])
        self.assertEqual(self.calls["abstract_seed"], 1)

    def test_the_candidates_event_still_carries_the_structural_axis(self):
        """The reordering must not cost the 'candidates' event its axis."""
        events = self.run_explore(theme="releasement")
        names = self.names(events)
        self.assertLess(names.index("candidates"), names.index("abstraction"))
        for item in self.payload(events, "candidates")["items"]:
            self.assertIsNotNone(item["structural_similarity"])

    def test_no_llm_call_when_the_engine_supplies_its_own_axis(self):
        """`structural` (and fused picks from it) already carry the axis from a
        persisted matrix — re-deriving it with an LLM is pure waste."""
        band = engines.get("band")

        class _Structural:
            key, label, blurb = "structural", "Structural", ""
            params: dict = {}

            def ready(self, ctx):
                return True, ""

            def candidates(self, seed, ctx, k=8, **params):
                picks = band.candidates(seed, ctx, k=k)
                for i, p in enumerate(picks):
                    p["structural_similarity"] = round(0.9 - 0.01 * i, 4)
                return picks

        with mock.patch.object(engines, "get", lambda key: _Structural()):
            events = self.run_explore(theme="releasement", engine="structural")
        items = self.payload(events, "candidates")["items"]
        self.assertTrue(items)
        self.assertEqual(self.calls["abstract_seed"], 0)
        # …and the axis still reaches the UI, read off the picks themselves
        self.assertEqual([i["structural_similarity"] for i in items][:2], [0.9, 0.89])

    def test_needs_struct_axis_predicate(self):
        self.assertTrue(rs._needs_struct_axis([{"id": "a"}]))
        self.assertTrue(rs._needs_struct_axis([{"structural_similarity": 0.7},
                                               {"structural_similarity": None}]))
        self.assertFalse(rs._needs_struct_axis([{"structural_similarity": 0.7}]))


# --------------------------------------------------------------------------- #
# B4 — band parity above the noise floor, silence below it                    #
# --------------------------------------------------------------------------- #
class BandGateParityTests(unittest.TestCase):
    """`band` is the parity oracle *and* it is gated. Both halves, on one
    gated context: identical to `Store.connections()` above the floor, `[]`
    below it while a direct call still answers. The fixture parity test in
    `test_engines.py` uses `Context.from_arrays` (ungated) and so cannot see
    the gate at all — this is the test that can.
    """

    def setUp(self):
        self.chunks, self.vecs = make_corpus()
        self.ctx = Context.from_arrays(self.chunks, self.vecs)
        self.band = engines.get("band")
        # a seed the band actually answers for, so "identical" has content
        self.seed = self.ctx.seed_from_chunk("alpha#0010")
        self.best = best_match(self.seed, self.ctx)

    @staticmethod
    def _geometry(picks):
        """A band pick minus the engine's own labelling — what parity is about."""
        return [{k: v for k, v in p.items() if k not in ("score", "path", "why")}
                for p in picks]

    def _direct(self):
        return self.ctx.store.connections(self.seed.vec, seed_book_id=self.seed.book_id,
                                          seed_author=self.seed.author, k=6)

    def test_above_the_floor_band_is_byte_identical_to_store_connections(self):
        self.ctx.noise_floor = self.best - 0.05
        direct = self._direct()
        self.assertTrue(direct)
        self.assertEqual(self._geometry(self.band.candidates(self.seed, self.ctx, k=6)),
                         direct)

    def test_below_the_floor_band_finds_nothing_where_the_store_still_answers(self):
        self.ctx.noise_floor = self.best + 0.05
        self.assertTrue(self._direct(), "the store's geometry is unchanged…")
        self.assertEqual(self.band.candidates(self.seed, self.ctx, k=6), [],
                         "…and the noise-floor gate is the only difference")

    def test_the_gate_is_the_only_difference(self):
        """Same seed, same context, floor moved across the seed's best match."""
        self.ctx.noise_floor = self.best + 0.05
        gated = self.band.candidates(self.seed, self.ctx, k=6)
        self.ctx.noise_floor = self.best - 0.05
        open_ = self.band.candidates(self.seed, self.ctx, k=6)
        self.assertEqual(gated, [])
        self.assertEqual(self._geometry(open_), self._direct())


if __name__ == "__main__":
    unittest.main()
