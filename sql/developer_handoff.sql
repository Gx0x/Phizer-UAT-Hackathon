-- Technical drafts and individually approved developer tickets.
begin;

alter table public.issues add column if not exists handoff_status text not null default 'review'
    check (handoff_status in ('review', 'forwarded'));
alter table public.issues add column if not exists forwarded_at timestamptz;

create table if not exists public.technical_drafts (
    id uuid primary key default gen_random_uuid(),
    issue_id uuid not null unique references public.issues(id) on delete cascade,
    content jsonb not null,
    source_snapshot jsonb not null,
    generation_status text not null check (generation_status in ('ok', 'fallback')),
    revision bigint not null default 1,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
create table if not exists public.developer_tickets (
    id uuid primary key default gen_random_uuid(),
    issue_id uuid not null unique references public.issues(id) on delete cascade,
    content jsonb not null,
    source_snapshot jsonb not null,
    status text not null default 'todo' check (status in ('todo', 'in_progress', 'ready_for_retest')),
    active boolean not null default true,
    revision bigint not null default 1,
    approved_by uuid references public.profiles(id) on delete set null,
    approved_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
alter table public.technical_drafts enable row level security;
alter table public.developer_tickets enable row level security;

create or replace function public.handoff_sources(target_issue_id uuid)
returns jsonb language sql stable set search_path = public as $$
    select coalesce(jsonb_agg(jsonb_build_object(
        'id', r.id::text, 'category', r.category, 'answers', coalesce(r.answers, '{}'::jsonb),
        'created_at', r.created_at, 'occurred_at', r.occurred_at,
        'follow_up_question', r.follow_up_question, 'follow_up_answer', r.follow_up_answer,
        'detail_revision', r.detail_revision,
        'manager_clarifications', (select coalesce(jsonb_agg(jsonb_build_object(
            'id', d.id::text, 'question', d.question, 'answer', d.answer, 'answered_at', d.answered_at
        ) order by d.id::text), '[]'::jsonb) from public.detail_requests d
            where d.report_id = r.id and d.status = 'answered')
    ) order by r.id::text), '[]'::jsonb)
    from public.reports r where r.issue_id = target_issue_id;
$$;

create or replace function public.normalize_handoff_sources(payload jsonb)
returns jsonb language sql stable set search_path = public as $$
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
    ) order by item->>'id'), '[]'::jsonb)
    from jsonb_array_elements(payload) as sources(item);
$$;

create or replace function public.valid_handoff_content(content jsonb, context jsonb)
returns boolean language sql immutable as $$
    select coalesce(
        jsonb_typeof(content) = 'object'
        and length(btrim(content->>'title')) > 0
        and length(btrim(content->>'problem_summary')) > 0
        and content->>'priority' in ('low', 'medium', 'high', 'critical')
        and jsonb_typeof(content->'included_log_ids') = 'array'
        and not exists (
            select 1 from jsonb_array_elements_text(content->'included_log_ids') as selected(id)
            where not exists (select 1 from jsonb_array_elements(context->'log_candidates') as candidate(entry)
                where entry->>'id' = selected.id)
        ), false);
$$;

create or replace function public.store_technical_draft(
    p_issue_id uuid, p_context jsonb, p_content jsonb, p_generation_status text
)
returns jsonb language plpgsql set search_path = public as $$
declare
    state text;
    saved public.technical_drafts%rowtype;
begin
    select handoff_status into state from public.issues where id = p_issue_id for update;
    if not found then return jsonb_build_object('status', 'not_found'); end if;
    if state = 'forwarded' then return jsonb_build_object('status', 'forwarded'); end if;
    if public.normalize_handoff_sources(p_context->'reports') is distinct from public.handoff_sources(p_issue_id) then
        return jsonb_build_object('status', 'sources_changed');
    end if;
    if not public.valid_handoff_content(p_content, p_context) then return jsonb_build_object('status', 'invalid_content'); end if;
    insert into public.technical_drafts(issue_id, content, source_snapshot, generation_status)
    values(p_issue_id, p_content, p_context, p_generation_status)
    on conflict(issue_id) do update set content = excluded.content, source_snapshot = excluded.source_snapshot,
        generation_status = excluded.generation_status, revision = technical_drafts.revision + 1, updated_at = now()
    returning * into saved;
    return jsonb_build_object('status', 'saved', 'draft', to_jsonb(saved));
