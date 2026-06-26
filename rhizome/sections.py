"""Book sections — the *reading* lens (companion to the concept map's content lens).

A book is divided into ~1000-word SECTIONS (consecutive chunks grouped to a word
target), and each section gets a Gemini-generated CONCEPTUAL DESCRIPTION: a short
title, what the stretch of text is doing, the concepts it works with (with a
one-line gloss each), the ones the author introduces, and the moves he makes.
This drives the parallel reader (/read): original passage ‖ conceptual
description ‖ notes ‖ AI brainstorm.

Two stages, deliberately split so the free tier is never spent silently:
  build_skeleton()   no LLM — divides the book into sections + metadata. Cheap,
                     run it freely; the reader works immediately on raw text.
  describe_section() one Gemini call per section, cached in place. Triggered
                     on-demand from the reader (a button) or batched via
                     build_descriptions() / `rhizome sections --llm`.

Stored at index/sections_<book_id>.json (text is rejoined from the chunk level at
read time, so the file stays small). Section ids follow the level-id convention
(P=parent, X=proposition, S=section): "<book_id>#S0003".
"""
import json

from . import config, chunking

SECTION_PREFIX = "S"
DEFAULT_TARGET_WORDS = 1000

_CHUNK_CACHE: dict[str, list[dict]] = {}   # book_id -> ordered chunk records


def sections_path(book_id: str):
    return config.INDEX_DIR / f"sections_{book_id}.json"


def _book_chunks(book_id: str) -> list[dict]:
    """All chunk-level records for a book, in reading order (ids increase)."""
    cached = _CHUNK_CACHE.get(book_id)
    if cached is not None:
        return cached
    chunks = [c for c in chunking.load_level("chunk") if c["book_id"] == book_id]
    chunks.sort(key=lambda c: c["id"])
    _CHUNK_CACHE[book_id] = chunks
    return chunks


def _words(text: str) -> int:
    return len(text.split())


# --- stage 1: skeleton (no LLM) ----------------------------------------------
def build_skeleton(book_id: str, target_words: int = DEFAULT_TARGET_WORDS,
                   *, force: bool = False) -> dict:
    """Group consecutive chunks into ~target_words sections. Idempotent: if a
    sections file already exists, descriptions/brainstorms on it are preserved
    unless --force (a re-division would orphan them)."""
    chunks = _book_chunks(book_id)
    if not chunks:
        raise SystemExit(f"No chunks for book '{book_id}'. Run `rhizome build` first.")
    meta0 = chunks[0]
    existing = None if force else _load_raw(book_id)
    if existing and existing.get("target_words") == target_words:
        print(f"sections[{book_id}]: {len(existing['sections'])} sections already "
              f"built (target {target_words}w); use --force to re-divide.")
        return existing

    sections, cur, cur_words = [], [], 0

    def flush():
        nonlocal cur, cur_words
        if not cur:
            return
        idx = len(sections)
        pages = [c.get("page") for c in cur if c.get("page") is not None]
        sections.append({
            "id": f"{book_id}#{SECTION_PREFIX}{idx:04d}",
            "idx": idx,
            "book_id": book_id,
            "chunk_ids": [c["id"] for c in cur],
            "heading": next((c.get("heading") for c in cur if c.get("heading")), ""),
            "page_start": min(pages) if pages else None,
            "page_end": max(pages) if pages else None,
            "word_count": cur_words,
            "description": None,   # filled by describe_section()
        })
        cur, cur_words = [], 0

    for c in chunks:
        cur.append(c)
        cur_words += _words(c["text"])
        if cur_words >= target_words:
            flush()
    flush()

    data = {"book_id": book_id, "title": meta0.get("title") or book_id,
            "author": meta0.get("author") or "", "target_words": target_words,
            "sections": sections}
    _save(book_id, data)
    print(f"sections[{book_id}]: {len(sections)} sections (~{target_words}w each) "
          f"from {len(chunks)} chunks -> {sections_path(book_id).name}")
    return data


