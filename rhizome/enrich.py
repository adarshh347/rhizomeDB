"""LLM enrichment passes over the chunk levels — all cost-guarded (PRD R3/R4/R8).

Three passes, sharing one discipline: batch aggressively, use the cheap/failover
client, cache by content hash (a second run with unchanged input does ~0 LLM
calls), scope with sample=/books=, and report tokens via the client's usage.

  enrich_contextual()  R3 — a ≤1-sentence context blurb per chunk; embed
                       blurb+text (raw text kept for display).
  characterize()       R4 — a controlled-vocab character + one-line desc per unit.
  build_propositions() R2 — decompose chunks into atomic statements, each linked
                       back to its chunk (a proposition is never read alone).
"""
import hashlib
import json
import time

from . import config, llm, chunking

# Polite pause between LLM batches so free-tier per-minute token limits don't
# trip on back-to-back calls. Override with RHIZOME_BATCH_PAUSE (seconds).
import os
BATCH_PAUSE = float(os.environ.get("RHIZOME_BATCH_PAUSE", "2.0"))


def _hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _load_cache(path):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cache(path, cache):
    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def _scope(records, books, sample):
    sel = [r for r in records if not books or r["book_id"] in books]
    if sample:
        sel = sel[:sample]
    return sel


def _tokens(client):
    return (getattr(client, "total_usage", {}) or {}).get("total", 0)


def _batches(items, n):
    for i in range(0, len(items), n):
        yield items[i:i + n]


# --- R3: contextual enrichment ------------------------------------------------
CONTEXT_SYSTEM = """\
For each numbered passage you are given its author, work and heading, then its
text. Write ONE short context sentence that situates the passage for retrieval —
of the form "From {author}, {work}{, heading} — on {the specific topic/move}."
Name the actual topic concretely; do not summarize the whole passage. Keep it to
a single clause-rich sentence.

Return ONLY JSON: {"0":"<context>","1":"<context>",...} keyed by the passage
number, one entry per passage."""


def enrich_contextual(level: str = "chunk", books=None, sample=None,
                      batch: int = 10) -> dict:
    client = llm.get_client()
    if client is None:
        raise SystemExit("No LLM client (set a provider key in .env).")
    records = chunking.load_level(level)
    if not records:
        raise SystemExit(f"Level '{level}' not built.")
    cache = _load_cache(config.CONTEXT_CACHE_PATH)
    targets = _scope(records, books, sample)
    todo = [r for r in targets if _hash(r["text"]) not in cache]
    print(f"contextual[{level}]: {len(targets)} in scope, {len(todo)} need generation "
          f"({len(targets)-len(todo)} cached)")
    t0 = _tokens(client)
    for batch_recs in _batches(todo, batch):
        listing = "\n\n".join(
            f"[{i}] {r.get('author') or 'Unknown'} — {r.get('title') or r['book_id']}"
            + (f" — {r['heading']}" if r.get('heading') else "")
            + f"\n{r['text'][:700]}"
            for i, r in enumerate(batch_recs))
        try:
            raw = client.complete(CONTEXT_SYSTEM, listing, max_tokens=1500,
                                  temperature=0.3, json_mode=True)
            obj = llm._strip_json(raw)
        except Exception as e:
            print(f"  batch failed ({type(e).__name__}); skipping"); continue
        for i, r in enumerate(batch_recs):
            blurb = (obj.get(str(i)) or "").strip()
            if blurb:
                cache[_hash(r["text"])] = blurb
        _save_cache(config.CONTEXT_CACHE_PATH, cache)
        time.sleep(BATCH_PAUSE)
    # write blurbs back onto the records in scope
    n_set = 0
    for r in targets:
        b = cache.get(_hash(r["text"]))
        if b:
            r["context_blurb"] = b; n_set += 1
    chunking.save_level(level, records)
    used = _tokens(client) - t0
    print(f"contextual[{level}]: {n_set} blurbs set · {used} tokens "
          f"· re-embed with: rhizome embed (level {level})")
    return {"set": n_set, "tokens": used}


# --- R4: character tagging ----------------------------------------------------
CHARACTER_SYSTEM = """\
You tag each numbered passage with its CHARACTER — what kind of philosophical
passage it is — choosing exactly one from this controlled set:
{vocab}
Definitions: definitional=states what something is; argumentative=advances a
claim with reasons; exegetical=reads/interprets another text; illustrative=gives
an example or image; poetic=lyrical/evocative language; citation=mostly quoting
or referencing; transitional=sets up/links sections; aporetic=poses a difficulty
or open question; historical=narrates intellectual history; polemical=attacks or
defends a position.

For each passage also give a ≤12-word description of its specific move.
Return ONLY JSON: {{"0":{{"character":"<one>","desc":"<...>"}}, ...}} per passage."""


