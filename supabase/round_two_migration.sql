alter table public.interview_links add column if not exists round_number integer not null default 1;
alter table public.interviews add column if not exists round_number integer not null default 1;
alter table public.interview_transcripts add column if not exists response_mode text not null default 'voice';

create table if not exists public.proctor_events (
    id text primary key default gen_random_uuid()::text,
    interview_id text not null references public.interviews(id) on delete cascade,
    candidate_id text not null references public.candidates(id) on delete cascade,
    event_type text not null,
    severity text not null default 'warning',
    details text,
    occurred_at timestamptz not null default now()
);
create index if not exists idx_proctor_events_interview on public.proctor_events(interview_id);
create index if not exists idx_proctor_events_candidate on public.proctor_events(candidate_id);
