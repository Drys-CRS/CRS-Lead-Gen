-- Add award and winner tracking features
alter table public.sa_tenders 
add column award_status text default 'In Evaluation' not null, -- In Evaluation, Awarded, Cancelled
add column winning_bidder text,                              -- Name of the successful company
add column award_value numeric;                              -- Contract value in ZAR