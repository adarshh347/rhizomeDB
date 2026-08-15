"""The constellatory eval harness — PRD §6c, the automatable subset.

Ordinary retrieval eval asks "did the gold passage come back?". A constellatory
engine is measured on different proxies, because the point is *non-obvious*
resonance, not recall of the nearest neighbour:

    mean_rank_pct    where in the full similarity sort the picks sit (0% = the
                     top hit; a band engine should live in the mid-band)
    median_rank      the same, as a raw rank
    ild              intra-list diversity: mean pairwise (1 - cos) across a
                     pick set — the set-spread proxy
    book_spread      distinct books / picks
    cross_book_rate  share of picks from a book other than the seed's
    empty_rate       share of seeds where the engine found nothing at all
    noise_fp_rate    share of *incoherent* theme seeds (word salad) on which the
                     engine still returned something — willingness to find
                     nothing; lower is better
    bridge_recall    share of held-out human/judge-confirmed bridges (source
                     chunk -> target chunk in `edges_judged.jsonl`) whose target
                     appears in the engine's top-k from the source seed
    ms_per_seed      wall time

Every registered engine is run over the same deterministic seed set (every
(N/n)-th chunk) so the rows are comparable. The report is written to
`index/eval_engines.json`, printed by `rhizome eval-engines` and served at
`/api/v2/engines/eval`.
"""
from __future__ import annotations

import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import config, engines
from .engines import Context, intra_list_diversity

REPORT_PATH = config.INDEX_DIR / "eval_engines.json"

# Deliberately incoherent theme seeds: gibberish and cross-domain word salad.
# A constellatory engine should be willing to return nothing for these.
NOISE_SEEDS = [
    "flurb wombat quintessence spanner ozone tuesday",
    "gearbox torque manifold invoice spreadsheet quarterly earnings",
    "zxq vlorp tandril moof plinth grebe",
    "recipe blender pancake sodium bicarbonate teaspoon oven 180",
    "asphalt parking lot barcode receipt refund policy",
    "lorem ipsum dolor sit amet consectetur adipiscing elit",
]

SAMPLE_SEEDS = 2      # per-engine sample: picks for the first N seeds
SAMPLE_PICKS = 4      # ... clipped to this many picks each
SAMPLE_WHY_CHARS = 140

METRIC_COLS = ["n_seeds", "mean_k", "empty_rate", "mean_rank_pct", "median_rank",
               "ild", "book_spread", "cross_book_rate", "noise_fp_rate",
               "bridge_recall", "ms_per_seed"]


# --------------------------------------------------------------------------- #
# persistence                                                                  #
# --------------------------------------------------------------------------- #
def load_report() -> dict | None:
    if not REPORT_PATH.exists():
        return None
    try:
        return json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save_report(report: dict) -> Path:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return REPORT_PATH


