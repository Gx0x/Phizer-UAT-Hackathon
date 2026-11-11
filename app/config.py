import os
from pathlib import Path

from dotenv import load_dotenv

# Load the project-root .env file; secrets stay on the server.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

# Fixed IDs for the two demo profiles, so the seed script can be run
# repeatedly without ever creating duplicates.
DEMO_TESTER_ID = "00000000-0000-0000-0000-000000000001"
DEMO_MANAGER_ID = "00000000-0000-0000-0000-000000000002"

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "")
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "15"))
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "")

# --- Slice 5: embeddings and duplicate thresholds (paste at the BOTTOM of app/config.py) ---
def _env_int(name: str, default: int = 0) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"{name} in .env must be a whole number, but it is {raw!r}.")


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        raise ValueError(f"{name} in .env must be a number, but it is {raw!r}.")


EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "local").strip().lower()
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "").strip()
EMBEDDING_DIM = _env_int("EMBEDDING_DIM", 0)
EMBEDDING_CACHE_DIR = os.getenv("EMBEDDING_CACHE_DIR", "").strip()
DUP_LIKELY_THRESHOLD = _env_float("DUP_LIKELY_THRESHOLD", 0.85)
DUP_POSSIBLE_THRESHOLD = _env_float("DUP_POSSIBLE_THRESHOLD", 0.70)

if not (0.0 < DUP_POSSIBLE_THRESHOLD < DUP_LIKELY_THRESHOLD < 1.0):
    raise ValueError(
        "In .env, the duplicate thresholds must satisfy "
        "0 < DUP_POSSIBLE_THRESHOLD < DUP_LIKELY_THRESHOLD < 1."
    )