def characterize(level: str = "chunk", books=None, sample=None,
                 batch: int = 14) -> dict:
    client = llm.get_client()
    if client is None:
        raise SystemExit("No LLM client (set a provider key in .env).")
    records = chunking.load_level(level)
    if not records:
        raise SystemExit(f"Level '{level}' not built.")
    cache = _load_cache(config.CHARACTER_CACHE_PATH)
    vocab = ", ".join(config.CHARACTERS)
    system = CHARACTER_SYSTEM.format(vocab=vocab)
    targets = _scope(records, books, sample)
    todo = [r for r in targets if _hash(r["text"]) not in cache]
    print(f"character[{level}]: {len(targets)} in scope, {len(todo)} need tagging "
          f"({len(targets)-len(todo)} cached)")
    t0 = _tokens(client)
    for batch_recs in _batches(todo, batch):
        listing = "\n\n".join(f"[{i}] {r['text'][:600]}" for i, r in enumerate(batch_recs))
        try:
            raw = client.complete(system, listing, max_tokens=1800,
                                  temperature=0.2, json_mode=True)
            obj = llm._strip_json(raw)
        except Exception as e:
            print(f"  batch failed ({type(e).__name__}); skipping"); continue
        for i, r in enumerate(batch_recs):
            v = obj.get(str(i)) or {}
            ch = str(v.get("character", "")).strip().lower()
            if ch in config.CHARACTERS:
                cache[_hash(r["text"])] = {"character": ch,
                                          "desc": str(v.get("desc", "")).strip()[:120]}
        _save_cache(config.CHARACTER_CACHE_PATH, cache)
        time.sleep(BATCH_PAUSE)
    n_set = 0
    from collections import Counter
    dist = Counter()
    for r in targets:
        c = cache.get(_hash(r["text"]))
        if c:
            r["character"] = c["character"]; r["character_desc"] = c["desc"]
            n_set += 1; dist[c["character"]] += 1
    chunking.save_level(level, records)
    used = _tokens(client) - t0
    print(f"character[{level}]: {n_set} tagged · {used} tokens · {dict(dist)}")
    return {"set": n_set, "tokens": used, "dist": dict(dist)}


# --- R2: proposition extraction ----------------------------------------------
PROP_SYSTEM = """\
Decompose each numbered passage into its atomic PROPOSITIONS — short, complete,
self-contained declarative statements, each expressing ONE claim, resolved of
pronouns so it stands alone. 2–6 per passage; skip throat-clearing and pure
citations. Stay faithful; do not add claims the passage doesn't make.

Return ONLY JSON: {"0":["prop","prop",...], "1":[...], ...} keyed by passage
number."""


def build_propositions(books=None, sample=None, batch: int = 6) -> dict:
    """Decompose CHUNK units into propositions (proposition ⊂ chunk ⊂ parent).
    Each proposition keeps parent_id = its chunk; chunk.child_ids gets the props."""
    client = llm.get_client()
    if client is None:
        raise SystemExit("No LLM client (set a provider key in .env).")
    chunks = chunking.load_level("chunk")
    if not chunks:
        raise SystemExit("No chunk level. Run `rhizome build` first.")
    by_id = {c["id"]: c for c in chunks}
    cache = _load_cache(config.INDEX_DIR / "cache_proposition.json")
    targets = _scope(chunks, books, sample)
    todo = [c for c in targets if _hash(c["text"]) not in cache]
    print(f"proposition: {len(targets)} chunks in scope, {len(todo)} need extraction "
          f"({len(targets)-len(todo)} cached)")
    t0 = _tokens(client)
    for batch_recs in _batches(todo, batch):
        listing = "\n\n".join(f"[{i}] {r['text'][:900]}" for i, r in enumerate(batch_recs))
        try:
            raw = client.complete(PROP_SYSTEM, listing, max_tokens=2200,
                                  temperature=0.2, json_mode=True)
            obj = llm._strip_json(raw)
        except Exception as e:
            print(f"  batch failed ({type(e).__name__}); skipping"); continue
        for i, r in enumerate(batch_recs):
            props = obj.get(str(i)) or []
            cache[_hash(r["text"])] = [str(p).strip() for p in props if str(p).strip()]
        _save_cache(config.INDEX_DIR / "cache_proposition.json", cache)
        time.sleep(BATCH_PAUSE)

    # materialize proposition records + link chunk.child_ids
    props = []
    per_book_n = {}
    # reset proposition children only for chunks in scope (idempotent re-runs)
    scope_ids = {c["id"] for c in targets}
    for c in chunks:
        if c["id"] in scope_ids:
            c["child_ids"] = []
    for c in targets:
        statements = cache.get(_hash(c["text"]), [])
        bid = c["book_id"]
        for s in statements:
            n = per_book_n.get(bid, 0)
            pid = f"{bid}#{config.LEVEL_ID_PREFIX['proposition']}{n:04d}"
            per_book_n[bid] = n + 1
            props.append({"id": pid, "level": "proposition", "parent_id": c["id"],
                          "child_ids": [], "book_id": bid, "author": c.get("author", ""),
                          "title": c.get("title", ""), "heading": c.get("heading"),
                          "page": c.get("page"), "text": s})
            by_id[c["id"]]["child_ids"].append(pid)
    chunking.save_level("proposition", props)
    chunking.save_level("chunk", chunks)
    used = _tokens(client) - t0
    print(f"proposition: {len(props)} propositions from {len(targets)} chunks · {used} tokens "
          f"-> {config.chunks_path('proposition')}")
    print("  re-embed with: rhizome embed-level proposition")
    return {"props": len(props), "tokens": used}
