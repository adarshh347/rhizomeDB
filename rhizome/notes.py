"""Parse annotated reading notes into structured records.

Reading notes carry inline annotations in a small markup (see SCHEMA.md):
block tags ``<corr> ... </corr>`` (or the paren form ``(corr) ... (/corr)``) and
inline suffix markers like ``...perspective.(anch)``.

This turns a note into a flat list of annotation records — correlations
(proto-edges across traditions), sutras and anchors (high-value seeds), actions
(a task queue), chamatkara markers (aesthetic-intensity signals) and the
reader's own thoughts — that the engine can act on. The human supplies the
structural judgement embeddings can't; this is how it enters the system.
"""
import json
import re

from . import config

# canonical tag -> (aliases, engine role)
TAGS = {
    "anchor":     (("anch",),       "seed"),       # a load-bearing claim
    "sutra":      (("sutrra",),     "seed"),       # a compressed key formulation
    "reveal":     (("rev",),        "pattern"),    # a perspective-shift
    "assert":     ((),              "claim"),
    "correlate":  (("corr",),       "edge"),       # a cross-tradition connection
    "chamatkara": (("chamat",),     "intensity"),  # a flash of aesthetic wonder
    "mythought":  (("mythoughts",), "voice"),      # the reader's own thinking
    "suggest":    ((),              "direction"),  # a direction for reader or engine
    "action":     ((),              "task"),       # something to build/write/do
    "describe":   (("des",),        "context"),
}

ALIAS = {}
ROLE = {}
for _canon, (_aliases, _role) in TAGS.items():
    ALIAS[_canon] = _canon
    ROLE[_canon] = _role
    for _a in _aliases:
        ALIAS[_a] = _canon

_NAMES = sorted(ALIAS, key=len, reverse=True)
_TOKEN = re.compile(
    r"[<(]\s*(?P<close>/?)\s*(?P<name>" + "|".join(re.escape(n) for n in _NAMES) + r")\s*[>)]",
    re.IGNORECASE,
)


def _clean(s: str) -> str:
    """Strip nested tag markers, leaving the prose."""
    return _TOKEN.sub("", s).strip()


def parse_note(text: str, note_id: str) -> list[dict]:
    """Return annotation records in document order, each with a stable id and a
    `parent` id for nesting."""
    records: list[dict] = []
    stack: list[dict] = []
    cnt = 0

    def newid() -> str:
        nonlocal cnt
        i = cnt
        cnt += 1
        return f"{note_id}#a{i:03d}"

    for m in _TOKEN.finditer(text):
        name = ALIAS[m.group("name").lower()]
        is_close = bool(m.group("close"))
        before = text[m.start() - 1] if m.start() > 0 else "\n"
        inline = (not is_close) and before not in " \t\r\n"  # suffix marker: .(anch)

        if inline:
            line_start = text.rfind("\n", 0, m.start()) + 1
            records.append({
                "id": newid(), "note_id": note_id, "type": name, "role": ROLE[name],
                "text": _clean(text[line_start:m.start()]), "inline": True,
                "parent": stack[-1]["id"] if stack else None,
            })
            continue

        if not is_close:
            stack.append({"id": newid(), "type": name, "role": ROLE[name],
                          "start": m.end(),
                          "parent": stack[-1]["id"] if stack else None})
        else:
            for i in range(len(stack) - 1, -1, -1):
                if stack[i]["type"] == name:
                    node = stack.pop(i)
                    records.append({
                        "id": node["id"], "note_id": note_id, "type": node["type"],
                        "role": node["role"], "text": _clean(text[node["start"]:m.start()]),
                        "inline": False, "parent": node["parent"],
                    })
                    del stack[i:]  # drop any deeper unclosed blocks
                    break

    for node in stack:  # auto-close leftovers at end of note
        records.append({
            "id": node["id"], "note_id": note_id, "type": node["type"],
            "role": node["role"], "text": _clean(text[node["start"]:]),
            "inline": False, "parent": node["parent"],
        })

    records.sort(key=lambda r: int(r["id"].rsplit("#a", 1)[1]))
    return records


def load_notes() -> list[tuple[str, str]]:
    if not config.NOTES_DIR.exists():
        return []
    return [(md.stem, md.read_text(encoding="utf-8"))
            for md in sorted(config.NOTES_DIR.rglob("*.md"))]


def build_annotations() -> list[dict]:
    all_recs: list[dict] = []
    for note_id, text in load_notes():
        recs = parse_note(text, note_id)
        all_recs.extend(recs)
        print(f"  {note_id:36s} {len(recs):4d} annotations")
    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    with config.ANNOTATIONS_PATH.open("w", encoding="utf-8") as f:
        for r in all_recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"Total: {len(all_recs)} annotations -> {config.ANNOTATIONS_PATH}")
    return all_recs


def load_annotations() -> list[dict]:
    if not config.ANNOTATIONS_PATH.exists():
        return []
    with config.ANNOTATIONS_PATH.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def _short(s: str, n: int = 150) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[:n] + "…"


def digest(recs: list[dict]) -> None:
    from collections import Counter
    by_role = Counter(r["role"] for r in recs)
    print("\nby role: " + ", ".join(f"{k}={v}" for k, v in by_role.most_common()))

    def show(role, header):
        items = [r for r in recs if r["role"] == role and r["text"]]
        if not items:
            return
        print(f"\n{header} ({len(items)})")
        for r in items:
            print(f"  · [{r['type']}] {_short(r['text'])}")

    show("edge", "CORRELATIONS  (proto-edges — bridges to persist in the graph)")
    show("seed", "SEEDS  (sutras/anchors — high-value evocation starting points)")
    show("task", "ACTIONS  (the build/write queue)")
    show("direction", "DIRECTIONS  (research / build leads)")
    show("voice", "YOUR VOICE  (original thoughts, attributed to you)")
    show("intensity", "CHAMATKARA  (disclosure-intensity markers)")
