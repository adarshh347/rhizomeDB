# Reader — Security Audit

- **Commit audited:** `f616bf8` (*Merge pull request #12 from adarshh347/reader-wide-marginalia*)
- **Date:** 2026-08-10
- **Scope:** the reader feature — `frontend/src/reader/*`, `frontend/src/routes/Reader.tsx`, `frontend/src/api/*`, `rhizome/reader_service.py`, `rhizome/anchor.py`, `rhizome/api.py`, `rhizome/imports.py`. The review followed data flow out of scope where it led (`rhizome/workspace.py`, `rhizome/sources.py`, `rhizome/ingest.py`, `rhizome/config.py`).
- **Method:** one finder pass over the source, then an **independent skeptical verifier per candidate**, each instructed to default to "the finding is wrong" and to test the load-bearing claim rather than accept it. Findings below survived that pass. Static analysis only — the server was never run and nothing was exploited live; the one dynamic check was importing `rhizome.anchor` in a throwaway interpreter to exercise `spine_path()` directly (read-only, no server, no writes).
- **Threat model.** This is a local-first personal reading tool. Both launch paths bind loopback (`api.py:518`, `cli.py:254` default `--host 127.0.0.1`) and there is no `0.0.0.0` anywhere in the repo. There is no authentication on any of the ~40 routes, and that is the documented architecture (`README.md:89-109`), not a defect. Severity below is calibrated to that: the realistic attacker is a co-resident local process, a LAN peer if the user opts into `--host 0.0.0.0`, or a chained same-origin XSS / DNS rebind — **not** an arbitrary web page.

**Result: 2 confirmed findings (both Medium), 1 candidate rejected.** Nothing High survived verification. Notably, the frontend reader code — the bulk of the requested scope — produced **no findings at all**; both confirmed issues are in the Python backend.

---

## S1 · Arbitrary file write via unsanitised session `id` — Medium

- **Location:** `rhizome/api.py:362-364` → `rhizome/workspace.py:256-266`
- **Category:** path traversal / arbitrary file write
- **Verifier verdict:** CONFIRMED, confidence 8/10

### What

`POST /api/v2/sessions` takes a free-form body and hands it straight to `workspace.save_session()`:

```python
# api.py:362-364
@app.post(f"{V2}/sessions")
def save_session(payload: dict[str, Any]):
    return {"ok": True, **workspace.save_session(payload)}
```

```python
# workspace.py:256-266
def save_session(payload: dict) -> dict:
    _ensure()
    sid = payload.get("id") or _uid("ses")
    payload["id"] = sid
    ...
    (SESSIONS_DIR / f"{sid}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
```

There is no Pydantic model, no validator, no dependency. Both the **path** (`sid`) and the **file contents** (the serialised body) are caller-controlled. `SESSIONS_DIR` is `config.ROOT / "workspace" / "sessions"` — inside the repo — so `../../` escapes into the working tree, and an absolute `sid` bypasses the join entirely (`Path("/a/b") / "/tmp/evil.json"` → `/tmp/evil.json`). The only constraints are the forced `.json` suffix and that the parent directory already exist.

### Why this is an omission rather than a decision

The module already has the sanitiser and applies it everywhere else that touches the filesystem:

| Location | Function | `_safe()` applied? |
|---|---|---|
| `workspace.py:42` | `_safe()` — `re.sub(r"[^A-Za-z0-9_.-]", "_", name)` | *(the definition)* |
| `workspace.py:228` | chat path | yes |
| `workspace.py:287` | `get_session` | yes |
| `workspace.py:294` | `delete_session` | yes |
| `rhythm.py:41` | `behavior_path` | yes |
| **`workspace.py:264`** | **`save_session`** | **no** |

The one function that writes attacker-supplied bytes to an attacker-supplied path is the only one that skips it — sitting directly above two siblings that don't. Supporting this reading: `grep -rn "sessions" frontend/src` returns nothing, so no client calls this endpoint today and the round-trip `id` it accepts has no legitimate consumer.

### Impact

Direct and certain: arbitrary file write with fully attacker-controlled JSON content, to any pre-existing directory. The escalation path to RCE is real but takes a second step and a wait — overwrite `frontend/package.json` with a `postinstall` hook, then the developer's next `npm install` executes it. Both `frontend/package.json` and `data/catalog.json` exist in this repo and are viable targets.

### Reachability

Loopback, no auth. In descending plausibility: **same-origin JS** (the production React build is served from the same origin as the API via `mount_frontend`, `api.py:492-510`, so any XSS in the reader pivots straight to this); **DNS rebinding** (no `TrustedHostMiddleware`, no `Host` check anywhere); any local process.

**Not** a drive-by. FastAPI only parses a body into `dict[str, Any]` for `Content-Type: application/json`, which forces a CORS preflight, and `allow_origins` is pinned to four localhost Vite origins (`api.py:100-107`). An arbitrary attacker page cannot reach this with a simple form post. *(The original finder implied it could; that was wrong.)*

### Fix

One line — `workspace.py:264`:

```python
sid = _safe(payload.get("id") or _uid("ses"))
path = (SESSIONS_DIR / f"{sid}.json").resolve()
if path.parent != SESSIONS_DIR.resolve():
    raise ValueError("invalid session id")
```

Better: ignore a client-supplied `id` on create and always mint via `_uid("ses")`, requiring a server-known id for updates. Also give the route a Pydantic model instead of `dict[str, Any]`.

---

## S2 · Path traversal via unsanitised `book_id` in filesystem globs — Medium

- **Location:** `rhizome/anchor.py:25-33`, `rhizome/sources.py:28-30`
- **Category:** path traversal / information disclosure
- **Verifier verdict:** CONFIRMED, confidence 9/10 — the highest-confidence finding in this audit

### What

```python
# anchor.py:25-33
def spine_path(book_id: str):
    matches = list(config.CONVERTED_DIR.rglob(f"{book_id}.md"))
    if len(matches) != 1:
        raise FileNotFoundError(f"expected one spine for {book_id!r}, found {len(matches)}")
    return matches[0]
```

`book_id` reaches this glob from request bodies with no validation. `api.py:40-44` declares `class ResolveRequest(BaseModel): book_id: str` — no regex, no validator, no catalog lookup; same for `AnnotationCreate` (`api.py:57`) and `MarkdownImport` (`api.py:88`).

**The load-bearing claim, verified rather than assumed.** `pathlib.rglob()` does not reject `..`, and honours glob metacharacters. On this machine's **Python 3.9.6**, running against the real `anchor.spine_path`:

```
anchor.spine_path('../../README')             -> /Users/…/rhizomedb/README.md
anchor.spine_path('../../**/*')               -> FileNotFoundError: … found 279
anchor.spine_path('../../../../**/*')         -> FileNotFoundError: … found 62455   # entire $HOME
anchor.spine_path('../../../../.claude/**/*') -> FileNotFoundError: … found 524
```

Because `rglob` prepends `**/` and `**` matches zero-or-more components, traversal is depth-fuzzy — `../../../README.md` matches through intermediate corpus directories too.

> **Version caveat — since closed.** First verified on Python 3.9.6, then **re-verified on Python 3.12.13**, which is what this project actually runs on (the CLI cannot import on 3.9 — see the environment note in the UI audit). Identical behaviour, against a live venv and the real 8-book index:
>
> ```
> CONVERTED_DIR.rglob('../../README.md')
>   -> data/converted/../../README.md
> anchor.spine_path('../../README')          -> …/rhizomedb/README.md
> anchor.spine_path('../../PRD-reader-native') -> …/rhizomedb/PRD-reader-native.md
> anchor.spine_path('../../**/*')            -> "expected one spine for '../../**/*', found 315"
> anchor.spine_path('../../../../**/*')      -> "… found 62528"          # entire $HOME
> anchor.resolve('A connection engine', book_id='../../README')
>   -> Resolution(spine_start=13, spine_end=32, exact=True, confidence=1.0)
> ```
>
> Python 3.13 reworked `glob` and remains unverified; re-check if the project moves to it.

### Two primitives

**(a) Enumeration.** `api.py:211-212` (and `143-144`, `278-279`, `288-289`, `301-302`) does `except FileNotFoundError as exc: raise HTTPException(404, str(exc))` — the message, *including the match count*, becomes the client-visible `detail`. The `len(matches) != 1` guard isn't a defence; it **is** the primitive, because the count leaks.

```
curl -XPOST localhost:8010/api/v2/anchors/resolve -H 'content-type: application/json' \
     -d '{"book_id":"../../../../**/*","quote":"x"}'
→ {"detail":"expected one spine for '../../../../**/*', found 62455"}
```

**(b) Content oracle.** Once a single file is targeted, `/api/v2/anchors/resolve` returns `spine_start`/`spine_end` offsets on a hit and nothing on a miss — verified end-to-end against `README.md`, outside the corpus:

```
resolve('A connection engine for philosophical texts.', book_id='../../README')
  -> Resolution(spine_start=13, spine_end=57, exact=True, confidence=1.0)
resolve('A connection engine ',  book_id='../../README')   # prefix extension
  -> Resolution(spine_start=13, spine_end=32, exact=True, confidence=1.0)
resolve('zzz-not-present-xyzzy', book_id='../../README')   -> None
```

The fuzzy tier (`anchor.py:109-123`, `SequenceMatcher`, `min_confidence=0.86`) makes incremental extraction tolerant of near-misses. And `POST /api/v2/import/markdown` (`imports.py:165-181`) resolves *every* quote in one request and returns per-quote selectors — a **batched** oracle testing dozens of candidates per HTTP round-trip.

### Reachable sinks

Body/form parameters only — `POST /api/v2/anchors/resolve` (`api.py:206-220`), `POST /api/v2/annotations` (`api.py:239-250`), `POST /api/v2/import/markdown` (`api.py:282-289`), `POST /api/v2/import/sidecar` (`api.py:292-304`, `book_id` as a form field).

URL path segments are **not** a vector: Starlette compiles `{book_id}` to `[^/]+`, so `GET /api/v2/books/{book_id}/spine` — which would return the whole file — cannot carry a traversal payload.

### Limits (stated honestly)

- The `f"{book_id}.md"` suffix confines reads to **Markdown files**. No `.env`, no `id_rsa`, no `~/.aws/credentials`.
- The enumeration oracle discloses `.md` file *counts*, not general path existence — a non-existent directory and an existing one with no Markdown both return `found 0`.
- Extraction is oracle-based (guess-and-confirm), not a content dump.
- Browser drive-by is largely blocked: JSON routes force a preflight against the pinned origin allowlist. `/api/v2/import/sidecar` is multipart and so fires without preflight, but the response can't be read — no cross-origin exfiltration.

The honest attacker is a **co-resident local process or another local user account** (crosses a privilege boundary on a multi-user box; doesn't on a single-user laptop, where the files were readable anyway), or a **LAN peer** if the user runs `--host 0.0.0.0` — plausible for a reading tool used from a tablet. Real target: a personal Obsidian vault or private notes directory, exactly the sort of `.md` corpus this tool's users keep.

### Fix

Validate `book_id` before it reaches a glob, in both `anchor.py:25` and `sources.py:28`:

```python
if not re.fullmatch(r"[A-Za-z0-9_-]+", book_id):
    raise FileNotFoundError("unknown book id")
```

Better: resolve through `load_catalog()` so only known ids are addressable, and assert `spine_path(...).resolve().is_relative_to(config.CONVERTED_DIR.resolve())`. Separately, stop echoing raw `FileNotFoundError` text into HTTP responses — return a generic "unknown book id" with no count.

---

## Rejected candidate

### R1 · "Unauthenticated loopback API with no Origin/Host validation" — rejected

- **Claimed:** Medium, authentication/CSRF, `api.py:99-107`, `159-172`, `292-304`
- **Verifier verdict:** REJECTED, confidence 8/10

The *mechanics* were accurate and I want to record that: there is genuinely no auth on any of the ~40 routes, no `TrustedHostMiddleware`, no `Host` or `Origin` check, and `POST /api/v2/books/upload` (`api.py:159`) and `POST /api/v2/import/sidecar` (`api.py:292`) are `multipart/form-data` — a CORS-safelisted content type, so no preflight, so a cross-site form post does reach and execute them. CORS does not stop the request, only the response read. That much is correct.

It was rejected on framing, not mechanics:

- **The unauthenticated loopback API is the documented architecture**, not a defect. `README.md:89-109` describes the FastAPI backend on `127.0.0.1:8010` behind a Vite dev server; both launch paths bind loopback; there is no `0.0.0.0` anywhere in the repo. "Add auth / `TrustedHostMiddleware` / Origin checks to a single-user local-first tool" is textbook missing-hardening, which is outside this review's remit.
- **The CSRF is blind write-only.** Every read endpoint is GET-JSON and every JSON write takes a Pydantic body forcing a preflight, which the four-origin allowlist rejects. An attacker gets no book text, annotations, or chat history. The claim conflated the CSRF surface (a handful of endpoints) with the DNS-rebinding surface (all 40).
- **The writes are bounded.** `ingest.py:104-127` enforces `ALLOWED_EXT = {".pdf",".epub",".mobi"}` and slugifies the stem to `[a-z0-9-]` — no traversal, no attacker-chosen extension. The catalog write is a scoped per-`book_id` append, not a corruption of existing entries.
- **The DNS-rebinding leg is speculative**, presented as a given: it needs attacker-controlled low-TTL DNS, the victim holding the tab open across the rebind, port 8010 guessed, and browser Private Network Access gating defeated.

Maximum real impact is unsolicited writes to a personal workspace: a junk book added to the library, injected annotations against a guessed `book_id`, behavior data cleared. Nuisance-tier and recoverable. A security team would close this as accepted-risk-by-design.

**Worth doing anyway, as hardening rather than a finding:** check `Origin`/`Sec-Fetch-Site` on state-changing routes. Note the verifier found endpoints the original finder missed here — several **no-body POSTs are also preflight-free and destructive**, since FastAPI ignores the absent body: `POST /api/v2/orphans/{ann_id}/dismiss` (`api.py:329`, deletes an annotation), `POST /api/v2/behavior/clear` (`api.py:408`), `POST /api/v2/books/{book_id}/import/pdf` (`api.py:274`). Any Origin check should cover these too. Adding `TrustedHostMiddleware` is also the single cheapest change here, because it independently closes the DNS-rebinding leg that **S1** depends on.

---

## Examined and ruled out

Recorded so a later reviewer knows these were looked at rather than missed.

| Area | Conclusion |
|---|---|
| **XSS across the reader UI** | None. No `dangerouslySetInnerHTML`, no dynamic `innerHTML` (the two `host.innerHTML = ""` in `PdfRenderer.tsx:35` / `EpubRenderer.tsx:36` are constant empty strings), no `eval`/`new Function`/`srcdoc`. Spine text, annotation quotes/notes, SSE candidate text and LLM-generated `exploration`/`note` strings all render as React text children (`SpineView.tsx`, `NotesRail.tsx`, `Marginalia.tsx`, `ConnectionsPanel.tsx`) and are escaped. `MdRenderer` goes through the hand-written `spine.ts` parser, which emits React nodes only — no HTML passthrough. |
| **EPUB iframe injection** | Not exploitable. epub.js `^0.3.93` is used without `allowScriptedContent`, so the default `sandbox="allow-same-origin"` (no `allow-scripts`) applies — scripts in a malicious EPUB do not execute. |
| **CSS injection via annotation `color`** | Not exploitable. `var(--hl-${a.color})` reaches `element.style.background`/`borderColor` (`PdfRenderer.tsx:155`, `SpineView.tsx:11`, `NotesRail.tsx:63`, `Marginalia.tsx:119`), but CSSOM property assignment rejects values containing `;` — no declaration smuggling. Cosmetic at worst. |
| **DOM selector injection** | Not exploitable. `querySelector(\`[data-aid="${a.id}"]\`)` at `MdRenderer.tsx:115` / `PdfRenderer.tsx:170` omits `CSS.escape` (unlike `Marginalia.tsx:67`), but `id` is server-minted (`workspace._uid`, `an_<sha1[:8]>`) and not attacker-influenced. Worth adding `CSS.escape` for consistency; not a vulnerability. |
| **SPA static handler** | Safe. `api.py:501-510` does `.resolve()` plus a `startswith(dist)` containment check; traversal falls through to `index.html`. |
| **Code execution sinks** | None anywhere in `rhizome/`: no `subprocess`, `os.system`, `pickle`, `yaml.load`, `eval`, `exec`. No SQL, no XML parsing, no template engine. |
| **Upload filename handling** | Safe. `ingest.py:33-47`, `115-128` slug the stem to `[a-z0-9-]` and allowlist the extension. The `source_file:` frontmatter is server-written and can't be poisoned by uploaded content (`_FRONTMATTER_RE` matches only the first block), so `sources._locate_file()`'s `rglob(source_file)` is not attacker-reachable — the same glob pattern as **S2**, but without the attacker-controlled input. |
| **Sidecar / KOReader / CSV / JSON import parsers** | Safe. `imports.py:255-372` is regex/`json`/`csv` only — no Lua evaluation, no object hooks. |

**Out of scope by instruction:** DoS and resource exhaustion (including the 120 MB upload cap and the unbounded `O(words × widths)` fuzzy anchoring at `anchor.py:109-119`), secrets on disk (`config.py:8-27` `.env` loading), and rate limiting.

---

## Summary

| ID | Finding | Severity | Confidence | Fix cost |
|---|---|---|---|---|
| S1 | Arbitrary file write via unsanitised session `id` | Medium | 8/10 | One line |
| S2 | Path traversal via `book_id` in `rglob` | Medium | 9/10 | One line ×2 |
| R1 | ~~Unauthenticated API / CSRF~~ | *rejected* | 8/10 (in rejection) | — |

Both confirmed findings are the same class — **an unvalidated string from a request body used as a filesystem path component** — and both have a one-line fix using a sanitiser the codebase already owns. S2 is the more certain (demonstrated end-to-end against the real function); S1 has the higher ceiling (write, not read, with a path to RCE).

Adding `TrustedHostMiddleware` is worth doing alongside both: it costs one line and closes the DNS-rebinding leg that gives S1 its only non-local reach.
