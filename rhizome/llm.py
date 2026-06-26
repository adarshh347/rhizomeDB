"""The judging + synthesis brain — provider-agnostic.

Two jobs:
  judge_connections()  — for each candidate pairing, decide whether a genuine
                         conceptual resonance arises "in the flow of the theory"
                         or whether it would be forced. Returns structured
                         verdicts (model emits JSON, we validate with Pydantic).
  synthesize()         — weave the surviving connections into a short cited
                         exploration that traces the lines of flight.

Provider is auto-detected from whichever API key is set, in this order:
  ANTHROPIC_API_KEY → Claude         (native SDK)
  GEMINI_API_KEY / GOOGLE_API_KEY → Gemini   (OpenAI-compatible endpoint)
  GROQ_API_KEY → Groq                (OpenAI-compatible endpoint)
Override with RHIZOME_LLM_PROVIDER (anthropic|gemini|groq) and/or
RHIZOME_LLM_MODEL. If no key is set, the engine runs geometry-only.
"""
import json
import os
from typing import Literal

from pydantic import BaseModel

from . import config


def _clip(text: str) -> str:
    """Token economy: cap passage text sent into prompts (the same passages go to
    judge + synthesis + brainstorm, so this is the biggest lever on tokens/run)."""
    lim = config.LLM_PASSAGE_CHARS
    if not lim or len(text) <= lim:
        return text
    return text[:lim].rstrip() + "…"


# --- provider registry -------------------------------------------------------
PROVIDERS = {
    "anthropic": {"keys": ["ANTHROPIC_API_KEY"], "model": "claude-opus-4-8",
                  "base_url": None},
    "gemini": {"keys": ["GEMINI_API_KEY", "GOOGLE_API_KEY"], "model": "gemini-2.5-flash",
               "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/"},
    "groq": {"keys": ["GROQ_API_KEY"], "model": "llama-3.3-70b-versatile",
             "base_url": "https://api.groq.com/openai/v1"},
}
ORDER = ["anthropic", "gemini", "groq"]


def _resolve_all():
    """Return [(provider, model, base_url, api_key), ...] for every key present,
    ordered so the primary is first. The primary is RHIZOME_LLM_PROVIDER if set,
    otherwise ORDER. The rest become failover backends (used when the primary
    rate-limits). RHIZOME_LLM_MODEL overrides the primary's model only."""
    override = os.environ.get("RHIZOME_LLM_PROVIDER")
    order = ([override] + [p for p in ORDER if p != override]) if override else list(ORDER)
    out = []
    for pos, prov in enumerate(order):
        cfg = PROVIDERS.get(prov)
        if not cfg:
            continue
        key = next((os.environ[k] for k in cfg["keys"] if os.environ.get(k)), None)
        if not key:
            continue
        model = (os.environ.get("RHIZOME_LLM_MODEL") if pos == 0 else None) or cfg["model"]
        out.append((prov, model, cfg["base_url"], key))
    return out


def _resolve():
    """Primary only — (provider, model, base_url, api_key) or None."""
    allp = _resolve_all()
    return allp[0] if allp else None


def provider_info() -> dict:
    """For the frontend: active provider/model + the failover chain (no keys)."""
    allp = _resolve_all()
    if allp:
        prov, model, _, _ = allp[0]
        chain = [p for p, _, _, _ in allp]
        return {"enabled": True, "provider": prov, "model": model,
                "providers": chain, "hint": ""}
    return {"enabled": False, "provider": None, "model": None, "providers": [],
            "hint": "set GEMINI_API_KEY or GROQ_API_KEY (or ANTHROPIC_API_KEY)"}


# --- client ------------------------------------------------------------------
def _zero_usage():
    return {"prompt": 0, "completion": 0, "total": 0}


def _is_rate_limit(e: Exception) -> bool:
    """True for rate-limit / quota-exhausted errors worth failing over on."""
    s = f"{type(e).__name__} {e}".lower()
    return any(t in s for t in ("ratelimit", "rate limit", "rate_limit", "429",
                                "quota", "resource_exhausted", "too many requests"))


