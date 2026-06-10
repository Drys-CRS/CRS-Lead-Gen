"""
run_all_scrapers.py
───────────────────
Master runner for all CRS African tender scrapers.
Replaces the old manual trigger of etender_api.py + etender_awards.py.

Run locally:
    python run_all_scrapers.py

Or trigger from the Streamlit app's "Refresh Data" button (cloud-safe subprocess call).
"""
import sys
import os
import time

# Make sure spider modules can import utils
sys.path.insert(0, os.path.dirname(__file__))

from etender_api import scrape_etenders as sa_open
from etender_awards import scrape_awarded_tenders as sa_awarded
from spiders.kenya_ppip import scrape_open as ke_open, scrape_awarded as ke_awarded
from spiders.ghana_ghaneps import scrape_open as gh_open, scrape_awarded as gh_awarded
from spiders.tanzania_nest import scrape_open as tz_open, scrape_awarded as tz_awarded
from spiders.uganda_ppda import scrape_open as ug_open, scrape_awarded as ug_awarded
from spiders.nigeria_bpp import scrape_open as ng_open, scrape_awarded as ng_awarded
from spiders.southern_africa import (
    scrape_botswana, scrape_namibia, scrape_zimbabwe, scrape_zambia
)

SCRAPERS = [
    # ── South Africa (existing) ──────────────────────────
    ("South Africa – Open",      sa_open),
    ("South Africa – Awarded",   sa_awarded),
    # ── East Africa ─────────────────────────────────────
    ("Kenya – Open",             ke_open),
    ("Kenya – Awarded",          ke_awarded),
    ("Tanzania – Open",          tz_open),
    ("Tanzania – Awarded",       tz_awarded),
    ("Uganda – Open",            ug_open),
    ("Uganda – Awarded",         ug_awarded),
    # ── West Africa ──────────────────────────────────────
    ("Nigeria – Open",           ng_open),
    ("Nigeria – Awarded",        ng_awarded),
    ("Ghana",                    gh_open),
    ("Ghana – Awarded",          gh_awarded),
    # ── Southern Africa ──────────────────────────────────
    ("Botswana",                 scrape_botswana),
    ("Namibia",                  scrape_namibia),
    ("Zimbabwe",                 scrape_zimbabwe),
    ("Zambia",                   scrape_zambia),
]


def run_all(delay: float = 1.5):
    """Run every scraper with a short delay between calls to avoid hammering portals."""
    print("\n" + "═" * 55)
    print("  CRS Africa-Wide Tender Pipeline  —  Starting")
    print("═" * 55)

    success, failed = [], []

    for label, fn in SCRAPERS:
        print(f"\n▶  {label}")
        try:
            fn()
            success.append(label)
        except Exception as e:
            print(f"  ❌  {label} failed: {e}")
            failed.append(label)
        time.sleep(delay)

    print("\n" + "═" * 55)
    print(f"  Pipeline complete.")
    print(f"  ✅  {len(success)}/{len(SCRAPERS)} scrapers succeeded.")
    if failed:
        print(f"  ❌  Failed: {', '.join(failed)}")
    print("═" * 55 + "\n")


if __name__ == "__main__":
    run_all()