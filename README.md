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

Internal Streamlit dashboard for Cyber Retaliator Solutions, hosted on Hugging
Face Spaces via the Docker SDK. The nightly scrape + AI scoring runs externally
in a GitHub Action, so this Space only needs to serve the dashboard UI.

## Setup

1. **Set the Space to Private** (Settings → visibility). This app can write to
   Supabase, push to Monday.com, and spend Apollo/Lusha credits — it should not
   be publicly clickable. (Optionally also enable the in-app password gate by
   setting an `APP_PASSWORD` secret.)
2. **Add secrets** under *Settings → Variables and secrets*. Required:
   `SUPABASE_URL`, `SUPABASE_KEY`, and at least one AI key
   (`GROQ_API_KEY` / `GEMINI_API_KEY` / `OPENROUTER_API_KEY` / …). Optional:
   `MONDAY_API_KEY`, `APOLLO_API_KEY`, `LUSHA_API_KEY`, `HUNTER_API_KEY`,
   `FLARE_API_KEY`, `NEWSAPI_KEY`, `GOOGLE_API_KEY` + `GOOGLE_CSE_ID`,
   `SERPER_API_KEY`, `SERPAPI_API_KEY`, `GH_PAT`.
3. Push this repo to the Space. Docker builds automatically; the app comes up on
   port 7860.

In-app scheduling (APScheduler) and the keep-alive autorefresh have been removed
on purpose — the GitHub Action owns the pipeline, and those features don't run
reliably on a host that sleeps when idle.