def _is_transient(e: Exception) -> bool:
    """Transient server-side errors (overloaded / unavailable / 5xx / timeout) —
    also worth failing over to the next provider rather than aborting the run."""
    s = f"{type(e).__name__} {e}".lower()
    return any(t in s for t in ("500", "502", "503", "504", "overloaded",
                                "unavailable", "internalservererror", "timeout",
                                "temporarily"))


def _should_failover(e: Exception) -> bool:
    return _is_rate_limit(e) or _is_transient(e)


class LLMClient:
    def __init__(self, provider, model, base_url, api_key):
        self.provider = provider
        self.model = model
        self.last_usage = _zero_usage()       # most recent call
        self.total_usage = _zero_usage()      # accumulated over this client's life
        if provider == "anthropic":
            import anthropic
            self._a = anthropic.Anthropic(api_key=api_key)
            self._o = None
        else:
            from openai import OpenAI
            self._o = OpenAI(api_key=api_key, base_url=base_url)
            self._a = None

    def _record(self, prompt_t: int, completion_t: int):
        self.last_usage = {"prompt": prompt_t, "completion": completion_t,
                           "total": prompt_t + completion_t, "provider": self.provider}
        for k in ("prompt", "completion", "total"):
            self.total_usage[k] += self.last_usage[k]

    def complete(self, system: str, user: str, *, max_tokens: int,
                 temperature: float, json_mode: bool) -> str:
        if self.provider == "anthropic":
            # Opus 4.8 rejects temperature; rely on the prompt for JSON shape.
            msg = self._a.messages.create(
                model=self.model, max_tokens=max_tokens, system=system,
                messages=[{"role": "user", "content": user}])
            u = getattr(msg, "usage", None)
            self._record(getattr(u, "input_tokens", 0) or 0,
                         getattr(u, "output_tokens", 0) or 0)
            return "".join(b.text for b in msg.content if b.type == "text")
        kwargs = dict(
            model=self.model, max_tokens=max_tokens, temperature=temperature,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}])
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        # Gemini 2.5 models "think" before answering, and that thinking is billed
        # against max_tokens — it can starve/truncate the visible output. Disable
        # it for structured JSON (we want the shape, not deliberation) and keep it
        # light for prose so the long answer stays coherent without truncating.
        if self.provider == "gemini":
            kwargs["reasoning_effort"] = "none" if json_mode else "low"
        resp = self._o.chat.completions.create(**kwargs)
        u = getattr(resp, "usage", None)
        self._record(getattr(u, "prompt_tokens", 0) or 0,
                     getattr(u, "completion_tokens", 0) or 0)
        return resp.choices[0].message.content or ""


class FailoverClient:
    """Tries each backend in order; on a rate-limit error, moves to the next.
    Exposes the same surface as LLMClient (provider/model/complete/usage) plus
    cumulative token accounting across whichever backend served each call."""

    def __init__(self, backends: list[LLMClient]):
        self.backends = backends
        self.active = backends[0]
        self.last_usage = _zero_usage()
        self.total_usage = _zero_usage()

    @property
    def provider(self):
        return self.active.provider

    @property
    def model(self):
        return self.active.model

    @property
    def chain(self):
        return [b.provider for b in self.backends]

    def complete(self, *args, **kwargs) -> str:
        errors = []
        for be in self.backends:
            try:
                text = be.complete(*args, **kwargs)
            except Exception as e:
                if _should_failover(e) and be is not self.backends[-1]:
                    why = "rate-limited" if _is_rate_limit(e) else "unavailable"
                    errors.append(f"{be.provider}:{why}"); continue
                raise
            self.active = be
            self.last_usage = dict(be.last_usage)
            self.last_usage["provider"] = be.provider
            self.last_usage["failover"] = errors        # which providers were skipped
            for k in ("prompt", "completion", "total"):
                self.total_usage[k] += be.last_usage[k]
            return text
        raise RuntimeError("all LLM providers failed: " + "; ".join(errors))


def get_client():
    """Build a FailoverClient over every available provider, primary first.
    Returns None if no key is set."""
    specs = _resolve_all()
    if not specs:
        return None
    backends = []
    for spec in specs:
        try:
            backends.append(LLMClient(*spec))
        except Exception:
            continue
    if not backends:
        return None
    return FailoverClient(backends)


