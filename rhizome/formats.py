"""Format registry — named pipeline variants, developed in parallel.

A *format* is a named recipe for turning a query into an answer + evidence. We
keep several alive at once and compare them on the same questions; nothing is
discarded, so each format stays a reproducible baseline as new ones appear.
This module is declarative (data only) — runners live with the pipelines, the
UI/CLI read this to list and select formats. Human spec: FORMATS.md.
"""

FORMATS = {
    "f1": {
        "id": "f1",
        "name": "Simple RAG + surface diagnostics",
        "status": "active",
        "granularity": "chunk",   # which rung on the SOLID→LIQUID dial it reads
        "essence": ("plain top-k retrieval with a long grounded answer, plus "
                    "experimental surface-similarity metrics overlaid to learn "
                    "how retrieval actually behaves"),
        "retrieval": "top-k cosine — nearest neighbours, no diversification, no exclusions",
        "generation": "long answer with [n] citations + 5 LLM follow-ups",
        "layers": [
            "source paragraphs with cosine scores",
            "surface metrics: DIRECT, DIRECT-DISSIM (=1-DIRECT), STRUCT (cosine to the query's abstracted move)",
            "follow-up questions",
        ],
        "testing": "what pure nearest-neighbour fetches; the lexical-vs-structural gap (STRUCT vs DIRECT)",
        "entrypoints": {"module": "rhizome.rag", "api": "POST /api/ask",
                        "page": "/ask", "metrics_view": "serve.py (:8000)"},
        "limits": ["STRUCT only measured on surface-retrieved passages",
                   "STRUCT is a single-abstraction proxy",
                   "no rerank / justification / faithfulness layers"],
    },
    "f2": {
        "id": "f2",
        "name": "Researched RAG",
        "status": "planned",
        "essence": ("a better pipeline informed by the structural-retrieval "
                    "research — direction, not yet fixed"),
        "candidates": [
            "dual-axis retrieval (surface + structural, merged)",
            "constellation-score ranking (STRUCT x DIRECT-DISSIM)",
            "cross-encoder / LLM rerank",
            "differential justification (one contrastive call)",
            "comparison matrix + tension layer",
            "faithfulness / attribution check",
            "model router + token economy",
        ],
        "testing": "does researched retrieval beat F1 on surprise AND groundedness?",
    },
    "praxis": {
        "id": "praxis",
        "name": "Praxis (solid end of the dial)",
        "status": "planned",
        "granularity": "proposition",   # match atomic statements
        "essence": ("precise lookup against atomic propositions, then small-to-big: "
                    "answer from the propositions' parent passages so the claim is "
                    "never read without its qualifying context"),
        "retrieval": "top-k over the proposition level, expand to parent passages",
        "testing": "definitional/'what is X' accuracy vs F1's chunk retrieval",
    },
    "liquid": {
        "id": "liquid",
        "name": "Liquid (constellatory end of the dial)",
        "status": "planned",
        "granularity": "parent",        # read large, context-laden passages
        "essence": ("read the largest, most context-laden units so resonance and "
                    "structural movement have room — the constellatory mood"),
        "retrieval": "parent level, contextual-enriched, fed to the connection engine",
        "testing": "does reading liquid surface richer connections than chunk?",
    },
}

# shared comparison questions — run every format through these
COMPARISON_SET = [
    "what is dwelling",
    "how does thinking differ from calculation",
    "what is the relation between language and world",
]


def list_formats() -> list[dict]:
    return list(FORMATS.values())


def get(format_id: str) -> dict | None:
    return FORMATS.get(format_id)


def active() -> list[dict]:
    return [f for f in FORMATS.values() if f["status"] == "active"]
