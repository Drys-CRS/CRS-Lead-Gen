-- Enable the pgvector extension for AI semantic matching
create extension if not exists vector;

-- Create the main Leads table
create table public.leads (
    id uuid default gen_random_uuid() primary key,
    created_at timestamp with time zone default timezone('utc'::text, now()) not null,
    company_name text not null,
    industry text,
    location text,
    source_url text,
    raw_signal_text text,     -- The job description or news article text scraped
    lead_score integer default 0,
    attack_angle text,        -- The AI-generated sales approach pitch
    contact_name text,
    contact_email text,
    contact_role text,
    status text default 'New', -- New, Contacted, Qualified, Rejected
    embedding vector(384)     -- 384 dimensions matches standard local embedding models
);

-- Index the embedding column for lightning-fast vector similarity searches
create index on public.leads using ivfflat (embedding vector_cosine_ops) with (lists = 100);