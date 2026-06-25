# CRS Lead Gen — Technical Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│  GitHub: Drys-CRS/CRS-Lead-Gen                                      │
│                                                                     │
│  app/streamlit_app.py     ← UI only, no scrapers, no schedulers     │
│  app/monday_client.py     ← Monday.com GraphQL wrapper              │
│  app/ingest_core.py       ← Streamlit-free scrape + AI pipeline     │
│  app/Daily_ingest.py      ← GitHub Action entry point               │
│  scripts/enrich_monday_companies.py  ← one-off enrichment utility   │
│                                                                     │
│  .github/workflows/                                                 │
│    daily-ingest.yml   ← runs ingest_core nightly (01:00 UTC)        │
│    sync-to-hf.yml     ← pushes main to HF Space on every push       │
└────────────────────────┬────────────────────────────────────────────┘
                         │ push to main
                         ▼
┌─────────────────────────────────────────────────────────────────────┐
│  HF Space: DrystanGovender/crs-competitive-intelligence             │
│                                                                     │
│  Dockerfile (Python 3.11-slim, UID 1000)                            │
│  entrypoint.sh                                                      │
│    1. python make_secrets.py  →  ~/.streamlit/secrets.toml          │
│    2. streamlit run app/streamlit_app.py --server.port=7860         │
└────────────────────────┬────────────────────────────────────────────┘
                         │ reads/writes
                         ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Supabase (Postgres)                                                │
│  sa_tenders · awarded_tenders · partner_recommendation_history      │
│  lead_verification_log · dork_leads · attack_signal_history         │
│  tender_score_history · ai_usage_log · pipeline_runs                │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Key Files

### `app/streamlit_app.py`

5,500+ line Streamlit app. UI-only — no schedulers, no scrapers.

**Structure:**
1. Imports + graceful fallbacks (`monday_client`, `streamlit-extras`)
2. Global CSS (card hover effects, metric styling, button gradients)
3. `CRS_PROFILE` string — injected into all AI prompts
4. Supabase client (`@st.cache_resource`)
5. AI provider initialisation (one `@st.cache_resource` function per provider)
6. AI cascade (`_call_ai`) + per-session usage tracking
7. `ai_score_tender` / `ai_analyse_partners` — the two main AI task functions
8. Supabase data loaders (`@st.cache_data(ttl=300)`)
9. Dork / enrichment helpers (`_dork_search`, `_apollo_*`, `_hunter_find`)
10. CRS scoring engine (`_score_org_for_crs`) — deterministic tech-stack scoring
11. Sidebar (navigation buttons, Apollo credit meter, pipeline status)
12. Nine page sections (one `if _page == "..."` block each)

**Session state keys (key ones):**
- `_active_page` — current navigation page
- `dm_queue` — list of queued Decision Maker searches
- `ai_usage` — `{provider: call_count}` for daily limit tracking
- `_revealed_*` — per-contact reveal state in Lead Verification

### `app/monday_client.py`

All Monday.com GraphQL interaction. Board and column IDs are verified constants; don't derive them elsewhere.

Key functions:

| Function | Destination | Notes |
|----------|-------------|-------|
| `push_tender_to_monday(row)` | Leads 2.0 board | Maps tender fields to column IDs |
| `push_partner_to_companies(rec)` | Companies board | Partner recommendation cards |
| `sync_lead_to_monday(contact)` | Leads 2.0 board | LinkedIn dork / weekly lead |
| `push_to_contacts_board(contact)` | Contacts board | Verified contacts |
| `lookup_monday_crm(contact)` | All boards | Checks if contact already exists |
| `lookup_monday_company(name)` | Companies board | Checks if company already on CRM |

`SOLUTION_MAP` maps tender/solution keyword strings to CRS divisions and vendor column values. `REGION_MAP` / `LOCATION_MAP` map country names to Monday.com select values.

### `app/ingest_core.py`

