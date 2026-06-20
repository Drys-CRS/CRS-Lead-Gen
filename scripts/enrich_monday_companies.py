#!/usr/bin/env python3
"""
scripts/enrich_monday_companies.py

One-time enrichment: reads partner recommendations (crs_score >= 7) from Supabase,
aggregates their awarded tender values converted to ZAR, then appends a CRS
intelligence note to any company already on the Monday.com Companies board.

Companies NOT found on Monday are skipped (no new records created).
Run from repo root with env vars set:

    python scripts/enrich_monday_companies.py

Required env vars:  SUPABASE_URL  SUPABASE_KEY  MONDAY_API_KEY
"""
import os
import sys
import json
import re
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
_APP  = os.path.join(os.path.dirname(_HERE), "app")
if _APP not in sys.path:
    sys.path.insert(0, _APP)

import monday_client as mc
from supabase import create_client

# ── Currency conversion (approximate mid-2025) ────────────────────────────────
# 1 ZAR ≈ 155 TZS  |  1 ZAR ≈ 18 USD  |  1 ZAR ≈ 22 CAD
_RATES_TO_ZAR = {
    "TZS": 1 / 155.0,
    "USD": 18.0,
    "CAD": 1 / 0.073,   # ~13.7 ZAR/CAD
    "EUR": 20.5,
    "GBP": 24.0,
    "ZAR": 1.0,
    "R":   1.0,
}

_DEAL_SIZE_ZAR = {          # fallback when no award_value rows exist
    "small":  "< R500K",
    "medium": "R500K – R5M",
    "large":  "R5M+",
}


def _parse_to_zar(raw: str, country: str) -> float:
    """Parse a free-text award_value string → float ZAR. Returns 0 on failure."""
    if not raw:
        return 0.0
    s = raw.strip()
    if not s:
        return 0.0

    # Detect currency prefix
    currency = None
    for ccy in ("TZS", "USD", "CAD", "EUR", "GBP", "ZAR"):
        if s.upper().startswith(ccy):
            currency = ccy
            s = s[len(ccy):].strip()
            break
    if s.startswith("R"):
        currency = "ZAR"
        s = s[1:].strip()

    # SA format: "39 219 503,40" (space = thousands, comma = decimal)
    # TZ format: "80084745.72" (standard)
    # Normalise: strip spaces then handle decimal separator
    if country == "South Africa" or currency in ("ZAR", "R"):
        # spaces are thousands separators; trailing comma is decimal
        s = s.replace(" ", "")
        s = s.replace(",", ".")
    else:
        # international: commas might be thousands separators
        s = s.replace(",", "")

    s = re.sub(r"[^\d.]", "", s)   # strip anything non-numeric
    try:
        amount = float(s)
    except ValueError:
        return 0.0

    rate = _RATES_TO_ZAR.get(currency or "", 1.0)
    return amount * rate


def _fmt_zar(amount: float) -> str:
    if amount <= 0:
        return "N/A"
    if amount >= 1_000_000_000:
        return f"R{amount / 1_000_000_000:.2f}B"
    if amount >= 1_000_000:
        return f"R{amount / 1_000_000:.1f}M"
    if amount >= 1_000:
        return f"R{amount / 1_000:.0f}K"
    return f"R{amount:,.0f}"


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip()).lower()


