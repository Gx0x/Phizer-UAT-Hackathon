-- Manager-approved detail requests and immutable reply history.
begin;

alter table public.reports add column if not exists detail_revision bigint not null default 0;

create table if not exists public.detail_requests (
    id uuid primary key default gen_random_uuid(),
    report_id uuid not null references public.reports(id) on delete cascade,
    manager_id uuid references public.profiles(id) on delete set null,
    question text not null check (length(btrim(question)) > 0),
    answer text,
    status text not null default 'draft' check (status in ('draft', 'pending', 'answered', 'cancelled')),
    suggestion_status text not null default 'unavailable' check (suggestion_status in ('ok', 'unavailable')),
    created_at timestamptz not null default now(),
    sent_at timestamptz,
    answered_at timestamptz,
    check (status <> 'pending' or sent_at is not null),
    check (status <> 'answered' or (answer is not null and length(btrim(answer)) > 0 and answered_at is not null))
);
create unique index if not exists detail_requests_one_active_per_report
    on public.detail_requests(report_id) where status in ('draft', 'pending');
create index if not exists detail_requests_report_created_idx
    on public.detail_requests(report_id, created_at);
alter table public.detail_requests enable row level security;

create or replace function public.answer_detail_request(
    request_id uuid, respondent uuid, new_answer text
)
returns jsonb
language plpgsql
set search_path = public
as $$
declare
    source_id uuid;
    source_issue uuid;
    owner_id uuid;
    item public.detail_requests%rowtype;
    revision bigint;
begin
    select report_id into source_id from public.detail_requests where id = request_id;
    if not found then return jsonb_build_object('status', 'not_found'); end if;
    -- Serialize replies for one report before changing its history and revision.
    select tester_id, issue_id into owner_id, source_issue
    from public.reports where id = source_id for update;
    if not found then return jsonb_build_object('status', 'not_found'); end if;
    select * into item from public.detail_requests where id = request_id for update;
    if not found then return jsonb_build_object('status', 'not_found'); end if;
    if coalesce(owner_id, '00000000-0000-0000-0000-000000000001'::uuid) is distinct from respondent then
        return jsonb_build_object('status', 'not_owner');
    end if;
    if item.status = 'answered' then return jsonb_build_object('status', 'already_answered'); end if;
    if item.status <> 'pending' then return jsonb_build_object('status', 'not_pending'); end if;
    if new_answer is null or length(btrim(new_answer)) = 0 then
        return jsonb_build_object('status', 'invalid_answer');
    end if;
    update public.detail_requests set answer = btrim(new_answer), status = 'answered', answered_at = now()
    where id = request_id;
    update public.reports set detail_revision = detail_revision + 1 where id = source_id
    returning detail_revision into revision;
    return jsonb_build_object('status', 'saved', 'report_id', source_id, 'issue_id', source_issue,
        'detail_revision', revision);
end;
$$;

-- Preserve the summary/evidence transaction while including manager replies in its source check.
create or replace function public.store_consolidated_report(
    target_issue_id uuid, expected_sources jsonb, assessment jsonb
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
    if not found then return false; end if;
    select coalesce(jsonb_agg(jsonb_build_object(
        'id', r.id::text, 'category', r.category, 'answers', coalesce(r.answers, '{}'::jsonb),
        'created_at', r.created_at, 'occurred_at', r.occurred_at,
        'follow_up_question', r.follow_up_question, 'follow_up_answer', r.follow_up_answer,
        'detail_revision', r.detail_revision,
        'manager_clarifications', (select coalesce(jsonb_agg(jsonb_build_object(
            'id', d.id::text, 'question', d.question, 'answer', d.answer, 'answered_at', d.answered_at
        ) order by d.id::text), '[]'::jsonb) from public.detail_requests d
            where d.report_id = r.id and d.status = 'answered')
    ) order by r.id::text), '[]'::jsonb) into current_sources
    from public.reports r where r.issue_id = target_issue_id;

    select coalesce(jsonb_agg(jsonb_build_object(
        'id', item->>'id', 'category', item->>'category',
        'answers', coalesce(item->'answers', '{}'::jsonb),
        'created_at', (item->>'created_at')::timestamptz,
        'occurred_at', (item->>'occurred_at')::timestamptz,
        'follow_up_question', item->>'follow_up_question', 'follow_up_answer', item->>'follow_up_answer',
        'detail_revision', coalesce((item->>'detail_revision')::bigint, 0),
        'manager_clarifications', (select coalesce(jsonb_agg(jsonb_build_object(
            'id', reply->>'id', 'question', reply->>'question', 'answer', reply->>'answer',
            'answered_at', (reply->>'answered_at')::timestamptz
        ) order by reply->>'id'), '[]'::jsonb)
         from jsonb_array_elements(coalesce(item->'manager_clarifications', '[]'::jsonb)) as replies(reply))
    ) order by item->>'id'), '[]'::jsonb) into normalized_expected
    from jsonb_array_elements(expected_sources) as sources(item);

    if normalized_expected is distinct from current_sources then return false; end if;
    update public.issues set consolidated_report = assessment where id = target_issue_id;
    delete from public.log_matches where issue_id = target_issue_id;
    evidence := assessment->'log_evidence';
    if evidence->>'status' = 'ok' and jsonb_array_length(coalesce(evidence->'matches', '[]'::jsonb)) > 0 then
        insert into public.log_matches (issue_id, confidence, matched_lines, reasoning)
        values (target_issue_id,
            (select max((entry->>'relevance_score')::double precision)
             from jsonb_array_elements(evidence->'matches') as entries(entry)),
            evidence->'matches', evidence->'matches'->0->>'reasoning');
    end if;
    return true;
end;
$$;

commit;