Streamlit-free pipeline module. Can be imported by the GitHub Action or run locally.

```python
import ingest_core as core
core.init_supabase()          # sets global `supabase` client from env vars
core.init_ai(log=print)       # initialises all provider clients
core.run_all(                 # full pipeline
    years_back=1,
    max_score=100,
    do_partner=True,
    ...
)
```

Reads secrets from environment variables (not `st.secrets`). Writes the same Supabase tables the app reads.

AI cascade priority matches the app. Logging via a `log` callable (defaults to `print`).

### `app/Daily_ingest.py`

Thin wrapper called by the GitHub Action. Reads tunable env vars (`YEARS_BACK`, `MAX_SCORE`, `SCORE_TIME_BUDGET`, `DO_PARTNER`, `INCLUDE_NON_OCDS`, `SKIP_STATE_PUBLISHERS`, `RUN_TRIGGER`) and calls `ingest_core.run_all(...)`. Returns exit code 0/1.

### `make_secrets.py`

Runs once at container startup. Reads `ALLOWED_KEYS` + optional `EXTRA_SECRET_KEYS` from the environment and writes a valid `~/.streamlit/secrets.toml`. Handles TOML escaping correctly via `json.dumps` (handles `\n`, `"`, etc.).

---

## AI Scoring

### Tender Scoring (`ai_score_tender`)

Sends a prompt to the cascade containing the tender's title, department, country, description, category, and closing date, plus the full `CRS_PROFILE` string. Returns JSON:

```json
{
  "score": 8,
  "rationale": "...",
  "partner_type": "System Integrator|MSP|VAR|Training Provider|Consulting/Advisory",
  "proposed_solutions": ["VECTRA AI", "vRx"],
  "outreach_angle": "..."
}
```

Score guide embedded in the prompt: 9-10 = urgent partner activation, 1-2 = not relevant.

### Partner Analysis (`ai_analyse_partners`)

Aggregates awarded tender data by winning company, sends the top 40 companies (pipe-delimited) to the cascade, and asks for the 12 best channel partner targets. Returns a JSON array with `urgency`, `estimated_deal_size`, `proposed_solutions`, `outreach_angle`, etc.

### CRS Portfolio Scoring (`_score_org_for_crs`)

Deterministic scoring for Apollo company results (no AI call, no credit cost):

| Factor | Points |
|--------|--------|
| Sector fit — strong | 28 |
| Sector fit — medium | 14 |
| Geography — Africa | 18 |
| Geography — non-Africa | 6 |
| Company size 50–500 (sweet spot) | 14 |
| Company size 501–5,000 | 10 |
| Company size > 5,000 | 6 |
| Company size 10–49 | 8 |
| Tech-stack signals (additive, capped) | 0–30 |

Tech-stack signals come from `_TECH_OPP` — a map of 40+ technology names (CrowdStrike, Splunk, Qualys, GitHub, AWS, etc.) to CRS solution opportunities with points and opportunity text. This drives the "Why CRS" angles shown on each company card.

---

## Contact Enrichment Pipeline

Used across Lead Verification, LinkedIn Dork, Intent Leads, and Decision Makers pages.

```
LinkedIn profile URL
    └─ Apollo people/match  →  work_email, personal_emails, phone, company info
    └─ Hunter email-finder   →  email + confidence score (if domain available)
    └─ Pattern guess         →  firstname.lastname@domain (unverified, shown as candidates)
    └─ Confidence score      →  0–100 based on sources and corroboration
```

Apollo `people/match` endpoint:
- Costs **1 export credit** per matched person.
- `reveal_personal_emails: true` exposes personal (e.g. Gmail) addresses.
- Phone reveal is async (webhook-based) so we extract whatever phone fields Apollo returns inline.

`_apollo_reveal_and_save(apollo_id)` — the "Reveal All" function:
1. Calls `people/match` with the Apollo ID (1 credit).
2. Saves the contact to the Apollo CRM list `"CRS Revealed"` via `POST /contacts` (no extra credit).

