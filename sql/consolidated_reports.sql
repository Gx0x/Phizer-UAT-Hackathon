-- Additive migration. Preserves all issues, reports and duplicate matches.
begin;

alter table public.issues
    add column if not exists consolidated_report jsonb;

-- Only store output if it still describes the current source reports.
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
begin
    perform 1 from public.issues where id = target_issue_id for update;
    if not found then
        return false;
    end if;

    select coalesce(jsonb_agg(jsonb_build_object(
        'id', r.id::text,
        'category', r.category,
        'answers', coalesce(r.answers, '{}'::jsonb),
        'follow_up_question', r.follow_up_question,
        'follow_up_answer', r.follow_up_answer
    ) order by r.id::text), '[]'::jsonb)
    into current_sources
    from public.reports r
    where r.issue_id = target_issue_id;

    if expected_sources is distinct from current_sources then
        return false;
    end if;

    update public.issues
    set consolidated_report = assessment
    where id = target_issue_id;
    return true;
end;
$$;

commit;
