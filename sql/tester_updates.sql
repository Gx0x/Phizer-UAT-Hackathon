-- Requires developer_handoff.sql and the previous detail-request migration.
begin;

alter table public.issues add column if not exists tester_resolution text not null default 'open'
    check (tester_resolution in ('open', 'completed', 'not_forwarded'));

create table if not exists public.tester_updates (
    id bigint generated always as identity primary key,
    issue_id uuid not null references public.issues(id) on delete cascade,
    status text not null check (status in ('under_review', 'forwarded', 'in_progress', 'ready_for_retest', 'completed', 'not_forwarded')),
    message text not null check (length(btrim(message)) > 0),
    reason text not null default '',
    created_at timestamptz not null default now(),
    check (status <> 'not_forwarded' or length(btrim(reason)) > 0)
);
create index if not exists tester_updates_issue_latest on public.tester_updates(issue_id, id desc);
alter table public.tester_updates enable row level security;

create or replace function public.tester_update_message(p_status text)
returns text language sql immutable as $$
    select case p_status
      when 'forwarded' then 'Your feedback has helped identify an issue. It has been approved for the development team to work on. Thank you for reporting it.'
      when 'in_progress' then 'The development team is working on this issue. Thank you for helping us identify it.'
      when 'ready_for_retest' then 'A change is ready to check. Could you try the steps again and let the UAT manager know whether the issue still happens? Thank you for your help.'
      else 'Your issue has returned to the UAT manager for another review. Your original feedback has been kept. Thank you for helping us look into it.' end;
$$;

create or replace function public.tester_feedback_context(p_issue_id uuid)
returns jsonb language plpgsql stable set search_path = public as $$
declare
    issue public.issues%rowtype;
    ticket public.developer_tickets%rowtype;
    current_state text;
begin
    select * into issue from public.issues where id = p_issue_id;
    if not found then return jsonb_build_object('status', 'not_found'); end if;
    select * into ticket from public.developer_tickets where issue_id = p_issue_id and active;
    current_state := case
      when issue.tester_resolution <> 'open' then issue.tester_resolution
      when issue.handoff_status = 'forwarded' and ticket.status = 'in_progress' then 'in_progress'
      when issue.handoff_status = 'forwarded' and ticket.status = 'ready_for_retest' then 'ready_for_retest'
      when issue.handoff_status = 'forwarded' then 'forwarded'
      else 'under_review' end;
    return jsonb_build_object('status', 'ok', 'current_status', current_state,
        'closed', issue.tester_resolution <> 'open',
        'can_complete', issue.tester_resolution = 'open' and issue.handoff_status = 'forwarded'
            and coalesce(ticket.status = 'ready_for_retest', false));
end;
$$;

create or replace function public.send_tester_feedback(
    p_issue_id uuid, p_action text, p_message text, p_reason text default '', p_checked_fix boolean default false
)
returns jsonb language plpgsql set search_path = public as $$
declare
    issue public.issues%rowtype;
    context jsonb;
    target_state text;
    event public.tester_updates%rowtype;
begin
    select * into issue from public.issues where id = p_issue_id for update;
    if not found then return jsonb_build_object('status', 'not_found'); end if;
    if p_message is null or length(btrim(p_message)) = 0 or length(p_message) > 3000 then
        return jsonb_build_object('status', 'invalid_message'); end if;
    if p_action = 'not_forwarded' and (p_reason is null or length(btrim(p_reason)) = 0) then
        return jsonb_build_object('status', 'reason_required'); end if;
    context := public.tester_feedback_context(p_issue_id);
    if p_action = 'reopen' then
        if issue.tester_resolution = 'open' then return jsonb_build_object('status', 'not_closed'); end if;
        perform public.reopen_technical_handoff(p_issue_id);
        update public.issues set tester_resolution = 'open' where id = p_issue_id;
        target_state := 'under_review';
    else
        if issue.tester_resolution <> 'open' then return jsonb_build_object('status', 'closed'); end if;
        if p_action in ('completed', 'not_forwarded') then
            if exists(select 1 from public.detail_requests d join public.reports r on r.id = d.report_id
                where r.issue_id = p_issue_id and d.status in ('draft', 'pending')) then
                return jsonb_build_object('status', 'open_requests'); end if;
            if p_action = 'completed' and (not (context->>'can_complete')::boolean or not coalesce(p_checked_fix, false)) then
                return jsonb_build_object('status', 'not_ready'); end if;
            -- Withdraw the active developer ticket. Preserve all source reports.
            perform public.reopen_technical_handoff(p_issue_id);
            update public.issues set tester_resolution = p_action where id = p_issue_id;
            target_state := p_action;
        elsif p_action = 'send_update' then
            target_state := context->>'current_status';
        else
            return jsonb_build_object('status', 'invalid_message');
        end if;
    end if;
    insert into public.tester_updates(issue_id, status, message, reason)
    values(p_issue_id, target_state, btrim(p_message), case when target_state = 'not_forwarded' then btrim(p_reason) else '' end)
    returning * into event;
    return jsonb_build_object('status', 'saved', 'update', to_jsonb(event));
