"""RhizomeDB command line.

  python -m rhizome.cli build                 # catalog -> chunk -> embed
  python -m rhizome.cli catalog               # (re)generate catalog.json
  python -m rhizome.cli explore --theme "the flight of the gods"
  python -m rhizome.cli explore --random
  python -m rhizome.cli explore --chunk being-and-truth#0042
  python -m rhizome.cli wander --random --steps 3
"""
import argparse
import textwrap

from . import (catalog, chunk as chunk_mod, embed as embed_mod, config,
               notes as notes_mod, graph as graph_mod, usage as usage_mod)


def _wrap(s, width=88, indent="    "):
    return textwrap.fill(s, width=width, initial_indent=indent, subsequent_indent=indent)


def cmd_catalog(_):
    cat = catalog.build_catalog()
    catalog.save_catalog(cat)
    print(f"Wrote {config.CATALOG_PATH} ({len(cat)} books):")
    for bid, m in cat.items():
        who = m.get("author") or "??? (edit catalog.json)"
        print(f"  {bid:42s} {who} — {m.get('title')}")


def cmd_notes(_):
    recs = notes_mod.build_annotations()
    notes_mod.digest(recs)


def cmd_graph(_):
    edges = graph_mod.build_edges()
    graph_mod.digest(edges)


def _theme_from_note(note_id: str) -> str:
    """Seed text for `explore --note`: the note's densest annotation
    (a sutra/anchor), else its first correlation."""
    recs = [r for r in notes_mod.load_annotations() if r["note_id"] == note_id]
    if not recs:
        raise SystemExit(f"No annotations for note '{note_id}'. Run:  rhizome notes")
    seeds = [r for r in recs if r["role"] == "seed" and r["text"]]
    pick = max(seeds, key=lambda r: len(r["text"])) if seeds else \
        next((r for r in recs if r["role"] == "edge" and r["text"]), recs[0])
    print(f"(seeding from {note_id} · {pick['type']}: \"{pick['text'][:70]}…\")\n")
    return pick["text"]


def cmd_build(args):
    """Multi-resolution build. `--levels` selects rungs on the SOLID→LIQUID dial.
    Idempotent: the chunk level is only (re)built when missing or --force, so
    existing embeddings/ids/annotations are preserved."""
    from . import chunking, enrich
    levels = [l.strip() for l in (args.levels or "chunk").split(",") if l.strip()]
    print(f"Building levels: {levels}")
    if "chunk" in levels:
        if config.CHUNKS_PATH.exists() and not args.force:
            print("1) chunk     exists — skipping (use --force to rebuild)")
        else:
            print("1) chunk"); catalog.save_catalog(catalog.build_catalog())
            chunk_mod.build_chunks(); embed_mod.build_embeddings()
    if "parent" in levels:
        print("2) parent")
        chunking.build_parents(books=args.book, method=args.method)
        chunking.build_level_embeddings("parent")
    if "proposition" in levels:
        print("3) proposition")
        if args.llm:
            enrich.build_propositions(books=args.book, sample=args.sample)
        else:
            chunking.build_propositions_sentences(books=args.book, sample=args.sample)
        chunking.build_level_embeddings("proposition")
    print("Done.  Visualise:  python -m rhizome.cli chunkmap")


def cmd_embed(args):
    keys = args.model or [config.DEFAULT_EMBED]
    if keys == ["all"]:
        keys = list(config.EMBED_MODELS)
    for key in keys:
        embed_mod.build_embeddings(key)


def cmd_embed_level(args):
    from . import chunking
    chunking.build_level_embeddings(args.level)


def cmd_enrich(args):
    from . import enrich, chunking
    if args.contextual:
        enrich.enrich_contextual(level=args.level, books=args.book, sample=args.sample)
        chunking.build_level_embeddings(args.level)   # re-embed blurb+text
    else:
        print("nothing to do — pass --contextual")


def cmd_characterize(args):
    from . import enrich
    enrich.characterize(level=args.level, books=args.book, sample=args.sample)


