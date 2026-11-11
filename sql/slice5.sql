-- Slice 5, Stage B: duplicate detection database changes.
-- Run ONCE in the Supabase SQL Editor. It runs as a single transaction, so any
-- error rolls the whole migration back and leaves your tables as they were.
--
-- What it does:
--   1. Aborts if any report already has an embedding (so nothing can be lost).
--   2. Replaces reports.embedding (vector(1024)) with vector(384) for the
--      local BAAI/bge-small-en-v1.5 model, and rebuilds its index.
--   3. Adds reports.duplicate_check (jsonb) to record each duplicate check.
--   4. Creates match_reports(), which finds the most similar earlier reports.
-- It does NOT touch report rows, issue rows, answers, follow-ups or AI checks.

begin;

-- 1. Safety check: refuse to continue if any embedding is already stored.
do $$
declare
    stored bigint;
begin
    select count(embedding) into stored from public.reports;
    if stored > 0 then
        raise exception
            'Aborting: % report(s) already have embeddings. Changing the column would delete them. Ask for help before continuing.',
            stored;
    end if;
end
$$;

-- 2. Replace only the embedding column. It holds no data (checked above).
drop index if exists public.reports_embedding_cosine_idx;
alter table public.reports drop column embedding;
alter table public.reports add column embedding extensions.vector(384);

create index reports_embedding_cosine_idx
    on public.reports using hnsw (embedding extensions.vector_cosine_ops);

-- 3. One record per report of what the duplicate check found.
alter table public.reports add column if not exists duplicate_check jsonb;

-- 4. Find the most similar earlier reports of the SAME category.
--
-- Similarity is 1 - cosine distance: 1.0 means identical meaning.
--
-- INDEXING NOTE: an HNSW index is approximate, and when a WHERE filter (here,
-- the category) removes many rows it can return fewer matches than exist, or
-- miss the best one. For a duplicate check, missing the best match is the one
-- thing we cannot accept. So this function turns index scans off for its own
-- queries ("set enable_indexscan = off") and always does an exact comparison.
-- That is fast for thousands of reports. If you ever have a very large table,
-- revisit this together with the index.
create or replace function public.match_reports(
    query_embedding extensions.vector(384),
    match_category text,
    match_count integer default 5
)
returns table (
    report_id uuid,
    issue_id uuid,
    similarity double precision
)
language sql
stable
set search_path = public, extensions
set enable_indexscan = off
as $$
    select
        r.id,
        r.issue_id,
        (1 - (r.embedding <=> query_embedding))::double precision
    from public.reports r
    join public.issues i on i.id = r.issue_id
    where r.embedding is not null
      and i.category = match_category
    order by r.embedding <=> query_embedding
    limit greatest(match_count, 1);
$$;

commit;