# --- structured verdicts -----------------------------------------------------
class Verdict(BaseModel):
    candidate_index: int
    connected: bool
    bridge_concept: str = ""
    articulation: str = ""
    relation_to_query: str = ""     # how this passage bears on the seed/query
    unique_shade: str = ""          # the fresh angle it adds the others don't
    forced_risk: str = "medium"     # low | medium | high (kept loose for small models)
    confidence: float = 0.5


class Verdicts(BaseModel):
    verdicts: list[Verdict]


def _parse_verdicts(raw: str) -> list[Verdict]:
    txt = raw.strip()
    if txt.startswith("```"):
        txt = txt.strip("`")
        if txt[:4].lower() == "json":
            txt = txt[4:]
    try:
        data = json.loads(txt)
    except Exception:
        i, j = txt.find("{"), txt.rfind("}")
        if i == -1 or j == -1:
            i, j = txt.find("["), txt.rfind("]")
        data = json.loads(txt[i:j + 1])
    if isinstance(data, list):
        data = {"verdicts": data}
    out = []
    for v in Verdicts(**data).verdicts:
        v.forced_risk = (v.forced_risk or "medium").strip().lower()
        out.append(v)
    return out


JUDGE_SYSTEM = """\
You are a philosophically literate reader working in the spirit of the rhizome \
(Deleuze & Guattari): you look for genuine, non-obvious connections between \
passages drawn from different authors and works.

You are given a SEED passage (or theme) and several CANDIDATE passages. For each \
candidate, judge whether a real conceptual resonance arises *from the flow of \
the theory itself* — a shared problem, a convergent or productively opposed \
concept, an echo one thinker would recognize in the other.

Be discerning. A connection is FORCED when it rests only on shared vocabulary, \
surface topic, or a link you must manufacture with heavy interpretive \
scaffolding. Mark those connected=false (or forced_risk "high"). Reward \
connections that are unexpected yet, once seen, feel earned. Most candidates \
will not connect, and that is fine — do not flatter the seed.

For every candidate you also justify the pick: say plainly HOW it bears on the \
query (relation_to_query), and name the UNIQUE shade of perspective it brings \
that the other candidates do not (unique_shade) — the distinct angle, tension, \
or register it opens. Make the unique_shade genuinely different across \
candidates; do not repeat the same point."""

JUDGE_JSON_SPEC = """

Return ONLY a JSON object of this exact shape (no prose, no code fences):
{"verdicts": [
  {"candidate_index": <int>, "connected": <true|false>,
   "bridge_concept": "<short phrase naming the shared concept>",
   "articulation": "<1-3 sentences naming the resonance>",
   "relation_to_query": "<1-2 sentences: how this passage bears on the query>",
   "unique_shade": "<1 sentence: the distinct angle it adds vs the others>",
   "forced_risk": "low|medium|high", "confidence": <0.0-1.0>}
]}
Include exactly one verdict per candidate index."""


SYNTH_SYSTEM = """\
You are writing a short 'exploration' for RhizomeDB — an invitation to think \
across texts, not a summary. You are given a SEED and a set of CONFIRMED \
connections (each a passage from a different author, with a named bridge \
concept).

Write flowing prose (roughly 300-550 words) that traces the lines of flight \
between the seed and these passages: how the thought migrates, where authors \
converge, where they pull against each other, what new question opens in the \
between. Move with the theory; never force a link the material doesn't support \
— if a connection is thin, say so honestly or let it go. Refer to each passage \
by author and work, and cite the page when given, e.g. (Heidegger, What Is \
Called Thinking?, p. 72). End with one genuine question the constellation \
opens up. No headers, no bullet lists, no preamble — begin in the thinking."""


SYNTH_LONG_SYSTEM = """\
You are writing a long, essayistic 'exploration' for RhizomeDB — an invitation \
to think across texts, not a summary and not an encyclopedia answer. You are \
given a SEED question or theme and a set of CONFIRMED passages (each from a \
different author/work, with a named bridge concept) that the retrieval engine \
surfaced as distant-but-resonant.

Write a sustained meditation of 900-1400 words. Begin inside the question \
itself, then let the thinking migrate through the passages: develop each \
resonance fully, show how one author's move opens or resists another's, follow \
the line of flight several steps rather than stating it once. Where the \
passages pull against each other, stay in the tension instead of resolving it \
cheaply. You are INSPIRED by these passages — draw on them, quote a phrase when \
it earns its place, but do not merely paraphrase them in sequence; let a single \
argument move through them.

Refer to each passage by author and work, and cite the page when given, e.g. \
(Heidegger, What Is Called Thinking?, p. 72), so the reader can trace every \
claim back to its source. Never force a link the material doesn't support — if \
a connection is thin, name that honestly. Close with two or three genuine \
questions the constellation opens up. No headers, no bullet lists, no preamble \
— begin in the thinking."""


