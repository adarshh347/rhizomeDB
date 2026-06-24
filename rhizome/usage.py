"""Gemini free-tier token accounting.

Turns the LLM client's raw token counters (llm.LLMClient tracks last_usage /
total_usage per call) into a human picture: how many tokens a run — and each
*part* of that run — spent, and what share of the Gemini free-tier daily budget
that is. Two views:

  per-run   — a Meter snapshots the client's cumulative counter around each LLM
              call, so explore() can attribute tokens to structural-seed vs
              judge vs synthesize, and enrich() to each batch.
  per-day   — a tiny on-disk ledger (index/usage_daily.json) accumulates tokens
              + requests per calendar day, so you can see how close today's
              activity already is to the free-tier ceilings.

The limits live in config (GEMINI_FREE_*), all env-overridable. Google gates the
free tier by requests/day (RPD) and tokens/minute (TPM) — there is no published
tokens/day cap — so the "% of day" is measured against the configurable
GEMINI_FREE_DAILY_TOKENS budget, while requests are measured against the real RPD.
"""
import datetime
import json

from . import config

LEDGER_PATH = config.INDEX_DIR / "usage_daily.json"


def limits() -> dict:
    return {"rpm": config.GEMINI_FREE_RPM, "tpm": config.GEMINI_FREE_TPM,
            "rpd": config.GEMINI_FREE_RPD,
            "daily_tokens": config.GEMINI_FREE_DAILY_TOKENS}


def _pct(n: float, d: float) -> float:
    return (100.0 * n / d) if d else 0.0


def pct_of_day(tokens: int) -> float:
    """Share of the configurable free-tier daily token budget these tokens are."""
    return _pct(tokens, config.GEMINI_FREE_DAILY_TOKENS)


def bar(pct: float, width: int = 22) -> str:
    fill = max(0, min(width, round(pct / 100 * width)))
    return "█" * fill + "·" * (width - fill)


# --- per-run metering --------------------------------------------------------
class Meter:
    """Snapshots a client's cumulative token counter so each LLM call in a run
    can be attributed to a labelled part. Call mark(label) right after each
    helper that makes exactly one LLM call. Safe with client=None (records
    nothing, report() comes back empty)."""

    def __init__(self, client):
        self.client = client
        self.parts: list[dict] = []
        self._base = self._total()
        self._last = self._base

    def _total(self) -> int:
        if not self.client:
            return 0
        return int((getattr(self.client, "total_usage", {}) or {}).get("total", 0) or 0)

    def _split(self) -> tuple[int, int]:
        u = getattr(self.client, "last_usage", {}) or {}
        return int(u.get("prompt", 0) or 0), int(u.get("completion", 0) or 0)

    def mark(self, label: str) -> dict | None:
        """Attribute the tokens spent since the previous mark to `label`.
        Returns the part record, or None if nothing was spent (e.g. no call)."""
        cur = self._total()
        delta = cur - self._last
        self._last = cur
        if delta <= 0:
            return None
        prompt, completion = self._split()
        part = {"label": label, "tokens": delta, "prompt": prompt,
                "completion": completion, "pct_day": pct_of_day(delta)}
        self.parts.append(part)
        return part

    @property
    def total(self) -> int:
        return self._last - self._base

    def report(self, *, provider=None) -> dict:
        prov = provider or getattr(self.client, "provider", None)
        total = self.total
        lim = limits()
        rep = {
            "provider": prov,
            "is_gemini": prov == "gemini",
            "parts": self.parts,
            "total_tokens": total,
            "requests": len(self.parts),
            "limits": lim,
            "pct_day": pct_of_day(total),
            "pct_rpd": _pct(len(self.parts), lim["rpd"]),
        }
        rep["summary"] = summary_line(rep)
        return rep


# --- per-day ledger ----------------------------------------------------------
def _today() -> str:
    return datetime.date.today().isoformat()


def _read_ledger(path=LEDGER_PATH) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def ledger_add(tokens: int, requests: int = 1, *, day: str | None = None,
               path=LEDGER_PATH) -> dict:
    """Accrue tokens + requests onto today's running total and return it.
    Only the Gemini free tier is budgeted, so callers should guard on the
    active provider. Returns {date, tokens, requests}."""
    if tokens <= 0 and requests <= 0:
        return ledger_today(path=path)
    day = day or _today()
    led = _read_ledger(path)
    cur = led.get(day) or {"tokens": 0, "requests": 0}
    cur["tokens"] = int(cur["tokens"]) + int(tokens)
    cur["requests"] = int(cur["requests"]) + int(requests)
    led[day] = cur
    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(led, ensure_ascii=False, indent=0), encoding="utf-8")
    return {"date": day, **cur}


