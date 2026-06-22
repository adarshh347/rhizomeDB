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
               notes as notes_mod, graph as graph_mod)


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


def cmd_build(_):
    print("1/3 catalog"); cat = catalog.build_catalog(); catalog.save_catalog(cat)
    print("2/3 chunk");   chunk_mod.build_chunks()
    print("3/3 embed");   embed_mod.build_embeddings()
    print("Done. Try:  python -m rhizome.cli explore --random")


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


def cmd_explore(args):
    from .engine import Engine
    eng = Engine(seed_int=args.seed)
    theme = args.theme
    if getattr(args, "note", None):
        theme = _theme_from_note(args.note)
    step = eng.explore(theme=theme, chunk_id=args.chunk, random=args.random,
                       structural=args.structural, k=args.candidates)
    _print_step(step)


def cmd_wander(args):
    from .engine import Engine
    eng = Engine(seed_int=args.seed)
    path = eng.wander(steps=args.steps, theme=args.theme, chunk_id=args.chunk,
                      random=args.random or (args.theme is None and args.chunk is None),
                      structural=args.structural, k=args.candidates)
    for n, step in enumerate(path, 1):
        print(f"\n########## STEP {n}/{len(path)} ##########")
        _print_step(step)


def main():
    p = argparse.ArgumentParser(prog="rhizome", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("catalog", help="(re)generate catalog.json").set_defaults(func=cmd_catalog)
    sub.add_parser("build", help="catalog -> chunk -> embed").set_defaults(func=cmd_build)
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