FOLLOWUP_SYSTEM = """\
You generate follow-up questions for RhizomeDB, a rhizomatic reading engine \
that surfaces non-obvious connections across philosophical texts. Given the \
reader's QUERY and the PASSAGES the engine actually retrieved, propose five \
follow-up questions that would each open a *different* line of flight — not \
restatements of the query, not generic ("what did X mean by Y?") prompts.

Ground them in what the passages actually contain: pull on a tension between \
two of them, push a shared concept to its limit, cross to an author or problem \
the passages gesture toward, or invert the question. Each should be answerable \
by exploring this corpus further. Vary the angle across the five.

Return ONLY a JSON object of this exact shape (no prose, no code fences):
{"questions": ["...", "...", "...", "...", "..."]}"""


def _cite(c: dict) -> str:
    who = c.get("author") or "Unknown"
    work = c.get("title") or c["book_id"]
    page = f", p.{c['page']}" if c.get("page") else ""
    return f"{who}, {work}{page}"


def judge_connections(seed_text: str, candidates: list[dict], client: LLMClient) -> list[Verdict]:
    listing = "\n\n".join(
        f"[CANDIDATE {i}] — {_cite(c)}\n{_clip(c['text'])}"
        for i, c in enumerate(candidates)
    )
    user = (f"SEED:\n{_clip(seed_text)}\n\nCANDIDATES:\n{listing}\n\n"
            f"Return a verdict for every candidate index 0..{len(candidates) - 1}."
            + JUDGE_JSON_SPEC)
    raw = client.complete(JUDGE_SYSTEM, user, max_tokens=config.JUDGE_MAX_TOKENS,
                          temperature=0.4, json_mode=True)
    return _parse_verdicts(raw)


ABSTRACT_SYSTEM = """\
You read a passage and name, in compressed form, the *underlying structure* it \
enacts — the move, the problem, or the shape of thought beneath its particular \
vocabulary — so that structurally-kindred passages written in entirely \
different words can be found. Do NOT summarize the content or name the author's \
topic; name the FORM, abstract and concrete at once. One or two sentences, no \
preamble. Examples: "the disclosure of being through a mood that individualizes \
the one attuned"; "a faculty defined by its essence or vocation, not its \
anatomy"; "the invisible condition becoming visible, and the disorientation \
that follows"."""


def abstract_seed(seed_text: str, client: LLMClient) -> str:
    """Structural-HyDE: name the seed's underlying move so we can retrieve on the
    *form* of the thought, not its surface words."""
    user = f"PASSAGE:\n{seed_text}\n\nName the underlying structure (1-2 sentences)."
    text = client.complete(ABSTRACT_SYSTEM, user, max_tokens=512,
                           temperature=0.7, json_mode=False)
    return text.strip()


def synthesize(seed_text: str, confirmed: list[dict], client: LLMClient,
               *, long: bool = False) -> str:
    blocks = "\n\n".join(
        f"[{i}] {_cite(c)}\nbridge: {c['bridge_concept']}\n"
        f"why: {c['articulation']}\npassage: {_clip(c['text'])}"
        for i, c in enumerate(confirmed)
    )
    user = f"SEED:\n{_clip(seed_text)}\n\nCONFIRMED CONNECTIONS:\n{blocks}"
    system = SYNTH_LONG_SYSTEM if long else SYNTH_SYSTEM
    max_tok = config.SYNTH_LONG_MAX_TOKENS if long else config.SYNTH_SHORT_MAX_TOKENS
    text = client.complete(system, user, max_tokens=max_tok,
                           temperature=0.85, json_mode=False)
    return text.strip()