end;
$$;

create or replace function public.save_technical_draft(
    p_issue_id uuid, p_expected_revision bigint, p_content jsonb
)
returns jsonb language plpgsql set search_path = public as $$
declare
    state text;
    saved public.technical_drafts%rowtype;
begin
    select handoff_status into state from public.issues where id = p_issue_id for update;
    if not found then return jsonb_build_object('status', 'not_found'); end if;
    if state = 'forwarded' then return jsonb_build_object('status', 'forwarded'); end if;
    select * into saved from public.technical_drafts where issue_id = p_issue_id for update;
    if not found then return jsonb_build_object('status', 'no_draft'); end if;
    if saved.revision <> p_expected_revision then return jsonb_build_object('status', 'revision_changed'); end if;
    if public.normalize_handoff_sources(saved.source_snapshot->'reports') is distinct from public.handoff_sources(p_issue_id) then
        return jsonb_build_object('status', 'sources_changed');
    end if;
    if not public.valid_handoff_content(p_content, saved.source_snapshot) then return jsonb_build_object('status', 'invalid_content'); end if;
    update public.technical_drafts set content = p_content, revision = revision + 1, updated_at = now()
    where issue_id = p_issue_id returning * into saved;
    return jsonb_build_object('status', 'saved', 'draft', to_jsonb(saved));
end;
$$;

create or replace function public.approve_technical_handoff(
    p_issue_id uuid, p_expected_revision bigint, p_content jsonb, p_manager_id uuid
)
returns jsonb language plpgsql set search_path = public as $$
declare
    state text;
    result jsonb;
    draft public.technical_drafts%rowtype;
    ticket public.developer_tickets%rowtype;
    approved_content jsonb;
begin
    select handoff_status into state from public.issues where id = p_issue_id for update;
    if not found then return jsonb_build_object('status', 'not_found'); end if;
    if state = 'forwarded' then return jsonb_build_object('status', 'forwarded'); end if;
    if exists(select 1 from public.detail_requests d join public.reports r on r.id = d.report_id
        where r.issue_id = p_issue_id and d.status in ('draft', 'pending')) then
        return jsonb_build_object('status', 'open_requests');
    end if;
    result := public.save_technical_draft(p_issue_id, p_expected_revision, p_content);
    if result->>'status' <> 'saved' then return result; end if;
    select * into draft from public.technical_drafts where issue_id = p_issue_id;
    approved_content := p_content || jsonb_build_object('supporting_logs',
        (select coalesce(jsonb_agg(entry), '[]'::jsonb)
         from jsonb_array_elements(draft.source_snapshot->'log_candidates') as candidates(entry)
         where (p_content->'included_log_ids') ? (entry->>'id')));
    insert into public.developer_tickets(issue_id, content, source_snapshot, approved_by)
    values(p_issue_id, approved_content, jsonb_build_object('reports', draft.source_snapshot->'reports'), p_manager_id)
    on conflict(issue_id) do update set content = excluded.content, source_snapshot = excluded.source_snapshot,
        status = 'todo', active = true, revision = developer_tickets.revision + 1,
        approved_by = excluded.approved_by, approved_at = now(), updated_at = now()
    returning * into ticket;
    update public.issues set handoff_status = 'forwarded', forwarded_at = now() where id = p_issue_id;
    return jsonb_build_object('status', 'forwarded', 'ticket_id', ticket.id);
end;
$$;

