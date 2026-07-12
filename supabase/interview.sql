-- AI Human Interview Platform schema for Supabase/PostgreSQL.
-- Run this file in the Supabase SQL editor.

create extension if not exists pgcrypto;

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

-- This product replaces the earlier single-interview prototype schema.
-- Back up old data before running this reset in a database that contains production records.
drop table if exists public.candidate_scores cascade;
drop table if exists public.interview_reports cascade;
drop table if exists public.interview_transcripts cascade;
drop table if exists public.resumes cascade;
drop table if exists public.candidate_profiles cascade;
drop table if exists public.otp_verifications cascade;
drop table if exists public.interview_links cascade;
drop table if exists public.email_logs cascade;
drop table if exists public.activity_logs cascade;
drop table if exists public.interview_results cascade;
drop table if exists public.answers cascade;
drop table if exists public.questions cascade;
drop table if exists public.interviews cascade;
drop table if exists public.candidates cascade;
drop table if exists public.job_descriptions cascade;
drop table if exists public.recruiter_invitations cascade;
drop table if exists public.users cascade;

create table if not exists public.users (
    id text primary key default gen_random_uuid()::text,
    full_name text not null,
    email text not null unique,
    role text not null default 'recruiter' check (role in ('recruiter', 'admin')),
    password_hash text not null,
    session_token_hash text,
    created_at timestamptz not null default now(),
    last_login_at timestamptz
);

create table if not exists public.recruiter_invitations (
    id text primary key default gen_random_uuid()::text,
    manager_id text not null references public.users(id) on delete cascade,
    email text not null,
    full_name text not null,
    role text not null default 'recruiter' check (role in ('recruiter', 'manager')),
    token_hash text not null unique,
    status text not null default 'pending' check (status in ('pending', 'accepted', 'expired', 'revoked')),
    invited_user_id text references public.users(id) on delete set null,
    expires_at timestamptz not null,
    created_at timestamptz not null default now(),
    accepted_at timestamptz
);

