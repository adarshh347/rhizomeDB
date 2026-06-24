"""Shared paths and tunable defaults for the pipeline."""
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load_dotenv():
    """Load ROOT/.env into os.environ (no override of already-set vars).

    Tiny stdlib parser — KEY=VALUE per line, '#' comments, optional quotes.
    Imported broadly via config, so an LLM key in .env is picked up by
    llm.get_client() in both the CLI and the server with no extra deps.
    """
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


_load_dotenv()
CONVERTED_DIR = ROOT / "converted"
INDEX_DIR = ROOT / "index"
CATALOG_PATH = ROOT / "catalog.json"

CHUNKS_PATH = INDEX_DIR / "chunks.jsonl"
EMBEDDINGS_PATH = INDEX_DIR / "embeddings.npy"

# Annotated reading notes (the human half of the loop — see SCHEMA.md).
NOTES_DIR = ROOT / "notes"
ANNOTATIONS_PATH = INDEX_DIR / "annotations.jsonl"

# Concept graph — human-authored bridges (corr annotations) + judged bridges.
EDGES_PATH = INDEX_DIR / "edges.jsonl"
JUDGED_PATH = INDEX_DIR / "edges_judged.jsonl"   # append-only: bridges the judge confirms

# Embedding models — ONNX via fastembed (no torch; runs fully local/offline).
# A registry so the corpus can be embedded with several frameworks and compared:
# different families (BAAI/BGE, sentence-transformers/MiniLM, thenlper/GTE,
# Snowflake/Arctic) place passages in different geometries, which matters most in
# the mid-similarity "resonance band" this engine works in.
# `query_prefix`: instruction prepended to QUERIES only (not corpus passages).
# Asymmetric models (BGE, Arctic) are trained with a query-side instruction and
# retrieve badly without it — our in-domain eval caught Arctic collapsing without
# it (median rank 24 → 1 once added). MiniLM is symmetric (no prefix).
_BGE_Q = "Represent this sentence for searching relevant passages: "
EMBED_MODELS = {
    "bge-base":    {"name": "BAAI/bge-base-en-v1.5",                  "dim": 768, "label": "BGE-base · BAAI",                 "query_prefix": _BGE_Q},
    "minilm":      {"name": "sentence-transformers/all-MiniLM-L6-v2", "dim": 384, "label": "MiniLM-L6 · sentence-transformers", "query_prefix": ""},
    "bge-small":   {"name": "BAAI/bge-small-en-v1.5",                 "dim": 384, "label": "BGE-small · BAAI",                "query_prefix": _BGE_Q},
    "snowflake-m": {"name": "snowflake/snowflake-arctic-embed-m",     "dim": 768, "label": "Arctic-embed-m · Snowflake",      "query_prefix": _BGE_Q},
}
DEFAULT_EMBED = "bge-base"

EMBED_MODEL = EMBED_MODELS[DEFAULT_EMBED]["name"]   # back-compat (primary model)
EMBED_DIM = EMBED_MODELS[DEFAULT_EMBED]["dim"]
EMBED_CACHE_DIR = ROOT / ".fastembed_cache"   # persistent (not the system temp dir)


def embeddings_path(key: str = DEFAULT_EMBED):
    """Per-model vector file. The default model keeps the legacy filename so we
    don't re-embed the corpus that's already on disk."""
    if key == DEFAULT_EMBED:
        return EMBEDDINGS_PATH
    return INDEX_DIR / f"emb_{key}.npy"

# Chunking (sizes are in words; ~1.3 tokens/word for English prose).
CHUNK_TARGET_WORDS = 240
CHUNK_OVERLAP_WORDS = 40
CHUNK_MIN_WORDS = 60      # drop fragments shorter than this

# --- Multi-resolution chunking (the SOLID→LIQUID dial; see CHUNKING.md) -------
# Same corpus indexed at several granularities, every unit linked to its parent
# and children, so retrieval reads at the rung it needs.
#   parent      ~500w passages — the LIQUID end (context-laden, constellatory)
#   chunk        the legacy ~240w working unit — DEFAULT, == existing chunks.jsonl
#   proposition  atomic LLM-extracted statements — the SOLID end (praxis/lookup)
CHUNK_LEVELS = ["parent", "chunk", "proposition"]
DEFAULT_LEVEL = "chunk"           # what /ask + the engine read unless told otherwise
PARENT_TARGET_WORDS = 500
PARENT_OVERLAP_WORDS = 60
CHUNK_METHOD = "recursive"        # "recursive" (current) | "semantic" (embedding-drop)
SEMANTIC_THRESHOLD = 0.55         # cosine below this between adjacent windows = topic shift
CONTEXTUAL_ENRICH = False         # prepend an LLM context blurb before embedding (R3)