def main():
    log = print
    ts  = datetime.now().strftime("%Y-%m-%d %H:%M")

    # ── 1. Supabase connection ────────────────────────────────────────────────
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_KEY", "").strip()
    if not url or not key:
        log("FATAL: SUPABASE_URL / SUPABASE_KEY not set")
        sys.exit(1)
    db = create_client(url, key)

    # ── 2. Pull deduplicated partner recommendations (crs_score >= 7) ─────────
    raw = (
        db.table("partner_recommendation_history")
        .select(
            "company,country,crs_score,tenders_won,partnership_type,estimated_deal_size,"
            "proposed_solutions,why,outreach_angle,issuing_departments,key_tenders,tenders_won_summary"
        )
        .gte("crs_score", 7)
        .order("crs_score", desc=True)
        .execute()
        .data
        or []
    )

    # Dedup: best row per normalised company name
    seen     = {}
    partners = []
    for row in raw:
        n = _norm(row.get("company") or "")
        if n and n not in seen:
            seen[n] = True
            partners.append(row)

    log(f"\n{'='*60}")
    log(f"CRS Monday.com Company Enrichment — {ts}")
    log(f"{'='*60}")
    log(f"Partner recommendations to process: {len(partners)}\n")

    # ── 3. Pull awarded tender values for all these companies ─────────────────
    # Fetch all awarded_tenders and match in-memory (handles name variations)
    all_awards = (
        db.table("awarded_tenders")
        .select("winning_bidder,department_name,award_value,country")
        .execute()
        .data
        or []
    )

    # Build map: norm_name → {total_zar, depts}
    award_map: dict[str, dict] = {}
    for aw in all_awards:
        n = _norm(aw.get("winning_bidder") or "")
        if not n:
            continue
        zar = _parse_to_zar(aw.get("award_value") or "", aw.get("country") or "")
        if n not in award_map:
            award_map[n] = {"total_zar": 0.0, "depts": set(), "count": 0}
        award_map[n]["total_zar"] += zar
        award_map[n]["count"]     += 1
        dept = (aw.get("department_name") or "").strip()
        if dept:
            award_map[n]["depts"].add(dept)

    # ── 4. For each partner: look up Monday, build note, post update ──────────
    updated   = 0
    not_found = 0
    errors    = 0

    for p in partners:
        company  = (p.get("company") or "").strip()
        norm_co  = _norm(company)
        country  = p.get("country") or ""
        score    = p.get("crs_score") or 0
        tenders  = p.get("tenders_won") or score
        ptype    = p.get("partnership_type") or ""
        deal_sz  = p.get("estimated_deal_size") or "medium"
        why      = (p.get("why") or "").strip()
        angle    = (p.get("outreach_angle") or "").strip()
        summary  = (p.get("tenders_won_summary") or "").strip()

        # Parse JSON string lists
        def _parse_list(v):
            if isinstance(v, list):
                return [str(x) for x in v]
            if isinstance(v, str):
                try:
                    return [str(x) for x in json.loads(v)]
                except Exception:
                    return [v] if v else []
            return []

        solutions = _parse_list(p.get("proposed_solutions"))
        rec_depts = _parse_list(p.get("issuing_departments"))

        # Aggregate award data
        aw_info  = award_map.get(norm_co, {})
        total_zar = aw_info.get("total_zar", 0.0)
        aw_depts  = aw_info.get("depts", set())
        aw_count  = aw_info.get("count", 0)

        all_depts = sorted(set(rec_depts) | aw_depts)[:10]  # cap at 10
        zar_str   = _fmt_zar(total_zar) if total_zar > 0 else f"Est. {_DEAL_SIZE_ZAR.get(deal_sz, deal_sz)}"
        note_count = aw_count if aw_count else tenders

        # Search Monday.com Companies board
        item_id = mc._find_company_by_name(company)
        if not item_id:
            log(f"  ⬛  {company:<45} | {country} | score={score} → NOT ON MONDAY")
            not_found += 1
            continue

        # Build the enrichment note
        NL   = "\n"
        sols = NL.join(f"  • {s}" for s in solutions)
        dpts = NL.join(f"  • {d}" for d in all_depts) if all_depts else "  (not recorded)"

        note = (
            f"**🔍 CRS Partner Intelligence Note** | {ts}{NL}"
            f"{'─' * 52}{NL}"
            f"**Partner Type:** {ptype}  |  **Country:** {country}{NL}"
            f"**Tenders Won:** {tenders}  |  **Total Value (ZAR approx):** {zar_str}{NL}{NL}"
            f"**Why CRS Aligned:**{NL}{why}{NL}{NL}"
            f"**Outreach Angle:**{NL}{angle}{NL}{NL}"
            f"**Proposed CRS Solutions:**{NL}{sols}{NL}{NL}"
            f"**Departments / Clients Won With ({len(all_depts)}):**{NL}{dpts}{NL}{NL}"
            f"**Tender Activity Summary:**{NL}{summary}"
        )

        try:
            mc._add_monday_update(item_id, mc.COMPANIES_BOARD_ID, note)
            log(f"  ✅  {company:<45} | {country} | score={score} | {zar_str}")
            updated += 1
        except Exception as exc:
            log(f"  ❌  {company:<45} | ERROR: {exc}")
            errors += 1

    # ── Summary ───────────────────────────────────────────────────────────────
    log(f"\n{'='*60}")
    log(f"Results: ✅ Updated={updated}  ⬛ Not on Monday={not_found}  ❌ Errors={errors}")
    log(f"{'='*60}\n")


if __name__ == "__main__":
    main()
