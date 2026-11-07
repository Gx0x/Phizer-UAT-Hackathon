-- Vector support for report embeddings and similarity search.
create extension if not exists vector with schema extensions;

create table if not exists public.profiles (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    role text not null check (role in ('tester', 'manager')),
    created_at timestamptz not null default now()
);

create table if not exists public.issues (
    id uuid primary key default gen_random_uuid(),
    title text not null,
    category text not null check (
        category in ('bug', 'awkward', 'suggestion', 'extra')
    ),
    status text not null default 'new',
    ai_priority text check (
        ai_priority is null or ai_priority in ('low', 'medium', 'high', 'critical')
    ),
    ai_severity text check (
        ai_severity is null or ai_severity in ('low', 'medium', 'high', 'critical')
    ),
    ai_reasoning text,
    ai_confidence double precision check (
        ai_confidence is null or ai_confidence between 0 and 1
    ),
    final_priority text check (
        final_priority is null or final_priority in ('low', 'medium', 'high', 'critical')
    ),
    final_severity text check (
        final_severity is null or final_severity in ('low', 'medium', 'high', 'critical')
    ),
    report_count integer not null default 1 check (report_count >= 0),
    upvote_count integer not null default 0 check (upvote_count >= 0),
    created_at timestamptz not null default now()
);

create table if not exists public.reports (
    id uuid primary key default gen_random_uuid(),
    issue_id uuid references public.issues(id) on delete set null,
    tester_id uuid references public.profiles(id) on delete set null,
    category text not null check (
        category in ('bug', 'awkward', 'suggestion', 'extra')
    ),
    answers jsonb not null default '{}'::jsonb,
    follow_up_question text,
    follow_up_answer text,
    -- 1024 dimensions matches the Voyage voyage-3 embedding model.
    embedding extensions.vector(1024),
    created_at timestamptz not null default now()
);

create table if not exists public.attachments (
    id uuid primary key default gen_random_uuid(),
    report_id uuid not null references public.reports(id) on delete cascade,
    type text not null,
    image_url text,
    ai_description text,
    confirmed_description text,
    confidence double precision check (
        confidence is null or confidence between 0 and 1
    ),
    tester_confirmed boolean not null default false,
    created_at timestamptz not null default now()
);

create table if not exists public.duplicate_matches (
    id uuid primary key default gen_random_uuid(),
    report_id uuid not null references public.reports(id) on delete cascade,
    matched_issue_id uuid not null references public.issues(id) on delete cascade,
    confidence double precision not null check (confidence between 0 and 1),
    reasoning text,
    manager_decision text not null default 'pending' check (
        manager_decision in ('pending', 'confirmed', 'rejected')
    ),
    created_at timestamptz not null default now()
);

create table if not exists public.log_matches (
    id uuid primary key default gen_random_uuid(),
    issue_id uuid not null references public.issues(id) on delete cascade,
    confidence double precision not null check (confidence between 0 and 1),
    matched_lines jsonb not null default '[]'::jsonb,
    reasoning text,
    created_at timestamptz not null default now()
);

create table if not exists public.manager_actions (
    id uuid primary key default gen_random_uuid(),
    issue_id uuid not null references public.issues(id) on delete cascade,
    manager_id uuid references public.profiles(id) on delete set null,
    action text not null,
    previous_value jsonb,
    new_value jsonb,
    reason text not null,
    created_at timestamptz not null default now()
);

create table if not exists public.notifications (
    id uuid primary key default gen_random_uuid(),
    tester_id uuid references public.profiles(id) on delete set null,
    issue_id uuid references public.issues(id) on delete set null,
    status text not null,
    message text not null,
    sent_at timestamptz not null default now()
);

-- Supports cosine similarity searches as report embeddings are added.
create index if not exists reports_embedding_cosine_idx
    on public.reports using hnsw (embedding extensions.vector_cosine_ops);

-- The connection test calls this function to confirm pgvector is working.
create or replace function public.pgvector_similarity_test()
returns double precision
language sql
immutable
as $$
    select 1 - (
        '[1,0,0]'::extensions.vector
        <=> '[1,0,0]'::extensions.vector
    );
$$;

-- This prototype accesses Supabase through the server-side service key.
-- RLS prevents browser/anon access; service-role requests bypass RLS.
alter table public.profiles enable row level security;
alter table public.issues enable row level security;
alter table public.reports enable row level security;
alter table public.attachments enable row level security;
alter table public.duplicate_matches enable row level security;
alter table public.log_matches enable row level security;
alter table public.manager_actions enable row level security;
alter table public.notifications enable row level security;