create or replace function public.reopen_technical_handoff(p_issue_id uuid)
returns jsonb language plpgsql set search_path = public as $$
begin
    perform 1 from public.issues where id = p_issue_id for update;
    if not found then return jsonb_build_object('status', 'not_found'); end if;
    update public.issues set handoff_status = 'review', forwarded_at = null where id = p_issue_id;
    update public.developer_tickets set active = false, revision = revision + 1, updated_at = now()
    where issue_id = p_issue_id and active;
    update public.technical_drafts set revision = revision + 1, updated_at = now() where issue_id = p_issue_id;
    return jsonb_build_object('status', 'reopened');
end;
$$;

create or replace function public.update_developer_ticket_status(
    p_ticket_id uuid, p_expected_revision bigint, p_status text
)
returns jsonb language plpgsql set search_path = public as $$
declare
    parent_id uuid;
    state text;
    ticket public.developer_tickets%rowtype;
begin
    select issue_id into parent_id from public.developer_tickets where id = p_ticket_id;
    if not found then return jsonb_build_object('status', 'not_found'); end if;
    select handoff_status into state from public.issues where id = parent_id for update;
    select * into ticket from public.developer_tickets where id = p_ticket_id for update;
    if not ticket.active or state <> 'forwarded' then return jsonb_build_object('status', 'withdrawn'); end if;
    if ticket.revision <> p_expected_revision then return jsonb_build_object('status', 'revision_changed'); end if;
    if p_status not in ('todo', 'in_progress', 'ready_for_retest') then return jsonb_build_object('status', 'invalid_content'); end if;
    update public.developer_tickets set status = p_status, revision = revision + 1, updated_at = now()
    where id = p_ticket_id returning * into ticket;
    return jsonb_build_object('status', 'saved', 'ticket', to_jsonb(ticket));
end;
$$;

-- Source changes withdraw a previously approved snapshot for fresh manager review.
create or replace function public.reopen_handoff_on_report_change()
returns trigger language plpgsql set search_path = public as $$
declare
    old_parent uuid;
    new_parent uuid;
    parent_id uuid;
    state text;
begin
    if TG_OP <> 'INSERT' then old_parent := OLD.issue_id; end if;
    if TG_OP <> 'DELETE' then new_parent := NEW.issue_id; end if;
    if TG_OP = 'UPDATE' and
       (NEW.issue_id, NEW.answers, NEW.follow_up_question, NEW.follow_up_answer, NEW.occurred_at, NEW.detail_revision)
       is not distinct from
       (OLD.issue_id, OLD.answers, OLD.follow_up_question, OLD.follow_up_answer, OLD.occurred_at, OLD.detail_revision) then
        return NEW;
    end if;
    for parent_id in select distinct value from unnest(array[old_parent, new_parent]) as parents(value)
        where value is not null order by value loop
        select handoff_status into state from public.issues where id = parent_id for update;
        if state = 'forwarded' then perform public.reopen_technical_handoff(parent_id); end if;
    end loop;
    if TG_OP = 'DELETE' then return OLD; end if;
    return NEW;
end;
$$;
drop trigger if exists reports_reopen_handoff on public.reports;
create trigger reports_reopen_handoff after insert or update or delete on public.reports
    for each row execute function public.reopen_handoff_on_report_change();

create or replace function public.guard_detail_request_handoff()
returns trigger language plpgsql set search_path = public as $$
declare
    state text;
begin
    if NEW.status in ('draft', 'pending') then
        select i.handoff_status into state from public.issues i
        join public.reports r on r.issue_id = i.id where r.id = NEW.report_id for update of i;
        if state = 'forwarded' then raise exception 'Reopen this issue before requesting more detail'; end if;
    end if;
    return NEW;
end;
$$;
drop trigger if exists detail_requests_guard_handoff on public.detail_requests;
create trigger detail_requests_guard_handoff before insert or update of status on public.detail_requests
    for each row execute function public.guard_detail_request_handoff();

commit;
