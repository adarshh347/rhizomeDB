"""Multi-resolution chunking — the SOLID→LIQUID dial (see CHUNKING.md / PRD).

The same corpus indexed at several linked granularities:

    parent  (~500w passages, LIQUID)  ⊃  chunk (~240w, the working unit)  ⊃
    proposition (atomic statements, SOLID)

Every unit carries {level, parent_id, child_ids}. The chunk level IS the legacy
`index/chunks.jsonl` — we never rebuild it (that would desync embeddings.npy and
break stable ids / saved annotations); we only *augment* its records with
parent_id/child_ids. Parents and propositions are additive new files
`index/chunks_<level>.jsonl` + `index/emb_<level>.npy`.

This module owns: the generic accumulator, the parent + semantic chunkers,
parent↔child linking, per-level load/embed, and the proposition extractor.
LLM passes (proposition, contextual, character) live in `enrich.py`.
"""
import json
import re

from . import config, catalog, embed as embed_mod
from .chunk import _iter_blocks, _is_boilerplate, _strip_frontmatter, _wordcount


# --- generic accumulator (mirrors chunk.chunk_book, parameterised by size) ----
def _accumulate(text: str, target: int, overlap: int, min_words: int) -> list[dict]:
    """Accumulate paragraphs into ~target-word units with an overlap tail,
    tracking page + heading, dropping boilerplate. Returns units WITHOUT ids."""
    units: list[dict] = []
    buf: list[str] = []
    buf_words = 0
    cur_page = cur_heading = start_page = None

    def flush():
        nonlocal buf, buf_words, start_page
        if buf_words >= min_words:
            body = "\n\n".join(buf).strip()
            if not _is_boilerplate(body):
                units.append({"text": body, "heading": cur_heading, "page": start_page})
        if buf and overlap:
            tail, tw = [], 0
            for para in reversed(buf):
                tail.insert(0, para)
                tw += _wordcount(para)
                if tw >= overlap:
                    break
            buf = tail
            buf_words = sum(_wordcount(p) for p in buf)
        else:
            buf, buf_words = [], 0
        start_page = cur_page

    for kind, payload in _iter_blocks(text):
        if kind == "page":
            cur_page = payload
            if start_page is None:
                start_page = payload
        elif kind == "heading":
            if buf_words >= target // 2:
                flush()
            cur_heading = payload
        else:  # para
            if start_page is None:
                start_page = cur_page
            buf.append(payload)
            buf_words += _wordcount(payload)
            if buf_words >= target:
                flush()
    if buf_words >= min_words:
        body = "\n\n".join(buf).strip()
        if not _is_boilerplate(body):
            units.append({"text": body, "heading": cur_heading, "page": start_page})
    return units


# --- semantic chunker (R2): start a new chunk at an embedding-similarity drop --
_SENT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'(])")


def _sentences(text: str) -> list[str]:
    out = []
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if para:
            out.extend(s.strip() for s in _SENT_RE.split(para) if s.strip())
    return out


def _semantic_units(text: str, target: int, min_words: int,
                    threshold: float) -> list[dict]:
    """Group sentences into chunks, cutting where adjacent-sentence cosine drops
    below `threshold` (a topic shift) or the running size exceeds `target`."""
    sents = _sentences(text)
    if not sents:
        return []
    vecs = embed_mod.embed_texts(sents)
    units, buf, bw = [], [], 0
    for i, s in enumerate(sents):
        if buf:
            sim = float(vecs[i] @ vecs[i - 1])
            shift = sim < threshold
            if (shift and bw >= min_words) or bw >= target:
                body = " ".join(buf).strip()
                if not _is_boilerplate(body):
                    units.append({"text": body, "heading": None, "page": None})
                buf, bw = [], 0
        buf.append(s)
        bw += _wordcount(s)
    if buf and bw >= min_words:
        body = " ".join(buf).strip()
        if not _is_boilerplate(body):
            units.append({"text": body, "heading": None, "page": None})
    return units


# --- per-level load / save ----------------------------------------------------
def load_level(level: str) -> list[dict]:
    path = config.chunks_path(level)
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def save_level(level: str, records: list[dict]) -> None:
    path = config.chunks_path(level)
    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# --- parent↔child linking (word-overlap; both are windows of the same text) ----
_WORD_RE = re.compile(r"[a-z]{3,}")


def _bag(text: str) -> set:
    return set(_WORD_RE.findall(text.lower()))


def _best_parent(chunk_bag: set, parents: list[dict], parent_bags: list[set]) -> int:
    """Index of the parent whose text best contains the chunk (max overlap)."""
    best_i, best = -1, 0.0
    denom = len(chunk_bag) or 1
    for i, pb in enumerate(parent_bags):
        ov = len(chunk_bag & pb) / denom
        if ov > best:
            best, best_i = ov, i
    return best_i