def cmd_chunkmap(_):
    from tools import chunkmap
    chunkmap.build()


def cmd_concepts(args):
    """Extract core concepts per chunk (the content lens). Heuristic by default;
    --llm for clean conceptual phrases when a provider key is set."""
    from . import concepts
    if args.llm:
        concepts.extract_llm(level=args.level, books=args.book, sample=args.sample)
    else:
        concepts.extract_heuristic(level=args.level, top_concepts=args.top)


def cmd_conceptmap(_):
    from tools import conceptmap
    conceptmap.build()


def cmd_eval_embed(_):
    from . import eval_embed
    eval_embed.main()


def _print_candidate(i, c, judged):
    page = f", p.{c['page']}" if c.get("page") else ""
    head = f"  [{i}] {c.get('author') or 'Unknown'} — {c.get('title') or c['book_id']}{page}"
    print(head + f"   (sim {c.get('similarity')})")
    if judged and "bridge_concept" in c:
        print(f"      bridge: {c['bridge_concept']}  ·  confidence {c['confidence']:.2f}")
        print(_wrap(c["articulation"], indent="      "))
    print(_wrap(c["text"][:280] + ("…" if len(c["text"]) > 280 else ""), indent="      "))
    print()


def _print_step(step):
    print("=" * 90)
    print(f"SEED — {step['seed_label']}")
    print(_wrap(step["seed_text"][:400] + ("…" if len(step["seed_text"]) > 400 else "")))
    if step.get("abstraction"):
        print()
        print(_wrap(f"structural seed → {step['abstraction']}", indent="    "))
    print()
    if step["mode"] == "geometry-only":
        print("Resonance band (cross-author, distant-but-related; no LLM — set "
              "ANTHROPIC_API_KEY for judging + synthesis):\n")
        for i, c in enumerate(step["candidates"]):
            _print_candidate(i, c, judged=False)
        return
    conf = step["confirmed"]
    print(f"Confirmed connections ({len(conf)} of {len(step['candidates'])} candidates "
          f"survived the not-forced filter):\n")
    for i, c in enumerate(conf):
        _print_candidate(i, c, judged=True)
    if step["exploration"]:
        print("-" * 90)
        print("EXPLORATION\n")
        print(textwrap.fill(step["exploration"], width=90))
        print()


def _show_usage(step):
    """Print the token breakdown for a run and accrue it into the daily ledger
    (Gemini only). No-op when geometry-only / no LLM tokens were spent."""
    rep = (step or {}).get("usage")
    if not rep or not rep.get("total_tokens"):
        return
    today = usage_mod.record_report(rep)   # accumulate today's free-tier usage
    text = usage_mod.format_report(rep, today=today)
    if text:
        print("-" * 90)
        print(text)
        print()


def cmd_explore(args):
    from .engine import Engine
    eng = Engine(seed_int=args.seed)
    theme = args.theme
    if getattr(args, "note", None):
        theme = _theme_from_note(args.note)
    step = eng.explore(theme=theme, chunk_id=args.chunk, random=args.random,
                       structural=args.structural, k=args.candidates)
    _print_step(step)
    _show_usage(step)


def cmd_wander(args):
    from .engine import Engine
    eng = Engine(seed_int=args.seed)
    path = eng.wander(steps=args.steps, theme=args.theme, chunk_id=args.chunk,
                      random=args.random or (args.theme is None and args.chunk is None),
                      structural=args.structural, k=args.candidates)
    for n, step in enumerate(path, 1):
        print(f"\n########## STEP {n}/{len(path)} ##########")
        _print_step(step)
        _show_usage(step)


def cmd_usage(_):
    """How much of today's Gemini free-tier budget is already spent."""
    print(usage_mod.format_day())


