from functools import lru_cache

from supabase import Client, create_client

from app.config import SUPABASE_SERVICE_KEY, SUPABASE_URL


@lru_cache(maxsize=1)
def get_supabase() -> Client:
    """Create (once) a client using the server-only Supabase service key."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        raise RuntimeError(
            "Set SUPABASE_URL and SUPABASE_SERVICE_KEY in your project .env file."
        )

    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def test_connection() -> None:
    client = get_supabase()

    # An empty table is fine; this checks that Supabase can query the schema.
    client.table("profiles").select("id").limit(1).execute()

    # Identical vectors should have cosine similarity 1.0.
    result = client.rpc("pgvector_similarity_test").execute()
    print("Supabase connection: OK")
    print(f"pgvector similarity test result: {result.data}")


if __name__ == "__main__":
    test_connection()