# --- build the parent level + link the (legacy) chunk level to it --------------
def build_parents(books: list[str] | None = None, method: str | None = None) -> dict:
    """Build parent units per book, link existing chunks to their parent, write
    chunks_parent.jsonl, and augment chunks.jsonl with parent_id/child_ids.
    Returns per-book counts. Does NOT rebuild the chunk level."""
    cat = catalog.load_catalog()
    method = method or config.CHUNK_METHOD
    chunks = load_level("chunk")
    if not chunks:
        raise SystemExit("No chunk level found. Run `rhizome build` first.")
    # group chunks by book, preserving file order (so ids/embeddings stay aligned)
    chunks_by_book: dict[str, list[dict]] = {}
    for c in chunks:
        chunks_by_book.setdefault(c["book_id"], []).append(c)

    parents: list[dict] = []
    counts = {}
    for md in sorted(config.CONVERTED_DIR.rglob("*.md")):
        book_id = md.stem
        if books and book_id not in books:
            continue
        meta = cat.get(book_id, {"author": "", "title": book_id})
        text = _strip_frontmatter(md.read_text(encoding="utf-8"))
        if method == "semantic":
            units = _semantic_units(text, config.PARENT_TARGET_WORDS,
                                    config.CHUNK_MIN_WORDS, config.SEMANTIC_THRESHOLD)
        else:
            units = _accumulate(text, config.PARENT_TARGET_WORDS,
                                config.PARENT_OVERLAP_WORDS, config.CHUNK_MIN_WORDS)
        book_parents = []
        for u in units:
            pid = f"{book_id}#{config.LEVEL_ID_PREFIX['parent']}{len(book_parents):04d}"
            book_parents.append({
                "id": pid, "level": "parent", "parent_id": None, "child_ids": [],
                "book_id": book_id, "author": meta.get("author", ""),
                "title": meta.get("title", ""), "heading": u["heading"],
                "page": u["page"], "text": u["text"],
            })
        # link this book's chunks to their best-overlap parent
        pbags = [_bag(p["text"]) for p in book_parents]
        for c in chunks_by_book.get(book_id, []):
            if not book_parents:
                continue
            j = _best_parent(_bag(c["text"]), book_parents, pbags)
            if j >= 0:
                c["parent_id"] = book_parents[j]["id"]
                book_parents[j]["child_ids"].append(c["id"])
                c.setdefault("level", "chunk")
                c.setdefault("child_ids", [])
        parents.extend(book_parents)
        counts[book_id] = len(book_parents)
        print(f"  {book_id:42s} {len(book_parents):5d} parents")

    save_level("parent", parents)
    # augment chunk records with level/parent_id/child_ids (ids & order unchanged)
    for c in chunks:
        c.setdefault("level", "chunk")
        c.setdefault("parent_id", None)
        c.setdefault("child_ids", [])
    save_level("chunk", chunks)
    print(f"Total parents: {len(parents)} -> {config.chunks_path('parent')}")
    return counts


# --- proposition level, deterministic (no-LLM fallback for the SOLID floor) ---
def build_propositions_sentences(books: list[str] | None = None,
                                 sample: int | None = None,
                                 min_words: int = 5) -> int:
    """Split each chunk into sentence-level propositions — real corpus sentences,
    no LLM. A usable SOLID floor and the offline fallback for enrich.build_
    propositions (the LLM version yields cleaner atomic, pronoun-resolved claims).
    proposition ⊂ chunk ⊂ parent; links both ways."""
    chunks = load_level("chunk")
    if not chunks:
        raise SystemExit("No chunk level. Run `rhizome build` first.")
    targets = [c for c in chunks if not books or c["book_id"] in books]
    if sample:
        targets = targets[:sample]
    scope = {c["id"] for c in targets}
    for c in chunks:
        if c["id"] in scope:
            c["child_ids"] = []
    by_id = {c["id"]: c for c in chunks}
    props, per_book = [], {}
    for c in targets:
        for s in _sentences(c["text"]):
            if _wordcount(s) < min_words:
                continue
            n = per_book.get(c["book_id"], 0); per_book[c["book_id"]] = n + 1
            pid = f"{c['book_id']}#{config.LEVEL_ID_PREFIX['proposition']}{n:04d}"
            props.append({"id": pid, "level": "proposition", "parent_id": c["id"],
                          "child_ids": [], "book_id": c["book_id"],
                          "author": c.get("author", ""), "title": c.get("title", ""),
                          "heading": c.get("heading"), "page": c.get("page"), "text": s})
            by_id[c["id"]]["child_ids"].append(pid)
    save_level("proposition", props)
    save_level("chunk", chunks)
    print(f"  {len(props)} propositions from {len(targets)} chunks (sentence split)")
    return len(props)


# --- small-to-big: match a small unit, read its parent (the dial mechanism) ---
def parents_of(units: list[dict]) -> list[dict]:
    """Given matched small units (chunk/proposition), return their PARENT
    passages — unique, order-preserving. This is the small-to-big move: match on
    the precise unit, hand the LLM the larger context. A proposition resolves up
    through its chunk to the chunk's parent so nothing is ever read alone."""
    parents = {p["id"]: p for p in load_level("parent")}
    chunks = {c["id"]: c for c in load_level("chunk")}
    seen, out = set(), []
    for u in units:
        pid = u.get("parent_id")
        # proposition → chunk → parent
        if pid in chunks:
            pid = chunks[pid].get("parent_id")
        elif u.get("level") == "chunk":
            pid = u.get("parent_id")
        if pid and pid in parents and pid not in seen:
            seen.add(pid)
            out.append(parents[pid])
    return out


# --- per-level embeddings -----------------------------------------------------
def build_level_embeddings(level: str) -> int:
    """Embed a level's units (context_blurb + text when enrichment is on) into
    emb_<level>.npy. The chunk level reuses the existing embeddings.npy unless it
    has been re-enriched — we leave it to `rhizome build` to (re)make that."""
    import numpy as np
    records = load_level(level)
    if not records:
        raise SystemExit(f"No records for level '{level}'.")
    texts = []
    for r in records:
        blurb = r.get("context_blurb")
        texts.append(f"{blurb}\n{r['text']}" if blurb else r["text"])
    print(f"Embedding {len(texts)} {level} units ...")
    vecs = embed_mod.embed_texts(texts)
    out = config.level_emb_path(level)
    np.save(out, vecs)
    print(f"Saved {vecs.shape} -> {out}")
    return len(records)
