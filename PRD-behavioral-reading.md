# PRD — Behavioural reading capture ("Reading Rhythm")

> Paste into Claude Code. A passive layer that captures reading behaviour, derives
> *evidence-bound* attention hotspots, and turns them into candidate sparks, engine
> seed-weights, and a reading self-portrait. Symptom, not verdict; local; opt-in.

## 1. Context
The reader already tracks the active passage (IntersectionObserver → `activeId`).
Chunks carry `character` tags + embeddings. Workspace persists notes/chat. The
engine seeds explorations from passages. This feature adds the *involuntary*
complement to explicit annotation — the body's reading, captured and offered back
as a question.

## 2. Goal
Log lightweight reading behaviour → per-passage attention features → corroborated
hotspots → (a) one-tap candidate sparks, (b) a rhythm heatmap, (c) dwell-weighted
engine seeds, (d) a dwell×character self-portrait. Every claim bound to evidence.

## 3. Non-goals
- No psyche "verdicts" (no "you found this profound"); claims are always
  evidence-bound and phrased as invitations.
- No deep learning on sparse personal data; no cloud; no eye-tracking model.
- No interruption — surface at session end, never mid-read.

## 4. Requirements

**R1 — Capture (client, cheap).** Event log: passage enter/exit (timestamps),
throttled scroll samples (~4/s, position+direction), `selectionchange` (selected
span, whether it became a highlight), idle (no pointer/scroll/key for >Ns) and
**Page Visibility** (tab hidden). Buffer and `POST /api/behavior` every ~15s and
on `visibilitychange`/unload. Store under `workspace/behavior/<book>.jsonl`.
Honest signal weighting: **lean on dwell-speed, re-reads, selection-without-
highlight; treat hover/clicks as noise** (log but don't score them).

**R2 — Sessionize (server).** Reconstruct the timeline; **strip idle + hidden
time** (mandatory — otherwise dwell is garbage). Per passage compute:
`attentive_ms`, `ms_per_word` (normalise by length), `revisits` (scroll-backs),
`selected_not_highlighted` (bool), `first_pass_ms_per_word`, `max_dwell`.

**R3 — Phase 0 scoring (stats, NO ML — ship first).** Robust z-score of
`ms_per_word` vs the reader's rolling baseline; **Bayesian/shrinkage** estimate so
thin-evidence passages pull toward baseline (kills cold-start false positives).
A **hotspot requires ≥2 corroborating signals** (e.g. slow AND revisited).

**R4 — Phase 1 analysis (unsupervised, label-free; optional deps).**
- **Change-point detection** (`ruptures`, PELT / BOCPD) → segment the session into
  **rhythm regimes** (skim / deep / stalled).
- **Clustering** (sklearn GMM or HDBSCAN) over `[ms_per_word, revisits, selected,
  character_onehot, embedding]` → **reading-moment types**.
- **(optional) HMM** (`hmmlearn`) → latent **reading states** (engaged/skim/stuck/away).
- **(optional) Isolation Forest / LOF** → multi-signal anomaly hotspots.

**R5 — Phase 2 personal salience model (supervised; only after enough labels).**
Each confirmed/dismissed candidate spark (R6b) is a **label**. Train a small
**regularised** per-user model — start `LogisticRegression` on the R2 features;
later a tiny 1D-CNN/transformer over the per-passage time-series — predicting
"this will matter to *you*." This is an **active-learning loop**: behaviour →
candidate → confirm → model sharpens. Guard: don't train under ~N labels; show
confidence; never overfit (strong regularisation).

**R6 — Outputs.**
a. **Rhythm heatmap** — the book shaded by attentive-time / speed / revisits,
   with regime bands (R4). A mirror, with the raw evidence on hover.
b. **End-of-session candidate sparks** — "N places drew you" → one-tap *Keep*
   (→ creates an annotation + an engine seed + a positive label) or *Dismiss*
   (negative label). The zero-effort capture loop from the Spark idea.
c. **Dwell-weighted engine seeds** — attention scores bias `store.connections`
   seed selection toward where the reader lingered.
d. **Dwell × character self-portrait** — "you slow on aporetic/poetic, skim
   historical," each claim backed by counts.
e. **Longitudinal atlas** — rhythm across books over time.

**R7 — Guardrails (the practicality contract).** Evidence-bound claims only;
local-only + opt-in + one-click clear + a "what's logged" view; low-confidence
until a baseline exists; offer at session end, never interrupt; the personal model
is optional and inspectable.

## 5. ML model map (what, where, why — and what to avoid)
| Phase | Method | Library | Role |
|---|---|---|---|
| 0 | robust z-score + Bayesian shrinkage | numpy/scipy | baseline hotspots, cold-start-safe |
| 1 | change-point (PELT/BOCPD) | ruptures | rhythm regimes |
| 1 | GMM / HDBSCAN | scikit-learn / hdbscan | reading-moment types |
| 1 | HMM | hmmlearn | latent reading states |
| 1 | Isolation Forest / LOF | scikit-learn | multi-signal anomalies |
| 2 | Logistic Reg → small 1D-CNN/Transformer | sklearn → torch (later) | personal salience, active learning |
**Avoid:** deep nets on tiny data; eye-tracking/scanpath models (no eye data);
any absolute (non-relative) scoring.

## 6. Endpoints / storage
- `POST /api/behavior` (batched events) · `GET /api/rhythm?book=` (heatmap+regimes)
  · `GET /api/candidates?session=` · `POST /api/candidates/confirm` (Keep/Dismiss → label).
- `workspace/behavior/<book>.jsonl` (events) + `workspace/rhythm/<book>.json` (derived cache).

## 7. Acceptance criteria
- Idle/hidden time is excluded (verify: leaving the tab does not inflate dwell).
- Hotspots require ≥2 signals; a single long dwell alone is not flagged.
- Candidate sparks are confirmable in one tap and create a real annotation + label.
- All UI claims show their evidence ("returned 3×; 2.1× your average pace").
- Works with zero extra deps at Phase 0 (numpy only); Phase 1/2 deps optional.

## 8. Sequencing
1. R1–R3 + R6a/R6b (capture → stats hotspots → heatmap + candidate sparks). Prove
   the signal matches where you *know* you were gripped. If it doesn't, stop —
   the signal is noise, cheaply learned.
2. R6c (dwell-weighted seeds) — trivial once scores exist.
3. R4 regimes/clusters + R6d self-portrait.
4. R5 personal model — only after enough confirm/dismiss labels accumulate.

## 9. Open questions
- Idle threshold (start 20s) and scroll-back window for "revisit."
- Heatmap metric default (attentive-time vs speed-z vs revisits).
- Min labels before the Phase-2 model activates; per-book vs global baseline.
