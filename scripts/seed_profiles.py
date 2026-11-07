"""Create the demo tester and manager profiles.

Safe to run as many times as you like: it upserts on fixed IDs, so you will
always end up with exactly one tester and one manager.

Run from the project root:  python -m scripts.seed_profiles
"""
from app.config import DEMO_MANAGER_ID, DEMO_TESTER_ID
from app.db import get_supabase

PROFILES = [
    {"id": DEMO_TESTER_ID, "name": "Demo Tester", "role": "tester"},
    {"id": DEMO_MANAGER_ID, "name": "Demo Manager", "role": "manager"},
]


def main() -> None:
    client = get_supabase()
    client.table("profiles").upsert(PROFILES, on_conflict="id").execute()

    rows = client.table("profiles").select("id, name, role").execute().data
    print(f"Profiles in database: {len(rows)}")
    for row in rows:
        print(f"  {row['role']:<8} {row['name']}  ({row['id']})")


if __name__ == "__main__":
    main()
