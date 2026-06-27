# CRS Lead Gen — Project Context (v2)

This file orients Claude Code. Read it before making changes.

## What this is
An internal competitive-intelligence + lead-generation dashboard for **Cyber
Retaliator Solutions (CRS)**, a South African cybersecurity value-added
distributor and IBM/Red Hat/SUSE/CompTIA training partner. It surfaces African
government + private-sector tenders, scores them as channel-partner
opportunities, recommends reseller/partner companies, and verifies B2B contacts.

## Architecture (important)
- **UI:** Streamlit app, hosted on **Hugging Face Spaces** via the **Docker SDK**
  (not Streamlit Community Cloud). Keep it lean and read-mostly.
- **Backend:** Supabase (Postgres). The app reads/writes tables; it does NOT scrape.
- **Heavy pipeline runs externally:** a nightly **GitHub Action**
  (`scripts/daily_ingest.py` → `app/ingest_core.py`) does scraping + AI scoring +
  partner analysis and writes the Supabase tables. The app just displays/acts on
  that data. **Do not add scrapers or schedulers back into the app.**
- **Reused backend modules (keep, don't rewrite):**
  - `app/monday_client.py` — all Monday.com GraphQL pushes (board/column IDs verified)
  - `app/ingest_core.py` — streamlit-free scrape + AI cascade used by the Action

## Deploy flow
1. Commit to `main` on GitHub (`Drys-CRS/CRS-Lead-Gen`).
2. The `sync-to-hf.yml` Action force-pushes the repo to the HF Space
   `DrystanGovender/crs-competitive-intelligence`.
3. HF rebuilds from the root `Dockerfile`; `entrypoint.sh` runs `make_secrets.py`
   (turns the Space's env-var Secrets into `~/.streamlit/secrets.toml`) then
   launches Streamlit on port 7860.

## Hard conventions (these caused real breakage — respect them)
- **Repo layout:** `Dockerfile`, `entrypoint.sh`, `make_secrets.py`,
  `requirements.txt`, `README.md`, `.dockerignore` live at the **repo root**.
  App code lives under `app/`. The `README.md` HF front-matter (`--- … ---`)
  must be the FIRST lines of the file.
- **Line endings:** `*.sh` files MUST be **LF**, never CRLF (a `.gitattributes`
  with `*.sh text eol=lf` enforces this). CRLF breaks the container entrypoint.
- **Secrets:** the app reads config via `st.secrets.get(...)`. On HF these arrive
  as env vars and are bridged by `make_secrets.py`. Never hardcode keys; never
  commit `.streamlit/secrets.toml` or `.env`. If a new secret is needed, add its
  name to `ALLOWED_KEYS` in `make_secrets.py`.
- **No APScheduler, no streamlit-autorefresh** — the Action owns scheduling.
- When adding a Python dependency, pin it in `requirements.txt`.
- Test locally with `streamlit run app/streamlit_app.py` before pushing.
- Commit in small, described steps.

## Supabase tables (read these names before querying)
- `sa_tenders` — open tenders (status, country, ai_score, ai_rationale, is_irrelevant, contact_*)
- `awarded_tenders` — awarded history (winning_bidder, award_value, country)
- `tender_score_history`, `partner_recommendation_history`, `attack_signal_history`
- `lead_verification_log` — verified/quarantined contacts
- `ai_usage_log` (usage_date, provider, count), `pipeline_runs` (run history)

## Monday.com (IDs in monday_client.py)
Leads 2.0 `7677528134`, Companies `3172010618`, Outstanding Tickets `5657844182`,
Contacts `3664655500`. Board/column IDs are already mapped in `monday_client.py` —
reuse its functions (`push_tender_to_monday`, `sync_lead_to_monday`,
`push_partner_to_companies`, `lookup_monday_crm`, etc.), don't re-derive IDs.

## v2 goal: LEANER
The v1 app had 8 tabs and ~3,000 lines. v2 trims to the core, since the Action
now does the heavy lifting. **Proposed** tab set (confirm with the user before
building):
1. **Overview** — counts + recent high-score tenders (read-only from Supabase).
2. **Opportunities** — open tenders: filter, detail view, push to Monday.
3. **Partners** — awarded → partner recommendations (read history / re-run analysis).
4. **Lead Verification** — dork/DB/breach → enrich (Apollo/Hunter/pattern) → score →
   classify authority → push verified leads to Monday.

Likely dropped or merged from v1: AI Tender Parser, AI Discovery (private sector),
Lead Intelligence (news/JSE), and the heavy Pipeline & Health tab (the Action has
its own logs; keep only a small read-only status panel if useful).

## Build order suggestion
Scaffold the lean `app/streamlit_app.py` (config + sidebar + the 4 tabs as stubs
reading Supabase), wire `monday_client.py` actions, then flesh out each tab. Keep
the existing deploy files untouched.

---

## Development Agent Directives

These are standing instructions for how to approach every change to this codebase.

### 1. Read before writing
- **Always** read the relevant section of `app/streamlit_app.py` (6 000+ lines) before
  editing it. Use `grep`/`glob` to locate the exact block; do not guess line numbers.
- Before adding a new helper, search for an existing one that does the same thing
  (`_norm_apollo`, `_call_ai`, `_sb_execute`, `_copy_block`, `_colored_header`, etc.).
- Check `app/monday_client.py` before touching any CRM push — board/column IDs are
  already mapped; never re-derive them.
- Understand where a new feature fits in the session-state model
  (`_active_page`, `dm_queue`, `lk_results`, `agent_leads`) before touching state keys.

### 2. Code quality rules
- **DRY**: if the same pattern appears more than twice, extract it.
  Key reusable patterns: `_render_agent_card`, `_copy_block`, `_tab_cards`.
- **No dead imports**: if a library is used conditionally, guard with `try/except`.
- **Error boundaries on every external call**: Supabase queries, Apollo API calls,
  AI calls, and Monday.com pushes must each be wrapped in `try/except` with a
  user-visible `st.error(...)` or `st.toast(...)`.
- **Cache correctly**: Supabase loaders use `@st.cache_data(ttl=300)`. Mutation
  functions (insert/update) must call `loader.clear()` after success.
- **Session state keys must be unique and predictable**. Prefix widget keys with
  the page abbreviation (`lk_`, `dm_`, `ia_`, `opp_`, etc.) to avoid collisions.
- **No hardcoded secrets** — always `st.secrets.get(...)` or `os.getenv(...)`.

### 3. Proactive quality checks
When building or modifying a feature:
- Verify the happy path *and* the empty-state (no data / no API key / API error).
- Add a human-readable placeholder/caption when a Supabase table is empty or a
  required key is missing — never let the UI silently render nothing.
- For any new Supabase table, document its required columns as a `st.caption()`
  help text (schema hint) so the user knows what to create if the table is absent.
- Prefer `st.container(border=True)` over raw markdown for card-style layouts.
- When a push button succeeds, immediately update the underlying session-state list
  so `st.rerun()` shows the new state without a double API call.

### 4. Commit discipline
- Commits require **explicit user request** — never auto-commit or auto-push.
- Each commit must cover one logical change with a descriptive message (what + why).
- Run a syntax check (`python -c "import ast; ast.parse(open('app/streamlit_app.py').read())"`)
  before every commit.
- Do NOT use `git add .` — stage specific files to avoid accidentally committing
  `.env`, `secrets.toml`, or large binaries.

### 5. Pipeline / agent files (separate concern from UI)
- `app/tender_agent.py` and `app/ingest_core.py` are headless pipeline modules.
  They must never import Streamlit.
- New pipeline phases go into `app/tender_agent.py` (web-search-driven agent) or
  `app/ingest_core.py` (OCDS API scraping), not into `streamlit_app.py`.
- New search queries go into `_TENDER_QUERIES`, `_ATTACK_QUERIES`, or
  `_PARTNER_QUERIES` in `tender_agent.py`.
- When adding a new secret used by the pipeline, add it to **both**:
  - `ALLOWED_KEYS` in `make_secrets.py` (for the HF Space)
  - The `env:` block in `.github/workflows/agent-tender.yml`