# --- stage 2: conceptual description (Gemini) --------------------------------
DESCRIBE_SYSTEM = """\
You read one continuous SECTION of a philosophical work and produce a compact
CONCEPTUAL MAP of it for a reader who has the original text open alongside. Do
not summarize line by line and do not editorialize — name what the section is
*doing* and the concepts it *works with*.

Return ONLY a JSON object of exactly this shape (no prose, no code fences):
{
  "title": "<3-7 word title for this section>",
  "summary": "<2-4 sentences: what this stretch of text is about and the move it makes>",
  "concepts": [
    {"name": "<concept as the tradition names it, lowercase unless a proper noun>",
     "gloss": "<one line: what it means AS USED HERE>"}
  ],
  "introduced": ["<concepts/terms the author introduces, coins, or first defines here>"],
  "discusses": ["<short phrases naming the things the author talks about / the steps of the argument>"]
}
Give 3-7 concepts, 0-5 introduced, 3-7 discusses. Prefer the author's own terms.
Ground everything in THIS section's text; never invent citations."""


def _norm_description(obj: dict) -> dict:
    """Coerce the model's JSON into the stable shape the reader expects."""
    def _strs(xs, lim):
        return [str(x).strip() for x in (xs or []) if str(x).strip()][:lim]
    concepts = []
    for c in (obj.get("concepts") or [])[:8]:
        if isinstance(c, dict):
            name = str(c.get("name", "")).strip()
            gloss = str(c.get("gloss", "")).strip()
        else:
            name, gloss = str(c).strip(), ""
        if name:
            concepts.append({"name": name[:80], "gloss": gloss[:240]})
    return {
        "title": str(obj.get("title", "")).strip()[:90],
        "summary": str(obj.get("summary", "")).strip(),
        "concepts": concepts,
        "introduced": _strs(obj.get("introduced"), 6),
        "discusses": _strs(obj.get("discusses"), 8),
    }


def section_text(book_id: str, section: dict) -> str:
    """Rejoin the section's original passage text from its chunks."""
    by_id = {c["id"]: c for c in _book_chunks(book_id)}
    return "\n\n".join(by_id[cid]["text"] for cid in section["chunk_ids"] if cid in by_id)


def section_passages(book_id: str, section: dict) -> list[dict]:
    """The section's chunks as passage dicts (for brainstorm / citation)."""
    by_id = {c["id"]: c for c in _book_chunks(book_id)}
    return [by_id[cid] for cid in section["chunk_ids"] if cid in by_id]


def describe_section(book_id: str, idx: int, client, *, force: bool = False) -> dict:
    """Generate (and persist) the conceptual description for one section. Returns
    {description, usage} where usage is a per-call meter report. Cached: an
    already-described section is returned untouched unless force=True."""
    from . import llm, usage
    data = _require(book_id)
    if idx < 0 or idx >= len(data["sections"]):
        raise ValueError(f"section idx {idx} out of range (0..{len(data['sections'])-1})")
    sec = data["sections"][idx]
    if sec.get("description") and not force:
        return {"description": sec["description"], "usage": None, "cached": True}
    if client is None:
        raise SystemExit("No LLM client (set GEMINI_API_KEY in .env).")

    meter = usage.Meter(client)
    text = section_text(book_id, sec)
    user = (f"WORK: {data['title']} — {data['author']}\n"
            f"SECTION {idx + 1} of {len(data['sections'])}"
            + (f" (heading: {sec['heading']})" if sec.get("heading") else "")
            + f"\n\nTEXT:\n{text}\n\nReturn the JSON conceptual map.")
    raw = client.complete(DESCRIBE_SYSTEM, user, max_tokens=1200,
                          temperature=0.3, json_mode=True)
    meter.mark("describe")
    desc = _norm_description(llm._strip_json(raw))
    sec["description"] = desc
    _save(book_id, data)
    return {"description": desc, "usage": meter.report(), "cached": False}


def build_descriptions(book_id: str, *, sample=None, force: bool = False) -> dict:
    """Batch: describe every (or the first `sample`) section. Cost-guarded by the
    per-section cache; reports tokens + free-tier share at the end."""
    from . import llm, usage
    client = llm.get_client()
    if client is None:
        raise SystemExit("No LLM client (set a provider key in .env).")
    data = _require(book_id)
    secs = data["sections"][:sample] if sample else data["sections"]
    todo = [s for s in secs if force or not s.get("description")]
    print(f"sections[{book_id}]: describing {len(todo)} of {len(secs)} sections "
          f"({len(secs) - len(todo)} cached)…")
    t0 = (client.total_usage or {}).get("total", 0)
    done = 0
    import time
    from .enrich import BATCH_PAUSE
    for s in todo:
        try:
            describe_section(book_id, s["idx"], client, force=force)
            done += 1
            print(f"  [{s['idx'] + 1}/{len(secs)}] {s['description']['title']}")
        except Exception as e:
            print(f"  [{s['idx'] + 1}] failed ({type(e).__name__}: {e}); skipping")
        time.sleep(BATCH_PAUSE)
    used = (client.total_usage or {}).get("total", 0) - t0
    note = usage.note_and_record(client, used, done)
    print(f"sections[{book_id}]: {done} described · {used} tokens{note}")
    return {"described": done, "tokens": used}


