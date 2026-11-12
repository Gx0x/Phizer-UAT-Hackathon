-- Read-only checks after installing developer_handoff.sql.
select table_name from information_schema.tables
where table_schema = 'public' and table_name in ('technical_drafts', 'developer_tickets')
order by table_name;

select column_name, data_type from information_schema.columns
where table_schema = 'public' and table_name = 'issues'
and column_name in ('handoff_status', 'forwarded_at') order by column_name;

select trigger_name, event_object_table from information_schema.triggers
where trigger_schema = 'public'
and trigger_name in ('reports_reopen_handoff', 'detail_requests_guard_handoff')
group by trigger_name, event_object_table order by trigger_name;

select (select count(*) from public.issues) as issues,
       (select count(*) from public.reports) as reports,
       (select count(*) from public.technical_drafts) as technical_drafts,
       (select count(*) from public.developer_tickets) as developer_tickets;
