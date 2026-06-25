---
title: CRS Competitive Intelligence
emoji: 🛡️
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# CRS Competitive Intelligence Dashboard

Internal Streamlit dashboard for **Cyber Retaliator Solutions (CRS)** — a South African cybersecurity VAD and IBM / Red Hat / SUSE / CompTIA training partner. It surfaces African government and private-sector tenders, scores them as channel-partner opportunities, recommends reseller companies, and assists with B2B contact discovery and outreach.

The **nightly GitHub Action** owns scraping and AI scoring. This Space is read-mostly: it displays that data, provides on-demand AI analysis, and lets you push opportunities and leads to Monday.com CRM.

---

## Quick Start

1. **Make the Space private** — Settings → Visibility. The app writes to Supabase and spends Apollo credits; public access is a billing risk. Optionally add `APP_PASSWORD` to gate it behind a password prompt.
2. **Add secrets** — Settings → Variables and secrets. See the [Secrets Reference](#secrets-reference) below.
3. **Push to the Space** — Docker builds automatically; the app comes up on port 7860.

Local development:
```bash
pip install -r requirements.txt
# Create .streamlit/secrets.toml with the required keys, then:
streamlit run app/streamlit_app.py
```

---

## Navigation Pages

The sidebar has nine pages. Each page supports live filtering, detail cards, and Monday.com push buttons.

| Page | What it does |
|------|-------------|
| **✅ Lead Verification** | Dork LinkedIn profiles by solution and country, enrich via Apollo / Hunter, score and classify contacts, push verified leads to Monday Contacts board. |
| **🔥 Intent Leads** | Companies actively researching cybersecurity on Apollo (Bombora signals). Filter by intent topic, signal strength, and geography; drill into decision-maker contacts. |
| **📢 Opportunities** | Open tenders from Supabase — filter by country / score, run on-demand AI scoring (1–10 channel-partner fit), push to Monday Leads board or Outstanding Tickets. |
| **🤝 Partners** | Partner recommendations derived from awarded tender data. Run or view past analysis; push company cards to Monday Companies board. |
| **🔍 LinkedIn Dork** | Google CSE / SerpAPI dork for LinkedIn profiles filtered by CRS solution and target country; cache enrichment in Supabase `dork_leads`; push to Monday CRM. |
| **🛡️ Lead Intelligence** | Cyber events (ransomware, breaches, dark-web exposure) pulled from Flare; AI rates each affected company as a CRS lead and surfaces decision-maker contacts. |
| **💡 Weekly Leads** | Apollo-powered proactive pipeline: search by CRS solution and African sector, scored for portfolio fit against the full tech-stack map, auto-checked against Monday CRM. |
| **🎯 End-User Targets** | Find African companies by industry and headcount; CRS-portfolio score uses the Bombora tech-stack map; expands to decision-maker contacts via Apollo. |
| **👥 Decision Makers** | Centralised Apollo contact search queue — fed from Intent Leads, End-User Targets, and Lead Verification; all in one place to avoid duplicate credits. |

---

## Nightly Pipeline

A GitHub Action (`daily-ingest.yml`) runs at **01:00 UTC (03:00 SAST)** and:

1. Scrapes open tenders from OCDS publisher APIs (South Africa, Kenya, Nigeria, Tanzania, Zimbabwe, Uganda, and more). Optionally includes World Bank and UNDP non-OCDS sources.
2. AI-scores each new tender as a CRS channel-partner opportunity on a 1–10 scale with rationale, proposed solutions, and outreach angle.
3. Runs partner analysis over awarded tender data — identifies the top 12 ICT / security companies CRS should approach as channel partners, with urgency ranking and deal-size estimate.
4. Writes results to Supabase: `sa_tenders`, `awarded_tenders`, `tender_score_history`, `partner_recommendation_history`, `ai_usage_log`, `pipeline_runs`.

The pipeline can also be triggered manually from the Actions tab with overrideable parameters:

| Parameter | Default | Effect |
|-----------|---------|--------|
| `years_back` | `1` | How many years of OCDS history to fetch |
| `max_score` | `100` | Maximum tenders to AI-score per run |
| `include_non_ocds` | `true` | Include World Bank / UNDP sources |
| `skip_state_publishers` | `true` | Skip sub-national OCDS feeds (e.g. Nigeria states) |

The sidebar shows the last run status. Runs stuck beyond 2 hours are auto-expired in both the cleanup step and the app UI.

---

## AI Provider Cascade

Both the app and the nightly Action share the same cascade:

**Groq → Cerebras → OpenRouter → GitHub Models → NVIDIA → DeepSeek → Gemini → HF**

Rate-limited or failed calls fall through automatically. At least one key is required for AI features (tender scoring, partner analysis, contact classification).

Session-scoped daily call limits:

| Provider | Daily limit | Notes |
|----------|-------------|-------|
| Groq | 14,400 | Llama 3.3 70B — primary |
| Cerebras | 10,000 | GPT-OSS 120B / Zai-GLM |
| OpenRouter | 9,999 | Free-tier models (DeepSeek R1, Llama 4) |
| GitHub Models | 150 | Llama 3.3, GPT-4o-mini, Mistral Large, Phi-4 |
| NVIDIA | 40 | Llama 3.3 70B via NIM |
| DeepSeek | 500 | DeepSeek Chat |
| Gemini | 20 | Gemini 2.5 Flash |
| HF | 1,000 | Qwen 2.5 7B via Inference API |

Provider status is shown at the bottom of the sidebar (🟢 active / ⚪ key not configured).

---

## Secrets Reference

Set each secret as a Space environment variable (Settings → Variables and secrets). `make_secrets.py` converts them to `~/.streamlit/secrets.toml` at container startup — no code changes needed to add or remove keys.

### Required

| Secret | Purpose |
|--------|---------|
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_KEY` | Supabase service or anon key |

### AI providers (at least one required)

| Secret | Provider |
|--------|---------|
| `GROQ_API_KEY` | Groq (recommended primary) |
| `GEMINI_API_KEY` | Google Gemini 2.5 Flash |
| `CEREBRAS_API_KEY` | Cerebras Cloud |
| `OPENROUTER_API_KEY` | OpenRouter (free-tier models) |
| `GH_PAT` or `GITHUB_TOKEN` | GitHub Models (Azure-hosted) |
| `NVIDIA_API_KEY` | NVIDIA NIM |
| `DEEPSEEK_API_KEY` | DeepSeek |
| `HF_TOKEN` | Hugging Face Inference API (also used by the sync Action) |

### Integrations (optional)

| Secret | Purpose |
|--------|---------|
| `MONDAY_API_KEY` | Monday.com CRM — enables all push-to-Monday buttons |
| `APOLLO_API_KEY` | Apollo contact enrichment, Intent Leads, Weekly Leads, End-User Targets, Decision Makers pages |
| `HUNTER_API_KEY` | Hunter.io email finder (fallback after Apollo) |
| `FLARE_API_KEY` | Flare dark-web intel for Lead Intelligence page |
| `FLARE_TENANT_ID` | Required alongside `FLARE_API_KEY` |
| `NEWSAPI_KEY` | News API for Lead Intelligence page |
| `GOOGLE_API_KEY` + `GOOGLE_CSE_ID` | Google Custom Search for LinkedIn dorking |
| `SERPAPI_API_KEY` | SerpAPI — alternative dorking engine |
| `SERPER_API_KEY` | Serper.dev — alternative dorking engine |
| `APP_PASSWORD` | Optional in-app password gate |

To add a new secret without editing `make_secrets.py`, set `EXTRA_SECRET_KEYS="MY_KEY1,MY_KEY2"` in the Space. For permanent additions, append the name to `ALLOWED_KEYS` in `make_secrets.py`.

---

## Supabase Tables

| Table | Contents |
|-------|---------|
| `sa_tenders` | Open tenders with `status`, `country`, `ai_score`, `ai_rationale`, `is_irrelevant`, `contact_*` fields |
| `awarded_tenders` | Awarded history: `winning_bidder`, `award_value`, `country` |
| `tender_score_history` | Historical AI scoring log per tender |
| `partner_recommendation_history` | Past partner analysis runs with full JSON output |
| `lead_verification_log` | Verified / quarantined contacts from Lead Verification page |
| `dork_leads` | LinkedIn dork results with cached Apollo enrichment (keyed by `linkedin_url`) |
| `attack_signal_history` | Flare cyber-event signals |
| `ai_usage_log` | Per-provider call counts (`usage_date`, `provider`, `count`) |
| `pipeline_runs` | Run history: `run_at`, `status`, `tenders_scraped`, `tenders_scored`, `error_log` |

---

## Monday.com Integration

Board IDs and column IDs are verified and hardcoded in `app/monday_client.py`. Reuse its exported functions — do not re-derive IDs.

| Board | ID | Used for |
|-------|----|---------|
| Leads 2.0 | 7677528134 | Open tenders, dork leads, weekly leads |
| Companies | 3172010618 | Partner recommendations |
| Outstanding Tickets | 5657844182 | High-score opportunity tickets |
| Contacts | 3664655500 | Verified contacts from lead enrichment |

Key functions in `monday_client.py`:

```
push_tender_to_monday(row)       → Leads 2.0
push_partner_to_companies(rec)   → Companies
sync_lead_to_monday(contact)     → Leads 2.0
push_to_contacts_board(contact)  → Contacts
lookup_monday_crm(contact)       → checks all CRM boards
lookup_monday_company(name)      → checks Companies board
```

---

## Deploy Flow

```
GitHub push to main
  └─ sync-to-hf.yml ──► HF Space: DrystanGovender/crs-competitive-intelligence
                              └─ Docker build from root Dockerfile
                                    └─ entrypoint.sh
                                          ├─ make_secrets.py  (env → secrets.toml)
                                          └─ streamlit run app/streamlit_app.py :7860

GitHub cron 01:00 UTC
  └─ daily-ingest.yml ──► ubuntu runner
                              └─ python app/Daily_ingest.py
                                    └─ app/ingest_core.py (scrape + score + partner)
                                          └─ writes Supabase tables
```

---

## Hard Conventions

- `*.sh` files must use **LF** line endings — enforced by `.gitattributes` (`*.sh text eol=lf`). CRLF breaks the container entrypoint.
- Secrets via `st.secrets.get(...)` only — never hardcoded, never committed.
- **No APScheduler, no `streamlit-autorefresh`** — the GitHub Action owns scheduling.
- Repo layout: `Dockerfile`, `entrypoint.sh`, `make_secrets.py`, `requirements.txt` at the **repo root**; all app code under `app/`.
- This `README.md` HF front-matter (`--- … ---`) must be the **first lines** of the file.
- New Python dependencies: pin in `requirements.txt` (app) and/or `requirements-ingest.txt` (Action only).
- Do not add scrapers or schedulers to `app/streamlit_app.py` — that file is UI-only.