# --- AI brainstorm per section (cached) --------------------------------------
def _brainstorm_path(book_id: str):
    return config.INDEX_DIR / f"sections_{book_id}_brainstorm.json"


def brainstorm_section(book_id: str, idx: int, client, *, force: bool = False) -> dict:
    """llm.brainstorm() over the section's passages — interpretations, comparisons,
    follow-ups — cached per section id. Returns {brainstorm, usage, cached}."""
    from . import llm, usage
    data = _require(book_id)
    if idx < 0 or idx >= len(data["sections"]):
        raise ValueError(f"section idx {idx} out of range")
    sec = data["sections"][idx]
    cache = _load_json(_brainstorm_path(book_id), {})
    if sec["id"] in cache and not force:
        return {"brainstorm": cache[sec["id"]], "usage": None, "cached": True}
    if client is None:
        raise SystemExit("No LLM client (set GEMINI_API_KEY in .env).")

    meter = usage.Meter(client)
    passages = section_passages(book_id, sec)
    desc = sec.get("description") or {}
    seed = desc.get("summary") or sec.get("heading") or data["title"]
    bs = llm.brainstorm(seed, passages, client)
    meter.mark("brainstorm")
    out = {"interpretations": [i.model_dump() for i in bs.interpretations],
           "comparisons": [c.model_dump() for c in bs.comparisons],
           "follow_ups": list(bs.follow_ups)}
    cache[sec["id"]] = out
    _save_json(_brainstorm_path(book_id), cache)
    return {"brainstorm": out, "usage": meter.report(), "cached": False}


# --- accessors / io ----------------------------------------------------------
def _load_json(path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default
    return default


def _save_json(path, data):
    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _load_raw(book_id: str):
    return _load_json(sections_path(book_id), None)


def _save(book_id: str, data: dict):
    _save_json(sections_path(book_id), data)


def _require(book_id: str) -> dict:
    data = _load_raw(book_id)
    if not data:
        raise SystemExit(f"No sections for '{book_id}'. Run: rhizome sections --book {book_id}")
    return data


def load_sections(book_id: str) -> dict | None:
    """Full sections file (skeleton + any descriptions), or None if not built."""
    return _load_raw(book_id)


def book_overview(book_id: str) -> dict:
    """Light payload for the reader's nav: per-section id/idx/title/heading/words
    and whether a description exists yet (no full text)."""
    data = _require(book_id)
    secs = [{"id": s["id"], "idx": s["idx"], "heading": s.get("heading", ""),
             "title": (s.get("description") or {}).get("title", ""),
             "word_count": s["word_count"], "page_start": s.get("page_start"),
             "page_end": s.get("page_end"), "described": bool(s.get("description"))}
            for s in data["sections"]]
    return {"book_id": book_id, "title": data["title"], "author": data["author"],
            "target_words": data["target_words"], "n_sections": len(secs),
            "n_described": sum(1 for s in secs if s["described"]), "sections": secs}


def get_section(book_id: str, idx: int) -> dict:
    """One section, fully resolved for the reader: original text + description +
    its chunk ids (annotation targets). Brainstorm is fetched lazily/separately."""
    data = _require(book_id)
    if idx < 0 or idx >= len(data["sections"]):
        raise ValueError(f"section idx {idx} out of range")
    sec = data["sections"][idx]
    bs_cache = _load_json(_brainstorm_path(book_id), {})
    return {
        "id": sec["id"], "idx": idx, "n_sections": len(data["sections"]),
        "book_id": book_id, "book_title": data["title"], "author": data["author"],
        "heading": sec.get("heading", ""), "chunk_ids": sec["chunk_ids"],
        "page_start": sec.get("page_start"), "page_end": sec.get("page_end"),
        "word_count": sec["word_count"],
        "text": section_text(book_id, sec),
        "description": sec.get("description"),
        "brainstorm": bs_cache.get(sec["id"]),
    }
