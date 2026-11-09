# Phizer / UAT, Untangled

Demo UAT reporting application using FastAPI, Supabase and optional Gemini AI quality checks.

## Setup and run (PowerShell, from project root)

```powershell
python -m pip install -r requirements.txt
python -m scripts.seed_profiles
python -m uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000 and API docs at http://127.0.0.1:8000/docs.

Apply `sql/schema.sql` for a new database and `sql/slice4.sql` in Supabase SQL Editor for Slice 4.
Copy `.env.example` to `.env` and fill in credentials locally. Never commit `.env`.

## AI tests

```powershell
python -m scripts.test_ai
python -m scripts.test_ai --live
```

Offline tests use fake model responses; live tests make real API calls with fake report content. A model failure must never prevent saving a report.

**Data warning:** Gemini free-tier requests may be used by the provider to improve its products. Use **fake data only** in this demo. A production version should use a paid endpoint with appropriate data-processing terms and proper authentication and access controls.

The model name is configured in `.env` rather than Python because Google may retire or rename models. Check Google AI Studio for current model names, free-tier limits and availability before running live tests.
