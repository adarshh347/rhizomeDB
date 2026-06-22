"""In-domain embedding eval — the single habit that beats chasing leaderboards.

A small hand-judged gold set (eval/embed_gold.jsonl: query -> the passage(s) that
genuinely answer it, picked by LEXICAL search so the labels are independent of any
embedding being tested) is run through each built model with PLAIN cosine ranking
(the full corpus, no resonance-band geometry — we are measuring whether the model
understands the corpus, not the rhizome layer on top).

Metrics per model: Recall@{1,3,5,10}, MRR, and median/mean rank of the gold
passage. Higher recall + MRR and lower median rank = the better embedding here.
"""
import json

import numpy as np

from . import config, embed as embed_mod, store as store_mod

GOLD_PATH = config.ROOT / "eval" / "embed_gold.jsonl"
KS = (1, 3, 5, 10)


def load_gold() -> list[dict]:
    if not GOLD_PATH.exists():
        return []
    return [json.loads(l) for l in GOLD_PATH.read_text(encoding="utf-8").splitlines() if l.strip()]


def _eval_model(model_key: str, gold: list[dict]) -> dict:
    st = store_mod.Store(model_key)
    by_id = st.by_id
    per_query = []
    for g in gold:
        qv = embed_mod.embed_query(g["query"], model_key)
        sims = st.vecs @ qv
        order = np.argsort(-sims)
        # rank position (0-based) of each chunk
        rankpos = np.empty(len(order), dtype=np.int64)
        rankpos[order] = np.arange(len(order))
        gold_ranks = [int(rankpos[by_id[gid]]) for gid in g["gold"] if gid in by_id]
        best = min(gold_ranks) if gold_ranks else len(order)  # 0-based
        per_query.append({"qid": g["qid"], "query": g["query"],
                          "best_rank": best + 1,            # 1-based for humans
                          "rr": 1.0 / (best + 1),
                          "gold_sim": round(float(sims[by_id[g["gold"][0]]]), 4)
                          if g["gold"][0] in by_id else None})
    n = len(per_query)
    rr = np.array([q["rr"] for q in per_query])
    ranks = np.array([q["best_rank"] for q in per_query])
    res = {"key": model_key, "label": config.EMBED_MODELS[model_key]["label"],
           "dim": config.EMBED_MODELS[model_key]["dim"], "n": n,
           "mrr": round(float(rr.mean()), 4),
           "median_rank": int(np.median(ranks)),
           "mean_rank": round(float(ranks.mean()), 1)}
    for k in KS:
        res[f"recall@{k}"] = round(float(np.mean(ranks <= k)), 3)
    res["per_query"] = per_query
    return res


def evaluate(model_keys: list[str] | None = None) -> dict:
    gold = load_gold()
    if not gold:
        return {"error": "no gold set at eval/embed_gold.jsonl"}
    if model_keys is None:
        model_keys = [k for k in config.EMBED_MODELS if config.embeddings_path(k).exists()]
    results = []
    for k in model_keys:
        if not config.embeddings_path(k).exists():
            continue
        try:
            results.append(_eval_model(k, gold))
        except Exception as e:
            results.append({"key": k, "label": k, "error": f"{type(e).__name__}: {e}"})
    # rank models by recall@5 then MRR
    ok = [r for r in results if "error" not in r]
    ok.sort(key=lambda r: (r.get("recall@5", 0), r.get("mrr", 0)), reverse=True)
    return {"gold_n": len(gold), "ks": list(KS),
            "results": ok + [r for r in results if "error" in r]}


def main():
    out = evaluate()
    if "error" in out:
        print(out["error"]); return
    print(f"\nIn-domain embedding eval  ·  {out['gold_n']} hand-judged query→passage pairs")
    print(f"(plain cosine over the full corpus; gold = the passage that answers the query)\n")
    cols = ["recall@1", "recall@3", "recall@5", "recall@10", "mrr", "median_rank", "mean_rank"]
    print(f"{'model':<34}" + "".join(f"{c:>11}" for c in cols))
    print("-" * (34 + 11 * len(cols)))
    for r in out["results"]:
        if "error" in r:
            print(f"{r['label']:<34} ERROR: {r['error']}"); continue
        print(f"{r['label']:<34}" + "".join(f"{r[c]:>11}" for c in cols))
    # which queries the winner still misses (gold not in top 10)
    win = out["results"][0]
    misses = [q for q in win["per_query"] if q["best_rank"] > 10]
    if misses:
        print(f"\nHardest queries for the leader ({win['label']}):")
        for q in sorted(misses, key=lambda x: -x["best_rank"])[:6]:
            print(f"  rank {q['best_rank']:<5} {q['qid']:<14} {q['query']}")


if __name__ == "__main__":
    main()
