"""The mini-engine registry.

Every module in this package that exposes a module-level ``ENGINE`` (an object
satisfying `base.Engine`) is discovered automatically — adding an engine is
adding a file, no central list to edit. Order in `all_engines()` follows
`ORDER` first (the ones the reader offers most prominently), then discovery
order for anything new.

    from rhizome import engines
    eng = engines.get("band")
    picks = eng.candidates(seed, ctx, k=8)
"""
from __future__ import annotations

import importlib
import pkgutil

from .base import (BaseEngine, Context, Engine, Seed, decorate, finish,  # noqa: F401
                   intra_list_diversity, ranks_from, similarities)

# The order engines are listed in the UI / CLI. Unlisted keys follow after.
ORDER = ["band", "spread", "plain", "lexical", "hybrid", "echo",
         "concept", "walk", "marks", "structural", "fused"]

DEFAULT_ENGINE = "band"

_REGISTRY: dict[str, Engine] | None = None


def _discover() -> dict[str, Engine]:
    found: dict[str, Engine] = {}
    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith("_") or info.name == "base":
            continue
        mod = importlib.import_module(f"{__name__}.{info.name}")
        eng = getattr(mod, "ENGINE", None)
        if eng is None:
            continue
        if eng.key in found:
            raise RuntimeError(f"duplicate engine key {eng.key!r} in {info.name}")
        found[eng.key] = eng
    ordered = {k: found[k] for k in ORDER if k in found}
    for k, e in found.items():
        ordered.setdefault(k, e)
    return ordered


def registry() -> dict[str, Engine]:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _discover()
    return _REGISTRY


def all_engines() -> list[Engine]:
    return list(registry().values())


def keys() -> list[str]:
    return list(registry().keys())


def get(key: str) -> Engine:
    reg = registry()
    if key not in reg:
        raise KeyError(f"unknown engine {key!r}; known: {', '.join(reg)}")
    return reg[key]


def describe_all(ctx: Context | None = None) -> list[dict]:
    """Every engine's card (key/label/blurb/needs/params/ready/reason)."""
    out = []
    for e in all_engines():
        if hasattr(e, "describe"):
            out.append(e.describe(ctx))
        else:  # a bare Protocol implementer
            ok, why = (True, "") if ctx is None else e.ready(ctx)
            out.append({"key": e.key, "label": e.label, "blurb": e.blurb,
                        "needs": list(e.needs), "params": dict(getattr(e, "params", {})),
                        "ready": ok, "reason": why})
    return out


def run(key: str, seed: Seed, ctx: Context, *, k: int | None = None, **params) -> list[dict]:
    """Convenience: look up + run, raising a clear error when not ready."""
    from .. import config
    eng = get(key)
    ok, why = eng.ready(ctx)
    if not ok:
        raise RuntimeError(f"engine {key!r} not ready: {why}")
    return eng.candidates(seed, ctx, k=k or config.N_CANDIDATES, **params)
