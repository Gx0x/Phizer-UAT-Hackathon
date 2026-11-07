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