end;
$$;

create or replace function public.notify_tester_handoff()
returns trigger language plpgsql set search_path = public as $$
begin
    if NEW.handoff_status is distinct from OLD.handoff_status then
        insert into public.tester_updates(issue_id, status, message)
        values(NEW.id, case when NEW.handoff_status = 'forwarded' then 'forwarded' else 'under_review' end,
            public.tester_update_message(case when NEW.handoff_status = 'forwarded' then 'forwarded' else 'under_review' end));
    end if;
    return NEW;
end;
$$;
drop trigger if exists issues_notify_testers on public.issues;
create trigger issues_notify_testers after update of handoff_status on public.issues
    for each row execute function public.notify_tester_handoff();

create or replace function public.notify_tester_development()
returns trigger language plpgsql set search_path = public as $$
declare state text;
begin
    select handoff_status into state from public.issues where id = NEW.issue_id;
    if NEW.active and state = 'forwarded' and NEW.status is distinct from OLD.status then
        insert into public.tester_updates(issue_id, status, message)
        values(NEW.issue_id, case when NEW.status = 'todo' then 'forwarded' else NEW.status end,
            public.tester_update_message(case when NEW.status = 'todo' then 'forwarded' else NEW.status end));
    end if;
    return NEW;
end;
$$;
drop trigger if exists developer_tickets_notify_testers on public.developer_tickets;
create trigger developer_tickets_notify_testers after update of status on public.developer_tickets
    for each row execute function public.notify_tester_development();

-- Closed issues must be explicitly reopened before forwarding or asking questions.
create or replace function public.guard_closed_tester_issue()
returns trigger language plpgsql set search_path = public as $$
declare outcome text;
begin
    if TG_TABLE_NAME = 'issues' then
        if NEW.handoff_status = 'forwarded' and NEW.tester_resolution <> 'open' then
            raise exception 'Reopen this issue before forwarding it'; end if;
    elsif NEW.status in ('draft', 'pending') then
        select i.tester_resolution into outcome from public.issues i join public.reports r on r.issue_id = i.id
        where r.id = NEW.report_id for update of i;
        if outcome <> 'open' then raise exception 'Reopen this issue before requesting more detail'; end if;
    end if;
    return NEW;
end;
$$;
drop trigger if exists issues_guard_closed_feedback on public.issues;
create trigger issues_guard_closed_feedback before update of handoff_status on public.issues
    for each row execute function public.guard_closed_tester_issue();
drop trigger if exists requests_guard_closed_feedback on public.detail_requests;
create trigger requests_guard_closed_feedback before insert or update of status on public.detail_requests
    for each row execute function public.guard_closed_tester_issue();

-- New or changed source evidence reopens a closed decision for human review.
create or replace function public.reopen_closed_feedback_on_source_change()
returns trigger language plpgsql set search_path = public as $$
declare old_parent uuid; new_parent uuid; parent uuid; outcome text;
begin
    if TG_OP <> 'INSERT' then old_parent := OLD.issue_id; end if;
    if TG_OP <> 'DELETE' then new_parent := NEW.issue_id; end if;
    if TG_OP = 'UPDATE' and
      (NEW.issue_id, NEW.answers, NEW.follow_up_question, NEW.follow_up_answer, NEW.occurred_at, NEW.detail_revision)
      is not distinct from
      (OLD.issue_id, OLD.answers, OLD.follow_up_question, OLD.follow_up_answer, OLD.occurred_at, OLD.detail_revision) then return NEW; end if;
    for parent in select distinct value from unnest(array[old_parent, new_parent]) as parents(value)
      where value is not null order by value loop
        select tester_resolution into outcome from public.issues where id = parent for update;
        if outcome <> 'open' then
            perform public.reopen_technical_handoff(parent);
            update public.issues set tester_resolution = 'open' where id = parent;
            insert into public.tester_updates(issue_id, status, message)
            values(parent, 'under_review', 'New or updated feedback has reopened this issue for manager review. Your original report has been kept. Thank you for helping us investigate.');
        end if;
    end loop;
    if TG_OP = 'DELETE' then return OLD; end if;
    return NEW;
end;
$$;
drop trigger if exists reports_reopen_closed_feedback on public.reports;
create trigger reports_reopen_closed_feedback after insert or update or delete on public.reports
    for each row execute function public.reopen_closed_feedback_on_source_change();

-- Give already forwarded issues their actual current status, once. Never populate
-- the tester panel with untouched reports merely awaiting their first review.
insert into public.tester_updates(issue_id, status, message)
select i.id, case when t.status = 'todo' then 'forwarded' else t.status end,
    public.tester_update_message(case when t.status = 'todo' then 'forwarded' else t.status end)
from public.issues i join public.developer_tickets t on t.issue_id = i.id and t.active
where i.handoff_status = 'forwarded' and i.tester_resolution = 'open'
and not exists(select 1 from public.tester_updates u where u.issue_id = i.id);

commit;
