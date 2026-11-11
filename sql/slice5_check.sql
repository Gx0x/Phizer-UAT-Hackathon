-- Run these AFTER sql/slice5.sql, in the Supabase SQL Editor (one at a time is fine).
-- They change nothing.

-- 1. The new columns. Expect two rows:
--      duplicate_check -> jsonb
--      embedding       -> USER-DEFINED (that is how a vector shows up here)
select column_name, data_type
from information_schema.columns
where table_schema = 'public'
  and table_name = 'reports'
  and column_name in ('embedding', 'duplicate_check')
order by column_name;

-- 2. The vector size. Expect exactly:  vector(384)
select format_type(a.atttypid, a.atttypmod) as embedding_type
from pg_attribute a
where a.attrelid = 'public.reports'::regclass
  and a.attname = 'embedding'
  and not a.attisdropped;

-- 3. The function exists and runs. Expect zero rows with no error (no reports
--    have embeddings yet). An error here means the migration did not apply.
select *
from public.match_reports(
    array_fill(0.1::real, array[384])::extensions.vector(384),
    'bug',
    3
);

-- 4. Your existing data is untouched. Compare with what you had before.
select
    (select count(*) from public.issues)  as issues,
    (select count(*) from public.reports) as reports;

-- ---------------------------------------------------------------------------
-- Run this later (after the seed), to see what was stored for each report:
--   select r.created_at, r.category,
--          r.duplicate_check->>'outcome'    as outcome,
--          r.duplicate_check->>'best_score' as best_score,
--          r.embedding is not null          as has_embedding,
--          r.issue_id
--   from public.reports r order by r.created_at;
--
-- If an issue's report_count ever looks wrong, this repairs every issue:
--   update public.issues i
--   set report_count = (select count(*) from public.reports r where r.issue_id = i.id);
-- ---------------------------------------------------------------------------
