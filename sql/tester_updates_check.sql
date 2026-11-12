-- Read-only verification. Untouched review reports should not acquire updates.
select column_name, data_type from information_schema.columns
where table_schema = 'public' and table_name = 'issues' and column_name = 'tester_resolution';

select table_name from information_schema.tables
where table_schema = 'public' and table_name = 'tester_updates';

select status, count(*) as updates from public.tester_updates group by status order by status;

select (select count(*) from public.issues) as issues,
       (select count(*) from public.reports) as reports,
       (select count(*) from public.tester_updates) as updates;
