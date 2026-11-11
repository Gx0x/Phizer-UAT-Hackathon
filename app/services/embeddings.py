"""Turn report text into a list of numbers (an "embedding") so we can measure
how similar two reports are.

Why this exists: the SIMILARITY SCORE shown to managers is calculated from
these numbers with cosine similarity. It is maths, not a language model's
opinion, so the same two reports always get the same score.

Everything goes through ONE function, embed_text(). The provider is chosen in
.env (EMBEDDING_PROVIDER), so the rest of the app never knows which is in use:
  - "local":  fastembed, runs on this computer. No API key, no rate limits, and
              the report text never leaves the machine.
  - "gemini": Google's embedding API. UNTESTED in this project. It shares the
              free-tier limits you have already seen with the quality check.

Failures raise EmbeddingError with a short machine-readable reason. The report
endpoint (Stage B) catches it, saves the report anyway, and records
{"status": "unavailable", "reason": ...}. A failed embedding never loses a report.
"""
import logging
import math
import threading
import time

from app import config
from app.form_config import FORMS

log = logging.getLogger("uat.embeddings")

# After a failed model load, don't retry for this long. fastembed retries a
# failed download for about 40 seconds, and we must never make every tester
# wait that long while the model is unavailable.
LOAD_RETRY_COOLDOWN_SECONDS = 300

_model = None
_model_lock = threading.Lock()
_load_failed_at: float | None = None
_load_failure: "EmbeddingError | None" = None

_gemini_client = None


class EmbeddingError(Exception):
    """Raised when we cannot produce a usable embedding.

    reason is one of: missing_configuration, unknown_provider, not_installed,
    model_load_failed, embedding_failed, empty_text, dimension_mismatch.
    detail holds only an exception TYPE or a count, never report text or keys.
    """

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


# --------------------------------------------------------------------------
# Local provider (fastembed)
# --------------------------------------------------------------------------
def _load_local_model():
    """Load the local model once, lazily, and reuse it for every call."""
    global _model, _load_failed_at, _load_failure

    if _model is not None:
        return _model

    with _model_lock:
        if _model is not None:
            return _model

        # Recently failed? Fail fast instead of waiting through retries again.
        if _load_failed_at is not None and (
            time.monotonic() - _load_failed_at < LOAD_RETRY_COOLDOWN_SECONDS
        ):
            raise _load_failure

        if not config.EMBEDDING_MODEL:
            raise EmbeddingError("missing_configuration", "EMBEDDING_MODEL is not set in .env")

        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise EmbeddingError("not_installed", "fastembed is not installed") from exc

        kwargs = {"model_name": config.EMBEDDING_MODEL}
        # Blank means fastembed's default: a "fastembed_cache" folder in the
        # system temp directory (NOT inside the project, so not in OneDrive).
        if config.EMBEDDING_CACHE_DIR:
            kwargs["cache_dir"] = config.EMBEDDING_CACHE_DIR

        try:
            _model = TextEmbedding(**kwargs)
        except Exception as exc:  # download blocked, bad name, missing runtime...
            log.warning("Could not load embedding model: %s", type(exc).__name__)
            _load_failure = EmbeddingError("model_load_failed", type(exc).__name__)
            _load_failed_at = time.monotonic()
            raise _load_failure from exc

        _load_failed_at = None
        _load_failure = None
        return _model


def _embed_local(text: str) -> list[float]:
    model = _load_local_model()
    try:
        vector = next(iter(model.embed([text])))
    except Exception as exc:
        log.warning("Local embedding failed: %s", type(exc).__name__)
        raise EmbeddingError("embedding_failed", type(exc).__name__) from exc
    return [float(x) for x in vector]


# --------------------------------------------------------------------------
# Gemini provider (optional, UNTESTED)
# --------------------------------------------------------------------------
def _embed_gemini(text: str) -> list[float]:
    global _gemini_client

    api_key = getattr(config, "GEMINI_API_KEY", "")
    if not api_key or not config.EMBEDDING_MODEL:
        raise EmbeddingError("missing_configuration", "GEMINI_API_KEY or EMBEDDING_MODEL is not set")

    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise EmbeddingError("not_installed", "google-genai is not installed") from exc

    try:
        if _gemini_client is None:
            _gemini_client = genai.Client(api_key=api_key)
        timeout_ms = int(getattr(config, "LLM_TIMEOUT_SECONDS", 15) * 1000)
        response = _gemini_client.models.embed_content(
            model=config.EMBEDDING_MODEL,
            contents=text,
            config=types.EmbedContentConfig(
                output_dimensionality=config.EMBEDDING_DIM or None,
                http_options=types.HttpOptions(timeout=timeout_ms),
            ),
        )
        return [float(x) for x in response.embeddings[0].values]
    except Exception as exc:
        status = getattr(exc, "code", None) or getattr(exc, "status_code", None)
        log.warning("Gemini embedding failed: %s status=%s", type(exc).__name__, status)
        raise EmbeddingError("embedding_failed", f"{type(exc).__name__} {status or ''}".strip()) from exc


# --------------------------------------------------------------------------
# Public functions
# --------------------------------------------------------------------------
def embed_raw(text: str) -> list[float]:
    """Embed text with NO length check. Used by the calibration script, which
    needs to see the model's real vector size before we set EMBEDDING_DIM."""
    if not text or not text.strip():
        raise EmbeddingError("empty_text", "nothing to embed")

    provider = config.EMBEDDING_PROVIDER
    if provider == "local":
        return _embed_local(text)
    if provider == "gemini":
        return _embed_gemini(text)
    raise EmbeddingError("unknown_provider", provider or "(blank)")


def embed_text(text: str) -> list[float]:
    """Embed text and make sure the vector matches the database column size."""
    if not config.EMBEDDING_DIM:
        raise EmbeddingError("missing_configuration", "EMBEDDING_DIM is not set in .env")

    vector = embed_raw(text)
    if len(vector) != config.EMBEDDING_DIM:
        raise EmbeddingError(
            "dimension_mismatch",
            f"model returned {len(vector)} values but EMBEDDING_DIM is {config.EMBEDDING_DIM}",
        )
    return vector


def warm_up() -> float:
    """Load the model now (first run downloads it). Returns seconds taken.
    Stage B can call this at startup so the first tester doesn't pay for it."""
    started = time.perf_counter()
    embed_raw("warm up")
    return time.perf_counter() - started


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """1.0 = pointing the same way (very similar), near 0 = unrelated."""
    if len(a) != len(b):
        raise ValueError("vectors must be the same length")
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def build_embedding_text(category: str, answers: dict[str, str]) -> str:
    """The exact text we embed for a report: each field's question label next
    to the tester's answer, in form order.

    The calibration script uses this SAME function, and Stage B will too. That
    matters: the shared labels ("What actually happened?") add words every bug
    report has in common, which raises ALL similarity scores. Thresholds tuned
    on bare phrases would not carry over to the real pipeline.
    """
    parts = []
    for field in FORMS[category]["fields"]:
        value = (answers.get(field["key"]) or "").strip()
        if value:
            parts.append(f"{field['label']}: {value}")
    return "\n".join(parts)