Apollo credit balance is shown in the sidebar (cached 5 min). Labels: lead credits and dial credits.

---

## Contact Normalisation (`_norm_apollo`)

All Apollo person dicts (from search or enrichment) are flattened through `_norm_apollo` before display or Supabase storage:

```python
{
  "id", "name", "title",
  "email", "work_email", "personal_email", "email_status", "has_email",
  "phone", "has_phone",
  "linkedin", "twitter",
  "company", "company_phone", "company_linkedin",
  "domain", "description", "employees", "revenue",
  "industry", "city", "country", "founded_year",
  "keywords", "tech_count", "tech_names",
  "source"
}
```

`_norm_org` does the same for Apollo organisation dicts.

---

## Supabase Data Loaders

All loaders use `@st.cache_data(ttl=300)` (5-minute cache) except `_load_dork_leads_bulk` (30s). A `_sb_execute` wrapper retries once on HTTP/2 connection drops.

| Function | Table | Filter |
|----------|-------|--------|
| `_load_tenders()` | `sa_tenders` | `is_irrelevant != true`, ordered by `closing_date` |
| `_load_awarded()` | `awarded_tenders` | ordered by `created_at` desc |
| `_load_partner_history()` | `partner_recommendation_history` | ordered by `run_at` desc |
| `_load_lead_verifications()` | `lead_verification_log` | ordered by `run_at` desc |
| `_load_dork_leads_bulk(urls)` | `dork_leads` | IN on `linkedin_url` |

Country and score filters are applied in-memory after load (sidebar globals `country_filter` and `min_score`).

---

## LinkedIn Dorking

`_dork_search(query, num, start)` supports two backends:

- **Google Custom Search API** (`GOOGLE_API_KEY` + `GOOGLE_CSE_ID`) — 1-based start index, max 10 per page.
- **SerpAPI** (`SERPAPI_API_KEY`) — 0-based start index.

Results are filtered to `linkedin.com/in/` URLs only. `_parse_li_result` extracts name, job title, and company from the Google result title string using regex (handles "Name — Title at Company | LinkedIn" format).

Dork queries are constructed per-solution from `_DORK_SOLUTIONS` and per-country from the target country list.

---

## Deployment Conventions

- `*.sh` files must be **LF** only. `.gitattributes` enforces `*.sh text eol=lf`. A CRLF entrypoint.sh will cause `\r: command not found` inside the container.
- The HF Space runs as **UID 1000**. The Dockerfile creates `user` with `uid=1000` so `$HOME` is writable (Streamlit writes `~/.streamlit/`).
- Streamlit is launched with `--server.enableCORS=false --server.enableXsrfProtection=false` because the Space runs inside an iframe proxy.
- The `sync-to-hf.yml` Action uses `upload_folder` (not a git push) to avoid force-push to HF's git. Files excluded: `.git`, `.github`, `.venv`, `__pycache__`, `*.pyc`, `.claudeignore`, `.clauderules`.
- `daily-ingest.yml` runs with `concurrency: group: daily-ingest, cancel-in-progress: true` — a manual trigger immediately cancels a stuck scheduled run.
- The `requirements-ingest.txt` is a subset of `requirements.txt` — excludes Streamlit and UI extras, adds `pdfminer.six` and `langdetect` for the pipeline.

---

## Adding a New Navigation Page

1. Add the page label to `_NAV_PAGES` in `streamlit_app.py` (line ~1580).
2. Add a corresponding `if _page == "your label":` block at the bottom of the file.
3. Use `_colored_header(label=..., description=..., color_name=...)` at the top of the block for consistent styling.
4. If the page uses a new secret, add it to `ALLOWED_KEYS` in `make_secrets.py`.
5. If the page needs Supabase data, add a `@st.cache_data(ttl=300)` loader function near the other loaders.
