# PRD — Annotate AI answers ("Companion notes")

> Paste into Claude Code. Let the reader highlight/annotate the companion's
> answers (Discuss drawer, rail chat, Plateau chat) and collect those notes in a
> section parallel to the passage notes, linked back to the passage they grew from.

## 1. Context
Annotations attach to a `target` via `workspace.add_annotation(target, kind,
quote, note)` and list via `workspace.list_annotations(target)`, stored in
`workspace/annotations.jsonl`. Chat lives in `workspace/chats/<target>.jsonl`
(`append_chat`, `load_chat`). Today only book passages (chunk ids) get annotated;
the companion's replies can't be. We want to annotate AI answers too, store them
*parallel but linked*, and view them in their own section.

## 2. Goal
Highlight a span of an AI reply (or note the whole reply) → save it as a
**companion annotation** carrying its own id, the message it came from, and the
**passage the discussion was about** → surface these in a dedicated section
alongside the reading notes, both anchored to the same passage.

## 3. Non-goals
- No new chat/LLM behaviour. No change to how answers are generated.
- Don't fork a separate datastore — reuse `workspace/annotations.jsonl` with
  provenance fields (R3). Parallelism is a *view*, not a second file.

## 4. Requirements

**R1 — Stable message ids.** `workspace.append_chat(target, role, content)`
assigns and returns a stable `msg_id` (e.g. `f"{target}:{n}"` or a short uid),
persisted in the chat record. `load_chat` returns it. The frontend renders each
message bubble with `data-msg-id` and `data-target` so a selection can be anchored.

**R2 — Annotate an AI answer.** The existing selection toolbar (highlight /
comment) must also fire inside `.msg.assistant` bubbles (book rail chat, the
thread drawer, and the Plateau chat). On save, POST an annotation with:
`{kind:'highlight'|'note', quote, note, source:'ai', msg_id, chat_target,
passage_id}` where `passage_id` is the chunk the discussion concerns (the rail's
`activeId`; the drawer's `ann.target`; the Plateau's `CHUNK_ID`).

**R3 — Parallel-but-linked storage.** Extend the annotation record with
`source` (`'reader'` default | `'ai'`), `passage_id`, `msg_id`, `chat_target`
(all optional; existing records stay valid). `list_annotations` gains optional
filters: `source=` and `passage_id=`. Add `list_companion_notes(passage_id=None)`
returning `source=='ai'` annotations (optionally for one passage).

**R4 — The "From the companion" section.** A third rail tab in the book reader
(and a section in the Plateau notes pane): **Notes & highlights · From the
companion · Discuss**. It lists `source=='ai'` annotations, grouped by passage,
each showing the highlighted quote + your note, the passage it links to (jump to
it), and a link back to the message/thread. On a given passage, the normal Notes
pane should also show, in a labelled sub-group, the companion-notes tied to that
same passage — so reading notes and companion notes sit parallel.

**R5 — Provenance for the concept layer (stub, not full build).** Mark these
annotations clearly as `source:'ai'` so a later graph pass can treat a
companion-said-and-human-endorsed insight as a distinct edge origin (e.g.
`origin:'companion'`), never silently merged with passage-grounded edges.

## 5. Endpoints (extend serve.py)
- `POST /api/annotations` — accept the new fields (`source, msg_id, chat_target,
  passage_id`); default `source:'reader'`.
- `GET /api/annotations?source=ai[&passage_id=…]` — filtered list.
- `GET /api/companion-notes[?passage_id=…]` — convenience for the new section.

## 6. Acceptance criteria
- Selecting text in an assistant bubble offers highlight/comment; saving creates
  an annotation with `source:'ai'`, the right `passage_id` and `msg_id`.
- The "From the companion" tab lists those notes grouped by passage; clicking one
  jumps to the passage and/or reopens the thread.
- A passage's Notes pane shows reading notes and companion notes in parallel,
  visually distinguished by source.
- Existing reader annotations are unaffected (old records load; `source` defaults
  to `reader`).

## 7. Sequencing
1. R1 message ids (backend + chat rendering) — the anchor everything needs.
2. R2 selection→save inside assistant bubbles (reuse the existing toolbar).
3. R3 storage fields + filters.
4. R4 the section/view.
5. R5 provenance tag (leave the graph hook as a TODO).

## 8. Open questions
- Section name: "From the companion" vs "Companion notes" vs "Gleanings".
- When the source message is regenerated/edited, keep the annotation pinned to
  the stored quote (it may no longer match live text) — store the quote verbatim
  so it survives.
