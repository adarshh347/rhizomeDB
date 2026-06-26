"""The concept graph — persisted bridges between ideas.

Embedding geometry can only ever surface what is *near*. The connections worth
having are often structural and lexically distant — invisible to similarity. So
the graph is a second retrieval path, grown from bridges a human (or the judge)
actually authored:

  - every `correlate` annotation in a reading note becomes an edge,
  - plus hand-authored SEED_EDGES that bootstrap the graph,
  - (later) every bridge the LLM judge confirms during an exploration.

An edge is *attributed*, never a bare fact: it records who/what asserts it and
where, so the graph holds contested, even contradictory, connections without
flattening them into "truth".
"""
import json

from . import config, notes as notes_mod

# Hand-authored bridges that bootstrap the graph. The first one is the
# constellation found inside the Heidegger reading note itself.
SEED_EDGES = [
    {
        "source": "Gelassenheit / releasement (Heidegger)",
        "target": "visranti / repose (Abhinavagupta)",
        "relation": "resonates",
        "bridge": "calmness as the precondition of disclosure",
        "text": ("Late Heidegger's Gelassenheit — releasement, the waiting in which the "
                 "open region lets things presence — meets Abhinavagupta's visranti, the "
                 "repose in which rasa and chamatkara culminate. In both, a non-doing "
                 "stillness is what lets appearance happen."),
        "provenance": "what-is-called-thinking#mythought",
        "origin": "authored",
    },
]

_STOP = {"that", "this", "the", "a", "an", "is", "of", "to", "and", "quite",
         "related", "idea", "it", "s", "moment", "where", "things", "get"}


def _target_label(text: str) -> str:
    """Best-effort short label for the far side of a correlation."""
    first = text.replace("\n", " ").split(".")[0].strip()
    return (first[:80] + "…") if len(first) > 80 else first


def build_edges() -> list[dict]:
    """SEED_EDGES + one edge per `correlate` annotation (sourced from the note's
    nearest preceding anchor/sutra)."""
    edges: list[dict] = [dict(e) for e in SEED_EDGES]
    recs = notes_mod.load_annotations()

    # group annotations by note, preserving document order
    by_note: dict[str, list[dict]] = {}
    for r in recs:
        by_note.setdefault(r["note_id"], []).append(r)

    for note_id, rs in by_note.items():
        rs.sort(key=lambda r: int(r["id"].rsplit("#a", 1)[1]))
        last_seed = None
        for r in rs:
            if r["role"] == "seed" and r["text"]:
                last_seed = r["text"]
            elif r["role"] == "edge" and r["text"]:
                edges.append({
                    "source": (last_seed[:80] + "…") if last_seed and len(last_seed) > 80
                              else (last_seed or note_id),
                    "target": _target_label(r["text"]),
                    "relation": "correlate",
                    "bridge": None,
                    "text": " ".join(r["text"].split()),
                    "provenance": r["id"],
                    "origin": "note",
                })

    edges.extend(load_judged())   # bridges the engine confirmed during explorations

    # dedup identical edges (same endpoints + provenance + origin)
    seen, uniq = set(), []
    for e in edges:
        key = (e["source"], e["target"], e.get("provenance"), e["origin"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(e)
    edges = uniq

    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    with config.EDGES_PATH.open("w", encoding="utf-8") as f:
        for e in edges:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    by_origin = {}
    for e in edges:
        by_origin[e["origin"]] = by_origin.get(e["origin"], 0) + 1
    print(f"Total: {len(edges)} edges -> {config.EDGES_PATH}  "
          f"({', '.join(f'{k}={v}' for k, v in by_origin.items())})")
    return edges


def load_edges() -> list[dict]:
    if not config.EDGES_PATH.exists():
        return []
    with config.EDGES_PATH.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_judged() -> list[dict]:
    if not config.JUDGED_PATH.exists():
        return []
    with config.JUDGED_PATH.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def append_judged(seed_label: str, confirmed: list[dict]) -> list[dict]:
    """Persist the bridges the judge confirmed during an exploration, so the
    graph accretes from the engine's own discoveries — not only from notes.
    Append-only; `build_edges` merges these into the unified graph."""
    rows = []
    for c in confirmed:
        rows.append({
            "source": seed_label,
            "target": f"{c.get('author') or 'Unknown'} — {c.get('title') or c['book_id']}",
            "relation": "evokes",
            "bridge": c.get("bridge_concept"),
            "text": " ".join((c.get("articulation") or "").split()),
            "confidence": c.get("confidence"),
            "provenance": c.get("id"),
            "origin": "judged",
        })
    if not rows:
        return []
    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    with config.JUDGED_PATH.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return rows


def digest(edges: list[dict]) -> None:
    print()
    for e in edges:
        print(f"  {e['source']}")
        arrow = e["relation"]
        print(f"     ──{arrow}──▶ {e['target']}")
        if e.get("bridge"):
            print(f"     bridge: {e['bridge']}")
        print(f"     [{e['origin']}] {e['provenance']}")
        print()
