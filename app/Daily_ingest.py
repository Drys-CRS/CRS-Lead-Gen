#!/usr/bin/env python3
"""
scripts/daily_ingest.py — headless entrypoint for the daily GitHub Action.

Reads config + secrets from environment variables, runs the full
scrape → AI-score → partner-analysis pipeline via ingest_core, and exits
non-zero if the run fails (so the Action shows red).

Local test:
    export SUPABASE_URL=... SUPABASE_KEY=... GROQ_API_KEY=...   # etc.
    python scripts/daily_ingest.py
"""

import os
import sys

# Make app/ importable regardless of where the Action invokes us from.
_HERE = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.join(os.path.dirname(_HERE), "app")
if _APP not in sys.path:
    sys.path.insert(0, _APP)

import ingest_core as core  # noqa: E402


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def _bool_env(name: str, default: bool) -> bool:
    v = os.environ.get(name, "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    return default


def main() -> int:
    log = print  # GitHub Actions captures stdout line-by-line

    years_back          = _int_env("YEARS_BACK", 1)
    max_score           = _int_env("MAX_SCORE", 100)
    score_budget        = _int_env("SCORE_TIME_BUDGET", 1800)
    do_partner          = _bool_env("DO_PARTNER", True)
    include_non_ocds    = _bool_env("INCLUDE_NON_OCDS", True)
    skip_state_pub      = _bool_env("SKIP_STATE_PUBLISHERS", True)
    trigger             = os.environ.get("RUN_TRIGGER", "github_action")

    # 1. Supabase (required)
    try:
        core.init_supabase()
    except Exception as e:
        log(f"FATAL: Supabase init failed: {e}")
        return 2

    # 2. AI providers (at least one expected; scoring is skipped gracefully if none)
    available = core.init_ai(log=lambda m: log(m))
    if available:
        log(f"AI providers online: {', '.join(available)}")
    else:
        log("WARNING: no AI providers configured — scraping only, no scoring.")

    # 3. Run
    result = core.run_all(
        years_back=years_back,
        max_score=max_score,
        do_partner=do_partner,
        score_time_budget_s=score_budget,
        include_non_ocds=include_non_ocds,
        skip_state_publishers=skip_state_pub,
        trigger=trigger,
        log=log,
    )

    return 0 if result.get("status") == "success" else 1


if __name__ == "__main__":
    sys.exit(main())