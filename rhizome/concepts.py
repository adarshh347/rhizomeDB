"""Core-concept extraction — the content lens for the concept map.

Two extractors, one output. Both answer: *what is each chunk about?* — and, by
aggregation, *where does a concept live across the corpus, and what does each
site do with it?* (the study question PCA-of-dots can't touch).

  extract_heuristic()  no key, runs now. tf-idf over the chunk level surfaces
                       salient terms/phrases; the placeholder that lets us SEE
                       the lens's shape today and decide if it earns its keep.
  extract_llm()        with a provider key. Clean conceptual phrases per chunk,
                       cached by content hash, cost-guarded — the upgrade path,
                       mirroring rhizome.enrich exactly.

Both write index/concepts.json:
  {"mode", "built_from", "concepts": [{"id","label","count","score","books"}],
   "chunk_concepts": {chunk_id: [label, ...]}}
The map (tools/conceptmap.py) reads this; chunk *text* is rejoined from the
chunk level, so this file stays small.
"""
import json
import math
import re
from collections import Counter, defaultdict

from . import config, chunking

CONCEPTS_PATH = config.INDEX_DIR / "concepts.json"

# Compact stopword set: function words + corpus-pervasive scholarly noise that
# would otherwise dominate tf-idf without naming a concept.
_STOP = set("""
a an the this that these those it its is are was were be been being am do does did
of in on at to from by for with without within into onto upon over under between
and or but nor so yet as if then than that which who whom whose what when where why how
not no nor only just also too very more most much many few less least own same other
i we you he she they them us our your his her their my me him then there here thus
can could may might must shall should will would have has had having not
one two three first second new way thing things make made makes making see seen
such about above below after before again further once each any all both either
say said says according e.g i.e cf ed eds vol pp p chapter section page note notes
text passage author work however therefore moreover indeed rather merely simply
""".split())


def _tokens(text: str):
    return [w for w in re.findall(r"[a-z][a-z'\-]{2,}", text.lower())
            if w not in _STOP and "'" not in w]


def _candidates(toks):
    """Unigrams + adjacent non-stopword bigrams (multiword concepts like
    'poetic thinking', 'eternal recurrence'). Connector-spanning phrases are
    left for the LLM upgrade — this is the cheap placeholder."""
    grams = list(toks)
    grams += [f"{a} {b}" for a, b in zip(toks, toks[1:])]
    return grams


def extract_heuristic(level: str = "chunk", top_concepts: int = 160,
                      per_chunk: int = 6, books=None) -> dict:
    chunks = chunking.load_level(level)
    if not chunks:
        raise SystemExit(f"Level '{level}' not built. Run `rhizome build` first.")
    if books:
        chunks = [c for c in chunks if c["book_id"] in books]
        if not chunks:
            raise SystemExit(f"No chunks for book(s) {books}.")
    n = len(chunks)
    per_chunk_grams = []
    df = Counter()
    for c in chunks:
        grams = _candidates(_tokens(c["text"]))
        tf = Counter(grams)
        per_chunk_grams.append(tf)
        df.update(tf.keys())

    # Keep terms that recur but aren't ubiquitous (the band where meaning lives).
    df_lo, df_hi = 3, max(4, int(0.40 * n))
    idf = {g: math.log(n / d) for g, d in df.items() if df_lo <= d <= df_hi}

    # Global vocabulary by total tf-idf mass.
    mass = Counter()
    for tf in per_chunk_grams:
        for g, t in tf.items():
            if g in idf:
                mass[g] += t * idf[g]
    vocab = [g for g, _ in mass.most_common(top_concepts)]
    vset = set(vocab)

    # Per-chunk assignment + per-concept stats.
    chunk_concepts = {}
    count = Counter()
    books = defaultdict(Counter)
    for c, tf in zip(chunks, per_chunk_grams):
        scored = sorted(((tf[g] * idf[g], g) for g in tf if g in vset), reverse=True)
        labels = [g for _, g in scored[:per_chunk]]
        if labels:
            chunk_concepts[c["id"]] = labels
            for g in labels:
                count[g] += 1
                books[g][c["book_id"]] += 1

    concepts = [{"id": g, "label": g, "count": count[g],
                 "score": round(mass[g], 2), "books": dict(books[g])}
                for g in vocab if count[g] > 0]
    concepts.sort(key=lambda x: x["count"], reverse=True)
    data = {"mode": "heuristic", "built_from": level, "books": books or "all",
            "concepts": concepts, "chunk_concepts": chunk_concepts}
    _save(data)
    print(f"concepts[heuristic]: {len(concepts)} concepts over {len(chunk_concepts)} "
          f"chunks{' ['+','.join(books)+']' if books else ''} -> {CONCEPTS_PATH.name}")
    return data


