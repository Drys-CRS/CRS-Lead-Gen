"""
modal_pipeline.py — Modal.com scheduled runner for the CRS daily ingest pipeline.

Deploy:  modal deploy modal_pipeline.py
Run now: modal run modal_pipeline.py

Secrets: create a secret group named "crs-ingest" in the Modal dashboard
         containing all keys listed in requirements-ingest.txt comments.
"""

import os
import sys
import modal

# ---------------------------------------------------------------------------
# Image — mirrors requirements-ingest.txt exactly
# ---------------------------------------------------------------------------
image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "supabase==2.15.3",
        "requests==2.34.2",
        "beautifulsoup4==4.15.0",
        "google-genai==1.20.0",
        "groq==1.4.0",
        "cerebras-cloud-sdk==1.67.0",
        "openai==2.41.1",
        "httpx==0.28.1",
        "huggingface_hub==0.30.2",
        "pdfminer.six==20231228",
        "langdetect==1.0.9",
    )
    .add_local_file("app/ingest_core.py", "/app/ingest_core.py")
    .add_local_file("app/Daily_ingest.py", "/app/Daily_ingest.py")
)

app = modal.App("crs-ingest", image=image)

secrets = modal.Secret.from_name("crs-ingest")


# ---------------------------------------------------------------------------
# Core function — runs the full pipeline
# ---------------------------------------------------------------------------
@app.function(
    secrets=[secrets],
    timeout=3600,       # 1-hour hard cap (pipeline usually finishes in ~30 min)
    cpu=2,
    memory=1024,
)
def run_pipeline(
    years_back: int = 1,
    max_score: int = 100,
    include_non_ocds: bool = True,
    skip_state_publishers: bool = True,
    trigger: str = "modal_scheduled",
):
    sys.path.insert(0, "/app")
    import ingest_core as core

    def log(msg):
        print(msg, flush=True)

    try:
        core.init_supabase()
    except Exception as e:
        log(f"FATAL: Supabase init failed: {e}")
        raise SystemExit(2)

    available = core.init_ai(log=log)
    if available:
        log(f"AI providers online: {', '.join(available)}")
    else:
        log("WARNING: no AI providers — scraping only, no scoring.")

    result = core.run_all(
        years_back=years_back,
        max_score=max_score,
        do_partner=True,
        score_time_budget_s=1800,
        include_non_ocds=include_non_ocds,
        skip_state_publishers=skip_state_publishers,
        trigger=trigger,
        log=log,
    )

    status = result.get("status", "unknown")
    log(f"Pipeline finished — status={status}")
    if status != "success":
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# Schedule — 03:00 SAST = 01:00 UTC, daily
# ---------------------------------------------------------------------------
@app.function(
    secrets=[secrets],
    timeout=3600,
    cpu=2,
    memory=1024,
    schedule=modal.Cron("0 1 * * *"),
)
def scheduled_run():
    run_pipeline.remote(trigger="modal_scheduled")


# ---------------------------------------------------------------------------
# Local entry point — `modal run modal_pipeline.py`
# ---------------------------------------------------------------------------
@app.local_entrypoint()
def main():
    run_pipeline.remote(trigger="modal_manual")