def main():
    p = argparse.ArgumentParser(prog="rhizome", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("catalog", help="(re)generate catalog.json").set_defaults(func=cmd_catalog)

    b = sub.add_parser("build", help="multi-resolution build (--levels parent,chunk,proposition)")
    b.add_argument("--levels", default="chunk", help="comma list: parent,chunk,proposition")
    b.add_argument("--method", default=None, help="parent chunker: recursive|semantic")
    b.add_argument("--llm", action="store_true", help="proposition via LLM (else sentence-split)")
    b.add_argument("--sample", type=int, default=None, help="cap units for the LLM passes")
    b.add_argument("--book", nargs="+", default=None, help="scope to book id(s)")
    b.add_argument("--force", action="store_true", help="rebuild the chunk level even if present")
    b.set_defaults(func=cmd_build)

    em = sub.add_parser("embed", help="(re)build embeddings for one/more models")
    em.add_argument("--model", nargs="+",
                    help=f"model key(s) from {list(config.EMBED_MODELS)}, or 'all'")
    em.set_defaults(func=cmd_embed)
    el = sub.add_parser("embed-level", help="(re)build a level's embeddings (parent|proposition)")
    el.add_argument("level")
    el.set_defaults(func=cmd_embed_level)

    en = sub.add_parser("enrich", help="contextual enrichment (R3): context blurb + re-embed")
    en.add_argument("--contextual", action="store_true")
    en.add_argument("--level", default="chunk")
    en.add_argument("--sample", type=int, default=None)
    en.add_argument("--book", nargs="+", default=None)
    en.set_defaults(func=cmd_enrich)

    cz = sub.add_parser("characterize", help="tag chunk character + desc (R4)")
    cz.add_argument("--level", default="chunk")
    cz.add_argument("--sample", type=int, default=None)
    cz.add_argument("--book", nargs="+", default=None)
    cz.set_defaults(func=cmd_characterize)

    sub.add_parser("chunkmap", help="(re)build the chunk map (json + offline html)"
                   ).set_defaults(func=cmd_chunkmap)

    cp = sub.add_parser("concepts", help="extract core concepts per chunk (content lens)")
    cp.add_argument("--llm", action="store_true", help="LLM concepts (needs key); else heuristic tf-idf")
    cp.add_argument("--level", default="chunk")
    cp.add_argument("--top", type=int, default=160, help="vocabulary size (heuristic)")
    cp.add_argument("--sample", type=int, default=None)
    cp.add_argument("--book", nargs="+", default=None)
    cp.set_defaults(func=cmd_concepts)
    sub.add_parser("conceptmap", help="(re)build the concept map (json + offline html)"
                   ).set_defaults(func=cmd_conceptmap)

    sub.add_parser("eval-embed", help="score embedding models on the in-domain gold set"
                   ).set_defaults(func=cmd_eval_embed)
    sub.add_parser("usage", help="show today's Gemini free-tier token/request usage"
                   ).set_defaults(func=cmd_usage)
    sub.add_parser("notes", help="parse annotated reading notes -> annotations.jsonl").set_defaults(func=cmd_notes)
    sub.add_parser("graph", help="build the concept graph (edges) from notes").set_defaults(func=cmd_graph)

    def add_seed_args(sp):
        g = sp.add_mutually_exclusive_group()
        g.add_argument("--theme", help="free-text theme or question to seed from")
        g.add_argument("--chunk", help="seed from a specific chunk id, e.g. being-and-truth#0042")
        g.add_argument("--note", help="seed from a note's sutra/anchor, e.g. what-is-called-thinking")
        g.add_argument("--random", action="store_true", help="seed from a random passage")
        sp.add_argument("--structural", action="store_true",
                        help="retrieve on the seed's underlying structure (structural-HyDE), "
                             "not its surface words — reaches lexically-distant kin")
        sp.add_argument("--candidates", type=int, default=config.N_CANDIDATES)
        sp.add_argument("--seed", type=int, default=None, help="RNG seed for reproducible randomness")

    e = sub.add_parser("explore", help="one exploration step"); add_seed_args(e)
    e.set_defaults(func=cmd_explore)
    w = sub.add_parser("wander", help="follow connections as new seeds"); add_seed_args(w)
    w.add_argument("--steps", type=int, default=3)
    w.set_defaults(func=cmd_wander)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
