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

# Embedding model — ONNX via fastembed (no torch; runs fully local/offline).
EMBED_MODEL = "BAAI/bge-base-en-v1.5"   # 768-dim
EMBED_DIM = 768
EMBED_CACHE_DIR = ROOT / ".fastembed_cache"   # persistent (not the system temp dir)

# Chunking (sizes are in words; ~1.3 tokens/word for English prose).
CHUNK_TARGET_WORDS = 240
CHUNK_OVERLAP_WORDS = 40
CHUNK_MIN_WORDS = 60      # drop fragments shorter than this

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

# LLM (the judging + synthesis brain).
LLM_MODEL = "claude-opus-4-8"
