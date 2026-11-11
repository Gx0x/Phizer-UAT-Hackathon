-- Mock CloudWatch evidence and optional occurrence time. Safe to rerun.
begin;

alter table public.reports add column if not exists occurred_at timestamptz;
alter table public.issues add column if not exists consolidated_report jsonb;

-- Save the summary and its supporting evidence together, only for current sources.
create or replace function public.store_consolidated_report(
    target_issue_id uuid,
    expected_sources jsonb,
    assessment jsonb
)
returns boolean
language plpgsql
set search_path = public
as $$
declare
    current_sources jsonb;
    normalized_expected jsonb;
    evidence jsonb;
begin
    perform 1 from public.issues where id = target_issue_id for update;
    if not found then
        return false;
    end if;

    select coalesce(jsonb_agg(jsonb_build_object(
        'id', r.id::text,
        'category', r.category,
        'answers', coalesce(r.answers, '{}'::jsonb),
        'created_at', r.created_at,
        'occurred_at', r.occurred_at,
        'follow_up_question', r.follow_up_question,
        'follow_up_answer', r.follow_up_answer
    ) order by r.id::text), '[]'::jsonb)
    into current_sources
    from public.reports r where r.issue_id = target_issue_id;

    -- Normalize equivalent timestamp spellings such as Z and +00:00.
    select coalesce(jsonb_agg(jsonb_build_object(
        'id', item->>'id',
        'category', item->>'category',
        'answers', coalesce(item->'answers', '{}'::jsonb),
        'created_at', (item->>'created_at')::timestamptz,
        'occurred_at', (item->>'occurred_at')::timestamptz,
        'follow_up_question', item->>'follow_up_question',
        'follow_up_answer', item->>'follow_up_answer'
    ) order by item->>'id'), '[]'::jsonb)
    into normalized_expected
    from jsonb_array_elements(expected_sources) as sources(item);

    if normalized_expected is distinct from current_sources then
        return false;
    end if;

    update public.issues set consolidated_report = assessment where id = target_issue_id;

    -- Keep one current log-match record per issue. Repeated refreshes replace it.
    delete from public.log_matches where issue_id = target_issue_id;
    evidence := assessment->'log_evidence';
    if evidence->>'status' = 'ok'
       and jsonb_array_length(coalesce(evidence->'matches', '[]'::jsonb)) > 0 then
        insert into public.log_matches (issue_id, confidence, matched_lines, reasoning)
        values (
            target_issue_id,
            (select max((entry->>'relevance_score')::double precision)
             from jsonb_array_elements(evidence->'matches') as entries(entry)),
            evidence->'matches',
            evidence->'matches'->0->>'reasoning'
        );
    end if;
    return true;
end;
$$;

commit;