def follow_up_questions(seed_text: str, passages: list[dict], client: LLMClient,
                        n: int = 5) -> list[str]:
    """LLM + RAG: five next questions grounded in the retrieved passages, each
    opening a different line of flight rather than restating the query."""
    blocks = "\n\n".join(
        f"[{i}] {_cite(c)}\n{_clip(c['text'])}" for i, c in enumerate(passages)
    )
    user = (f"QUERY:\n{_clip(seed_text)}\n\nPASSAGES THE ENGINE RETRIEVED:\n{blocks}\n\n"
            f"Propose {n} follow-up questions as JSON.")
    raw = client.complete(FOLLOWUP_SYSTEM, user, max_tokens=900,
                          temperature=0.9, json_mode=True)
    txt = raw.strip()
    if txt.startswith("```"):
        txt = txt.strip("`")
        if txt[:4].lower() == "json":
            txt = txt[4:]
    try:
        data = json.loads(txt)
    except Exception:
        i, j = txt.find("{"), txt.rfind("}")
        data = json.loads(txt[i:j + 1]) if i != -1 and j != -1 else {"questions": []}
    qs = data.get("questions") if isinstance(data, dict) else data
    return [str(q).strip() for q in (qs or []) if str(q).strip()][:n]


# --- brainstorm: interpretation line + comparison + follow-ups (one call) ----
class Interpretation(BaseModel):
    passage: int = -1          # index of the passage this step leans on (-1 = synthetic)
    reading: str = ""          # the interpretive move at this step of the line


class Comparison(BaseModel):
    between: str = ""          # e.g. "Bambach vs Heidegger (What Is Called Thinking?)"
    contrast: str = ""         # how they differ / pull apart on the shared concern


class Brainstorm(BaseModel):
    interpretations: list[Interpretation] = []
    comparisons: list[Comparison] = []
    follow_ups: list[str] = []


BRAINSTORM_SYSTEM = """\
You are the brainstorming layer of RhizomeDB. You are given a QUERY and the \
PASSAGES the engine retrieved (each indexed, from a different work). Produce \
three things, grounded strictly in these passages:

1. interpretations — a *line of interpretation*: an ORDERED sequence of moves \
that builds a single train of thought, each step leaning on one passage (give \
its index) and advancing the reading the previous step opened. Not a summary of \
each passage in turn — a thread that travels through them and gains something at \
every step. 5-8 steps.

2. comparisons — put the passages in tension with one another: for several \
pairs (or small groups), name what they share and exactly where they pull \
apart — divergent assumptions, registers, or consequences. 3-5 comparisons.

3. follow_ups — five follow-up questions, each opening a *different* line of \
flight, grounded in what the passages contain, answerable by exploring this \
corpus further. Not restatements of the query.

Return ONLY a JSON object of this exact shape (no prose, no code fences):
{"interpretations": [{"passage": <int>, "reading": "<...>"}],
 "comparisons": [{"between": "<author/work vs author/work>", "contrast": "<...>"}],
 "follow_ups": ["<...>", "<...>", "<...>", "<...>", "<...>"]}"""


def _strip_json(raw: str):
    txt = raw.strip()
    if txt.startswith("```"):
        txt = txt.strip("`")
        if txt[:4].lower() == "json":
            txt = txt[4:]
    try:
        return json.loads(txt)
    except Exception:
        i, j = txt.find("{"), txt.rfind("}")
        return json.loads(txt[i:j + 1]) if i != -1 and j != -1 else {}


CHAT_SYSTEM = """\
You are a thinking companion in RhizomeDB, discussing a specific passage (or an \
exploration the engine wrote) with a reader. Engage closely and precisely with \
the text in front of you and the philosophical tradition it belongs to. When \
the reader points at a line, work with that line. Be substantive — explain, \
draw connections, push back, open questions — but stay grounded in the passage; \
do not invent citations. Speak plainly, in flowing prose (no bullet lists \
unless asked). Aim for ~200-400 words (more only if the reader explicitly asks), \
and ALWAYS bring the reply to a clean close — finish your thought and end on a \
complete sentence; never trail off mid-sentence or stop in the middle of a list."""


