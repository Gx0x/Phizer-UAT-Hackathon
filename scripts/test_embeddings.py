"""Slice 5, Stage A: check the embedding model works and calibrate thresholds.

Run from the project root:
    python -m scripts.test_embeddings

It does NOT touch Supabase or the web app. It:
  1. loads the embedding model (the first run downloads it, so it can be slow),
  2. reports the vector length, which we need to set EMBEDDING_DIM,
  3. embeds 8 FAKE reports and prints how similar every pair is,
  4. suggests values for DUP_POSSIBLE_THRESHOLD and DUP_LIKELY_THRESHOLD.

The suggestions come from only 8 fake reports. Treat them as a starting point
and re-check them on the demo data in Stage B.
"""
import sys
import time

from app import config
from app.services import embeddings
from app.services.embeddings import EmbeddingError, build_embedding_text, cosine_similarity

# Fake reports, written the way testers write them. "problem" is only used to
# group the results; the model never sees it.
SAMPLES = [
    {"id": "A1", "problem": "export-hang", "answers": {"actual": "Export hangs", "page": "Export page"}},
    {"id": "A2", "problem": "export-hang", "answers": {"actual": "Report download never finishes", "steps": "Clicked Export, waited ten minutes"}},
    {"id": "A3", "problem": "export-hang", "answers": {"actual": "Spinner forever on Export"}},
    {"id": "A4", "problem": "export-hang", "answers": {"actual": "Export button just sits there loading", "page": "Reports"}},
    {"id": "B1", "problem": "export-dates", "answers": {"actual": "Exported dates are in the wrong format", "page": "Export page"}},
    {"id": "C1", "problem": "login", "answers": {"actual": "Something went wrong with the login", "steps": "Entered my password and pressed Sign in"}},
    {"id": "D1", "problem": "save", "answers": {"actual": "Clicking Save does nothing and my changes are lost", "page": "Settings"}},
    {"id": "E1", "problem": "vague", "answers": {"actual": "It didn't work"}},
]

HINTS = {
    "missing_configuration": "Check .env: EMBEDDING_PROVIDER, EMBEDDING_MODEL (and EMBEDDING_DIM for the real app).",
    "unknown_provider": "EMBEDDING_PROVIDER must be 'local' or 'gemini'.",
    "not_installed": "Run: python -m pip install fastembed",
    "model_load_failed": (
        "The model could not be downloaded or started. Common causes:\n"
        "  - no internet, or a firewall/VPN blocking huggingface.co\n"
        "  - EMBEDDING_MODEL is misspelled (try BAAI/bge-small-en-v1.5)\n"
        "  - a missing Microsoft Visual C++ Redistributable (x64) on Windows\n"
        "  - an unsupported Python version for the 'onnxruntime' package\n"
        "Or switch to EMBEDDING_PROVIDER=gemini (untested; see the notes)."
    ),
    "embedding_failed": "The model loaded but failed while embedding. If you use gemini, check the model name and free-tier limits.",
    "empty_text": "Nothing to embed.",
}


def group_of(a: dict, b: dict) -> str:
    """same problem / related-but-different / unrelated."""
    if a["problem"] == b["problem"]:
        return "same"
    if {a["problem"], b["problem"]} <= {"export-hang", "export-dates"}:
        return "related"
    return "unrelated"


def suggest_thresholds(lowest_same: float, highest_related: float, highest_unrelated: float):
    """Pick thresholds that sit in the gaps between the three groups.

    possible: above everything unrelated, ideally below the related-but-different
              pair, so that pair gets flagged for a human to judge.
    likely:   above the related-but-different pair, ideally at or below the
              weakest same-problem pair, so true duplicates are grouped.
    """
    notes = []

    if highest_unrelated < highest_related:
        possible = (highest_unrelated + highest_related) / 2
    else:
        possible = highest_unrelated + 0.02
        notes.append(
            "The related-but-different pair scores no higher than unrelated pairs, "
            "so they cannot be told apart. Expect it to be treated as a new issue."
        )

    if highest_related < lowest_same:
        likely = (highest_related + lowest_same) / 2
    else:
        likely = highest_related + 0.02
        notes.append(
            "Some same-problem pairs score no higher than the related-but-different "
            "pair. Likely is set above it, so those same-problem reports will only be "
            "flagged as 'possible'. That is the safe direction."
        )

    if possible >= likely:
        likely = possible + 0.02
    likely = min(likely, 0.99)
    if possible >= likely:
        possible = likely - 0.02
        notes.append("The groups overlap heavily. These thresholds cannot separate them reliably.")

    if likely - possible < 0.03:
        notes.append(
            "The two thresholds are very close together. Scores for this model may be "
            "squashed into a narrow range, so treat these numbers with caution."
        )

    return round(possible, 2), round(likely, 2), notes