def ledger_today(*, path=LEDGER_PATH) -> dict:
    day = _today()
    cur = _read_ledger(path).get(day) or {"tokens": 0, "requests": 0}
    return {"date": day, "tokens": int(cur["tokens"]), "requests": int(cur["requests"])}


def note_and_record(client, tokens: int, requests: int = 0) -> str:
    """For the batch passes (enrich/characterize/propositions): record Gemini
    tokens into the daily ledger and return a short ' · N.NN% of free-tier day
    (today M.MM%)' suffix to append to the pass's log line. Empty for non-Gemini."""
    if getattr(client, "provider", None) != "gemini" or tokens <= 0:
        return ""
    today = ledger_add(tokens, requests)
    return (f" · {pct_of_day(tokens):.2f}% of free-tier day"
            f" (today {pct_of_day(today['tokens']):.2f}%)")


def record_report(rep: dict | None) -> dict | None:
    """Add a run's report to the daily ledger (Gemini only). Returns today's
    running total, or None if there was nothing Gemini to record."""
    if not rep or not rep.get("is_gemini") or rep.get("total_tokens", 0) <= 0:
        return None
    return ledger_add(rep["total_tokens"], rep.get("requests", 0) or 0)


# --- formatting --------------------------------------------------------------
def summary_line(rep: dict | None) -> str:
    """One compact line — for the panel / a log: total tokens + % of the day."""
    if not rep or rep.get("total_tokens", 0) <= 0:
        return ""
    n = rep["total_tokens"]
    if rep.get("is_gemini"):
        return (f"{n:,} tokens · {rep['pct_day']:.2f}% of the "
                f"{int(rep['limits']['daily_tokens']):,}-token free-tier day "
                f"· {rep['requests']} req")
    return f"{n:,} tokens · {rep['requests']} req ({rep.get('provider') or 'llm'})"


def format_report(rep: dict | None, *, indent: str = "", today: dict | None = None) -> str:
    """Multi-line breakdown for the CLI: a line per part with its token amount
    and % of the daily budget, then the run total, then (optionally) today's
    running total against the free-tier ceilings."""
    if not rep or rep.get("total_tokens", 0) <= 0:
        return ""
    gem = rep.get("is_gemini")
    daily = int(rep["limits"]["daily_tokens"])
    lines = ["Token usage  —  " + (rep.get("provider") or "llm")
             + ("  (Gemini free tier)" if gem else "")]
    for p in rep["parts"]:
        line = f"  {p['label']:<18}{p['tokens']:>8,} tok   (in {p['prompt']:,} / out {p['completion']:,})"
        if gem:
            line += f"   {p['pct_day']:5.2f}% / day"
        lines.append(line)
    total_line = f"  {'RUN TOTAL':<18}{rep['total_tokens']:>8,} tok"
    if gem:
        total_line += (f"   {rep['pct_day']:5.2f}% / day  {bar(rep['pct_day'])}\n"
                       f"  {'':<18}{rep['requests']:>8} req   "
                       f"{rep['pct_rpd']:5.2f}% of {int(rep['limits']['rpd'])} req/day")
    lines.append(total_line)
    if gem and today:
        tpct = pct_of_day(today["tokens"])
        rpct = _pct(today["requests"], rep["limits"]["rpd"])
        lines.append(f"  {'TODAY SO FAR':<18}{today['tokens']:>8,} tok   {tpct:5.2f}% / day  "
                     f"{bar(tpct)}\n"
                     f"  {'':<18}{today['requests']:>8} req   {rpct:5.2f}% of "
                     f"{int(rep['limits']['rpd'])} req/day   (budget {daily:,} tok)")
    return "\n".join(indent + l for l in lines)


def format_day(today: dict | None = None, *, indent: str = "") -> str:
    """Standalone 'how much of today's free tier is gone' summary (the `usage`
    command). Reads the ledger if `today` isn't supplied."""
    today = today or ledger_today()
    lim = limits()
    tpct = pct_of_day(today["tokens"])
    rpct = _pct(today["requests"], lim["rpd"])
    lines = [
        f"Gemini free-tier usage — {today['date']}",
        f"  tokens   {today['tokens']:>9,} / {int(lim['daily_tokens']):,}   "
        f"{tpct:6.2f}%  {bar(tpct)}",
        f"  requests {today['requests']:>9} / {int(lim['rpd'])}        "
        f"{rpct:6.2f}%  {bar(rpct)}",
        f"  limits   {int(lim['rpm'])} req/min · {int(lim['tpm']):,} tok/min · "
        f"{int(lim['rpd'])} req/day   (override via GEMINI_FREE_* env)",
    ]
    return "\n".join(indent + l for l in lines)