def chat(context_text: str, history: list[dict], message: str, client: LLMClient,
         *, source_label: str = "") -> str:
    """A grounded, multi-turn discussion about a passage/exploration. History is
    a list of {role: 'user'|'assistant', content: str}; folded into the prompt."""
    convo = "\n".join(
        f"{'Reader' if m.get('role') == 'user' else 'Companion'}: {m.get('content', '')}"
        for m in (history or [])
    )
    hdr = f" — {source_label}" if source_label else ""
    user = f"TEXT UNDER DISCUSSION{hdr}:\n{context_text}\n\n"
    if convo:
        user += f"CONVERSATION SO FAR:\n{convo}\n\n"
    user += f"Reader: {message}\n\nReply as the companion."
    return client.complete(CHAT_SYSTEM, user, max_tokens=config.CHAT_MAX_TOKENS,
                           temperature=0.8, json_mode=False).strip()


# --- Plateau: a study map for a single passage (concepts + edges + prompts) ---
STUDY_SYSTEM = """\
You are the study layer of RhizomeDB ("the Plateau"). Given ONE passage from a \
philosophy text, produce a compact study map, grounded strictly in the passage \
— do not invent material it does not contain.

1. concepts — the 5-9 core concepts the passage actually works with. For each: a \
short label (1-3 words, the tradition's own term where it has one) and a \
one-sentence gloss of how THIS passage uses it.
2. edges — the relations between those concepts as the passage stages them. \
Reference concepts by their index in the concepts list; name the relation in \
1-4 words (e.g. "grounds", "opposed to", "unfolds into", "presupposes"). Only \
edges the passage actually supports; 4-10 of them.
3. follow_ups — 5 questions, each opening a different line of inquiry from this \
passage (not restatements).
4. angles — 3-5 brainstorming angles: each a short title and a 1-2 sentence \
interpretive provocation that opens a way into the passage.

Return ONLY a JSON object of this exact shape (no prose, no code fences):
{"concepts":[{"label":"<...>","gloss":"<...>"}],
 "edges":[{"a":<int>,"b":<int>,"relation":"<...>"}],
 "follow_ups":["<...>"],
 "angles":[{"title":"<...>","thought":"<...>"}]}"""


def study_passage(text: str, client: LLMClient) -> dict:
    """One call → the Plateau study map for a single passage: a concept graph
    (nodes + named edges), follow-up questions, and brainstorming angles."""
    user = (f"PASSAGE:\n{_clip(text)}\n\nReturn the JSON study map.")
    raw = client.complete(STUDY_SYSTEM, user, max_tokens=1600,
                          temperature=0.6, json_mode=True)
    data = _strip_json(raw) or {}
    concepts = [{"label": str(c.get("label", "")).strip(),
                 "gloss": str(c.get("gloss", "")).strip()}
                for c in (data.get("concepts") or []) if str(c.get("label", "")).strip()][:9]
    n = len(concepts)
    edges = []
    for e in (data.get("edges") or []):
        try:
            a, b = int(e["a"]), int(e["b"])
        except (KeyError, ValueError, TypeError):
            continue
        if 0 <= a < n and 0 <= b < n and a != b:
            edges.append({"a": a, "b": b, "relation": str(e.get("relation", "")).strip()})
    follow_ups = [str(q).strip() for q in (data.get("follow_ups") or []) if str(q).strip()][:6]
    angles = [{"title": str(a.get("title", "")).strip(), "thought": str(a.get("thought", "")).strip()}
              for a in (data.get("angles") or []) if str(a.get("title", "")).strip()][:5]
    return {"concepts": concepts, "edges": edges, "follow_ups": follow_ups, "angles": angles}


def brainstorm(seed_text: str, passages: list[dict], client: LLMClient) -> Brainstorm:
    """One call → line of interpretations + comparisons + follow-ups, all
    grounded in the retrieved passages. Cheaper than three separate calls."""
    blocks = "\n\n".join(
        f"[PASSAGE {i}] — {_cite(c)}\n{_clip(c['text'])}" for i, c in enumerate(passages)
    )
    user = (f"QUERY:\n{_clip(seed_text)}\n\nPASSAGES:\n{blocks}\n\n"
            f"Passage indices run 0..{len(passages) - 1}. Return the JSON object.")
    raw = client.complete(BRAINSTORM_SYSTEM, user, max_tokens=config.BRAINSTORM_MAX_TOKENS,
                          temperature=0.85, json_mode=True)
    try:
        return Brainstorm(**_strip_json(raw))
    except Exception:
        return Brainstorm()