def main() -> int:
    print("=== Embedding check and calibration (FAKE data only) ===")
    print(f"Provider:   {config.EMBEDDING_PROVIDER}")
    print(f"Model:      {config.EMBEDDING_MODEL or '(not set)'}")
    print(f"EMBEDDING_DIM in .env: {config.EMBEDDING_DIM or '(not set yet)'}")
    cache = config.EMBEDDING_CACHE_DIR or "default (a 'fastembed_cache' folder in your system temp folder)"
    if config.EMBEDDING_PROVIDER == "local":
        print(f"Model cache: {cache}")
    print()

    texts = [build_embedding_text("bug", s["answers"]) for s in SAMPLES]

    print("Loading the model. The FIRST run downloads it, which can take a minute...")
    started = time.perf_counter()
    try:
        first = embeddings.embed_raw(texts[0])
    except EmbeddingError as error:
        print(f"\nFAILED: {error.reason} ({error.detail})")
        print(HINTS.get(error.reason, ""))
        return 1
    load_seconds = time.perf_counter() - started
    print(f"Model ready in {load_seconds:.1f}s.\n")

    dim = len(first)
    print(f"Vector length: {dim}")
    if config.EMBEDDING_DIM == dim:
        print("EMBEDDING_DIM matches. Good.")
    else:
        print(f"-> Set  EMBEDDING_DIM={dim}  in your .env (it is currently "
              f"{config.EMBEDDING_DIM or 'not set'}).")
    print()

    started = time.perf_counter()
    try:
        vectors = [first] + [embeddings.embed_raw(t) for t in texts[1:]]
    except EmbeddingError as error:
        print(f"FAILED while embedding: {error.reason} ({error.detail})")
        return 1
    per_report_ms = (time.perf_counter() - started) / (len(texts) - 1) * 1000
    print(f"Embedding speed: about {per_report_ms:.0f} ms per report.\n")

    # --- similarity matrix ---
    ids = [s["id"] for s in SAMPLES]
    print("Similarity matrix (1.00 = identical meaning):")
    print("      " + "".join(f"{i:>6}" for i in ids))
    for i, a in enumerate(SAMPLES):
        row = "".join(f"{cosine_similarity(vectors[i], vectors[j]):6.2f}" for j in range(len(SAMPLES)))
        print(f"{a['id']:>5} {row}")
    print()

    # --- grouped pairs ---
    groups = {"same": [], "related": [], "unrelated": []}
    for i in range(len(SAMPLES)):
        for j in range(i + 1, len(SAMPLES)):
            score = cosine_similarity(vectors[i], vectors[j])
            groups[group_of(SAMPLES[i], SAMPLES[j])].append((score, f"{ids[i]} vs {ids[j]}"))

    titles = {
        "same": "SAME PROBLEM (should score highest)",
        "related": "RELATED BUT DIFFERENT export problem (should be flagged, not merged)",
        "unrelated": "UNRELATED (should score lowest)",
    }
    for key in ("same", "related", "unrelated"):
        print(titles[key])
        for score, label in sorted(groups[key], reverse=True):
            print(f"  {score:.2f}  {label}")
        print()

    lowest_same = min(s for s, _ in groups["same"])
    highest_related = max(s for s, _ in groups["related"])
    highest_unrelated = max(s for s, _ in groups["unrelated"])
    print("Key numbers")
    print(f"  Lowest SAME-problem score:       {lowest_same:.2f}")
    print(f"  Highest RELATED-but-different:   {highest_related:.2f}")
    print(f"  Highest UNRELATED score:         {highest_unrelated:.2f}")
    print()

    possible, likely, notes = suggest_thresholds(lowest_same, highest_related, highest_unrelated)
    print("Suggested settings for your .env (a starting point, tuned on 8 fake reports):")
    print(f"  EMBEDDING_DIM={dim}")
    print(f"  DUP_POSSIBLE_THRESHOLD={possible}")
    print(f"  DUP_LIKELY_THRESHOLD={likely}")
    for note in notes:
        print(f"  NOTE: {note}")
    print()
    print("Next: paste the 'Vector length' line, the three groups and the key numbers back to me.")
    print("Do not change anything in Supabase yet. That is Stage B.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