# --- LLM upgrade (mirrors rhizome.enrich: cached, batched, cost-guarded) ------
CONCEPTS_SYSTEM = """\
For each numbered passage, name the 1–4 CORE CONCEPTS it actually works with —
the philosophical notions a reader would file it under (e.g. "the nothing",
"eternal recurrence", "poetic thinking", "ontological difference"). Prefer the
tradition's own terms; lowercase unless a proper name; 1–3 words each. Name what
the passage USES, not every word it contains; skip pure citations/throat-clearing.

Return ONLY JSON: {"0":["concept",...],"1":[...], ...} keyed by passage number."""


def extract_llm(level: str = "chunk", books=None, sample=None,
                batch: int = 12, per_chunk: int = 4) -> dict:
    import time
    from . import llm, enrich, usage
    client = llm.get_client()
    if client is None:
        raise SystemExit("No LLM client (set a provider key in .env). "
                         "Use heuristic mode meanwhile: rhizome concepts")
    records = chunking.load_level(level)
    if not records:
        raise SystemExit(f"Level '{level}' not built.")
    cache = enrich._load_cache(config.INDEX_DIR / "cache_concepts.json")
    targets = enrich._scope(records, books, sample)
    todo = [r for r in targets if enrich._hash(r["text"]) not in cache]
    print(f"concepts[llm/{level}]: {len(targets)} in scope, {len(todo)} need extraction "
          f"({len(targets)-len(todo)} cached)")
    t0 = enrich._tokens(client); calls = 0
    for batch_recs in enrich._batches(todo, batch):
        listing = "\n\n".join(f"[{i}] {r['text'][:700]}" for i, r in enumerate(batch_recs))
        try:
            raw = client.complete(CONCEPTS_SYSTEM, listing, max_tokens=1600,
                                  temperature=0.2, json_mode=True)
            obj = llm._strip_json(raw); calls += 1
        except Exception as e:
            print(f"  batch failed ({type(e).__name__}); skipping"); continue
        for i, r in enumerate(batch_recs):
            cs = [str(x).strip().lower() for x in (obj.get(str(i)) or []) if str(x).strip()]
            cache[enrich._hash(r["text"])] = cs[:per_chunk]
        enrich._save_cache(config.INDEX_DIR / "cache_concepts.json", cache)
        time.sleep(enrich.BATCH_PAUSE)

    chunk_concepts = {}
    count = Counter()
    books_d = defaultdict(Counter)
    for r in targets:
        labels = cache.get(enrich._hash(r["text"]), [])
        if labels:
            chunk_concepts[r["id"]] = labels
            for g in labels:
                count[g] += 1
                books_d[g][r["book_id"]] += 1
    concepts = [{"id": g, "label": g, "count": c, "score": float(c),
                 "books": dict(books_d[g])} for g, c in count.most_common()]
    data = {"mode": "llm", "built_from": level,
            "concepts": concepts, "chunk_concepts": chunk_concepts}
    _save(data)
    used = enrich._tokens(client) - t0
    note = usage.note_and_record(client, used, calls)
    print(f"concepts[llm]: {len(concepts)} concepts over {len(chunk_concepts)} chunks "
          f"· {used} tokens{note} -> {CONCEPTS_PATH.name}")
    return data


def _save(data: dict):
    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    CONCEPTS_PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def load_concepts() -> dict:
    if not CONCEPTS_PATH.exists():
        raise SystemExit("No concepts built. Run: rhizome concepts")
    return json.loads(CONCEPTS_PATH.read_text(encoding="utf-8"))