# --------------------------------------------------------------------------- #
# seeds                                                                        #
# --------------------------------------------------------------------------- #
def seed_set(ctx: Context, n: int = 40) -> list[str]:
    """Deterministic: every (len/n)-th chunk id (at most n of them)."""
    chunks = ctx.chunks
    total = len(chunks)
    if total == 0 or n <= 0:
        return []
    step = max(1, total // n)
    return [chunks[i]["id"] for i in range(0, total, step)][:n]


def noise_seeds() -> list[str]:
    return list(NOISE_SEEDS)


# --------------------------------------------------------------------------- #
# bridges (held-out)                                                           #
# --------------------------------------------------------------------------- #
def _chunk_id_from_label(label: str, ctx: Context) -> str | None:
    """Judged-edge sources look like '<chunk id> (<author>, <title>)'."""
    if not isinstance(label, str) or not label:
        return None
    if ctx.index_of(label) is not None:
        return label
    head = label.split(" (", 1)[0].strip()
    if head and ctx.index_of(head) is not None:
        return head
    return None


def load_bridges(ctx: Context) -> list[tuple[str, str]]:
    """(src_chunk_id, tgt_chunk_id) pairs from judged edges whose endpoints
    are both chunks present in the context. Deduplicated, order-preserving."""
    from . import graph
    seen, out = set(), []
    for e in graph.load_judged():
        src = _chunk_id_from_label(e.get("source"), ctx)
        tgt = e.get("provenance")
        if src is None or not isinstance(tgt, str) or ctx.index_of(tgt) is None:
            continue
        if src == tgt or (src, tgt) in seen:
            continue
        seen.add((src, tgt))
        out.append((src, tgt))
    return out


# --------------------------------------------------------------------------- #
# metrics                                                                      #
# --------------------------------------------------------------------------- #
def _mean(xs) -> float | None:
    xs = [x for x in xs if x is not None]
    return round(float(np.mean(xs)), 4) if xs else None


def _run(eng, seed, ctx, k):
    t0 = time.perf_counter()
    picks = eng.candidates(seed, ctx, k=k)
    return picks, (time.perf_counter() - t0) * 1000.0


def _sample(seed, picks) -> dict:
    return {
        "seed": seed.chunk_id or seed.label,
        "picks": [{
            "chunk_id": p.get("id"),
            "why": (p.get("why") or "")[:SAMPLE_WHY_CHARS],
            "rank": p.get("rank"),
            "similarity": p.get("similarity"),
        } for p in picks[:SAMPLE_PICKS]],
    }


def eval_engine(eng, ctx: Context, chunk_ids: list[str], noise: list, k: int,
                bridges: list[tuple[str, str]]) -> dict:
    """Run one engine over the seed set, the noise seeds and the bridges."""
    row = {"key": eng.key, "label": eng.label, "ready": True}
    ks, ranks, rank_pcts, ilds, spreads, cross, ms = [], [], [], [], [], [], []
    samples = []
    corpus_size = max(1, len(ctx.chunks))
    for n, cid in enumerate(chunk_ids):
        seed = ctx.seed_from_chunk(cid)
        picks, dt = _run(eng, seed, ctx, k)
        ms.append(dt)
        ks.append(len(picks))
        if n < SAMPLE_SEEDS:
            samples.append(_sample(seed, picks))
        if not picks:
            continue
        for p in picks:
            r = p.get("rank")
            if r is not None:
                ranks.append(int(r))
                rank_pcts.append(100.0 * r / p.get("corpus_size", corpus_size))
        books = [p.get("book_id") for p in picks]
        spreads.append(len(set(books)) / len(picks))
        cross.extend(1.0 if b != seed.book_id else 0.0 for b in books)
        d = intra_list_diversity(ctx, picks)
        if d is not None:
            ilds.append(d)

    n_seeds = len(chunk_ids)
    row.update({
        "n_seeds": n_seeds,
        "mean_k": _mean(ks) if ks else 0.0,
        "empty_rate": round(sum(1 for x in ks if x == 0) / n_seeds, 4) if n_seeds else None,
        "mean_rank_pct": _mean(rank_pcts),
        "median_rank": (int(statistics.median(ranks)) if ranks else None),
        "ild": _mean(ilds),
        "book_spread": _mean(spreads),
        "cross_book_rate": _mean(cross),
        "ms_per_seed": _mean(ms) if ms else None,
    })

    # willingness to find nothing
    if noise:
        fp = 0
        for seed in noise:
            picks, _ = _run(eng, seed, ctx, k)
            fp += 1 if picks else 0
        row["noise_fp_rate"] = round(fp / len(noise), 4)
    else:
        row["noise_fp_rate"] = None

    # held-out bridge recall
    row["n_bridges"] = len(bridges)
    if bridges:
        hits = 0
        for src, tgt in bridges:
            picks, _ = _run(eng, ctx.seed_from_chunk(src), ctx, k)
            if any(p.get("id") == tgt for p in picks):
                hits += 1
        row["bridge_recall"] = round(hits / len(bridges), 4)
    else:
        row["bridge_recall"] = None

    row["sample"] = samples
    return row


def _not_ready_row(eng, reason: str, n_bridges: int) -> dict:
    row = {"key": eng.key, "label": eng.label, "ready": False, "reason": reason}
    for c in METRIC_COLS:
        row[c] = None
    row["n_seeds"] = 0
    row["n_bridges"] = n_bridges
    row["sample"] = []
    return row


# --------------------------------------------------------------------------- #
# report                                                                       #
# --------------------------------------------------------------------------- #
def build_report(ctx: Context | None = None, k: int = 8, engine_keys=None,
                 n_seeds: int = 40, bridges: list[tuple[str, str]] | None = None) -> dict:
    """Run every (ready) engine over the deterministic seed set and return the
    report dict served by `/api/v2/engines/eval`.

    `bridges` overrides the held-out set (tests); by default it comes from
    `edges_judged.jsonl` (chunk-addressed judged edges only)."""
    if ctx is None:
        from .store import Store
        ctx = Context.from_store(Store())
    keys = list(engine_keys) if engine_keys else engines.keys()

    chunk_ids = seed_set(ctx, n_seeds)
    if bridges is None:
        bridges = load_bridges(ctx)
    bridges = list(bridges)

    # noise seeds embed only when vectors exist; otherwise they stay text-only
    # (lexical engines still see them; vector engines return [] which we must
    # not count as "found nothing on purpose") — so per-engine we drop the
    # noise metric when the engine needs vectors we could not embed with.
    can_embed = ctx.has_vectors
    noise_texts = noise_seeds()
    noise = []
    for t in noise_texts:
        try:
            noise.append(ctx.seed_from_text(t, embed=can_embed))
        except Exception:
            noise.append(ctx.seed_from_text(t, embed=False))
    noise_embedded = all(s.vec is not None for s in noise)

    rows = []
    for key in keys:
        eng = engines.get(key)
        ok, why = eng.ready(ctx)
        if not ok:
            rows.append(_not_ready_row(eng, why, len(bridges)))
            continue
        needs_vec = "vectors" in getattr(eng, "needs", [])
        eng_noise = noise if (noise_embedded or not needs_vec) else []
        row = eval_engine(eng, ctx, chunk_ids, eng_noise, k, bridges)
        rows.append(row)

    return {
        "built": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "embed_key": ctx.embed_key,
        "k": int(k),
        "n_seeds": len(chunk_ids),
        "n_noise": len(noise_texts),
        "engines": rows,
    }


# --------------------------------------------------------------------------- #
# presentation                                                                 #
# --------------------------------------------------------------------------- #
def _fmt(v, kind: str) -> str:
    if v is None:
        return "n/a"
    if kind == "int":
        return str(int(v))
    if kind == "pct":
        return f"{v:.1f}%"
    if kind == "rate":
        return f"{v:.2f}"
    if kind == "ms":
        return f"{v:.1f}"
    return f"{v:.3f}"


_TABLE_COLS = [
    ("n_seeds", "seeds", "int"), ("mean_k", "mean_k", "rate"), ("empty_rate", "empty", "rate"),
    ("mean_rank_pct", "rank%", "pct"), ("median_rank", "med_rank", "int"),
    ("ild", "ild", "float"), ("book_spread", "books/k", "rate"),
    ("cross_book_rate", "x-book", "rate"), ("noise_fp_rate", "noise_fp", "rate"),
    ("bridge_recall", "bridge_r", "rate"), ("ms_per_seed", "ms", "ms"),
]


def format_table(report: dict) -> str:
    rows = report.get("engines", [])
    header = ["engine"] + [c[1] for c in _TABLE_COLS]
    ready_rows = [[r["key"]] + [_fmt(r.get(c[0]), c[2]) for c in _TABLE_COLS]
                  for r in rows if r.get("ready", False)]
    widths = [max(len(str(x)) for x in col) for col in zip(header, *ready_rows)]
    widths[0] = max([widths[0]] + [len(r["key"]) for r in rows])
    n_br = next((r.get("n_bridges", 0) for r in rows), 0)
    lines = [
        f"Constellatory engine eval  ·  embed={report.get('embed_key')}  ·  k={report.get('k')}"
        f"  ·  {report.get('n_seeds')} chunk seeds + {report.get('n_noise')} noise seeds"
        f"  ·  {n_br} held-out bridges  ·  built {report.get('built')}",
        "",
        "  ".join(h.ljust(w) if i == 0 else h.rjust(w)
                  for i, (h, w) in enumerate(zip(header, widths))),
        "  ".join("-" * w for w in widths),
    ]
    for r in rows:
        if not r.get("ready", False):
            lines.append(f"{r['key'].ljust(widths[0])}  not ready: {r.get('reason') or ''}".rstrip())
            continue
        cells = [r["key"]] + [_fmt(r.get(c[0]), c[2]) for c in _TABLE_COLS]
        lines.append("  ".join(c.ljust(w) if i == 0 else c.rjust(w)
                               for i, (c, w) in enumerate(zip(cells, widths))))
    lines.append("")
    lines.append("rank% = mean corpus rank of picks (0 = top hit; a band should sit mid-band) · "
                 "ild = mean pairwise 1-cos · noise_fp = share of incoherent seeds still answered "
                 "(lower is better) · bridge_r = held-out judged-bridge recall@k")
    return "\n".join(lines)


def merge_report(existing: dict | None, fresh: dict) -> dict:
    """Fold a partial rebuild (`--engines a,b`) into the stored report so a
    subset run refreshes those rows instead of clobbering the whole table.
    Only merges when the two reports are comparable (same k / embed / seeds)."""
    if not existing or any(existing.get(f) != fresh.get(f)
                           for f in ("k", "embed_key", "n_seeds", "n_noise")):
        return fresh
    new_rows = {r["key"]: r for r in fresh.get("engines", [])}
    rows = [new_rows.pop(r["key"], r) for r in existing.get("engines", [])]
    rows.extend(new_rows.values())
    order = {key: i for i, key in enumerate(engines.keys())}
    rows.sort(key=lambda r: order.get(r["key"], len(order)))
    merged = dict(existing)
    merged.update(built=fresh.get("built"), engines=rows)
    return merged


def main(k: int = 8, engine_keys=None, refresh: bool = False) -> dict:
    report = None if refresh else load_report()
    if report is None or (engine_keys and
                          set(engine_keys) - {r["key"] for r in report.get("engines", [])}):
        fresh = build_report(k=k, engine_keys=engine_keys)
        report = merge_report(report if engine_keys else None, fresh)
        path = save_report(report)
        print(f"wrote {path}")
    else:
        print(f"loaded {REPORT_PATH} (pass refresh to rebuild)")
    print(format_table(report))
    return report


if __name__ == "__main__":
    main()