create table if not exists public.job_descriptions (
    id text primary key default gen_random_uuid()::text,
    created_by text not null references public.users(id) on delete cascade,
    job_title text not null,
    company_name text not null,
    department text not null,
    experience_required text not null,
    location text not null,
    employment_type text not null,
    skills_required text not null,
    responsibilities text not null,
    full_job_description text not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.candidates (
    id text primary key default gen_random_uuid()::text,
    job_id text not null references public.job_descriptions(id) on delete cascade,
    created_by text not null references public.users(id) on delete cascade,
    full_name text not null,
    email text not null,
    mobile_number text not null,
    "current_role" text not null,
    current_company text,
    status text not null default 'Pending Interview' check (
        status in (
            'Pending Interview',
            'Interview Scheduled',
            'Interview Completed',
            'Shortlisted',
            'Rejected',
            'Moved To Next Round'
        )
    ),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.interview_links (
    id text primary key default gen_random_uuid()::text,
    candidate_id text not null references public.candidates(id) on delete cascade,
    job_id text not null references public.job_descriptions(id) on delete cascade,
    token_hash text not null unique,
    magic_link text not null,
    expires_at timestamptz not null,
    consumed_at timestamptz,
    otp_verified_at timestamptz,
    candidate_session_token_hash text unique,
    session_expires_at timestamptz,
    created_at timestamptz not null default now()
);

create table if not exists public.otp_verifications (
    id text primary key default gen_random_uuid()::text,
    candidate_id text not null references public.candidates(id) on delete cascade,
    interview_link_id text not null references public.interview_links(id) on delete cascade,
    otp_hash text not null,
    purpose text not null default 'interview_access',
    expires_at timestamptz not null,
    verified_at timestamptz,
    attempts integer not null default 0 check (attempts >= 0),
    created_at timestamptz not null default now()
);

create table if not exists public.candidate_profiles (
    id text primary key default gen_random_uuid()::text,
    candidate_id text not null unique references public.candidates(id) on delete cascade,
    current_ctc text not null,
    expected_ctc text not null,
    notice_period text not null,
    current_location text not null,
    linkedin_url text,
    portfolio_url text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.resumes (
    id text primary key default gen_random_uuid()::text,
    candidate_id text not null references public.candidates(id) on delete cascade,
    file_name text not null,
    content_type text not null,
    storage_bucket text not null default 'resumes',
    storage_path text not null,
    public_url text,
    parsed_text text,
    uploaded_at timestamptz not null default now()
);

create table if not exists public.interviews (
    id text primary key default gen_random_uuid()::text,
    candidate_id text not null references public.candidates(id) on delete cascade,
    job_id text not null references public.job_descriptions(id) on delete cascade,
    interview_link_id text references public.interview_links(id) on delete set null,
    status text not null default 'not_started' check (status in ('not_started', 'in_progress', 'completed', 'abandoned')),
    started_at timestamptz,
    completed_at timestamptz,
    duration_seconds integer check (duration_seconds is null or duration_seconds >= 0),
    max_questions integer not null default 8 check (max_questions > 0),
    current_question_index integer not null default 0 check (current_question_index >= 0),
    overall_score integer check (overall_score is null or overall_score between 0 and 100),
    created_at timestamptz not null default now()
);

create table if not exists public.interview_transcripts (
    id text primary key default gen_random_uuid()::text,
    interview_id text not null references public.interviews(id) on delete cascade,
    sequence_number integer not null check (sequence_number > 0),
    question_text text not null,
    answer_text text,
    category text,
    difficulty text check (difficulty is null or difficulty in ('easy', 'medium', 'hard')),
    follow_up_of text references public.interview_transcripts(id) on delete set null,
    asked_at timestamptz not null default now(),
    answered_at timestamptz,
    constraint uq_interview_transcript_sequence unique (interview_id, sequence_number)
);

create table if not exists public.interview_reports (
    id text primary key default gen_random_uuid()::text,
    interview_id text not null unique references public.interviews(id) on delete cascade,
    candidate_id text not null references public.candidates(id) on delete cascade,
    summary text not null,
    strengths text not null,
    weaknesses text not null,
    key_observations text not null,
    technical_assessment text not null,
    behavioral_assessment text not null,
    recommendation text not null check (recommendation in ('Strong Hire', 'Hire', 'Borderline', 'No Hire', 'Strong No Hire')),
    recommendation_reason text not null,
    raw_json text,
    created_at timestamptz not null default now()
);

create table if not exists public.candidate_scores (
    id text primary key default gen_random_uuid()::text,
    report_id text not null references public.interview_reports(id) on delete cascade,
    interview_id text not null references public.interviews(id) on delete cascade,
    candidate_id text not null references public.candidates(id) on delete cascade,
    category text not null check (
        category in (
            'Technical Skills',
            'Communication Skills',
            'Problem Solving',
            'Confidence',
            'Domain Knowledge',
            'Culture Fit'
        )
    ),
    score integer not null check (score between 1 and 10),
    reasoning text,
    constraint uq_candidate_score_category unique (report_id, category)
);

create table if not exists public.email_logs (
    id text primary key default gen_random_uuid()::text,
    candidate_id text references public.candidates(id) on delete set null,
    job_id text references public.job_descriptions(id) on delete set null,
    email_type text not null,
    recipient_email text not null,
    subject text not null,
    body text not null,
    status text not null check (status in ('sent', 'failed', 'logged')),
    error_message text,
    sent_at timestamptz,
    created_at timestamptz not null default now()
);

create table if not exists public.activity_logs (
    id text primary key default gen_random_uuid()::text,
    actor_user_id text references public.users(id) on delete set null,
    candidate_id text references public.candidates(id) on delete set null,
    job_id text references public.job_descriptions(id) on delete set null,
    action text not null,
    details text,
    created_at timestamptz not null default now()
);

create index if not exists idx_users_session_token_hash on public.users(session_token_hash);
create index if not exists idx_job_descriptions_created_by on public.job_descriptions(created_by);
create index if not exists idx_candidates_job on public.candidates(job_id);
create index if not exists idx_candidates_created_by on public.candidates(created_by);
create index if not exists idx_candidates_status on public.candidates(status);
create index if not exists idx_interview_links_candidate on public.interview_links(candidate_id);
create index if not exists idx_interview_links_job on public.interview_links(job_id);
create index if not exists idx_interview_links_token_hash on public.interview_links(token_hash);
create index if not exists idx_interview_links_session_hash on public.interview_links(candidate_session_token_hash);
create index if not exists idx_otp_link on public.otp_verifications(interview_link_id);
create index if not exists idx_profiles_candidate on public.candidate_profiles(candidate_id);
create index if not exists idx_resumes_candidate on public.resumes(candidate_id);
create index if not exists idx_interviews_candidate on public.interviews(candidate_id);
create index if not exists idx_interviews_job on public.interviews(job_id);
create index if not exists idx_transcripts_interview on public.interview_transcripts(interview_id);
create index if not exists idx_reports_interview on public.interview_reports(interview_id);
create index if not exists idx_scores_report on public.candidate_scores(report_id);
create index if not exists idx_email_logs_candidate on public.email_logs(candidate_id);
create index if not exists idx_activity_logs_job on public.activity_logs(job_id);

drop trigger if exists set_job_descriptions_updated_at on public.job_descriptions;
create trigger set_job_descriptions_updated_at
before update on public.job_descriptions
for each row execute function public.set_updated_at();

drop trigger if exists set_candidates_updated_at on public.candidates;
create trigger set_candidates_updated_at
before update on public.candidates
for each row execute function public.set_updated_at();

drop trigger if exists set_candidate_profiles_updated_at on public.candidate_profiles;
create trigger set_candidate_profiles_updated_at
before update on public.candidate_profiles
for each row execute function public.set_updated_at();

alter table public.users enable row level security;
alter table public.job_descriptions enable row level security;
alter table public.candidates enable row level security;
alter table public.interview_links enable row level security;
alter table public.otp_verifications enable row level security;
alter table public.candidate_profiles enable row level security;
alter table public.resumes enable row level security;
alter table public.interviews enable row level security;
alter table public.interview_transcripts enable row level security;
alter table public.interview_reports enable row level security;
alter table public.candidate_scores enable row level security;
alter table public.email_logs enable row level security;
alter table public.activity_logs enable row level security;

drop policy if exists users_service_role_all on public.users;
drop policy if exists users_self_read on public.users;
drop policy if exists users_self_update on public.users;
drop policy if exists job_service_role_all on public.job_descriptions;
drop policy if exists job_recruiter_all on public.job_descriptions;
drop policy if exists candidate_service_role_all on public.candidates;
drop policy if exists candidate_recruiter_all on public.candidates;
drop policy if exists link_service_role_all on public.interview_links;
drop policy if exists link_recruiter_read on public.interview_links;
drop policy if exists otp_service_role_all on public.otp_verifications;
drop policy if exists profile_service_role_all on public.candidate_profiles;
drop policy if exists profile_recruiter_read on public.candidate_profiles;
drop policy if exists resume_service_role_all on public.resumes;
drop policy if exists resume_recruiter_read on public.resumes;
drop policy if exists interview_service_role_all on public.interviews;
drop policy if exists interview_recruiter_read on public.interviews;
drop policy if exists transcript_service_role_all on public.interview_transcripts;
drop policy if exists transcript_recruiter_read on public.interview_transcripts;
drop policy if exists report_service_role_all on public.interview_reports;
drop policy if exists report_recruiter_read on public.interview_reports;
drop policy if exists score_service_role_all on public.candidate_scores;
drop policy if exists score_recruiter_read on public.candidate_scores;
drop policy if exists email_log_service_role_all on public.email_logs;
drop policy if exists email_log_recruiter_read on public.email_logs;
drop policy if exists activity_log_service_role_all on public.activity_logs;
drop policy if exists activity_log_recruiter_read on public.activity_logs;
drop policy if exists storage_service_role_all on storage.objects;
drop policy if exists storage_authenticated_read_owned on storage.objects;

create policy users_service_role_all on public.users for all to service_role using (true) with check (true);
create policy users_self_read on public.users for select to authenticated using (id = auth.uid()::text);
create policy users_self_update on public.users for update to authenticated using (id = auth.uid()::text) with check (id = auth.uid()::text);

create policy job_service_role_all on public.job_descriptions for all to service_role using (true) with check (true);
create policy job_recruiter_all on public.job_descriptions for all to authenticated
using (created_by = auth.uid()::text)
with check (created_by = auth.uid()::text);

create policy candidate_service_role_all on public.candidates for all to service_role using (true) with check (true);
create policy candidate_recruiter_all on public.candidates for all to authenticated
using (created_by = auth.uid()::text)
with check (created_by = auth.uid()::text);

create policy link_service_role_all on public.interview_links for all to service_role using (true) with check (true);
create policy link_recruiter_read on public.interview_links for select to authenticated
using (exists (
    select 1 from public.job_descriptions jd
    where jd.id = interview_links.job_id and jd.created_by = auth.uid()::text
));

create policy otp_service_role_all on public.otp_verifications for all to service_role using (true) with check (true);

create policy profile_service_role_all on public.candidate_profiles for all to service_role using (true) with check (true);
create policy profile_recruiter_read on public.candidate_profiles for select to authenticated
using (exists (
    select 1 from public.candidates c
    where c.id = candidate_profiles.candidate_id and c.created_by = auth.uid()::text
));

create policy resume_service_role_all on public.resumes for all to service_role using (true) with check (true);
create policy resume_recruiter_read on public.resumes for select to authenticated
using (exists (
    select 1 from public.candidates c
    where c.id = resumes.candidate_id and c.created_by = auth.uid()::text
));

create policy interview_service_role_all on public.interviews for all to service_role using (true) with check (true);
create policy interview_recruiter_read on public.interviews for select to authenticated
using (exists (
    select 1 from public.job_descriptions jd
    where jd.id = interviews.job_id and jd.created_by = auth.uid()::text
));

create policy transcript_service_role_all on public.interview_transcripts for all to service_role using (true) with check (true);
create policy transcript_recruiter_read on public.interview_transcripts for select to authenticated
using (exists (
    select 1
    from public.interviews i
    join public.job_descriptions jd on jd.id = i.job_id
    where i.id = interview_transcripts.interview_id and jd.created_by = auth.uid()::text
));

create policy report_service_role_all on public.interview_reports for all to service_role using (true) with check (true);
create policy report_recruiter_read on public.interview_reports for select to authenticated
using (exists (
    select 1
    from public.interviews i
    join public.job_descriptions jd on jd.id = i.job_id
    where i.id = interview_reports.interview_id and jd.created_by = auth.uid()::text
));

create policy score_service_role_all on public.candidate_scores for all to service_role using (true) with check (true);
create policy score_recruiter_read on public.candidate_scores for select to authenticated
using (exists (
    select 1
    from public.interviews i
    join public.job_descriptions jd on jd.id = i.job_id
    where i.id = candidate_scores.interview_id and jd.created_by = auth.uid()::text
));

create policy email_log_service_role_all on public.email_logs for all to service_role using (true) with check (true);
create policy email_log_recruiter_read on public.email_logs for select to authenticated
using (exists (
    select 1 from public.job_descriptions jd
    where jd.id = email_logs.job_id and jd.created_by = auth.uid()::text
));

create policy activity_log_service_role_all on public.activity_logs for all to service_role using (true) with check (true);
create policy activity_log_recruiter_read on public.activity_logs for select to authenticated
using (actor_user_id = auth.uid()::text or exists (
    select 1 from public.job_descriptions jd
    where jd.id = activity_logs.job_id and jd.created_by = auth.uid()::text
));

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values
    ('resumes', 'resumes', false, 10485760, array[
        'application/pdf',
        'application/msword',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    ]),
    ('recordings', 'recordings', false, 524288000, array['audio/mpeg', 'audio/webm', 'video/webm', 'video/mp4']),
    ('reports', 'reports', false, 52428800, array['application/pdf'])
on conflict (id) do update
set public = excluded.public,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;

create policy storage_service_role_all on storage.objects for all to service_role using (true) with check (true);
create policy storage_authenticated_read_owned on storage.objects for select to authenticated
using (bucket_id in ('resumes', 'recordings', 'reports'));
