"""Durable quote anchoring against a book's canonical converted-text spine."""
from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import re
import unicodedata

from . import config
from .chunk import _strip_frontmatter


_SPACE_RE = re.compile(r"\s+")
_HYPHEN_BREAK_RE = re.compile(r"(?<=\w)-\s*\n\s*(?=\w)")


@dataclass(frozen=True)
class Resolution:
    spine_start: int
    spine_end: int
    exact: bool
    confidence: float


def spine_path(book_id: str):
    matches = list(config.CONVERTED_DIR.rglob(f"{book_id}.md"))
    if len(matches) != 1:
        raise FileNotFoundError(f"expected one spine for {book_id!r}, found {len(matches)}")
    return matches[0]


def load_spine(book_id: str) -> str:
    return _strip_frontmatter(spine_path(book_id).read_text(encoding="utf-8"))


def _normalise_with_map(text: str) -> tuple[str, list[int]]:
    """Normalise typography/whitespace while retaining source positions."""
    out: list[str] = []
    positions: list[int] = []
    in_space = False
    pos = 0
    while pos < len(text):
        char = text[pos]
        # Join extraction line-break hyphenation while mapping retained text
        # back to positions in the original (un-normalised) spine.
        if char == "-" and re.match(r"\s*\n\s*\w", text[pos + 1:]):
            pos += 1
            while pos < len(text) and text[pos].isspace():
                pos += 1
            continue
        for decomposed in unicodedata.normalize("NFKD", char):
            if decomposed == "\u00ad" or unicodedata.combining(decomposed):
                continue
            if decomposed.isspace():
                if out and not in_space:
                    out.append(" "); positions.append(pos)
                in_space = True
            else:
                out.append(decomposed); positions.append(pos); in_space = False
        pos += 1
    return "".join(out).strip(), positions


def _context_score(spine: str, start: int, end: int, prefix: str, suffix: str) -> float:
    scores = []
    if prefix:
        actual = spine[max(0, start - len(prefix) - 40):start]
        scores.append(SequenceMatcher(None, _SPACE_RE.sub(" ", prefix).strip(),
                                     _SPACE_RE.sub(" ", actual).strip()).ratio())
    if suffix:
        actual = spine[end:end + len(suffix) + 40]
        scores.append(SequenceMatcher(None, _SPACE_RE.sub(" ", suffix).strip(),
                                     _SPACE_RE.sub(" ", actual).strip()).ratio())
    return sum(scores) / len(scores) if scores else 1.0


def resolve(quote: str, prefix: str = "", suffix: str = "", *,
            book_id: str, min_confidence: float = .86) -> Resolution | None:
    """Resolve exactly, then normalised-exact, then conservatively fuzzy.

    Tied/weak candidates return None: an orphan is safer than a wrong note.
    """
    quote = quote.strip()
    if not quote:
        return None
    spine = load_spine(book_id)
    exacts = [m.start() for m in re.finditer(re.escape(quote), spine)]
    if exacts:
        ranked = sorted(((_context_score(spine, s, s + len(quote), prefix, suffix), s)
                         for s in exacts), reverse=True)
        if len(ranked) > 1 and ranked[0][0] == ranked[1][0] and not (prefix or suffix):
            return None
        score, start = ranked[0]
        return Resolution(start, start + len(quote), True, score)

    norm_spine, posmap = _normalise_with_map(spine)
    norm_quote, _ = _normalise_with_map(quote)
    idxs = [m.start() for m in re.finditer(re.escape(norm_quote), norm_spine)]
    if idxs:
        if len(idxs) > 1 and not (prefix or suffix):
            return None
        ranked = []
        for idx in idxs:
            start, end = posmap[idx], posmap[idx + len(norm_quote) - 1] + 1
            ranked.append((_context_score(spine, start, end, prefix, suffix), start, end))
        score, start, end = max(ranked)
        return Resolution(start, end, False, min(.99, score))

    # Windowed edit-distance approximation around quote-sized word windows.
    words = list(re.finditer(r"\S+", norm_spine))
    qwords = max(1, len(norm_quote.split()))
    candidates = []
    for width in range(max(1, qwords - 2), qwords + 3):
        for i in range(0, max(0, len(words) - width + 1)):
            a, b = words[i].start(), words[i + width - 1].end()
            ratio = SequenceMatcher(None, norm_quote, norm_spine[a:b]).ratio()
            if ratio >= min_confidence:
                candidates.append((ratio, a, b))
    candidates.sort(reverse=True)
    if not candidates or (len(candidates) > 1 and candidates[0][0] - candidates[1][0] < .02):
        return None
    score, a, b = candidates[0]
    return Resolution(posmap[a], posmap[b - 1] + 1, False, score)


def chunks_for(start: int, end: int, *, book_id: str,
               chunks: list[dict] | None = None) -> list[dict]:
    if chunks is None:
        from .chunk import load_chunks
        chunks = load_chunks()
    hits = []
    for chunk in chunks:
        if chunk.get("book_id") != book_id:
            continue
        a, b = chunk.get("spine_start"), chunk.get("spine_end")
        if a is None or b is None:
            continue
        overlap = max(0, min(end, b) - max(start, a))
        if overlap:
            hits.append({"chunk_id": chunk["id"], "overlap": overlap})
    hits.sort(key=lambda h: (-h["overlap"], h["chunk_id"]))
    for i, hit in enumerate(hits):
        hit["primary"] = i == 0
    return hits


def selector_bundle(quote: str, prefix: str, suffix: str, resolution: Resolution,
                    locator: dict | None = None) -> dict:
    return {
        "text_quote": {"quote": quote, "prefix": prefix, "suffix": suffix},
        "text_position": {"spine_start": resolution.spine_start,
                          "spine_end": resolution.spine_end},
        "locator": locator or {},
        "approximate": not resolution.exact,
        "confidence": round(resolution.confidence, 4),
    }