# ID prefixes per level. NOTE: we deliberately do NOT use level[:1] uniformly —
# the chunk level keeps its LEGACY id form ({book}#{n:04d}) so existing
# embeddings.npy rows, workspace annotations and saved sessions stay valid, and
# parent/proposition both start with 'p' which would collide. Explicit prefixes:
LEVEL_ID_PREFIX = {"parent": "P", "chunk": "", "proposition": "X"}

# Chunk character — a controlled vocabulary (R4). What KIND of passage it is.
CHARACTERS = [
    "definitional", "argumentative", "exegetical", "illustrative", "poetic",
    "citation", "transitional", "aporetic", "historical", "polemical",
]


def chunks_path(level: str = DEFAULT_LEVEL):
    """Per-level chunk file. The chunk level keeps the legacy filename."""
    if level == "chunk":
        return CHUNKS_PATH
    return INDEX_DIR / f"chunks_{level}.jsonl"


def level_emb_path(level: str = DEFAULT_LEVEL, model: str = DEFAULT_EMBED):
    """Per-level embedding file (default model). The chunk level reuses the
    existing per-model vector files so nothing is re-embedded needlessly."""
    if level == "chunk":
        return embeddings_path(model)
    return INDEX_DIR / f"emb_{level}.npy"


# Caches for the LLM enrichment passes (keyed by content hash; R8 cost guard).
CONTEXT_CACHE_PATH = INDEX_DIR / "cache_context.json"
CHARACTER_CACHE_PATH = INDEX_DIR / "cache_character.json"

# Connection engine — the constellatory geometry.
SKIP_TOP = 8             # drop the N most-similar candidates (the "obvious" ones)
POOL = 120               # size of the resonance band to draw diverse picks from
N_CANDIDATES = 8         # how many connections to propose per seed
MMR_LAMBDA = 0.4         # < 0.5 favours diversity across books/ideas over closeness
MIN_SIM = 0.15           # floor: below this, candidates are noise, not resonance
DEDUP_SIM = 0.97         # ceiling: at/above this a candidate is a near-duplicate /
#                          verbatim quotation of the seed, not a connection — drop it.
# Intra-corpus constellation: the deep aim is relational surprise *within* a corpus,
# not merely across authors (cross-author was only a proxy for distance). So exclude
# the seed's own *book* always, but let connections cross between an author's works.
EXCLUDE_SAME_BOOK = True
EXCLUDE_SAME_AUTHOR = False  # set True only to force strictly cross-author connections

# Token economy (R8-style guard for the live pipeline). The SAME passages are
# sent into judge + synthesis + brainstorm, and the judge reads every candidate,
# so clipping passage text in prompts is the single biggest lever on tokens/run.
# Raise LLM_PASSAGE_CHARS / the synth caps for richer (costlier) runs.
LLM_PASSAGE_CHARS = 800          # max chars of each passage fed into LLM prompts (0 = no clip)
SYNTH_LONG_MAX_TOKENS = 2800     # long answer output cap (was 6000)
SYNTH_SHORT_MAX_TOKENS = 1600    # short answer output cap (was 2200)
JUDGE_MAX_TOKENS = 2600          # verdict output cap (was 4000)
BRAINSTORM_MAX_TOKENS = 2000     # brainstorm output cap (was 2600)

# LLM (the judging + synthesis brain).
LLM_MODEL = "claude-opus-4-8"


# --- Gemini free-tier budget (token-usage accounting; see usage.py) -----------
# The Google AI Studio free tier rate-limits the Gemini API per model. These are
# the published gemini-2.5-flash limits as of early 2026 — override any of them
# via the matching env var if your tier differs (billing enabled, -lite model…).
#   RPM  requests / minute     TPM  tokens / minute     RPD  requests / day
# Google does NOT publish a hard tokens-per-DAY cap, so we expose a configurable
# daily token *budget* to answer "how much of my day did this run cost?". It
# defaults to RPD × 4000 tokens/request (== 1,000,000) — adjust to taste.
def _envf(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name) or default)
    except (TypeError, ValueError):
        return float(default)

GEMINI_FREE_RPM = _envf("GEMINI_FREE_RPM", 10)
GEMINI_FREE_TPM = _envf("GEMINI_FREE_TPM", 250_000)
GEMINI_FREE_RPD = _envf("GEMINI_FREE_RPD", 250)
GEMINI_FREE_DAILY_TOKENS = _envf("GEMINI_FREE_DAILY_TOKENS", GEMINI_FREE_RPD * 4000)
