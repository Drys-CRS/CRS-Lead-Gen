-- Create the main South African Tenders table
create table public.sa_tenders (
    id uuid default gen_random_uuid() primary key,
    created_at timestamp with time zone default timezone('utc'::text, now()) not null,
    tender_number text not null,
    department_name text not null,        -- e.g., SITA, Dept of Health, Eskom
    title text not null,
    description text,
    issue_date date,
    closing_date date,
    source_url text,
    status text default 'Open',           -- Open, Closed, Bid Submitted
    crs_alignment_score integer default 0,-- AI score: How well this fits your architecture/training capabilities
    compliance_requirements text,         -- e.g., B-BBEE Level 1-4, CSD registration required
    embedding vector(384)                 -- Ready for semantic AI matching
);

-- Index the embedding column for lightning-fast similarity searches
create index on public.sa_tenders using ivfflat (embedding vector_cosine_ops) with (lists = 100);