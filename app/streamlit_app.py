import streamlit as st
import pandas as pd
import os
import json
import re
try:
    import google.genai as genai
    _GENAI_NEW = True
except ImportError:
    import google.generativeai as genai  # legacy fallback
    _GENAI_NEW = False
from supabase import create_client

# Monday.com integration (optional — only active if MONDAY_API_KEY is set)
try:
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from monday_client import (
        push_tender_to_monday,
        push_partner_to_companies,
        get_ticket_board_id, get_leads_board_id, get_companies_board_id,
    )
    _MONDAY_AVAILABLE = bool(st.secrets.get("MONDAY_API_KEY") if hasattr(st, 'secrets') else False)
except ImportError:
    _MONDAY_AVAILABLE = False


# ─────────────────────────────────────────────────────────────────────────────
# AUTONOMOUS PIPELINE — Provider health checks, scheduled runner, keep-alive
# ─────────────────────────────────────────────────────────────────────────────
import threading as _threading
import datetime as _sched_dt

try:
    from apscheduler.schedulers.background import BackgroundScheduler as _BGScheduler
    from apscheduler.triggers.cron import CronTrigger as _CronTrigger
    _APSCHEDULER_AVAILABLE = True
except ImportError:
    _APSCHEDULER_AVAILABLE = False

try:
    from streamlit_autorefresh import st_autorefresh
    _AUTOREFRESH_AVAILABLE = True
except ImportError:
    _AUTOREFRESH_AVAILABLE = False

# ── Provider health check ─────────────────────────────────────────────────────
_HEALTH_PROBE = "Reply with the single word: ok"

def check_provider_health() -> dict:
    """
    Probe each provider independently.
    Returns {name: {available, quota_ok, latency_ms, status, error}}
    
    status values:
      "ok"          — responded successfully
      "quota"       — rate limited / daily quota exceeded (reachable but throttled)
      "error"       — auth or connection failure
      "no_key"      — API key not configured
    """
    import time as _t
    results = {}
    usage = _get_usage()

    def _probe(name, fn, client_obj):
        if client_obj is None:
            results[name] = {
                "available": False, "quota_ok": False,
                "latency_ms": None, "status": "no_key", "error": "No API key configured"
            }
            return
        t0 = _t.time()
        try:
            fn(_HEALTH_PROBE)
            used  = usage.get(name, 0)
            limit = _AI_DAILY_LIMITS.get(name, 9999)
            results[name] = {
                "available":  True,
                "quota_ok":   used < limit,
                "latency_ms": int((_t.time() - t0) * 1000),
                "status":     "ok" if used < limit else "quota",
                "error":      f"Daily usage {used}/{limit}" if used >= limit else None,
            }
        except Exception as e:
            err_str = str(e)
            is_quota = _is_rate_limit(err_str)
            results[name] = {
                "available":  is_quota,   # quota errors mean reachable, just throttled
                "quota_ok":   False,
                "latency_ms": None,
                "status":     "quota" if is_quota else "error",
                "error":      err_str[:200],
            }

    probes = [
        ("Groq",       _call_groq,       groq_ai),
        ("Cerebras",   _call_cerebras,   cerebras_ai),
        ("OpenRouter", _call_openrouter, openrouter_ai),
        ("GitHub",     _call_github,     github_ai),
        ("NVIDIA",     _call_nvidia,     nvidia_ai),
        ("DeepSeek",   _call_deepseek,   deepseek_ai),
        ("Gemini",     _call_gemini,     True),   # Gemini always has a key
    ]

    threads = [
        _threading.Thread(target=_probe, args=(n, fn, client))
        for n, fn, client in probes
    ]
    for th in threads: th.start()
    for th in threads: th.join(timeout=20)

    # Persist to Supabase
    try:
        rows = [
            {"provider": k, "available": v["available"],
             "latency_ms": v.get("latency_ms"),
             "error": f"[{v.get('status','?')}] {v.get('error','') or ''}"}
            for k, v in results.items()
        ]
        supabase.table("provider_health_log").insert(rows).execute()
    except Exception:
        pass

    return results


def _reset_daily_usage():
    """Called at midnight — wipes session-state usage counters so limits reset."""
    if "ai_usage" in st.session_state:
        for k in st.session_state["ai_usage"]:
            st.session_state["ai_usage"][k] = 0
    st.session_state["ai_usage_date"] = _sched_dt.date.today().isoformat()
    st.session_state["ai_last_ops"]   = {}


# ── Autonomous pipeline job ────────────────────────────────────────────────────
def _pipeline_log(msg: str):
    """Silent logger — writes to Supabase pipeline_runs table if a run is active."""
    run_id = st.session_state.get("_pipeline_run_id")
    if run_id:
        try:
            supabase.table("pipeline_runs").update(
                {"error_log": supabase.table("pipeline_runs")
                 .select("error_log").eq("id", run_id).execute()
                 .data[0].get("error_log","") + f"\n{msg}"}
            ).eq("id", run_id).execute()
        except Exception:
            pass



def scrape_non_ocds_countries(out):
    """
    Scrape tenders for countries without OCDS feeds using three free sources:
    1. World Bank Group Procurement Notices (covers all African countries, JSON API)
    2. UNDP Procurement Notices (UN system, covers fragile states)
    3. AfDB (African Development Bank) procurement notices (JSON API)

    All results go to sa_tenders (open) and awarded_tenders (awarded)
    with correct country attribution.
    """
    import requests
    from datetime import datetime, timezone, timedelta

    today = datetime.now(timezone.utc).date().isoformat()
    cutoff = "2015-01-01"  # as far back as WB/UNDP APIs hold data

    # ── Map country names to World Bank country codes ──────────────────────
    WB_COUNTRY_CODES = {
        "Angola": "AO", "Botswana": "BW", "Egypt": "EG", "Eritrea": "ER",
        "Eswatini": "SZ", "Ethiopia": "ET", "The Gambia": "GM", "Lesotho": "LS",
        "Libya": "LY", "Malawi": "MW", "Mauritius": "MU", "Mozambique": "MZ",
        "Namibia": "NA", "Republic of South Sudan": "SS", "Seychelles": "SC",
        "Sierra Leone": "SL", "Somalia": "SO", "Sudan": "SD", "Zimbabwe": "ZW",
        # Also fetch for OCDS countries as supplementary (they publish less frequently)
        "Kenya": "KE", "Nigeria": "NG", "Ghana": "GH", "Tanzania": "TZ",
        "Uganda": "UG", "Zambia": "ZM", "Rwanda": "RW",
    }

    total_open, total_awarded = 0, 0

    for country, wb_code in WB_COUNTRY_CODES.items():
        flag = NON_OCDS_COUNTRIES.get(country, OCDS_REGISTRY.get(country, ("🌍", "Africa")))[0]                if isinstance(NON_OCDS_COUNTRIES.get(country, OCDS_REGISTRY.get(country)), tuple)                else "🌍"

        # ── Source 1: World Bank Procurement Notices ───────────────────────
        try:
            # WB Open Contracting for Infrastructure (OCI) + procurement API
            wb_url = "https://search.worldbank.org/api/v2/procnotices"
            params = {
                "format":     "json",
                "fl":         "id,project_name,project_id,notice_type,deadline_date,"
                              "submission_date,contact_country,procurement_method,"
                              "description,contact_organization,status",
                "fq":         f"contact_country:{wb_code}",
                "rows":       200,
                "sort":       "submission_date desc",
            }
            r = requests.get(wb_url, params=params,
                             headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
            if r.ok:
                notices = r.json().get("docs", [])
                open_batch, awarded_batch = [], []

                for n in notices:
                    title = str(n.get("project_name") or n.get("description") or "")[:200]
                    if not _is_relevant(title):
                        continue

                    notice_type = str(n.get("notice_type") or "")
                    deadline = str(n.get("deadline_date") or n.get("submission_date") or "")[:10]
                    org = str(n.get("contact_organization") or "")[:200]
                    tender_no = f"WB-{n.get('id','')}"
                    portal = f"https://projects.worldbank.org/en/projects-operations/procurement/procnotices/{n.get('id','')}"

                    base = {
                        "tender_number":   tender_no[:100],
                        "department_name": org,
                        "title":           title,
                        "description":     title,
                        "category":        notice_type,
                        "portal_link":     portal,
                        "country":         country,
                        "contact_person":  str(n.get("contact_name") or "")[:200],
                        "contact_email":   str(n.get("contact_email") or "")[:200],
                        "contact_phone":   str(n.get("contact_phone") or "")[:50],
                    }

                    status = str(n.get("status") or "").lower()
                    if status in ("awarded", "contract signed"):
                        awarded_batch.append({
                            **base,
                            "winning_bidder":  "Not Disclosed",
                            "award_value":     "Not Disclosed",
                            "issue_date":      deadline,
                        })
                    elif deadline >= today or not deadline:
                        open_batch.append({
                            **base,
                            "compliance_requirements": n.get("procurement_method") or "See portal",
                            "closing_date": deadline or None,
                            "status":       "Open",
                            "award_status": "Published",
                        })

                if open_batch:
                    # Replace open WB notices for this country
                    supabase.table("sa_tenders").delete()                        .eq("country", country)                        .like("tender_number", "WB-%")                        .execute()
                    _upsert(open_batch, country, f"WB Open", lambda m: None)
                    total_open += len(open_batch)
                if awarded_batch:
                    _upsert_awarded(awarded_batch, country, f"WB Awarded", lambda m: None)
                    total_awarded += len(awarded_batch)

        except Exception as e:
            pass  # non-fatal per country

        # ── Source 2: UNDP Procurement Notices ────────────────────────────
        try:
            undp_url = "https://procurement-notices.undp.org/search.cfm"
            params2 = {
                "op":      "search",
                "country": country,
                "type":    "all",
                "output":  "json",
                "rows":    50,
            }
            r2 = requests.get(undp_url, params=params2,
                              headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
            if r2.ok and r2.text.strip().startswith("["):
                notices2 = r2.json()
                undp_open = []
                for n in notices2:
                    title = str(n.get("title") or "")[:200]
                    if not _is_relevant(title):
                        continue
                    deadline = str(n.get("deadline") or "")[:10]
                    if deadline and deadline < today:
                        continue
                    undp_open.append({
                        "tender_number":           f"UNDP-{n.get('id','')}",
                        "department_name":         str(n.get("agency") or "UNDP")[:200],
                        "title":                   title,
                        "description":             title,
                        "category":                str(n.get("type") or ""),
                        "portal_link":             str(n.get("url") or "https://procurement-notices.undp.org"),
                        "closing_date":            deadline or None,
                        "country":                 country,
                        "compliance_requirements": "See UNDP portal",
                        "status":                  "Open",
                        "award_status":            "Published",
                        "contact_person":          str(n.get("contact_name") or n.get("contact") or "")[:200],
                        "contact_email":           str(n.get("contact_email") or n.get("email") or "")[:200],
                        "contact_phone":           str(n.get("contact_phone") or n.get("phone") or "")[:50],
                    })
                if undp_open:
                    _upsert(undp_open, country, "UNDP Open", lambda m: None)
                    total_open += len(undp_open)
        except Exception:
            pass

    out(f"  🌍 Non-OCDS countries: {total_open} open + {total_awarded} awarded tenders collected")



def run_pipeline(trigger: str = "scheduled"):
    """
    Full autonomous pipeline:
    1. Scrape all countries
    2. Score all new open tenders → append to tender_score_history
    3. Run partner analysis → append to partner_recommendation_history
    4. Collect attack signals + score → append to attack_signal_history
    5. Mark pipeline_run as complete
    """
    import time as _pt
    t_start = _pt.time()
    log_lines = []
    counters  = {"tenders_scraped": 0, "tenders_scored": 0,
                 "signals_found": 0,   "partners_found": 0}

    def out(msg):
        log_lines.append(msg)

    # Create pipeline run record
    try:
        run_row = supabase.table("pipeline_runs").insert(
            {"trigger": trigger, "status": "running"}
        ).execute()
        run_id = run_row.data[0]["id"]
        st.session_state["_pipeline_run_id"] = run_id
    except Exception as e:
        run_id = None
        out(f"Could not create run record: {e}")

    try:
        # ── 1. Scrape ──────────────────────────────────────────────────────
        out("Starting scrape…")
        scrape_south_africa(out)
        for country in OCDS_REGISTRY:
            if country != "South Africa":
                try:
                    scrape_ocds_country(country, out)
                except Exception as e:
                    out(f"  ❌ {country}: {e}")
        try:
            out("Scraping non-OCDS countries via World Bank & UNDP…")
            scrape_non_ocds_countries(out)
        except Exception as e:
            out(f"  ❌ Non-OCDS scraper: {e}")
        st.cache_data.clear()

        # Reload fresh data
        tenders_df = fetch_tenders()
        if not tenders_df.empty:
            counters["tenders_scraped"] = len(tenders_df)

            # ── 2. Score open tenders ─────────────────────────────────────
            out("Scoring open tenders…")
            open_df = tenders_df[tenders_df["status"] == "Open"].copy()
            for col in ["ai_score", "ai_rationale"]:
                if col not in open_df.columns:
                    open_df[col] = None
            unscored = open_df[open_df["ai_score"].isna()]
            score_rows = []
            for _, row in unscored.iterrows():
                try:
                    scored = ai_score_tender(row.to_dict())
                    supabase.table("sa_tenders").update({
                        "ai_score": scored["score"],
                        "ai_rationale": scored["rationale"],
                    }).eq("tender_number", row["tender_number"]).execute()
                    score_rows.append({
                        "tender_number": str(row.get("tender_number", ""))[:100],
                        "department":    str(row.get("department_name", ""))[:200],
                        "title":         str(row.get("title", ""))[:200],
                        "country":       str(row.get("country", "")),
                        "closing_date":  str(row.get("closing_date", ""))[:10] or None,
                        "ai_score":      scored["score"],
                        "ai_rationale":  scored["rationale"],
                        "status":        "Open",
                    })
                    counters["tenders_scored"] += 1
                    _time.sleep(2)  # throttle
                except Exception as e:
                    out(f"  Scoring error {row.get('tender_number')}: {e}")
            if score_rows:
                try:
                    supabase.table("tender_score_history").insert(score_rows).execute()
                except Exception as e:
                    out(f"  History insert error: {e}")
                if _MONDAY_AVAILABLE:
                    high_score = [r for r in score_rows if (r.get("ai_score") or 0) >= 8]
                    mon_count = 0
                    for row in high_score:
                        try:
                            r = push_tender_to_monday(row)
                            if r.get("ticket_action") == "created" or r.get("lead_action") == "created":
                                mon_count += 1
                        except Exception:
                            pass
                    if mon_count:
                        out(f"  📋 {mon_count} high-score tenders pushed to Monday.com")

            # ── 3. Partner analysis ───────────────────────────────────────
            out("Running partner analysis…")
            try:
                awarded_df = tenders_df[tenders_df["status"] == "Awarded"].copy()
                if not awarded_df.empty:
                    partners = ai_analyse_partners(awarded_df)
                    partner_rows = []
                    for p in partners:
                        partner_rows.append({
                            "company":          str(p.get("company",""))[:200],
                            "country":          str(p.get("country",""))[:100],
                            "crs_score":        p.get("crs_score") or p.get("urgency_score"),
                            "why":              str(p.get("why_aligned",""))[:500],
                            "outreach_angle":   str(p.get("outreach_angle",""))[:500],
                            "urgency":          str(p.get("urgency",""))[:20],
                            "partnership_type": str(p.get("partnership_type",""))[:100],
                        })
                    if partner_rows:
                        supabase.table("partner_recommendation_history").insert(partner_rows).execute()
                        counters["partners_found"] = len(partner_rows)
            except Exception as e:
                out(f"  Partner analysis error: {e}")

            # ── 4. Attack signals ─────────────────────────────────────────
            out("Collecting attack signals…")
            try:
                signals = _search_attack_news(["South Africa","Kenya","Nigeria","Ghana"])
                if signals:
                    # AI-parse them
                    nl = "\n"
                    signal_lines = nl.join(
                        f"[{i+1}] TITLE: {s.get('title','')[:150]}\n    BODY: {s.get('body','')[:200]}"
                        for i, s in enumerate(signals[:20])
                    )
                    stage1_prompt = f"""For each item, extract victim_org, attack_type (ransomware|data breach|phishing|DDoS|malware|unknown), crs_score 1-10, contact_title, outreach_angle.
CRS sells: cybersecurity solutions, IBM/RedHat/SUSE/CompTIA training, Vectra NDR/XDR, vulnerability management, SIEM, SOC services, penetration testing.
Items:
{signal_lines}
Return JSON array only: [{{"index":1,"victim_org":"...","attack_type":"...","crs_score":N,"contact_title":"...","outreach_angle":"..."}}]"""
                    try:
                        raw   = _call_ai(stage1_prompt)
                        parsed = json.loads(raw)
                        for item in parsed:
                            idx = item.get("index",0) - 1
                            if 0 <= idx < len(signals):
                                signals[idx].update({
                                    "victim_org":    item.get("victim_org",""),
                                    "attack_type":   item.get("attack_type",""),
                                    "crs_score":     item.get("crs_score"),
                                    "contact_title": item.get("contact_title",""),
                                    "outreach_angle":item.get("outreach_angle",""),
                                })
                    except Exception:
                        pass

                    signal_rows = [{
                        "source":         s.get("source",""),
                        "title":          str(s.get("title",""))[:300],
                        "victim_org":     str(s.get("victim_org",""))[:200],
                        "attack_type":    str(s.get("attack_type",""))[:50],
                        "crs_score":      s.get("crs_score"),
                        "contact_title":  str(s.get("contact_title",""))[:100],
                        "outreach_angle": str(s.get("outreach_angle",""))[:500],
                        "url":            str(s.get("url",""))[:500],
                        "published":      str(s.get("published",""))[:20],
                        "country_context":"Africa",
                    } for s in signals]
                    supabase.table("attack_signal_history").insert(signal_rows).execute()
                    counters["signals_found"] = len(signal_rows)
            except Exception as e:
                out(f"  Signal collection error: {e}")

    except Exception as e:
        out(f"Pipeline failed: {e}")
        if run_id:
            supabase.table("pipeline_runs").update(
                {"status": "failed", "error_log": "\n".join(log_lines),
                 "duration_secs": int(_pt.time() - t_start)}
            ).eq("id", run_id).execute()
        return

    # ── Mark complete ──────────────────────────────────────────────────────────
    if run_id:
        try:
            supabase.table("pipeline_runs").update({
                "status":           "complete",
                "tenders_scraped":  counters["tenders_scraped"],
                "tenders_scored":   counters["tenders_scored"],
                "signals_found":    counters["signals_found"],
                "partners_found":   counters["partners_found"],
                "error_log":        "\n".join(log_lines[-20:]),
                "duration_secs":    int(_pt.time() - t_start),
            }).eq("id", run_id).execute()
        except Exception:
            pass

    st.session_state.pop("_pipeline_run_id", None)
    _reset_daily_usage()
    out(f"Pipeline complete in {int(_pt.time()-t_start)}s")


# ── APScheduler setup (runs once per Streamlit process) ───────────────────────
_SCHEDULER_KEY = "_crs_scheduler_started"

def _ensure_scheduler():
    """Start the background scheduler if not already running in this process."""
    if not _APSCHEDULER_AVAILABLE:
        return
    if st.session_state.get(_SCHEDULER_KEY):
        return
    try:
        scheduler = _BGScheduler(timezone="Africa/Johannesburg")
        # Daily pipeline at 02:00 SAST (off-peak, after midnight credit reset)
        scheduler.add_job(
            lambda: run_pipeline("scheduled"),
            _CronTrigger(hour=2, minute=0),
            id="daily_pipeline",
            replace_existing=True,
            misfire_grace_time=3600,
        )
        # Daily usage reset at 00:01 SAST
        scheduler.add_job(
            _reset_daily_usage,
            _CronTrigger(hour=0, minute=1),
            id="daily_reset",
            replace_existing=True,
        )
        scheduler.start()
        st.session_state[_SCHEDULER_KEY] = True
    except Exception as e:
        st.session_state[_SCHEDULER_KEY] = f"failed: {e}"


# ─────────────────────────────────────────────
# 1. PAGE CONFIG
# ─────────────────────────────────────────────
st.set_page_config(page_title="CRS Competitive Intelligence", layout="wide")

# ── Keep-alive: reload every 3 hours (10 800 000 ms) ──────────────────────────
# Keep-alive: st_autorefresh must only be rendered once per session.
# Streamlit reruns the whole script on every interaction — calling it
# unconditionally causes a duplicate key error. The fragment=True approach
# isn't available in all versions, so we use a unique per-session key instead.
if _AUTOREFRESH_AVAILABLE:
    import uuid as _uuid
    # Set session ID first, then use it — ensures same key on every rerun
    if "_session_id" not in st.session_state:
        st.session_state["_session_id"] = str(_uuid.uuid4())[:8]
    st_autorefresh(
        interval=10_800_000,
        key=f"keepalive_{st.session_state['_session_id']}",
        debounce=True,
    )

# ── Start background scheduler (once per process) ─────────────────────────────
_ensure_scheduler()

# ─────────────────────────────────────────────
# 2. CRS COMPANY PROFILE
#    Edit this to reflect your actual capabilities.
#    Gemini uses this when scoring and matching.
# ─────────────────────────────────────────────
CRS_PROFILE = """
Company: Cyber Retaliator Solutions (CRS) — #RetaliatorNation
Tagline: "The Bug Stops Here."
Head Office: Eco Court Office Park, Suite C4, 340 Witch-Hazel Street, Centurion, South Africa
Training Centres: Centurion, Midrand, Sandton, Cape Town
Experience: 25+ years in Cyber Security. Channel-focused Value-Added Distributor.
Authorised training partner for IBM, RedHat, SUSE, CompTIA, Agile SAFe.

── TECHNICAL TRAINING ──
- IBM Technical Training (z/OS, IBM i, IBM Power, Mainframe)
- Red Hat Learning (RHEL, OpenShift — RHCSA, RHCE certifications)
- SUSE Technical Product Training
- CompTIA (A+, Network+, Security+, CySA+)
- Agile SAFe Training (scaling Agile in large organisations)

── CYBER SECURITY DISTRIBUTION (full portfolio) ──
VECTRA AI — XDR/NDR/CDR/ITDR platform
  Leader in 2025 Gartner Magic Quadrant for NDR
  Target: 500+ concurrent IPs, 250+ internal accounts, medium-large orgs
  Modules: NDR, CDR for AWS/M365/Azure AD, ITDR, MDR, Recall, Stream
  Keywords: AI-powered XDR, NDR, SIEM optimisation, SOC modernisation, MITRE

vRx (Vicarius) — Strategic Exposure Remediation Platform
  Target: 100+ endpoints, replacing Patch/VM tools
  Features: continuous vulnerability detection, X-TAGS prioritisation,
  patch management (Win/Mac/Linux), auto-actions, patchless protection
  Keywords: vulnerability management, patch management, MTTR reduction

Strobes Security — AI-Driven CTEM Platform
  Target: Enterprise 1000+ assets, CISOs consolidating risk exposure
  Modules: ASM, PTaaS (1 credit = 8 pentest hours), RBVM, ASPM
  Keywords: attack surface management, pentesting, threat exposure, CTEM

Aikido — Developer-Centric AppSec Platform
  Target: Any org with a dev team; replaces Snyk/Orca/Veracode
  Features: SAST, DAST, SCA, secrets, IaC, container, CSPM, AI autofix
  Pricing: Bundles of users (Basic/Pro/Custom for MSSPs)
  Keywords: DevSecOps, code security, SBOM, shift-left, CI/CD

Flare — Dark Web Monitoring & Threat Exposure Management
  Target: Orgs needing threat intel, leaked credential monitoring
  Features: dark web monitoring, GitHub leak detection, SIEM integration,
  AI Assist, Entra ID response, takedown services (sold individually or in bands of 10)
  Pricing: per number of employees with commitment tier discounts
  Keywords: threat intelligence, dark web, ransomware, credential exposure

BeachheadSecure — Endpoint Data Security & Encryption
  Target: SMBs not wanting E3/E5 costs; compliance-driven orgs
  Products: Core/Premium (encryption + RiskResponder), Server MFA,
  Mobile, Outlook Plugin (PDF email encryption + Check4Phish)
  Keywords: POPIA compliance, encryption, MFA, data protection, device kill/wipe

SMBsecure — All-in-One SMB Cyber Protection
  Target: Small-medium businesses, FSPs, compliance-driven SMEs
  Features: BitLocker/FileVault encryption, MDM, Outlook email encryption,
  phishing defence, SAT, dark web monitoring, Cyber Warranty
  Warranty: R1M data breach, R500K extortion (ransomware), R250K BEC cover
  Packages: ESSENTIAL, STANDARD, ADVANCED, StarterPack/ComplianceSuite
  Keywords: POPIA, encryption, cyber warranty, SMB, MFA, phishing

Telivy — Cyber Security Auditing for MSSPs
  Target: MSSPs providing cyber audits at scale
  Features: attack surface assessment, dark web scan, M365/Google Workspace,
  PII identification, vulnerability assessment, financial risk calculator
  Pricing: Prospecting Module (unlimited assessments) + Risk Monitoring Endpoints
  Keywords: MSSP, cyber audit, attack surface, vulnerability assessment

Strobes PTaaS — Penetration Testing as a Service
  Priced per credit (1 credit = 8 pentest hours); requires scoping form
  Types: network, web app, API, mobile, cloud config, red team

VAPT Services — CRS Own Penetration Testing
  Scoped: internal/external IPs, web apps, domains
  Models: CAPEX (once-off) or OPEX (ongoing subscription)
  Keywords: penetration testing, whitebox, blackbox, greybox, compliance

Cyber Risk Essentials (CRE) — Managed Cyber Awareness Program
  Components: phishing simulations (every 3-5 weeks), online training,
  instructor-led quarterly sessions, executive lunch-and-learns (half-yearly)
  Vendors: GoldPhish, Prventi
  Keywords: phishing simulation, security awareness, human firewall, SAT

BlueFlag Security — SDLC Identity & Supply Chain Security
  Target: mid-large enterprises with dev teams, DevSecOps, IP-heavy orgs
  Features: least privilege enforcement, identity hygiene, insider threat detection,
  continuous CI/CD monitoring, AI-driven identity intelligence
  Keywords: SDLC security, software supply chain, DevOps, identity, least privilege

Standss (SendGuard/SendConfirm) — Email GRC
  Features: confirm recipients/attachments before send, DLP rules, unsend, audit logs
  Target: orgs with high email reliance, SMBs, compliance-driven

── TARGET MARKETS ──
Government (all levels, all African countries), financial services, banking,
healthcare, education, telcos, mining, enterprises with dev teams.
Strong fit: cybersecurity solutions, technical training (IBM/RH/SUSE/CompTIA),
SOC/MDR services, vulnerability management, POPIA compliance, MSSP tooling.
Weak fit: pure hardware, civil construction, non-ICT goods/services.

── PARTNER INCENTIVES ──
CompTIA vouchers for partners on annual deals ($2,600+ qualifies for exam voucher)
MDF: quarterly for MSSPs, annually for others
Account managers: Takealot vouchers ($800–$2,650+ deals)
"""

# ─────────────────────────────────────────────
# 3. DATABASE CONNECTION
# ─────────────────────────────────────────────
@st.cache_resource
def init_connection():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_connection()

# ─────────────────────────────────────────────
# 4. AI CLIENTS  (Groq → Cerebras → OpenRouter → Gemini cascade)
#
# Priority for scoring/parsing:
#   1. Groq        — 30 RPM free, fastest inference (~1s responses)
#   2. Cerebras    — token-based free tier, fast
#   3. OpenRouter  — free :free models, no hard daily cap, OpenAI-compatible
#   4. Gemini      — 20 req/day free, kept for grounded web search (Discovery tab)
#
# Each key is optional — the cascade skips any provider whose key is missing.
# ─────────────────────────────────────────────
import time as _time

@st.cache_resource
def init_gemini():
    try:
        key = st.secrets.get("GEMINI_API_KEY", "")
        if not key:
            return None
        if _GENAI_NEW:
            return genai.Client(api_key=key)
        else:
            genai.configure(api_key=key)
            return genai.GenerativeModel("gemini-2.5-flash")
    except Exception as e:
        st.error(f"Gemini init error: {e}")
        return None

@st.cache_resource
def init_groq():
    try:
        from groq import Groq
        key = st.secrets.get("GROQ_API_KEY")
        if not key:
            return None
        return Groq(api_key=key)
    except Exception:
        return None

@st.cache_resource
def init_cerebras():
    try:
        from cerebras.cloud.sdk import Cerebras
        key = st.secrets.get("CEREBRAS_API_KEY")
        if not key:
            return None
        return Cerebras(api_key=key)
    except Exception:
        return None

@st.cache_resource
def init_openrouter():
    try:
        from openai import OpenAI
        key = st.secrets.get("OPENROUTER_API_KEY")
        if not key:
            return None
        return OpenAI(
            api_key=key,
            base_url="https://openrouter.ai/api/v1",
            default_headers={
                "HTTP-Referer": "https://github.com/Drys-CRS/CRS-Lead-Gen",
                "X-Title": "CRS Competitive Intelligence",
            }
        )
    except Exception:
        return None

@st.cache_resource
def init_github_models():
    try:
        from openai import OpenAI
        # Try direct bracket access first (handles all TOML layouts),
        # then .get() fallback, then GH_PAT alias
        key = ""
        for k in ("GITHUB_TOKEN", "GH_PAT", "github_token"):
            try:
                v = st.secrets[k]
                if v:
                    key = str(v).strip()
                    break
            except Exception:
                pass
        if not key:
            key = (st.secrets.get("GITHUB_TOKEN") or
                   st.secrets.get("GH_PAT") or "").strip()
        if not key:
            return None
        return OpenAI(
            api_key=key,
            base_url="https://models.inference.ai.azure.com",
        )
    except Exception:
        return None

@st.cache_resource
def init_nvidia_nim():
    try:
        from openai import OpenAI
        key = st.secrets.get("NVIDIA_API_KEY", "")
        if not key:
            return None
        return OpenAI(
            api_key=key,
            base_url="https://integrate.api.nvidia.com/v1",
        )
    except Exception:
        return None

@st.cache_resource
def init_deepseek():
    try:
        from openai import OpenAI
        key = st.secrets.get("DEEPSEEK_API_KEY", "")
        if not key:
            return None
        return OpenAI(
            api_key=key,
            base_url="https://api.deepseek.com",
        )
    except Exception:
        return None

ai            = init_gemini()
groq_ai       = init_groq()
cerebras_ai   = init_cerebras()
openrouter_ai = init_openrouter()
github_ai     = init_github_models()
nvidia_ai     = init_nvidia_nim()
deepseek_ai   = init_deepseek()

# GitHub Models — best free models available (no card, uses your GitHub token)
# GitHub Models — verified IDs June 2026 (case-sensitive on Azure endpoint)
# Source: github.com/marketplace/models + GitHub changelog 2025-06-26
_GITHUB_FREE_MODELS = [
    "Llama-3.3-70B-Instruct",   # Meta Llama 3.3 70B — primary
    "gpt-4o-mini",               # OpenAI GPT-4o Mini — reliable fallback
    "Mistral-Large-2411",        # Mistral Large — strong structured output
    "Phi-4",                     # Microsoft Phi-4 — fast, good for scoring
]

# OpenRouter model strategy:
# 1. openrouter/free  — meta-router that auto-selects from all currently available
#                       free models; never needs updating as models rotate in/out
# 2. deepseek/deepseek-r1:free — explicit fallback, excellent at structured JSON
# 3. deepseek/deepseek-v3:free — fast, reliable second fallback
# 4. meta-llama/llama-4-maverick:free — strong reasoning third fallback
_OPENROUTER_FREE_MODELS = [
    "openrouter/free",                   # auto-selects best available free model
    "deepseek/deepseek-r1:free",         # explicit: great structured JSON output
    "deepseek/deepseek-v3:free",         # explicit: fast general reasoning
    "meta-llama/llama-4-maverick:free",  # explicit: strong reasoning fallback
]

# ── Provider status shown in sidebar ──
def _provider_status() -> str:
    parts = []
    parts.append("🟢 Groq"        if groq_ai        else "⚪ Groq (no key)")
    parts.append("🟢 Cerebras"    if cerebras_ai     else "⚪ Cerebras (no key)")
    parts.append("🟢 OpenRouter"  if openrouter_ai   else "⚪ OpenRouter (no key)")
    parts.append("🟢 GitHub"      if github_ai       else "⚪ GitHub (no token)")
    parts.append("🟢 NVIDIA NIM"  if nvidia_ai       else "⚪ NVIDIA NIM (no key)")
    parts.append("🟢 DeepSeek"    if deepseek_ai     else "⚪ DeepSeek (no key)")
    parts.append("🟢 Gemini")
    return " · ".join(parts)

def _clean(raw: str) -> str:
    """Strip markdown fences from an AI response."""
    return re.sub(r"^```json[\s]*|^```[\s]*|```$", "", raw.strip(), flags=re.MULTILINE).strip()

def _is_rate_limit(err: str) -> bool:
    return any(x in err.lower() for x in ["429", "quota", "rate limit", "too many", "throttl"])

def _call_groq(prompt: str) -> str:
    """Call Groq (llama-3.3-70b-versatile). Raises on any error."""
    resp = groq_ai.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=1500,
    )
    return _clean(resp.choices[0].message.content)

def _call_cerebras(prompt: str) -> str:
    """Call Cerebras. Current public models per inference-docs.cerebras.ai June 2026:
      gpt-oss-120b  (production, reasoning model)
      zai-glm-4.7   (preview, high quality)
    All Llama/Qwen models removed from public endpoints as of May 2026.
    """
    for model in ["gpt-oss-120b", "zai-glm-4.7"]:
        try:
            resp = cerebras_ai.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=1500,
            )
            msg  = resp.choices[0].message
            text = (getattr(msg, "content", None) or
                    getattr(msg, "reasoning_content", None) or "").strip()
            if text:
                return _clean(text)
        except Exception as e:
            err = str(e)
            if any(x in err for x in ["404", "does not exist", "not found",
                                        "deprecated", "unavailable"]):
                continue
            raise
    raise ValueError("All Cerebras models unavailable — check inference-docs.cerebras.ai")

def _call_github(prompt: str) -> str:
    """Call GitHub Models — free with any GitHub account, OpenAI-compatible."""
    last_err = None
    for model in _GITHUB_FREE_MODELS:
        try:
            resp = github_ai.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=1500,
            )
            text = (resp.choices[0].message.content or "").strip()
            if text:
                return _clean(text)
        except Exception as e:
            last_err = e
            if any(x in str(e).lower() for x in ["404", "not found", "does not exist"]):
                continue
            if _is_rate_limit(str(e)):
                _time.sleep(2)
                continue
            raise
    raise RuntimeError(f"All GitHub Models failed. Last: {last_err}")


def _call_openrouter(prompt: str) -> str:
    """Call OpenRouter — cascades through free :free models until one succeeds."""
    last_err = None
    for model in _OPENROUTER_FREE_MODELS:
        try:
            resp = openrouter_ai.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=1500,
                timeout=30,
            )
            text = (resp.choices[0].message.content or "").strip()
            if text:
                return _clean(text)
        except Exception as e:
            last_err = e
            err_str = str(e)
            if _is_rate_limit(err_str):
                _time.sleep(3)   # brief pause between free model attempts
                continue
            if any(x in err_str.lower() for x in ["404", "unavailable", "does not exist", "not found"]):
                continue         # model gone — try next
            raise                # unexpected error — propagate
    raise RuntimeError(f"All OpenRouter free models failed. Last: {last_err}")


def _call_gemini(prompt: str, retries: int = 3) -> str:
    """Call Gemini with backoff. Handles both new google.genai and legacy SDK."""
    if ai is None:
        raise RuntimeError("Gemini not initialised — check GEMINI_API_KEY in secrets.")
    delay = 20
    for attempt in range(retries):
        try:
            if _GENAI_NEW:
                # New google.genai SDK
                response = ai.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                )
                text = response.text
            else:
                # Legacy google.generativeai SDK
                response = ai.generate_content(prompt)
                text = response.text
            return _clean(text)
        except Exception as e:
            if _is_rate_limit(str(e)) and attempt < retries - 1:
                wait = delay * (attempt + 1)
                st.toast(f"⏳ Gemini rate limit — retrying in {wait}s ({attempt+2}/{retries})…")
                _time.sleep(wait)
            else:
                raise
    raise RuntimeError("Gemini quota exceeded after retries.")

def _call_ai(prompt: str) -> str:
    """Smart cascade: Groq → Cerebras → Gemini.
    Skips any provider that has exhausted its daily budget.
    Raises only if ALL providers fail."""
    providers = []
    if groq_ai and _provider_budget_ok("Groq"):
        providers.append(("Groq", _call_groq))
    elif groq_ai:
        st.toast("⚠️ Groq daily limit reached — skipping")
    if cerebras_ai and _provider_budget_ok("Cerebras"):
        providers.append(("Cerebras", _call_cerebras))
    elif cerebras_ai:
        st.toast("⚠️ Cerebras daily limit reached — skipping")
    if openrouter_ai:
        providers.append(("OpenRouter", _call_openrouter))
    if github_ai and _provider_budget_ok("GitHub"):
        providers.append(("GitHub", _call_github))
    if nvidia_ai and _provider_budget_ok("NVIDIA"):
        providers.append(("NVIDIA", _call_nvidia))
    if deepseek_ai and _provider_budget_ok("DeepSeek"):
        providers.append(("DeepSeek", _call_deepseek))
    if _provider_budget_ok("Gemini"):
        providers.append(("Gemini", _call_gemini))
    else:
        st.toast("⚠️ Gemini daily limit reached — skipping")

    if not providers:
        raise RuntimeError(
            "All AI providers have hit their daily limits. "
            "Limits reset at midnight. Come back tomorrow or upgrade your API plan."
        )

    last_err = None
    for name, fn in providers:
        try:
            result = fn(prompt)
            _increment_usage(name)   # track successful call
            return result
        except Exception as e:
            last_err = e
            err_str = str(e)
            if _is_rate_limit(err_str):
                st.toast(f"⏳ {name} rate limit hit — trying next provider…")
                _increment_usage(name)  # count it even if failed — quota was consumed
                continue
            else:
                st.toast(f"⚠️ {name} error: {err_str[:80]} — trying next provider…")
                continue
    raise RuntimeError(
        f"All AI providers failed. Last error: {last_err}\n"
        "Check your API keys in Streamlit secrets."
    )


def _call_ai_grounded(prompt: str) -> str:
    """Call Gemini WITH Google Search grounding. Handles both new and legacy SDK."""
    key = st.secrets.get("GEMINI_API_KEY", "")
    if not key:
        return _call_ai(prompt)
    try:
        if _GENAI_NEW:
            # New google.genai SDK
            from google.genai import types as _gtypes
            client = genai.Client(api_key=key)
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=_gtypes.GenerateContentConfig(
                    tools=[_gtypes.Tool(google_search=_gtypes.GoogleSearch())]
                ),
            )
            raw = response.text.strip()
        else:
            # Legacy SDK
            response = genai.GenerativeModel(
                "gemini-2.5-flash",
                tools=[{"google_search": {}}]
            ).generate_content(prompt)
            raw = response.text.strip()
        return re.sub(r"^```json[\s]*|^```[\s]*|```$", "", raw, flags=re.MULTILINE).strip()
    except Exception:
        pass
    # Ungrounded fallback
    return _call_ai(prompt)


def ai_analyse_partners(awarded_df) -> list:
    """Analyse awarded tender winners to identify CRS channel partner candidates.

    Pre-aggregates data per company before sending to AI to keep the prompt
    compact and the response reliably parseable.
    """
    import re as _re

    df = awarded_df.dropna(subset=["winning_bidder"]).copy()
    if df.empty:
        return []

    # ── Pre-aggregate: group by company so each company = one row ──────────
    agg_rows = []
    grouped = df.groupby("winning_bidder", sort=False)
    for company, grp in grouped:
        company = str(company).strip()
        if not company or len(company) < 3:
            continue
        country  = str(grp["country"].mode().iloc[0]) if "country" in grp else "Unknown"
        titles   = grp["title"].dropna().str[:60].tolist()[:3] if "title" in grp else []
        depts    = grp["department_name"].dropna().str[:50].unique().tolist()[:2] if "department_name" in grp else []
        t_nums   = grp["tender_number"].dropna().str[:30].tolist()[:2] if "tender_number" in grp else []
        agg_rows.append({
            "company":  company[:80],
            "country":  country[:50],
            "wins":     len(grp),
            "titles":   " | ".join(titles),
            "depts":    " | ".join(depts),
            "ref_nos":  " | ".join(t_nums),
        })

    # Sort by wins desc, take top 40 unique companies for analysis
    agg_rows.sort(key=lambda x: x["wins"], reverse=True)
    agg_rows = agg_rows[:40]

    # Build compact table string — much smaller than raw CSV
    lines = ["company|country|wins|sample_tenders|departments|ref_numbers"]
    for r in agg_rows:
        lines.append(f"{r['company']}|{r['country']}|{r['wins']}|{r['titles']}|{r['depts']}|{r['ref_nos']}")
    table_text = "\n".join(lines)

    # Build prompt using % formatting to avoid f-string brace escaping issues
    schema_example = (
        '{"company":"Acme Tech","country":"South Africa","tenders_won":5,'
        '"partner_classification":"System Integrator",'
        '"proposed_solutions":["VECTRA","vRx"],'
        '"key_tenders":["RFQ/2024/001","ICT-2023-045"],'
        '"issuing_departments":["SAPS","Dept of Health"],'
        '"why_aligned":"Wins large ICT integration tenders for government clients.",'
        '"outreach_angle":"Lead with VECTRA NDR — they won the SAPS network monitoring tender.",'
        '"urgency":"high","estimated_deal_size":"large"}'
    )

    prompt = (
        "You are a channel-partner analyst for Cyber Retaliator Solutions (CRS), "
        "a cyber security distributor and IBM/RedHat/SUSE/CompTIA training partner in South Africa.\n\n"
        "CRS VENDOR PORTFOLIO: VECTRA (NDR/XDR), vRx (vuln/patch), Strobes (CTEM/PTaaS), "
        "Aikido (AppSec), Flare (dark web intel), BeachheadSecure (encryption/MFA), "
        "SMBsecure (SMB/POPIA), Telivy (MSSP audit), BlueFlag (SDLC), Standss/SendGuard (email GRC), "
        "CRE/GoldPhish (cyber awareness), VAPT services, IBM/RedHat/SUSE/CompTIA/Agile training.\n\n"
        "PARTNER TYPES: System Integrator | MSP | VAR | Training Provider | Consulting/Advisory | End-user\n\n"
        "AGGREGATED TENDER WIN DATA (pipe-delimited):\n"
        + table_text +
        "\n\nIdentify the TOP 12 companies CRS should approach as channel partners or resellers. "
        "Focus on ICT/security companies — exclude government departments, construction, catering, "
        "cleaning, vehicles, stationery.\n\n"
        "Return ONLY a valid JSON array — no markdown fences, no explanation, no text before or after. "
        "Array must start with [ and end with ]. Each element must follow this exact schema:\n"
        "[" + schema_example + ", ...]"
    )

    raw = _call_ai(prompt)

    # ── Robust JSON extraction ──────────────────────────────────────────────
    import re as _re2
    # Strip markdown fences
    raw = _re2.sub(r"```json[\s]*|```[\s]*", "", raw.strip()).strip()
    # Try direct parse first
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        # Find first [...] block
        m = _re2.search(r"\[[\s\S]*\]", raw)
        if m:
            try:
                parsed = json.loads(m.group(0))
            except json.JSONDecodeError:
                parsed = []
        else:
            # Last resort — salvage individual objects
            parsed = []
            for obj in _re2.findall(r"\{[^{}]+\}", raw):
                try:
                    parsed.append(json.loads(obj))
                except Exception:
                    pass

    # Normalise to list of dicts with a company key
    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list):
        parsed = []
    return [p for p in parsed if isinstance(p, dict) and p.get("company")]


_FENCE_RE = None

def _safe_json(raw: str, expect_list: bool = True):
    """Robustly parse a JSON string from AI output.
    Strips markdown fences, extracts first [...] or {...}, handles partial output."""
    import re as _re
    global _FENCE_RE
    if _FENCE_RE is None:
        _FENCE_RE = _re.compile(r"^```json[\s]*|^```[\s]*|```$", _re.MULTILINE)
    raw = _FENCE_RE.sub("", raw.strip()).strip()
    # Try to extract array or object
    pattern = r"\[.*\]" if expect_list else r"\{.*\}"
    m = _re.search(pattern, raw, _re.DOTALL)
    if m:
        raw = m.group(0)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Salvage complete objects from partial output
        objects = _re.findall(r'\{[^{}]+\}', raw, _re.DOTALL)
        results = []
        for obj in objects:
            try:
                results.append(json.loads(obj))
            except Exception:
                pass
        if expect_list:
            return results
        return results[0] if results else {}


def _call_nvidia(prompt: str) -> str:
    """Call NVIDIA NIM — 100+ open-weight models, 40 RPM free tier.
    Primary: meta/llama-3.3-70b-instruct
    Fallback: mistralai/mistral-large-2411, nvidia/llama-3.3-nemotron-super-49b-v1
    """
    for model in [
        "meta/llama-3.3-70b-instruct",
        "mistralai/mistral-large-2411",
        "nvidia/llama-3.3-nemotron-super-49b-v1",
    ]:
        try:
            resp = nvidia_ai.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=1500,
            )
            text = (resp.choices[0].message.content or "").strip()
            if text:
                return _clean(text)
        except Exception as e:
            err = str(e)
            if any(x in err for x in ["404", "not found", "unknown", "unavailable"]):
                continue
            raise
    raise RuntimeError("All NVIDIA NIM models failed")


def _call_deepseek(prompt: str) -> str:
    """Call DeepSeek API — 5M free tokens on signup, very low cost after.
    deepseek-v4-flash: fast, cheap ($0.28/M input)
    deepseek-v4-pro: frontier quality (~GPT-5 class)
    Note: deepseek-chat/deepseek-reasoner deprecated 2026-07-24, use v4 names.
    """
    for model in ["deepseek-v4-flash", "deepseek-v4-pro"]:
        try:
            resp = deepseek_ai.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=1500,
            )
            text = (resp.choices[0].message.content or "").strip()
            if text:
                return _clean(text)
        except Exception as e:
            err = str(e)
            if any(x in err for x in ["404", "not found", "unknown", "insufficient"]):
                continue
            raise
    raise RuntimeError("All DeepSeek models failed")


def ai_discover_tenders(countries: list, focus: str) -> list:
    """Use Gemini + Google Search to discover private-sector and parastatal
    tenders/RFPs not covered by government portals. Returns a list of dicts."""
    prompt = f"""You are a tender discovery researcher for Cyber Retaliator Solutions (CRS),
a cyber security distributor and IBM/RedHat/SUSE/CompTIA training partner in Africa.

Search the web for CURRENTLY OPEN tenders, RFPs, RFQs, and EOIs that match this focus:
{focus}

Target countries: {', '.join(countries)}

PRIORITIZE non-government sources that national procurement portals do NOT cover:
- Banks and financial institutions (e.g. procurement pages of major African banks)
- Telecommunications companies
- Mining houses and energy companies
- Universities and private hospitals
- Parastatals / state-owned enterprises with their own procurement portals
- Development finance institutions (AfDB, World Bank country procurement notices)

Return ONLY a JSON array (no other text). Each element:
{{
  "title": "tender title",
  "organisation": "issuing company/org",
  "country": "country name",
  "sector": "banking/telco/mining/parastatal/etc",
  "closing_date": "YYYY-MM-DD or null if unknown",
  "description": "1-2 sentence summary",
  "source_url": "direct URL to the tender notice or null"
}}

Only include tenders you have real evidence of from search results. If you cannot find
any current ones, return tenders from organisations' known procurement pages with
closing_date null and note "verify on portal" in the description. Maximum 15 results.
"""
    raw = _call_ai_grounded(prompt)
    parsed = _safe_json(raw, expect_list=True)
    return parsed if isinstance(parsed, list) else []

# ─────────────────────────────────────────────
# 4b. AI USAGE TRACKER
# Tracks per-provider daily request counts in Supabase so limits persist
# across browser sessions. Falls back to session-state-only if table missing.
# ─────────────────────────────────────────────
import datetime as _dt

# Free-tier daily limits (requests/day)
_AI_DAILY_LIMITS = {
    "Groq":       1000,   # 1 000 req/day on free tier
    "Cerebras":   500,    # conservative — token-based (~1M tokens/day)
    "OpenRouter": 200,    # ~200 req/day on :free models
    "GitHub":     150,    # 150 req/day on free GitHub Copilot tier
    "NVIDIA":     200,    # ~40 RPM, ~1000 credits/day free tier
    "DeepSeek":   500,    # 5M free tokens on signup, then very cheap
    "Gemini":     20,     # 20 req/day on 2.5 Flash free tier
}
# Minimum minutes between full AI operations (score-all, partner analysis, lead discovery)
_AI_OP_COOLDOWN_MINUTES = {
    "score_all":         5,
    "partner_analysis":  10,
    "lead_discovery":    15,   # burns 2 calls (stage1 + stage2)
    "tender_parser":     1,
    "tender_discovery":  10,
}

def _today_str() -> str:
    return _dt.date.today().isoformat()

def _get_usage() -> dict:
    """Load today's usage counts. Returns {provider: count}."""
    today = _today_str()
    if "ai_usage" not in st.session_state or st.session_state.get("ai_usage_date") != today:
        st.session_state["ai_usage"] = {p: 0 for p in _AI_DAILY_LIMITS}
        st.session_state["ai_usage_date"] = today
        st.session_state["ai_last_ops"] = {}
        # Try to load persisted count from Supabase
        try:
            row = supabase.table("ai_usage_log").select("*").eq("usage_date", today).execute()
            if row.data:
                for entry in row.data:
                    provider = entry.get("provider","")
                    if provider in st.session_state["ai_usage"]:
                        st.session_state["ai_usage"][provider] = entry.get("count", 0)
        except Exception:
            pass  # table may not exist yet — session state only
    return st.session_state["ai_usage"]

def _increment_usage(provider: str):
    """Increment usage counter for a provider and persist to Supabase."""
    usage = _get_usage()
    usage[provider] = usage.get(provider, 0) + 1
    try:
        today = _today_str()
        supabase.table("ai_usage_log").upsert(
            {"usage_date": today, "provider": provider, "count": usage[provider]},
            on_conflict="usage_date,provider"
        ).execute()
    except Exception:
        pass  # non-critical — session state already updated

def _check_cooldown(op_key: str) -> tuple[bool, int]:
    """Returns (can_run, minutes_remaining). Updates last-op timestamp if can_run."""
    if "ai_last_ops" not in st.session_state:
        st.session_state["ai_last_ops"] = {}
    cooldown_mins = _AI_OP_COOLDOWN_MINUTES.get(op_key, 5)
    last = st.session_state["ai_last_ops"].get(op_key)
    if last is None:
        return True, 0
    elapsed = (_dt.datetime.now() - last).total_seconds() / 60
    if elapsed >= cooldown_mins:
        return True, 0
    return False, int(cooldown_mins - elapsed) + 1

def _record_op(op_key: str):
    """Record that an AI operation just ran."""
    if "ai_last_ops" not in st.session_state:
        st.session_state["ai_last_ops"] = {}
    st.session_state["ai_last_ops"][op_key] = _dt.datetime.now()

def _provider_budget_ok(provider: str) -> bool:
    """True if this provider still has daily budget remaining."""
    usage = _get_usage()
    return usage.get(provider, 0) < _AI_DAILY_LIMITS.get(provider, 999)

def _usage_sidebar():
    """Render a compact usage meter in the sidebar."""
    usage = _get_usage()
    st.sidebar.markdown("**AI Usage Today**")
    for provider, limit in _AI_DAILY_LIMITS.items():
        used  = usage.get(provider, 0)
        pct   = min(used / limit, 1.0)
        color = "🟢" if pct < 0.7 else "🟡" if pct < 0.9 else "🔴"
        st.sidebar.caption(f"{color} {provider}: {used}/{limit}")


# ─────────────────────────────────────────────
# 5. DATA FETCHING
# ─────────────────────────────────────────────
@st.cache_data(ttl=300)
def fetch_tenders():
    """Fetch OPEN tenders only from sa_tenders (non-irrelevant)."""
    try:
        response = supabase.table("sa_tenders").select("*")            .neq("status", "Awarded")            .neq("is_irrelevant", True)            .execute()
        return pd.DataFrame(response.data)
    except Exception as e:
        st.error(f"Error fetching open tenders: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=300)
def fetch_awarded_tenders():
    """Fetch awarded tenders from the dedicated awarded_tenders table.
    Uses select("*") — returns all 5000+ records regardless of open-tender country filter."""
    try:
        response = supabase.table("awarded_tenders").select("*").execute()
        df = pd.DataFrame(response.data)
        if df.empty:
            raise ValueError("awarded_tenders table is empty or missing")
        return df
    except Exception:
        # Fallback: try old sa_tenders awarded rows if migration not yet run
        try:
            r2 = supabase.table("sa_tenders").select("*").eq("status", "Awarded").execute()
            return pd.DataFrame(r2.data)
        except Exception:
            return pd.DataFrame()

@st.cache_data(ttl=600)
def fetch_awarded_countries() -> list:
    """Get distinct countries from awarded_tenders — separate from open tender countries."""
    try:
        r = supabase.table("awarded_tenders").select("country").execute()
        return sorted({row["country"] for row in r.data if row.get("country")})
    except Exception:
        return []

# ─────────────────────────────────────────────
# 6. AI HELPERS
# ─────────────────────────────────────────────

def ai_parse_tender(raw_text: str) -> dict:
    """Extract structured fields from raw tender text using Claude."""
    prompt = f"""You are a government tender analyst. Extract structured information from the following tender text.

Return ONLY a valid JSON object with these exact keys:
{{
  "tender_number": "string or null",
  "title": "string",
  "department_name": "string or null",
  "description": "string",
  "issue_date": "YYYY-MM-DD or null",
  "closing_date": "YYYY-MM-DD or null",
  "award_value": "string or null",
  "compliance_requirements": "string summarising key requirements",
  "status": "Open",
  "winning_bidder": null
}}

Do not include any text outside the JSON object.

TENDER TEXT:
{raw_text}
"""
    raw = _call_ai(prompt)
    return _safe_json(raw, expect_list=False)


def ai_score_tender(tender: dict) -> dict:
    """Score a tender 1-10 as a CRS partner opportunity.
    
    Logic: CRS does NOT respond to tenders directly. Instead, CRS identifies
    in-country partners (SIs, MSPs, VARs, Training Providers) who can respond
    to the tender and who CRS should approach to supply the relevant products/services.
    
    Returns {score, rationale, partner_type, proposed_solutions, outreach_angle}.
    """
    country = tender.get("country", "South Africa")
    title   = tender.get("title", "N/A")
    dept    = tender.get("department_name", "N/A")
    desc    = tender.get("description", "N/A")
    value   = tender.get("award_value", "Unknown")
    closing = tender.get("closing_date", "N/A")
    compliance = tender.get("compliance_requirements", "N/A")

    prompt = (
        "You are a channel-partner strategist for Cyber Retaliator Solutions (CRS), "
        "a South African cyber security distributor and training partner.\n\n"
        "IMPORTANT: CRS does NOT respond to tenders directly. "
        "CRS sells through in-country channel partners "
        "(System Integrators, MSPs, VARs, Training Providers, Consultancies). "
        "Your job is to score this tender as a PARTNER OPPORTUNITY — "
        "i.e. how urgently should CRS find and activate a local partner to respond to this tender "
        "on behalf of CRS's vendor portfolio?\n\n"
        "CRS VENDOR PORTFOLIO (solutions to propose through partners):\n"
        "VECTRA (NDR/XDR/ITDR), vRx (vuln/patch mgmt), Strobes (CTEM/PTaaS/ASM), "
        "Aikido (AppSec/DevSecOps), Flare (dark web/threat intel), "
        "BeachheadSecure (encryption/MFA/POPIA), SMBsecure (SMB all-in-one), "
        "Telivy (MSSP audit), BlueFlag (SDLC security), Standss/SendGuard (email GRC), "
        "CRE/GoldPhish/Prventi (cyber awareness/SAT), VAPT (pentest services), "
        "IBM/RedHat/SUSE/CompTIA/Agile SAFe training.\n\n"
        f"TENDER:\n"
        f"Country: {country}\n"
        f"Title: {title}\n"
        f"Department: {dept}\n"
        f"Description: {desc}\n"
        f"Compliance: {compliance}\n"
        f"Closing Date: {closing}\n"
        f"Value: {value}\n\n"
        "SCORING GUIDE (partner opportunity score 1-10):\n"
        "9-10 = High-value ICT/security tender — CRS must urgently find/activate a local partner\n"
        "7-8  = Good fit — worth proactively contacting existing in-country partners\n"
        "5-6  = Partial fit — one or two CRS solutions relevant, lower priority\n"
        "3-4  = Weak fit — mostly non-ICT but has a technology component\n"
        "1-2  = Not relevant — construction, catering, vehicles, stationery, etc.\n\n"
        "PARTNER TYPE DEFINITIONS:\n"
        "System Integrator: large ICT integration and implementation projects\n"
        "MSP: managed services, SOC, monitoring, helpdesk contracts\n"
        "VAR: supply and install of hardware/software\n"
        "Training Provider: training, skills development, learnerships\n"
        "Consulting/Advisory: assessments, audits, strategy, GRC\n\n"
        "Return ONLY a valid JSON object, no markdown, no extra text:\n"
        '{"score":<1-10>,'
        '"rationale":"2-3 sentences: why this is a partner opportunity, which CRS solutions fit, urgency",'
        '"partner_type":"System Integrator|MSP|VAR|Training Provider|Consulting/Advisory",'
        '"proposed_solutions":["sol1","sol2"],'
        '"outreach_angle":"one sentence — what CRS should say to a local partner to get them to respond"}'
    )

    raw = _call_ai(prompt)
    try:
        result = _safe_json(raw, expect_list=False)
        if not isinstance(result, dict):
            result = {}
    except Exception:
        result = {}

    # Normalise — ensure score is always present
    if "score" not in result:
        # Try to extract score from raw text as fallback
        import re as _re
        m = _re.search(r'"score"[\s]*:[\s]*(\d+)', raw)
        result["score"] = int(m.group(1)) if m else 5
    if "rationale" not in result:
        result["rationale"] = raw[:300] if raw else "No rationale returned."

    return result


# Seconds between scoring calls — Groq allows 30 RPM so 2s is safe; Gemini-only needs 13s
_SCORE_THROTTLE_SECS = 2

def ai_match_tenders(open_df: pd.DataFrame) -> pd.DataFrame:
    """Score UNSCORED open tenders only, throttled to stay within free-tier limits.
    Already-scored tenders are skipped to avoid wasting quota."""
    import time
    if open_df.empty:
        return open_df

    # Only score tenders that don't already have a score
    unscored = open_df[open_df["ai_score"].isna()].copy()
    already_scored = open_df[open_df["ai_score"].notna()].copy()

    if unscored.empty:
        st.info("All visible tenders are already scored. Clear scores in Supabase to re-run.")
        return open_df.sort_values("ai_score", ascending=False, na_position="last")

    st.caption(
        f"Scoring {len(unscored)} unscored tenders "
        f"({len(already_scored)} already scored, skipping). "
        f"Free tier: ~1 request per {_SCORE_THROTTLE_SECS}s — est. "
        f"{len(unscored) * _SCORE_THROTTLE_SECS // 60 + 1} min."
    )

    results = []
    progress = st.progress(0, text="Starting AI scoring…")

    for i, (_, row) in enumerate(unscored.iterrows()):
        pct = (i + 1) / len(unscored)
        progress.progress(pct, text=f"Scoring {i+1}/{len(unscored)}: {str(row.get('tender_number', ''))[:40]}")

        try:
            scored = ai_score_tender(row.to_dict())
            import json as _bj
            _rat_json = _bj.dumps({
                "rationale":          scored.get("rationale", ""),
                "partner_type":       scored.get("partner_type", ""),
                "proposed_solutions": scored.get("proposed_solutions", []),
                "outreach_angle":     scored.get("outreach_angle", ""),
            })
            results.append({
                "tender_number": row["tender_number"],
                "ai_score":      scored["score"],
                "ai_rationale":  _rat_json,
            })
            supabase.table("sa_tenders").update({
                "ai_score":    scored["score"],
                "ai_rationale": _rat_json,
            }).eq("tender_number", row["tender_number"]).execute()
        except Exception as e:
            results.append({
                "tender_number": row["tender_number"],
                "ai_score": None,
                "ai_rationale": f"Scoring failed: {e}",
            })

        # Throttle — don't fire next request immediately
        if i < len(unscored) - 1:
            time.sleep(_SCORE_THROTTLE_SECS)

    progress.empty()

    if results:
        scores_df = pd.DataFrame(results)
        unscored = unscored.merge(scores_df, on="tender_number", how="left", suffixes=("", "_new"))
        if "ai_score_new" in unscored.columns:
            unscored["ai_score"] = unscored["ai_score_new"].combine_first(unscored["ai_score"])
            unscored["ai_rationale"] = unscored["ai_rationale_new"].combine_first(unscored["ai_rationale"])
            unscored.drop(columns=["ai_score_new", "ai_rationale_new"], inplace=True)

    combined = pd.concat([already_scored, unscored], ignore_index=True)
    return combined.sort_values("ai_score", ascending=False, na_position="last")


# ─────────────────────────────────────────────
# 7. SCORE BADGE HELPER
# ─────────────────────────────────────────────
def copy_button(text: str, label: str = "📋 Copy", key: str = "copy") -> None:
    """Render a small copy-to-clipboard button using an HTML component.
    Escapes the text so any quotes or newlines are safe inside JS."""
    import streamlit.components.v1 as _comp
    import html as _html
    safe = _html.escape(str(text), quote=True).replace("\n", "&#10;").replace("\r", "")
    unique = abs(hash(key + text[:30])) % 10_000_000
    _comp.html(f"""
<style>
#cbtn_{unique} {{
    background: #1e3a5f; color: #e8f0fe; border: 1px solid #3a6fa8;
    border-radius: 6px; padding: 4px 12px; font-size: 13px;
    cursor: pointer; font-family: sans-serif; transition: background 0.2s;
}}
#cbtn_{unique}:hover {{ background: #2a5298; }}
#cbtn_{unique}.copied {{ background: #1a5c2e; border-color: #2d9e52; color: #b7ffd0; }}
</style>
<button id="cbtn_{unique}"
  onclick="navigator.clipboard.writeText(decodeURIComponent('{safe}'.replace(/&#10;/g,'\\n')));
           this.textContent='✅ Copied!'; this.classList.add('copied');
           setTimeout(()=>{{this.textContent='{label}';this.classList.remove('copied')}},2000)">
  {label}
</button>""", height=38)


def format_tender_card(t) -> str:
    """Format a tender row as plain text for clipboard."""
    lines = [
        f"TENDER: {t.get('tender_number','N/A')}",
        f"Title: {t.get('title','N/A')}",
        f"Department: {t.get('department_name','N/A')}",
        f"Country: {t.get('country','N/A')}",
        f"Closing Date: {t.get('closing_date','N/A')}",
        f"Description: {t.get('description','N/A')}",
    ]
    if t.get('compliance_requirements'):
        lines.append(f"Compliance: {t.get('compliance_requirements')}")
    if t.get('contact_person'):
        lines.append(f"Contact Person: {t.get('contact_person')}")
    if t.get('contact_email'):
        lines.append(f"Contact Email: {t.get('contact_email')}")
    if t.get('contact_phone'):
        lines.append(f"Contact Phone: {t.get('contact_phone')}")
    if t.get('ai_score'):
        lines.append(f"Partner Opportunity Score: {t.get('ai_score')}/10")
    if t.get('ai_rationale'):
        _rat_raw = t.get('ai_rationale', '')
        try:
            import json as _fj
            _rp = _fj.loads(_rat_raw) if str(_rat_raw).strip().startswith("{") else {}
        except Exception:
            _rp = {}
        if _rp:
            if _rp.get('partner_type'):       lines.append(f"Partner Type: {_rp['partner_type']}")
            if _rp.get('proposed_solutions'): lines.append(f"Proposed Solutions: {', '.join(_rp['proposed_solutions'])}")
            if _rp.get('rationale'):          lines.append(f"Rationale: {_rp['rationale']}")
            if _rp.get('outreach_angle'):     lines.append(f"Outreach Angle: {_rp['outreach_angle']}")
        else:
            lines.append(f"Analysis: {_rat_raw}")
    if t.get('portal_link'):
        lines.append(f"Portal Link: {t.get('portal_link')}")
    return "\n".join(lines)


def format_partner_card(p) -> str:
    """Format a partner analysis result as plain text for clipboard."""
    solutions = ", ".join(p.get("proposed_solutions") or [])
    tenders   = ", ".join(str(t) for t in (p.get("key_tenders") or [])[:3])
    depts     = ", ".join(str(d) for d in (p.get("issuing_departments") or [])[:3])
    lines = [
        f"PARTNER: {p.get('company','N/A')}",
        f"Country: {p.get('country','N/A')}",
        f"Partner Type: {p.get('partner_classification') or p.get('partnership_type','N/A')}",
        f"Tenders Won: {p.get('tenders_won','?')}",
        f"Urgency: {p.get('urgency','N/A').upper()}",
        f"Deal Size: {p.get('estimated_deal_size','N/A')}",
        f"Proposed Solutions: {solutions}",
        f"Key Tenders: {tenders}",
        f"Departments Served: {depts}",
        f"Why Aligned: {p.get('why_aligned','')}",
        f"Outreach Angle: {p.get('outreach_angle','')}",
    ]
    return "\n".join(lines)


def format_lead_card(co, enriched: dict = None) -> str:
    """Format a lead intelligence company card as plain text for clipboard."""
    solutions = ", ".join(co.get("proposed_solutions") or [])
    lines = [
        f"LEAD: {co.get('name','N/A')}",
        f"Lead Type: {co.get('lead_type','N/A')}",
        f"Country: {co.get('country','N/A')}",
        f"CRS Score: {co.get('crs_score','?')}/10",
        f"Urgency: {co.get('urgency','N/A').upper()}",
        f"Proposed Solutions: {solutions}",
        f"Why Now: {co.get('why','')}",
        f"Outreach Angle: {co.get('outreach_angle','')}",
    ]
    if enriched:
        if enriched.get("employees"):
            lines.append(f"Employees: {enriched['employees']}")
        if enriched.get("revenue"):
            lines.append(f"Revenue: {enriched['revenue']}")
        if enriched.get("tech_stack"):
            lines.append(f"Tech Stack: {', '.join(enriched['tech_stack'])}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# GITHUB SYNC MODULE
# ═══════════════════════════════════════════════════════════════════════════

_GH_REPO   = "Drys-CRS/CRS-Lead-Gen"
_GH_BRANCH = "main"

# All files managed by the sync system: repo_path → local filename
_GH_FILES = {
    "app/streamlit_app.py": "streamlit_app.py",
    "app/monday_client.py": "monday_client.py",
}

def _gh_headers() -> dict:
    token = ""
    for k in ("GITHUB_TOKEN", "GH_PAT", "github_token"):
        try:
            v = st.secrets[k]
            if v:
                token = str(v).strip()
                break
        except Exception:
            pass
    if not token:
        token = (st.secrets.get("GITHUB_TOKEN") or
                 st.secrets.get("GH_PAT") or "").strip()
    if not token:
        raise ValueError("No GitHub token found. Add GITHUB_TOKEN to Streamlit secrets.")
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
    }

def _gh_base() -> str:
    return f"https://api.github.com/repos/{_GH_REPO}/contents"

def github_get_file_info(repo_path: str) -> dict:
    """Fetch metadata + content of a single file from GitHub.
    Returns dict with sha, size, last_modified, content_b64, decoded lines."""
    import requests as _req, base64 as _b64
    r = _req.get(
        f"{_gh_base()}/{repo_path}",
        headers=_gh_headers(),
        params={"ref": _GH_BRANCH},
        timeout=15,
    )
    if r.status_code != 200:
        return {"error": f"HTTP {r.status_code}: {r.json().get('message','?')}"}
    d = r.json()
    raw = _b64.b64decode(d.get("content","").replace("\n",""))
    return {
        "sha":           d.get("sha",""),
        "size":          d.get("size", 0),
        "html_url":      d.get("html_url",""),
        "last_modified": d.get("last_modified",""),
        "content":       raw.decode("utf-8", errors="replace"),
        "lines":         len(raw.decode("utf-8", errors="replace").splitlines()),
    }

def github_diff_file(repo_path: str, local_path: str) -> dict:
    """Compare local file to GitHub version.
    Returns {changed: bool, added: int, removed: int, summary: str}"""
    import difflib, os as _os
    remote = github_get_file_info(repo_path)
    if "error" in remote:
        return {"changed": True, "added": 0, "removed": 0,
                "summary": f"Cannot compare — {remote['error']}"}
    try:
        with open(local_path) as f:
            local_lines = f.readlines()
    except FileNotFoundError:
        return {"changed": False, "added": 0, "removed": 0,
                "summary": "Local file not found"}

    remote_lines = remote["content"].splitlines(keepends=True)
    diff = list(difflib.unified_diff(remote_lines, local_lines,
                                     fromfile=f"github/{repo_path}",
                                     tofile=f"local/{repo_path}", n=0))
    added   = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))
    changed = added > 0 or removed > 0
    summary = f"+{added} lines / -{removed} lines" if changed else "Up to date"
    return {"changed": changed, "added": added, "removed": removed,
            "summary": summary, "diff": "".join(diff[:120])}  # cap diff preview

def github_push_file(repo_path: str, local_path: str,
                     commit_message: str, sha: str = None) -> dict:
    """Push a single local file to GitHub. sha required for updates."""
    import base64 as _b64, requests as _req
    try:
        with open(local_path, "rb") as f:
            encoded = _b64.b64encode(f.read()).decode()
    except FileNotFoundError:
        return {"ok": False, "message": f"Local file not found: {local_path}"}

    payload = {"message": commit_message, "content": encoded, "branch": _GH_BRANCH}
    if sha:
        payload["sha"] = sha

    r = _req.put(f"{_gh_base()}/{repo_path}",
                 headers=_gh_headers(), json=payload, timeout=30)
    if r.status_code in (200, 201):
        commit_sha = r.json().get("commit",{}).get("sha","")[:7]
        action = "updated" if sha else "created"
        return {"ok": True, "message": f"{repo_path} {action} — commit {commit_sha}",
                "commit_sha": commit_sha}
    return {"ok": False,
            "message": f"{repo_path}: HTTP {r.status_code} — {r.json().get('message','?')}"}

def github_push_all(commit_message: str = None, files: list = None) -> dict:
    """Push one or all managed files to GitHub.
    files: list of repo_paths to push (None = all)"""
    import datetime, os as _os
    if not commit_message:
        ts = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        commit_message = f"chore: CRS Dashboard auto-sync [{ts}]"

    app_dir  = _os.path.dirname(_os.path.abspath(__file__))
    to_push  = files or list(_GH_FILES.keys())
    results  = []
    any_fail = False

    for repo_path in to_push:
        local_name = _GH_FILES.get(repo_path)
        if not local_name:
            results.append({"file": repo_path, "ok": False,
                            "message": "Not in managed file list"})
            continue
        local_path = _os.path.join(app_dir, local_name)
        # Get current SHA
        info = github_get_file_info(repo_path)
        sha  = info.get("sha") if "error" not in info else None
        res  = github_push_file(repo_path, local_path, commit_message, sha)
        res["file"] = repo_path
        results.append(res)
        if not res["ok"]:
            any_fail = True

    return {"ok": not any_fail, "results": results,
            "commit_message": commit_message}

def github_get_recent_commits(n: int = 5) -> list:
    """Fetch the last n commits on the main branch."""
    import requests as _req
    try:
        r = _req.get(
            f"https://api.github.com/repos/{_GH_REPO}/commits",
            headers=_gh_headers(),
            params={"sha": _GH_BRANCH, "per_page": n},
            timeout=10,
        )
        if r.status_code != 200:
            return []
        return [
            {
                "sha":     c["sha"][:7],
                "message": c["commit"]["message"].split("\n")[0][:80],
                "author":  c["commit"]["author"]["name"],
                "date":    c["commit"]["author"]["date"][:16].replace("T"," "),
                "url":     c["html_url"],
            }
            for c in r.json()
        ]
    except Exception:
        return []


def score_badge(score):
    if score is None or pd.isna(score):
        return "⚪ —"
    score = int(score)
    if score >= 8:
        return f"🟢 {score}/10"
    elif score >= 5:
        return f"🟡 {score}/10"
    else:
        return f"🔴 {score}/10"


# ─────────────────────────────────────────────
# 8. SCRAPER ENGINE  (runs in-process, no subprocess)
# ─────────────────────────────────────────────

TARGET_KEYWORDS = [
    # ── Technical Training (IBM / RedHat / SUSE / CompTIA / AI) ──
    "ibm training", "ibm technical training", "ibm certification",
    "red hat training", "redhat training", "red hat certification", "rhcsa", "rhce",
    "suse training", "suse certification", "linux training", "linux certification",
    "comptia", "security+", "network+", "a+ certification", "cysa",
    "ai training", "artificial intelligence training", "machine learning training",
    "technical training", "ict training", "it training", "cybersecurity training",
    "cyber security training", "information security training", "security awareness training",
    "training and certification", "skills development", "capacity building ict",
    "learnership ict", "training provider", "accredited training",
    # ── Platform / OS skills CRS trains on ──
    "z/os", "ibm i", "ibm power", "mainframe", "red hat", "redhat", "suse", "rhel",
    # ── NDR / XDR / Threat Detection (Vectra) ──
    "ndr", "network detection and response", "xdr", "extended detection",
    "threat detection", "threat hunting", "attack detection", "intrusion detection",
    "cloud detection and response", "identity threat detection", "itdr",
    "managed detection", "mdr", "soc", "security operations centre", "security operations center",
    # ── Vulnerability & Patch Management (vRx / Strobes / Telivy) ──
    "vulnerability management", "vulnerability assessment", "vulnerability scanning",
    "patch management", "penetration testing", "pentest", "vapt",
    "attack surface management", "risk based vulnerability", "ctem",
    "threat exposure management", "security assessment", "security audit",
    # ── AppSec / DevSecOps (Aikido / BlueFlag) ──
    "application security", "sast", "dast", "sca", "devsecops",
    "code security", "secure development", "software supply chain",
    "container security", "cloud security posture", "cspm", "secrets detection",
    # ── Data Protection & Endpoint (BeachheadSecure / SMBsecure) ──
    "endpoint security", "endpoint protection", "edr", "encryption",
    "data protection", "data security", "data loss prevention", "dlp",
    "bitlocker", "mobile device management", "mdm", "popia compliance",
    "multi-factor authentication", "mfa", "access control",
    # ── Threat Intel / Dark Web (Flare) ──
    "threat intelligence", "cyber threat intelligence", "dark web monitoring",
    "digital risk protection", "brand protection", "credential monitoring",
    "leaked credentials", "ransomware", "takedown",
    # ── Phishing & Awareness (Cyber Risk Essentials) ──
    "phishing simulation", "phishing awareness", "cyber awareness",
    "security culture", "awareness programme", "awareness program",
    # ── General cyber & ICT infrastructure ──
    "cyber", "cybersecurity", "cyber security", "cyber risk", "cyber defence", "cyber defense",
    "incident response", "cyber incident", "firewall", "siem",
    "security orchestration", "soar", "zero trust",
    "identity and access management", "iam", "network security", "cloud security",
    "information security", "infosec", "iso 27001", "nist",
    "information technology", "ict", "ict infrastructure",
    "software licence", "software license", "software procurement",
    "server", "cloud", "infrastructure", "data center", "data centre",
]

import re as _re

# Pre-compile: short keywords (<=5 chars) use word boundaries to avoid
# false positives like "ndr" matching inside "laundry" or "iam" in "diameter".
_KW_PATTERNS = []
for _kw in TARGET_KEYWORDS:
    _k = _kw.lower().strip()
    if len(_k) <= 5:
        _KW_PATTERNS.append(_re.compile(r"\b" + _re.escape(_k) + r"\b"))
    else:
        _KW_PATTERNS.append(_re.compile(_re.escape(_k)))

def _is_relevant(text: str) -> bool:
    lower = text.lower()
    return any(p.search(lower) for p in _KW_PATTERNS)

def _upsert_awarded(records: list, country: str, label: str, status_container):
    """Upsert awarded tenders into the dedicated awarded_tenders table.
    Never deletes — history accumulates indefinitely."""
    if not records:
        return 0
    ok, failed, first_err = 0, 0, None
    for r in records:
        # Remove status field — awarded_tenders table doesn't need it
        row = {k: v for k, v in r.items() if k != "status"}
        try:
            supabase.table("awarded_tenders").upsert(
                row, on_conflict="tender_number,department_name,country"
            ).execute()
            ok += 1
        except Exception as e:
            failed += 1
            if first_err is None:
                first_err = str(e)[:200]
    msg = f"  ✅ {country} — {label}: {ok} saved to awarded_tenders"
    if failed:
        msg += f" | ❌ {failed} failed (first: {first_err})"
    status_container(msg)
    return ok


def _upsert(records: list, country: str, label: str, status_container):
    if not records:
        return 0
    ok, failed, first_err = 0, 0, None
    for r in records:
        try:
            supabase.table("sa_tenders").upsert(r, on_conflict="tender_number,department_name").execute()
            ok += 1
        except Exception as e:
            failed += 1
            if first_err is None:
                first_err = str(e)[:200]
    msg = f"  ✅ {country} — {label}: {ok} saved"
    if failed:
        msg += f" | ❌ {failed} failed (first error: {first_err})"
    status_container(msg)
    return ok

def _get_json(url, params=None, headers=None, timeout=20, retries=3):
    """GET JSON with retries for transient DNS/connection failures."""
    import requests, time
    h = {"User-Agent": "Mozilla/5.0", "X-Requested-With": "XMLHttpRequest",
         "Accept": "application/json"}
    if headers:
        h.update(headers)
    last_err = None
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=h, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))  # 2s, 4s backoff
    raise last_err

def _get_html(url, timeout=20):
    import requests
    from bs4 import BeautifulSoup
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")

# ── South Africa ──────────────────────────────────────────────────────────────
def scrape_south_africa(out):
    country = "South Africa"
    out(f"🇿🇦 Scraping {country}…")
    from datetime import datetime, timedelta

    cutoff = "2015-01-01"  # eTenders holds data back to ~2015

    try:
        # ── OPEN tenders (replace fully — these change daily) ────────────────
        supabase.table("sa_tenders").delete().eq("status", "Open").eq("country", country).execute()
        open_records, start = [], 0
        while True:
            data = _get_json("https://www.etenders.gov.za/Home/PaginatedTenderOpportunities", {
                "draw": "1", "start": str(start), "length": "500",
                "status": "1", "search[value]": "", "search[regex]": "false",
                "order[0][column]": "2", "order[0][dir]": "desc",
            })
            batch = data.get("data", [])
            if not batch:
                break
            for t in batch:
                text = f"{t.get('description','')} {t.get('category','')}"
                if not _is_relevant(text):
                    continue
                open_records.append({
                    "tender_number": t.get("tender_No", ""),
                    "department_name": t.get("department", ""),
                    "title": str(t.get("description", ""))[:200],
                    "description": t.get("description", ""),
                    "category": t.get("category", ""),
                    "compliance_requirements": t.get("conditions", "Not specified"),
                    "portal_link": "https://www.etenders.gov.za/Home/opportunities?id=1",
                    "issue_date": t.get("date_Published"),
                    "closing_date": t.get("closing_Date"),
                    "contact_person": str(t.get("contactPerson") or t.get("contact_person") or "")[:200],
                    "contact_email":  str(t.get("contactEmail")  or t.get("contact_email")  or t.get("email") or "")[:200],
                    "contact_phone":  str(t.get("contactPhone")  or t.get("contact_phone")  or t.get("phone") or "")[:50],
                    "status": "Open", "award_status": "Published", "country": country,
                })
            start += len(batch)
            if start >= int(data.get("recordsTotal", 0)):
                break
        _upsert(open_records, country, "Open", out)

        # ── AWARDED tenders: paginate back 12 months, UPSERT only (keep history) ──
        out(f"  🇿🇦 Fetching awarded tenders back to {cutoff}…")
        awarded_records, start = [], 0
        stop_early = False
        while not stop_early:
            data2 = _get_json("https://www.etenders.gov.za/Home/PaginatedTenderOpportunities", {
                "draw": "1", "start": str(start), "length": "500", "status": "2",
            })
            batch = data2.get("data", [])
            if not batch:
                break
            for t in batch:
                # eTenders returns results newest-first; stop when we pass the cutoff
                award_date = (t.get("closing_Date") or t.get("date_Published") or "")[:10]
                if award_date and award_date < cutoff:
                    stop_early = True
                    break
                text = f"{t.get('description','')} {t.get('category','')}"
                if not _is_relevant(text):
                    continue
                companies = t.get("company", [])
                winner, amount = "Not Disclosed", "Not Disclosed"
                if companies and isinstance(companies, list):
                    winner = companies[0].get("company", "Unknown")
                    amount = companies[0].get("tenderAmount", "Not Disclosed")
                if winner == "Not Disclosed":
                    winner = t.get("bidders") or "Unknown"
                    amount = t.get("tenderAmount") or "Not Disclosed"
                awarded_records.append({
                    "tender_number": t.get("tender_No", ""),
                    "department_name": t.get("department", ""),
                    "title": str(t.get("description", ""))[:200],
                    "description": t.get("description", ""),
                    "status": "Awarded", "winning_bidder": winner,
                    "award_value": str(amount), "country": country,
                    "contact_person": str(t.get("contactPerson") or t.get("contact_person") or "")[:200],
                    "contact_email":  str(t.get("contactEmail")  or t.get("contact_email")  or t.get("email") or "")[:200],
                    "contact_phone":  str(t.get("contactPhone")  or t.get("contact_phone")  or t.get("phone") or "")[:50],
                })
            start += len(batch)
            if start >= int(data2.get("recordsTotal", 0)):
                break
        # Write to dedicated awarded_tenders table — never wiped
        _upsert_awarded(awarded_records, country, "Awarded (all history)", out)

    except Exception as e:
        out(f"  ❌ {country} error: {e}")

# ── OCDS Registry scraper (Kenya, Ghana, Tanzania, Uganda, Nigeria, Zambia, Rwanda) ──
# Downloads standardised OCDS data from the Open Contracting Data Registry:
# https://data.open-contracting.org — one consistent JSONL format for all countries.

OCDS_REGISTRY = {
    # country: (publication_id, flag)
    # Verified publication IDs from data.open-contracting.org 2026-06-11
    # South Africa is FALLBACK only — live eTenders API is primary
    "South Africa": (143, "🇿🇦"),
    "Kenya":        (147, "🇰🇪"),   # PPIP — daily updates
    "Nigeria":      (64,  "🇳🇬"),   # BPP NoCoPo
    "Ghana":        (85,  "🇬🇭"),   # GHANEPS
    "Tanzania":     (152, "🇹🇿"),   # PPRA/NeST
    "Uganda":       (130, "🇺🇬"),   # PPDA
    "Zambia":       (3,   "🇿🇲"),   # ZPPA
    "Rwanda":       (145, "🇷🇼"),   # RPPA
    "Liberia":      (79,  "🇱🇷"),   # PPCC
}

# Countries on target list WITHOUT OCDS — scraped via World Bank / UNDP / AfDB notices
# and AI-grounded discovery. Grouped for the secondary scraper.
NON_OCDS_COUNTRIES = {
    # country: (flag, region)
    "Angola":               ("🇦🇴", "Southern Africa"),
    "Botswana":             ("🇧🇼", "Southern Africa"),
    "Egypt":                ("🇪🇬", "North Africa"),
    "Eritrea":              ("🇪🇷", "East Africa"),
    "Eswatini":             ("🇸🇿", "Southern Africa"),
    "Ethiopia":             ("🇪🇹", "East Africa"),
    "The Gambia":           ("🇬🇲", "West Africa"),
    "Lesotho":              ("🇱🇸", "Southern Africa"),
    "Libya":                ("🇱🇾", "North Africa"),
    "Malawi":               ("🇲🇼", "East Africa"),
    "Mauritius":            ("🇲🇺", "Indian Ocean"),
    "Mozambique":           ("🇲🇿", "Southern Africa"),
    "Namibia":              ("🇳🇦", "Southern Africa"),
    "Republic of South Sudan": ("🇸🇸", "East Africa"),
    "Seychelles":           ("🇸🇨", "Indian Ocean"),
    "Sierra Leone":         ("🇸🇱", "West Africa"),
    "Somalia":              ("🇸🇴", "East Africa"),
    "Sudan":                ("🇸🇩", "East Africa"),
    "Zimbabwe":             ("🇿🇼", "Southern Africa"),
}

def _download_ocds_year(pub_id: int, year: int):
    """Download and decompress one year's JSONL from the OCDS registry.
    Returns list of text lines, or None if unavailable."""
    import requests, gzip, io
    url = f"https://data.open-contracting.org/en/publication/{pub_id}/download?name={year}.jsonl.gz"
    try:
        r = requests.get(url, timeout=180, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200 or len(r.content) < 100:
            return None
        with gzip.open(io.BytesIO(r.content), "rt", encoding="utf-8") as f:
            return f.readlines()
    except Exception:
        return None


def scrape_ocds_country(country: str, out):
    """Pull all available awarded tenders for one country from the OCDS registry.
    - Downloads current year back to 2015 and merges them.
    - Open records replace existing ones (stale tenders close daily).
    - Awarded records are UPSERTED only — history is never wiped.
    """
    import json as _json
    from datetime import datetime, timezone, timedelta

    pub_id, flag = OCDS_REGISTRY[country]
    out(f"{flag} Scraping {country} (OCDS — 12 months)…")

    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    cutoff = "2015-01-01"  # collect all available history
    current_year = now.year

    # Download all available years from current back to 2015
    all_lines = []
    for yr in range(current_year, 2014, -1):
        yr_lines = _download_ocds_year(pub_id, yr)
        if yr_lines:
            all_lines.extend(yr_lines)
            out(f"  ℹ️ {country} {yr}: {len(yr_lines):,} records")
        # Stop going further back once two consecutive years return nothing
        elif yr < current_year - 1:
            break

    if not all_lines:
        out(f"  ❌ {country}: no data available from registry")
        return

    open_records, awarded_records = [], []
    seen_awarded = set()  # deduplicate across year files

    for line in all_lines:
        try:
            rel = _json.loads(line)
        except Exception:
            continue

        tender  = rel.get("tender") or {}
        title   = tender.get("title") or ""
        desc    = tender.get("description") or title
        category = tender.get("mainProcurementCategory") or ""

        if not _is_relevant(f"{title} {desc} {category}"):
            continue

        buyer      = (rel.get("buyer") or {}).get("name") or                      (tender.get("procuringEntity") or {}).get("name", "")
        ocid       = rel.get("ocid", "")
        tender_id  = tender.get("id") or ocid
        period     = tender.get("tenderPeriod") or {}
        end_date   = (period.get("endDate") or "")[:10]
        start_date = (period.get("startDate") or rel.get("date", ""))[:10]
        awards     = rel.get("awards") or []

        # Extract contact info from OCDS parties array
        _contact_person, _contact_email, _contact_phone = "", "", ""
        for party in (rel.get("parties") or []):
            if party.get("roles") and any(r in ["buyer","procuringEntity"]
                                           for r in party.get("roles",[])):
                cp = party.get("contactPoint") or {}
                _contact_person = str(cp.get("name") or "")[:200]
                _contact_email  = str(cp.get("email") or "")[:200]
                _contact_phone  = str(cp.get("telephone") or "")[:50]
                break

        base = {
            "tender_number":   str(tender_id)[:100],
            "department_name": str(buyer)[:200],
            "title":           str(title or desc)[:200],
            "description":     str(desc),
            "category":        str(category),
            "portal_link":     f"https://data.open-contracting.org/en/publication/{pub_id}",
            "country":         country,
            "contact_person":  _contact_person,
            "contact_email":   _contact_email,
            "contact_phone":   _contact_phone,
        }

        # Open: not yet closed, not cancelled
        status = (tender.get("status") or "").lower()
        if end_date and end_date >= today and status not in ("cancelled", "unsuccessful", "withdrawn"):
            open_records.append({
                **base,
                "compliance_requirements": tender.get("submissionMethodDetails") or "See portal",
                "issue_date":   start_date or None,
                "closing_date": end_date,
                "status":       "Open",
                "award_status": "Published",
            })

        # Awarded: within 12-month window, deduplicated
        for aw in awards:
            award_date = (aw.get("date") or rel.get("date") or "")[:10]
            # Skip if award date is known and outside the 12-month window
            if award_date and award_date < cutoff:
                continue
            suppliers = aw.get("suppliers") or []
            winner    = suppliers[0].get("name", "Unknown") if suppliers else "Not Disclosed"
            val       = aw.get("value") or {}
            amount    = f"{val.get('currency','')} {val.get('amount','')}".strip() if val else "Not Disclosed"
            dedup_key = f"{tender_id}|{winner}"
            if dedup_key in seen_awarded:
                continue
            seen_awarded.add(dedup_key)
            awarded_records.append({
                **base,
                "status":         "Awarded",
                "winning_bidder": str(winner)[:200],
                "award_value":    amount or "Not Disclosed",
                "issue_date":     award_date or None,
            })

    # Open records: replace (stale tenders close)
    supabase.table("sa_tenders").delete().eq("status", "Open").eq("country", country).execute()
    _upsert(open_records, country, "Open", out)

    # Write to dedicated awarded_tenders table — never wiped
    _upsert_awarded(awarded_records, country, f"Awarded (all history, {len(awarded_records)} records)", out)


def run_all_scrapers():
    """Run every country scraper with a live progress log in the main area."""
    st.subheader("🔄 Refreshing tender data across Africa…")
    log = st.empty()
    lines = []

    def out_write(msg):
        lines.append(msg)
        log.markdown("\n\n".join(lines))

    # South Africa: live eTenders API (most current), registry fallback if unreachable
    sa_ok = False
    try:
        scrape_south_africa(out_write)
        sa_ok = True
    except Exception as e:
        out_write(f"  ⚠️ South Africa live API unreachable: {e}")
    if not sa_ok:
        out_write("  🔁 Falling back to OCDS registry for South Africa…")
        try:
            scrape_ocds_country("South Africa", out_write)
        except Exception as e:
            out_write(f"  ❌ South Africa registry fallback also failed: {e}")

    # OCDS countries
    for country in OCDS_REGISTRY:
        if country == "South Africa":
            continue  # handled above with live API + fallback
        try:
            scrape_ocds_country(country, out_write)
        except Exception as e:
            out_write(f"  ❌ {country} crashed: {e}")

    # Non-OCDS countries via World Bank + UNDP
    try:
        out_write("\n🌍 Scraping non-OCDS countries via World Bank & UNDP…")
        scrape_non_ocds_countries(out_write)
    except Exception as e:
        out_write(f"  ❌ Non-OCDS scraper crashed: {e}")

    out_write("\n✅ **All 28 countries done!**")

# ─────────────────────────────────────────────
# 9. MAIN DASHBOARD
# ─────────────────────────────────────────────
# Logo — sidebar top, compact
_logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "crs_logo.png")
if os.path.exists(_logo_path):
    st.sidebar.image(_logo_path, width=160)

st.title("🛡️ CRS Competitive Intelligence Dashboard")

st.sidebar.header("Controls")
st.sidebar.caption(_provider_status())
_usage_sidebar()
if _MONDAY_AVAILABLE:
    st.sidebar.success("🟢 Monday.com connected")
else:
    st.sidebar.caption("⚪ Monday.com — add MONDAY_API_KEY to secrets")
if st.sidebar.button("🔄 Refresh All Countries"):
    run_all_scrapers()
    st.cache_data.clear()
    st.rerun()

if st.sidebar.button("🚀 Run Full Pipeline Now"):
    with st.spinner("Running full pipeline…"):
        run_pipeline("manual")
    st.cache_data.clear()
    st.success("Pipeline complete!")
    st.rerun()

if st.sidebar.button("🩺 Check Provider Health"):
    with st.spinner("Pinging providers…"):
        health = check_provider_health()
    st.session_state["provider_health"] = health

# Load data first so sidebar filters can use it
tenders_df = fetch_tenders()

if tenders_df.empty:
    st.warning("No data found. Ensure your scrapers have run successfully.")
    st.stop()

# Ensure AI columns exist in DataFrame
for col in ["ai_score", "ai_rationale"]:
    if col not in tenders_df.columns:
        tenders_df[col] = None

st.sidebar.header("Filters")
competitor_search = st.sidebar.text_input("Filter by Winning Bidder")
dept_search = st.sidebar.text_input("Filter by Department")

# Country filter — populated from live DB values
all_countries = sorted(tenders_df["country"].dropna().unique().tolist()) if "country" in tenders_df.columns else []
# All 28 target countries for quick reference
ALL_TARGET_COUNTRIES = [
    "South Africa", "Angola", "Botswana", "Egypt", "Eritrea", "Eswatini",
    "Ethiopia", "The Gambia", "Ghana", "Kenya", "Lesotho", "Liberia", "Libya",
    "Malawi", "Mauritius", "Mozambique", "Namibia", "Nigeria",
    "Republic of South Sudan", "Rwanda", "Seychelles", "Sierra Leone",
    "Somalia", "Sudan", "Uganda", "United Republic of Tanzania", "Zambia", "Zimbabwe",
]
# Use live DB countries if available, fall back to target list
_country_opts = sorted(set(all_countries) | set(ALL_TARGET_COUNTRIES))     if all_countries else ALL_TARGET_COUNTRIES

selected_countries = st.sidebar.multiselect(
    "Filter by Country",
    options=_country_opts,
    default=all_countries if all_countries else ALL_TARGET_COUNTRIES,
    help="28 African countries tracked"
)

# Date range filter for awarded tenders (12-month history)
st.sidebar.header("Awarded Date Range")
from datetime import date, timedelta
default_from = date(2015, 1, 1)  # show all available history by default
awarded_date_from = st.sidebar.date_input("From", value=default_from)
awarded_date_to   = st.sidebar.date_input("To",   value=date.today())

# Apply filters
df_filtered = tenders_df.copy()
if dept_search:
    df_filtered = df_filtered[
        df_filtered["department_name"].str.contains(dept_search, case=False, na=False)
    ]
if selected_countries and "country" in df_filtered.columns:
    df_filtered = df_filtered[df_filtered["country"].isin(selected_countries)]

# ─────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📢 Open Opportunities",
    "🏆 Competitive Intelligence",
    "🤖 AI Tender Parser",
    "🔎 AI Discovery (Private Sector)",
    "🎯 Lead Intelligence",
    "⚙️ Pipeline & Health"
])

# ══════════════════════════════════════════════
# TAB 1 — OPEN OPPORTUNITIES
# ══════════════════════════════════════════════
with tab1:
    open_df = df_filtered[df_filtered["status"] == "Open"].copy()

    col_left, col_right = st.columns([3, 1])
    with col_left:
        st.subheader(f"Open Opportunities ({len(open_df)})")
    with col_right:
        _can_score, _score_wait = _check_cooldown("score_all")
        _score_btn = st.button(
            "🤖 Score All with AI",
            key="btn_score_all",
            help=f"Run AI fit scoring on all open tenders",
            disabled=not _can_score
        )
        if not _can_score:
            st.caption(f"⏳ Available in {_score_wait} min")

        if _MONDAY_AVAILABLE:
            if st.button("📋 Push High-Score (≥7) to Monday", key="mon_bulk_tenders",
                         help="Create Monday.com leads for all open tenders scored 7+"):
                high = open_df[open_df["ai_score"].fillna(0) >= 7]
                if high.empty:
                    st.info("No tenders scored 7+ yet. Run AI scoring first.")
                else:
                    pushed, skipped = 0, 0
                    prog = st.progress(0, text="Pushing to Monday.com…")
                    for i, (_, row) in enumerate(high.iterrows()):
                        prog.progress((i+1)/len(high), text=f"Pushing {i+1}/{len(high)}…")
                        try:
                            r = push_tender_to_monday(row.to_dict())
                            if r.get("ticket_action") == "created" or r.get("lead_action") == "created":
                                pushed += 1
                            else:
                                skipped += 1
                        except Exception:
                            skipped += 1
                    prog.empty()
                    st.success(f"✅ {pushed} leads pushed to Monday.com ({skipped} skipped/errors)")

        if _score_btn and _can_score:
            _record_op("score_all")
            ai_match_tenders(open_df)
            st.cache_data.clear()
            st.success("Scoring complete! Reloading…")
            st.rerun()

    # Sort by score if available
    if "ai_score" in open_df.columns and open_df["ai_score"].notna().any():
        open_df = open_df.sort_values("ai_score", ascending=False, na_position="last")

    # Build display frame — Partner Score column is always shown (⚪ — when unscored)
    open_df["Partner Score"] = open_df["ai_score"].apply(score_badge)
    display_cols = ["Partner Score", "country", "tender_number", "department_name", "title", "closing_date"]

    event = st.dataframe(
        open_df[display_cols],
        use_container_width=True,
        selection_mode="single-row",
        on_select="rerun",
        hide_index=True,
    )

    # Detail panel — use tender_number as stable key, not row index
    if event.selection.rows:
        idx = event.selection.rows[0]

        # Guard: idx must be a valid integer within bounds
        if not isinstance(idx, int) or idx >= len(open_df):
            st.warning("Selection lost after refresh — please re-select a tender.")
        else:
            row = open_df.iloc[idx]
            # Guard: row must be a Series/dict-like with a tender_number
            if not hasattr(row, "get") or not row.get("tender_number"):
                st.warning("Could not read tender data — please re-select.")
            else:
                # Lock onto tender_number so reruns can re-fetch reliably
                _tn = str(row.get("tender_number", ""))
                # Re-fetch from dataframe by tender_number (survives rerun row-shift)
                _matches = open_df[open_df["tender_number"] == _tn]
                t = _matches.iloc[0] if not _matches.empty else row

                st.divider()
                header_col, score_col = st.columns([4, 1])
                with header_col:
                    st.subheader(f"📄 {t.get('tender_number','N/A')} — {t.get('title', '')}")
                with score_col:
                    if pd.notna(t.get("ai_score")):
                        st.metric("Partner Opportunity", score_badge(t["ai_score"]))

                _cp_col, _ = st.columns([1, 5])
                with _cp_col:
                    copy_button(format_tender_card(t.to_dict()),
                                label="📋 Copy Tender",
                                key=f"cp_t_{_tn[:20]}")

                st.write(f"**Country:** {t.get('country', 'N/A')}  |  **Department:** {t.get('department_name', 'N/A')}")
                st.write(f"**Description:** {t.get('description', 'N/A')}")
                st.write(f"**Compliance Requirements:** {t.get('compliance_requirements', 'N/A')}")
                st.write(f"**Closing Date:** {t.get('closing_date', 'N/A')}")

                # Contact info for enquiries
                _cp = t.get("contact_person","")
                _ce = t.get("contact_email","")
                _ph = t.get("contact_phone","")
                if any([_cp, _ce, _ph]):
                    with st.expander("📞 Enquiry Contact", expanded=True):
                        cinfo = []
                        if _cp: cinfo.append(f"**Person:** {_cp}")
                        if _ce: cinfo.append(f"**Email:** {_ce}")
                        if _ph: cinfo.append(f"**Phone:** {_ph}")
                        st.write("  |  ".join(cinfo))

                # AI rationale
                if pd.notna(t.get("ai_rationale")):
                    with st.expander("🤖 Partner Opportunity Analysis", expanded=True):
                        _rat_raw = str(t.get("ai_rationale", ""))
                        try:
                            import json as _dj
                            _rp = _dj.loads(_rat_raw) if _rat_raw.strip().startswith("{") else {}
                        except Exception:
                            _rp = {}
                        if _rp:
                            if _rp.get("partner_type"):
                                st.write(f"**🏢 Partner Type to Activate:** {_rp['partner_type']}")
                            if _rp.get("proposed_solutions"):
                                st.write(f"**💡 CRS Solutions to Propose:** {' · '.join(_rp['proposed_solutions'])}")
                            if _rp.get("rationale"):
                                st.info(f"**Why this is a partner opportunity:** {_rp['rationale']}")
                            if _rp.get("outreach_angle"):
                                st.success(f"**💬 Outreach angle to partner:** {_rp['outreach_angle']}")
                        else:
                            st.info(_rat_raw)
                else:
                    if st.button("🤖 Analyse Partner Opportunity", key=f"score_{_tn}"):
                        with st.spinner("Analysing partner opportunity…"):
                            try:
                                result = ai_score_tender(t.to_dict())
                                supabase.table("sa_tenders").update({
                                    "ai_score": result["score"],
                                    "ai_rationale": result["rationale"]
                                }).eq("tender_number", _tn).execute()
                                st.cache_data.clear()
                                st.rerun()
                            except Exception as e:
                                st.error(f"Scoring failed: {e}")

                # Actions row — 3 columns: eTenders link | Monday push | Mark irrelevant
                action_col1, action_col2, action_col3 = st.columns(3)
                with action_col1:
                    st.link_button("🌐 View on eTenders", "https://www.etenders.gov.za/Home/opportunities")
                with action_col2:
                    if _MONDAY_AVAILABLE:
                        if st.button("📋 Push to Monday", key=f"mon_{_tn}",
                                     help="Create lead on Monday.com Leads Board"):
                            with st.spinner("Pushing to Monday.com…"):
                                try:
                                    r = push_tender_to_monday(t.to_dict())
                                    t_act = r.get("ticket_action","?")
                                    l_act = r.get("lead_action","?")
                                    if "error" in str(t_act) or "error" in str(l_act):
                                        st.warning(f"Partial — Ticket: {t_act} | Lead: {l_act}")
                                    elif t_act == "exists":
                                        st.info(f"ℹ️ Ticket already exists (updated) | Lead: {l_act}")
                                    else:
                                        st.success(f"✅ Pushed → Outstanding Tickets + Leads")
                                except Exception as e:
                                    st.error(f"Monday push failed: {e}")
                with action_col3:
                    if st.button("🚫 Mark as Irrelevant", key=f"del_{_tn}",
                                 help="Hides this tender — stays in database but won't appear again"):
                        try:
                            supabase.table("sa_tenders").update({"is_irrelevant": True})                                .eq("tender_number", _tn).execute()
                            st.cache_data.clear()
                            st.rerun()
                        except Exception as e:
                            st.error(f"Could not mark as irrelevant: {e}")


# ══════════════════════════════════════════════
# TAB 2 — COMPETITIVE INTELLIGENCE
# ══════════════════════════════════════════════
with tab2:
    st.subheader("🤝 Potential CRS Channel Partners")
    st.write(
        "Companies winning ICT and security tenders across Africa — "
        "AI recommends which ones CRS should approach as resellers, "
        "integration partners, or training sub-contractors."
    )

    # Load from dedicated awarded_tenders table (never wiped on refresh)
    awarded_df = fetch_awarded_tenders()

    # ── Tab 2 has its own independent filters (not tied to open-tender sidebar) ──
    awarded_all_countries = fetch_awarded_countries()

    t2_col1, t2_col2, t2_col3 = st.columns([2, 2, 2])
    with t2_col1:
        t2_countries = st.multiselect(
            "Filter by Country",
            options=awarded_all_countries or ALL_TARGET_COUNTRIES,
            default=[],   # empty = show all
            key="t2_country_filter",
            help=f"{len(awarded_all_countries)} countries in awarded history"
        )
    with t2_col2:
        t2_date_from = st.date_input("Awarded From", value=date(2015, 1, 1),
                                      key="t2_date_from")
        t2_date_to   = st.date_input("Awarded To",   value=date.today(),
                                      key="t2_date_to")
    with t2_col3:
        t2_bidder = st.text_input("Filter by Winning Bidder", key="t2_bidder",
                                   placeholder="e.g. Dimension Data")

    if not awarded_df.empty:
        # Country filter — only apply if user explicitly selected countries
        if t2_countries and "country" in awarded_df.columns:
            awarded_df = awarded_df[awarded_df["country"].isin(t2_countries)]
        # Date range filter
        if "issue_date" in awarded_df.columns:
            try:
                _from_ts = pd.Timestamp(t2_date_from)
                _to_ts   = pd.Timestamp(t2_date_to)
                _dates   = pd.to_datetime(awarded_df["issue_date"], errors="coerce")
                awarded_df = awarded_df[_dates.isna() | ((_dates >= _from_ts) & (_dates <= _to_ts))]
            except Exception:
                pass
        # Bidder search
        if t2_bidder and "winning_bidder" in awarded_df.columns:
            awarded_df = awarded_df[
                awarded_df["winning_bidder"].str.contains(t2_bidder, case=False, na=False)
            ]

    if awarded_df.empty:
        st.info("No awarded tenders found. Run a data refresh to populate — awarded tenders are stored permanently and never wiped.")
    else:
        total_awarded = len(awarded_df)
        n_countries   = awarded_df["country"].nunique() if "country" in awarded_df.columns else "?"
        st.success(f"📊 **{total_awarded:,} awarded tenders** across **{n_countries} countries** (use filters above to narrow down)")
        # ── AI Partner Analysis ──────────────────────────────────────────────
        col_run, col_info = st.columns([2, 5])
        with col_run:
            _can_analyse, _analyse_wait = _check_cooldown("partner_analysis")
            run_analysis = st.button(
                "🤖 Analyse Partners with AI",
                key="btn_analyse_partners",
                help="Gemini reviews all awarded tender winners and recommends partner candidates",
                disabled=not _can_analyse
            )
            if not _can_analyse:
                st.caption(f"⏳ Available in {_analyse_wait} min")
            if run_analysis:
                _record_op("partner_analysis")
        with col_info:
            st.caption(
                f"Analysing {len(awarded_df[awarded_df['winning_bidder'].notna()]):,} awarded tenders "
                f"across {awarded_df['country'].nunique() if 'country' in awarded_df.columns else '?'} countries "
                f"— increase the sample by adjusting filters above."
            )

        if run_analysis:
            with st.spinner("Gemini is analysing winning companies…"):
                try:
                    partners = ai_analyse_partners(awarded_df)
                    st.session_state["partner_analysis"] = partners
                except json.JSONDecodeError:
                    st.error("Gemini returned an unexpected format. Try again.")
                except Exception as e:
                    st.error(f"Analysis failed: {e}")

        if "partner_analysis" in st.session_state and st.session_state["partner_analysis"]:
            partners = st.session_state["partner_analysis"]

            # Sanitise — ensure list of dicts (guards against stale/corrupt session state)
            if not isinstance(partners, list):
                partners = []
            partners = [p for p in partners if isinstance(p, dict) and p.get("company")]

            if not partners:
                st.warning("Analysis returned no valid partner records. Try running again.")
            else:
                # Urgency colour coding
                URGENCY_ICON = {"high": "🔴", "medium": "🟡", "low": "🟢"}

                # Summary cards row
                high = [p for p in partners if p.get("urgency") == "high"]
                med  = [p for p in partners if p.get("urgency") == "medium"]
                low  = [p for p in partners if p.get("urgency") == "low"]

                m1, m2, m3 = st.columns(3)
                m1.metric("🔴 High Priority", len(high))
                m2.metric("🟡 Medium Priority", len(med))
                m3.metric("🟢 Lower Priority", len(low))

                st.divider()

                # Expandable cards — one per partner
                for p in sorted(partners, key=lambda x: {"high": 0, "medium": 1, "low": 2}.get(x.get("urgency","low"), 2)):
                    urgency_icon = URGENCY_ICON.get(p.get("urgency", "low"), "⚪")
                    ptype = p.get("partner_classification") or p.get("partnership_type", "")
                    company = p.get("company", "Unknown")
                    country = p.get("country", "")
                    wins = p.get("tenders_won", "?")
                    deal_size = p.get("estimated_deal_size", "")

                    with st.expander(
                        f"{urgency_icon} **{company}** — {country}  |  {wins} wins  |  {ptype}  |  {deal_size}"
                    ):
                        # Partner classification badge
                        ptype_colors = {
                            "System Integrator": "🔷",
                            "MSP": "🟣",
                            "VAR": "🟦",
                            "Training Provider": "🟩",
                            "Consulting/Advisory": "🟧",
                        }
                        ptype_icon = ptype_colors.get(ptype, "⚪")
                        st.write(f"**{ptype_icon} Partner Type:** {ptype}")

                        # Proposed solutions
                        solutions = p.get("proposed_solutions", [])
                        if solutions:
                            st.write(f"**💡 Proposed CRS Solutions:** {' · '.join(solutions)}")

                        # Key tenders won
                        key_tenders = p.get("key_tenders", [])
                        if key_tenders:
                            st.write(f"**📋 Key Tenders Won:** {', '.join(str(t) for t in key_tenders[:3])}")

                        # Departments served
                        depts = p.get("issuing_departments", [])
                        if depts:
                            st.write(f"**🏛️ Departments Served:** {', '.join(str(d) for d in depts[:3])}")

                        st.write(f"**Why aligned:** {p.get('why_aligned', '')}")
                        st.info(f"💬 Outreach angle: {p.get('outreach_angle', '')}")

                        copy_button(format_partner_card(p),
                                    label="📋 Copy Partner Card",
                                    key=f"cp_p_{company[:20].replace(' ','_')}")

                        # Per-company Monday push button
                        if _MONDAY_AVAILABLE:
                            btn_key = f"push_co_{company[:30].replace(' ','_')}"
                            if st.button(f"📋 Push to Monday Companies", key=btn_key,
                                         help="Create or update this company on the 2.1 - Companies board"):
                                with st.spinner(f"Pushing {company}…"):
                                    try:
                                        result = push_partner_to_companies(p)
                                        action = result.get("action","?")
                                        item_id = result.get("item_id","")
                                        if action == "created":
                                            st.success(f"✅ **{company}** created on Companies board (ID: {item_id})")
                                        elif action == "updated":
                                            st.success(f"✅ **{company}** already exists — AI analysis added as update (ID: {item_id})")
                                        else:
                                            st.info(f"ℹ️ {company}: {action}")
                                    except Exception as e:
                                        st.error(f"Push failed: {e}")

            st.divider()

        # ── Award Detail table (always visible) ─────────────────────────────
        st.subheader("Award Detail")
        with st.expander("Show full award list", expanded=False):
            st.dataframe(
                awarded_df[[
                    "country", "tender_number", "department_name",
                    "winning_bidder", "award_value", "title"
                ]].sort_values("country"),
                use_container_width=True,
                hide_index=True,
            )


# ══════════════════════════════════════════════
# TAB 3 — AI TENDER PARSER
# ══════════════════════════════════════════════
with tab3:
    st.subheader("🤖 AI Tender Parser")
    st.write(
        "Paste raw tender text below — from an email, a PDF copy, or any unstructured source. "
        "Gemini will extract structured fields and optionally save the tender to your database."
    )

    raw_input = st.text_area(
        "Paste tender text here",
        height=280,
        placeholder="e.g. TENDER NUMBER: GT/GDARD/001/2025\nDepartment of Agriculture...\nClosing Date: 30 July 2025..."
    )

    if st.button("🔍 Parse Tender", key="btn_parse_tender", disabled=not raw_input.strip()):
        with st.spinner("Extracting structured fields…"):
            try:
                parsed = ai_parse_tender(raw_input)
                st.success("Parsing complete!")

                # Display parsed result
                st.subheader("Extracted Fields")
                field_map = {
                    "Tender Number": parsed.get("tender_number"),
                    "Title": parsed.get("title"),
                    "Department": parsed.get("department_name"),
                    "Description": parsed.get("description"),
                    "Issue Date": parsed.get("issue_date"),
                    "Closing Date": parsed.get("closing_date"),
                    "Value": parsed.get("award_value"),
                    "Compliance Requirements": parsed.get("compliance_requirements"),
                }
                for label, value in field_map.items():
                    st.write(f"**{label}:** {value or '—'}")

                # Store in session for save action
                st.session_state["parsed_tender"] = parsed

                # Auto-score
                with st.spinner("Calculating fit score…"):
                    scored = ai_score_tender(parsed)
                    parsed["ai_score"] = scored["score"]
                    parsed["ai_rationale"] = scored["rationale"]
                    st.session_state["parsed_tender"] = parsed

                st.divider()
                st.subheader("AI Fit Assessment")
                st.metric("Partner Score", score_badge(scored["score"]))
                st.info(scored["rationale"])

            except json.JSONDecodeError:
                st.error("Gemini returned an unexpected format. Try again or simplify the input text.")
            except Exception as e:
                st.error(f"Parsing failed: {e}")

    # Save button — only show after a successful parse
    if "parsed_tender" in st.session_state:
        st.divider()
        if st.button("💾 Save to Database", key="btn_save_parsed"):
            try:
                record = st.session_state["parsed_tender"]
                supabase.table("sa_tenders").upsert(record, on_conflict="tender_number").execute()
                st.success(f"Tender {record.get('tender_number', '')} saved to Supabase.")
                del st.session_state["parsed_tender"]
                st.cache_data.clear()
            except Exception as e:
                st.error(f"Save failed: {e}")

    st.divider()
    st.caption("💡 Tip: You can also drag a PDF into the browser and copy-paste the text here.")

# ══════════════════════════════════════════════
# TAB 4 — AI DISCOVERY (PRIVATE SECTOR)
# ══════════════════════════════════════════════
with tab4:
    st.subheader("🔎 AI-Powered Tender Discovery")
    st.write(
        "Government portals miss private-sector RFPs from banks, telcos, mining houses, "
        "universities, and parastatals. Gemini searches the live web for these and "
        "returns candidates you can review and save."
    )

    disc_col1, disc_col2 = st.columns([2, 3])
    with disc_col1:
        disc_countries = st.multiselect(
            "Countries to search",
            ["South Africa", "Kenya", "Nigeria", "Ghana", "Tanzania", "Uganda",
             "Zambia", "Rwanda", "Botswana", "Namibia", "Zimbabwe"],
            default=["South Africa", "Kenya", "Nigeria"],
        )
    with disc_col2:
        disc_focus = st.text_input(
            "Focus (what to look for)",
            value="cybersecurity solutions, SOC services, penetration testing, "
                  "IBM / Red Hat / CompTIA technical training, vulnerability management",
        )

    _can_discover, _discover_wait = _check_cooldown("tender_discovery")
    if not _can_discover:
        st.caption(f"⏳ Tender discovery available in {_discover_wait} min")
    if st.button("🔎 Discover Tenders", key="btn_discover_tenders", disabled=(not disc_countries or not _can_discover)):
        _record_op("tender_discovery")
        with st.spinner("Gemini is searching the web — this can take up to a minute…"):
            try:
                found = ai_discover_tenders(disc_countries, disc_focus)
                if found:
                    st.session_state["discovered"] = found
                    st.success(f"Found {len(found)} candidate tenders.")
                else:
                    st.info("No candidates found this run. Try broadening the focus or fewer countries.")
            except json.JSONDecodeError:
                st.error("Gemini returned an unexpected format — try running discovery again.")
            except Exception as e:
                st.error(f"Discovery failed: {e}")

    # Review & save discovered tenders
    if "discovered" in st.session_state and st.session_state["discovered"]:
        st.divider()
        st.subheader("Review Candidates")
        st.caption("⚠️ AI-discovered results can include stale or incorrect listings — verify the source link before bidding.")

        disc_df = pd.DataFrame(st.session_state["discovered"])
        st.dataframe(disc_df, use_container_width=True, hide_index=True)

        save_col1, save_col2 = st.columns(2)
        with save_col1:
            if st.button("💾 Save All to Database", key="btn_save_all_discovered"):
                import hashlib
                saved = 0
                for t in st.session_state["discovered"]:
                    ref = t.get("source_url") or f"{t.get('organisation','')}{t.get('title','')}"
                    tender_no = "AI-" + hashlib.md5(ref.encode()).hexdigest()[:10].upper()
                    record = {
                        "tender_number": tender_no,
                        "department_name": t.get("organisation", "Unknown"),
                        "title": str(t.get("title", ""))[:200],
                        "description": t.get("description", ""),
                        "category": f"Private Sector — {t.get('sector', 'unspecified')}",
                        "compliance_requirements": "Verify on source portal",
                        "portal_link": t.get("source_url") or "",
                        "closing_date": t.get("closing_date"),
                        "status": "Open",
                        "award_status": "AI Discovered",
                        "country": t.get("country", ""),
                    }
                    try:
                        supabase.table("sa_tenders").upsert(
                            record, on_conflict="tender_number,department_name"
                        ).execute()
                        saved += 1
                    except Exception as e:
                        st.error(f"Save failed for {t.get('title','')[:50]}: {e}")
                st.success(f"Saved {saved}/{len(st.session_state['discovered'])} tenders. They now appear in Open Opportunities.")
                del st.session_state["discovered"]
                st.cache_data.clear()
        with save_col2:
            if st.button("🗑️ Discard Results", key="btn_discard_discovered"):
                del st.session_state["discovered"]
                st.rerun()

# ══════════════════════════════════════════════
# TAB 5 — LEAD INTELLIGENCE
# ══════════════════════════════════════════════
with tab5:
    import hashlib as _hashlib

    st.subheader("🎯 Lead Intelligence")
    st.write(
        "Find companies and decision-makers showing buying signals for CRS solutions. "
        "Sources: Reddit pain-point threads, African tech news, JSE-listed ICT companies, "
        "and Apollo contact search — all free."
    )

    # ── Credit tracker ──────────────────────────────────────────────────────
    if "apollo_credits_used" not in st.session_state:
        st.session_state["apollo_credits_used"] = 0
    APOLLO_MONTHLY_BUDGET = 75
    credits_left = APOLLO_MONTHLY_BUDGET - st.session_state["apollo_credits_used"]
    cred_col1, cred_col2, cred_col3 = st.columns(3)
    cred_col1.metric("Apollo Credits Budget", APOLLO_MONTHLY_BUDGET)
    cred_col2.metric("Credits Used This Session", st.session_state["apollo_credits_used"])
    cred_col3.metric("Credits Remaining", credits_left, delta_color="inverse")
    st.caption("⚠️ Apollo credits reset monthly. Organization enrichment costs 1 credit each — people search is free.")

    st.divider()

    # ── Search configuration ─────────────────────────────────────────────────
    cfg_col1, cfg_col2 = st.columns(2)
    with cfg_col1:
        lead_countries = st.multiselect(
            "Target countries",
            ["South Africa", "Kenya", "Nigeria", "Ghana", "Tanzania", "Uganda", "Zambia", "Rwanda"],
            default=["South Africa", "Kenya", "Nigeria"]
        )
        job_titles = st.multiselect(
            "Decision-maker titles to find",
            ["CISO", "Chief Information Security Officer", "CTO", "Chief Technology Officer",
             "IT Manager", "IT Director", "Head of IT", "Head of Cybersecurity",
             "Security Manager", "Security Architect", "Procurement Manager",
             "ICT Manager", "Digital Transformation Manager", "Head of Infrastructure"],
            default=["CISO", "CTO", "IT Director", "Head of Cybersecurity", "IT Manager"]
        )
    with cfg_col2:
        solution_focus = st.multiselect(
            "Solution focus (for sentiment matching)",
            ["cybersecurity", "endpoint protection", "vulnerability management",
             "SIEM", "SOC", "penetration testing", "security training",
             "IBM training", "Red Hat", "cloud security", "ransomware",
             "data protection", "POPIA compliance", "network security"],
            default=["cybersecurity", "endpoint protection", "SOC", "ransomware", "POPIA compliance"]
        )
        include_jse = st.checkbox("Include JSE-listed ICT companies", value=True)
        enrich_orgs = st.checkbox(
            f"Enrich top companies via Apollo (uses credits — {credits_left} left)",
            value=False
        )

    _can_leads, _leads_wait = _check_cooldown("lead_discovery")
    if not _can_leads:
        st.caption(f"⏳ Lead discovery available in {_leads_wait} min (burns 2 AI calls)")
    run_leads = st.button(
        "🎯 Find Leads", key="btn_find_leads", type="primary",
        disabled=(not lead_countries or not _can_leads)
    )
    if run_leads:
        _record_op("lead_discovery")

    # ────────────────────────────────────────────────────────────────────────
    # HELPER FUNCTIONS (scoped inside tab so they share session state)
    # ────────────────────────────────────────────────────────────────────────

    def _apollo_headers():
        key = st.secrets.get("APOLLO_API_KEY", "")
        return {"x-api-key": key, "Content-Type": "application/json", "accept": "application/json"}

    # ── Cyber attack signal keywords ─────────────────────────────────────────
    _ATTACK_KEYWORDS = [
        "ransomware", "cyberattack", "cyber attack", "data breach", "hacked",
        "malware", "phishing attack", "security breach", "data leak",
        "ransomware attack", "cyber incident", "network intrusion",
        "compromised", "stolen data", "extortion", "DDoS attack",
    ]
    _AFRICA_GEO_TERMS = [
        "South Africa", "Kenya", "Nigeria", "Ghana", "Tanzania", "Uganda",
        "Zambia", "Rwanda", "Africa", "African", "Johannesburg", "Cape Town",
        "Nairobi", "Lagos", "Accra", "Pretoria", "Durban",
    ]

    def _search_attack_news(countries: list, limit: int = 30) -> list:
        """NewsAPI — African cyber attack news. Each article = a company in distress."""
        import requests
        key = st.secrets.get("NEWSAPI_KEY", "")
        results = []

        # Two complementary queries for maximum coverage
        _geo = " OR ".join(countries[:4] + ["Africa"])
        queries = [
            f"(ransomware OR cyberattack OR hacked OR breach) AND ({_geo})",
            f"(malware OR phishing OR ransomware OR DDoS) AND ({_geo})",
        ]

        if key:
            for q in queries:
                try:
                    r = requests.get("https://newsapi.org/v2/everything", params={
                        "q": q, "sortBy": "publishedAt", "language": "en",
                        "pageSize": limit // 2, "apiKey": key,
                    }, timeout=15)
                    if r.ok:
                        for a in r.json().get("articles", []):
                            results.append({
                                "source":      f"News: {a.get('source',{}).get('name','')}",
                                "title":       a.get("title", ""),
                                "url":         a.get("url", ""),
                                "body":        (a.get("description") or "")[:400],
                                "published":   a.get("publishedAt", "")[:10],
                                "victim_org":  "",   # filled by AI
                                "attack_type": "",   # filled by AI
                                "crs_score":   None,
                                "contact_title": "",
                            })
                except Exception as e:
                    st.toast(f"NewsAPI error: {e}")

        # Reddit fallback / supplement — no key needed
        try:
            import requests as _req
            geo_part = " OR ".join(f'"{g}"' for g in _AFRICA_GEO_TERMS[:5])
            atk_part = " OR ".join(f'"{k}"' for k in _ATTACK_KEYWORDS[:5])
            q = f"({atk_part}) ({geo_part})"
            r = _req.get("https://www.reddit.com/search.json",
                         params={"q": q, "sort": "new", "t": "year",
                                 "limit": 15, "type": "link"},
                         headers={"User-Agent": "CRS-LeadGen/1.0"}, timeout=15)
            if r.ok:
                for post in r.json().get("data", {}).get("children", []):
                    d = post.get("data", {})
                    results.append({
                        "source":      f"Reddit r/{d.get('subreddit','')}",
                        "title":       d.get("title", ""),
                        "url":         f"https://reddit.com{d.get('permalink','')}",
                        "body":        d.get("selftext", "")[:400],
                        "published":   "",
                        "victim_org":  "",
                        "attack_type": "",
                        "crs_score":   None,
                        "contact_title": "",
                    })
        except Exception as e:
            st.toast(f"Reddit fetch error: {e}")

        # Deduplicate by title
        seen, deduped = set(), []
        for s in results:
            key_str = s["title"][:60]
            if key_str not in seen:
                seen.add(key_str)
                deduped.append(s)
        return deduped

    def _jse_ict_companies() -> list:
        """Return a curated list of JSE-listed ICT / financial services companies
        that are strong CRS prospects — sourced from Wikipedia JSE list."""
        return [
            {"name": "Datatec", "ticker": "DTC", "sector": "ICT Solutions & Services", "domain": "datatec.com"},
            {"name": "BCX (EOH subsidiary)", "ticker": "EOH", "sector": "ICT", "domain": "bcx.co.za"},
            {"name": "EOH Holdings", "ticker": "EOH", "sector": "ICT Services", "domain": "eoh.co.za"},
            {"name": "Dimension Data (NTT)", "ticker": "N/A", "sector": "ICT", "domain": "dimensiondata.com"},
            {"name": "Telkom SA", "ticker": "TKG", "sector": "Telco/ICT", "domain": "telkom.co.za"},
            {"name": "MTN Group", "ticker": "MTN", "sector": "Telco", "domain": "mtn.com"},
            {"name": "Vodacom", "ticker": "VOD", "sector": "Telco", "domain": "vodacom.co.za"},
            {"name": "FirstRand (FNB)", "ticker": "FSR", "sector": "Banking", "domain": "fnb.co.za"},
            {"name": "Standard Bank", "ticker": "SBK", "sector": "Banking", "domain": "standardbank.co.za"},
            {"name": "Absa Group", "ticker": "ABG", "sector": "Banking", "domain": "absa.co.za"},
            {"name": "Nedbank", "ticker": "NED", "sector": "Banking", "domain": "nedbank.co.za"},
            {"name": "Discovery Limited", "ticker": "DSY", "sector": "Insurance/Health", "domain": "discovery.co.za"},
            {"name": "Old Mutual", "ticker": "OMU", "sector": "Financial Services", "domain": "oldmutual.com"},
            {"name": "Sanlam", "ticker": "SLM", "sector": "Financial Services", "domain": "sanlam.co.za"},
            {"name": "Capitec Bank", "ticker": "CPI", "sector": "Banking", "domain": "capitecbank.co.za"},
            {"name": "Multichoice Group", "ticker": "MCG", "sector": "Media/Digital", "domain": "multichoice.com"},
            {"name": "Altron", "ticker": "AEL", "sector": "ICT/Electronics", "domain": "altron.com"},
            {"name": "Mustek", "ticker": "MST", "sector": "ICT Distribution", "domain": "mustek.co.za"},
            {"name": "Alviva Holdings", "ticker": "AVV", "sector": "ICT Distribution", "domain": "alviva.com"},
            {"name": "Adapt IT", "ticker": "ADI", "sector": "Software/ICT", "domain": "adaptit.co.za"},
            {"name": "Bytes Technology Group", "ticker": "BYI", "sector": "Software/ICT", "domain": "bytes.co.za"},
            {"name": "Liquid Intelligent Technologies", "ticker": "N/A", "sector": "Network/Cloud", "domain": "liquid.tech"},
            {"name": "Atos South Africa", "ticker": "N/A", "sector": "ICT Services", "domain": "atos.net"},
            {"name": "NEC XON", "ticker": "N/A", "sector": "ICT/Security", "domain": "necxon.com"},
        ]

    def _apollo_search_contacts(titles: list, countries: list) -> list:
        """contacts/search — find existing contacts in your Apollo account by title/location."""
        import requests
        payload = {
            "contact_titles": titles[:8],
            "contact_locations": countries,
            "per_page": 25,
            "page": 1,
        }
        try:
            r = requests.post(
                "https://api.apollo.io/api/v1/contacts/search",
                json=payload, headers=_apollo_headers(), timeout=20
            )
            if r.ok:
                contacts = r.json().get("contacts", [])
                return [{
                    "name": f"{c.get('first_name','')} {c.get('last_name','')}".strip(),
                    "title": c.get("title", ""),
                    "company": (c.get("account") or {}).get("name", ""),
                    "country": c.get("country", ""),
                    "linkedin": c.get("linkedin_url", ""),
                    "email": c.get("email", ""),
                    "phone": c.get("sanitized_phone", ""),
                    "apollo_id": c.get("id", ""),
                    "source": "Apollo CRM",
                } for c in contacts if c.get("first_name")]
            else:
                st.toast(f"Apollo contacts/search {r.status_code}: {r.text[:120]}")
                return []
        except Exception as e:
            st.toast(f"Apollo contacts error: {e}")
            return []

    def _apollo_search_orgs(keywords: list, countries: list) -> list:
        """organizations/search — find companies by keyword/location."""
        import requests
        payload = {
            "q_organization_keyword_tags": keywords[:6],
            "organization_locations": countries,
            "per_page": 20,
            "page": 1,
        }
        try:
            r = requests.post(
                "https://api.apollo.io/api/v1/organizations/search",
                json=payload, headers=_apollo_headers(), timeout=20
            )
            if r.ok:
                orgs = r.json().get("organizations", [])
                return [{
                    "name": o.get("name", ""),
                    "domain": o.get("primary_domain", ""),
                    "industry": o.get("industry", ""),
                    "employees": o.get("estimated_num_employees"),
                    "country": o.get("country", ""),
                    "linkedin": o.get("linkedin_url", ""),
                    "description": o.get("short_description", "")[:200],
                    "apollo_id": o.get("id", ""),
                } for o in orgs if o.get("name")]
            else:
                st.toast(f"Apollo orgs/search {r.status_code}: {r.text[:120]}")
                return []
        except Exception as e:
            st.toast(f"Apollo orgs error: {e}")
            return []

    def _apollo_top_people(org_id: str, titles: list) -> list:
        """mixed_people/organization_top_people — get key contacts at a specific org."""
        import requests
        payload = {
            "organization_id": org_id,
            "person_titles": titles[:5],
            "per_page": 10,
        }
        try:
            r = requests.post(
                "https://api.apollo.io/api/v1/mixed_people/organization_top_people",
                json=payload, headers=_apollo_headers(), timeout=20
            )
            if r.ok:
                people = r.json().get("people", [])
                return [{
                    "name": f"{p.get('first_name','')} {p.get('last_name','')}".strip(),
                    "title": p.get("title", ""),
                    "linkedin": p.get("linkedin_url", ""),
                    "email_status": p.get("email_status", ""),
                    "apollo_id": p.get("id", ""),
                    "source": "Apollo Top People",
                } for p in people if p.get("first_name")]
        except Exception as e:
            st.toast(f"Apollo top people error: {e}")
        return []

    def _apollo_enrich_org(domain: str) -> dict:
        """organizations/enrich — full enrichment by domain. Uses 1 credit."""
        import requests
        try:
            r = requests.get(
                "https://api.apollo.io/api/v1/organizations/enrich",
                params={"domain": domain},
                headers=_apollo_headers(), timeout=15
            )
            if r.ok:
                org = r.json().get("organization", {})
                st.session_state["apollo_credits_used"] += 1
                return {
                    "name": org.get("name", ""),
                    "industry": org.get("industry", ""),
                    "employees": org.get("estimated_num_employees"),
                    "revenue": org.get("annual_revenue_printed", ""),
                    "linkedin": org.get("linkedin_url", ""),
                    "description": org.get("short_description", ""),
                    "tech_stack": [t.get("name","") for t in (org.get("technology_names") or [])[:10]],
                }
        except Exception:
            pass
        return {}

    def _apollo_create_contact(person: dict, account_id: str = None) -> bool:
        """contacts/create — push a qualified lead into Apollo CRM."""
        import requests
        payload = {
            "first_name": person.get("name","").split(" ")[0],
            "last_name":  " ".join(person.get("name","").split(" ")[1:]) or ".",
            "title":      person.get("title",""),
            "organization_name": person.get("company",""),
            "linkedin_url": person.get("linkedin",""),
            "label_names": ["CRS Lead", "Dashboard Import"],
        }
        if account_id:
            payload["account_id"] = account_id
        try:
            r = requests.post(
                "https://api.apollo.io/api/v1/contacts/create",
                json=payload, headers=_apollo_headers(), timeout=15
            )
            return r.ok
        except Exception:
            return False

    def _apollo_bulk_create_accounts(companies: list) -> dict:
        """accounts/bulk_create — push target companies into Apollo CRM (up to 25 at once)."""
        import requests
        accounts = [{"name": c.get("name",""), "domain": c.get("domain",""),
                     "label_names": ["CRS Target", "Dashboard Import"]}
                    for c in companies[:25] if c.get("name")]
        if not accounts:
            return {}
        try:
            r = requests.post(
                "https://api.apollo.io/api/v1/accounts/bulk_create",
                json={"accounts": accounts}, headers=_apollo_headers(), timeout=20
            )
            if r.ok:
                created = r.json().get("accounts", [])
                return {a.get("name",""): a.get("id","") for a in created}
        except Exception as e:
            st.toast(f"Apollo bulk account error: {e}")
        return {}

    def _ai_score_leads(signals: list, people: list, companies: list, focus: list) -> dict:
        """
        Two-stage AI analysis:
        Stage 1 — Parse each attack signal: extract victim org, attack type, CRS fit score,
                   and the specific contact title CRS should reach out to.
        Stage 2 — Rank companies and contacts, produce outreach strategy.
        """
        nl = "\n"

        def _co_label(c):
            sector = c.get("sector") or c.get("industry") or "?"
            return f"- {c.get('name','?')} ({sector}, {c.get('country','')})"

        # Build signal list with body text for richer extraction
        signal_lines = nl.join(
            f"[{i+1}] TITLE: {s.get('title','')[:150]}\n    BODY: {s.get('body','')[:200]}"
            for i, s in enumerate(signals[:20])
        )
        company_summary = nl.join(_co_label(c) for c in companies[:30])
        people_summary  = nl.join(
            f"- {p.get('name','?')} | {p.get('title','')} at {p.get('company','')} ({p.get('country','')})"
            for p in people[:25]
        )

        # ── STAGE 1 prompt: parse attack signals ──────────────────────────
        stage1_prompt = f"""You are a cyber threat analyst and sales strategist for CRS (Cyber Retaliator Solutions).

CRS sells: {", ".join(focus[:8])} and more. Full profile: {CRS_PROFILE[:400]}

TASK: For each news/Reddit item below, extract:
1. The VICTIM ORGANISATION (company/government body that was attacked) — if named
2. The ATTACK TYPE (ransomware / data breach / phishing / DDoS / malware / unknown)
3. CRS FIT SCORE 1-10: how relevant is this incident for CRS to approach the victim?
   (10 = CRS has a direct solution for this exact attack type, victim is likely in market now)
4. CONTACT TITLE: the specific job title at the victim org CRS should reach out to
   (e.g. "CISO", "IT Director", "Head of Cybersecurity" — be specific to the attack type)
5. OUTREACH ANGLE: one sentence — what CRS should say to get a meeting

ATTACK SIGNALS (Africa-focused):
{signal_lines or "None found."}

Return ONLY a JSON array — one object per signal, in the same order:
[
  {{
    "index": 1,
    "victim_org": "Company name or null if not identifiable",
    "attack_type": "ransomware|data breach|phishing|DDoS|malware|unknown",
    "crs_score": 1-10,
    "contact_title": "specific job title to target",
    "outreach_angle": "one sentence CRS pitch"
  }}
]
Only return the JSON array.
"""
        try:
            stage1_raw    = _call_ai(stage1_prompt)
            parsed_signals = json.loads(stage1_raw)
            if not isinstance(parsed_signals, list):
                parsed_signals = []
        except Exception:
            parsed_signals = []

        # Back-fill extracted fields onto original signal dicts
        for item in parsed_signals:
            idx = item.get("index", 0) - 1
            if 0 <= idx < len(signals):
                signals[idx]["victim_org"]    = item.get("victim_org") or ""
                signals[idx]["attack_type"]   = item.get("attack_type") or ""
                signals[idx]["crs_score"]     = item.get("crs_score")
                signals[idx]["contact_title"] = item.get("contact_title") or ""
                signals[idx]["outreach_angle"]= item.get("outreach_angle") or ""

        # ── STAGE 2 prompt: company + contact strategy ────────────────────
        # Build a concise attack summary for context
        attack_summary = nl.join(
            f"- {s.get('victim_org','unknown org')} | {s.get('attack_type','')} | Score {s.get('crs_score','?')}/10"
            for s in sorted(signals, key=lambda x: x.get("crs_score") or 0, reverse=True)[:10]
        )

        stage2_prompt = f"""You are a B2B sales strategist for CRS (Cyber Retaliator Solutions).

CRS PROFILE: {CRS_PROFILE[:600]}

RECENT AFRICAN CYBER ATTACKS (with CRS fit scores):
{attack_summary or "None found."}

COMPANIES IN SCOPE (JSE + Apollo):
{company_summary or "None."}

DECISION-MAKERS (Apollo):
{people_summary or "None found."}

Return ONLY a valid JSON object:
{{
  "scored_companies": [
    {{
      "name": "company",
      "crs_score": 1-10,
      "lead_type": "System Integrator | MSP | VAR | Training Provider | End-user | Consulting/Advisory",
      "proposed_solutions": ["Solution1", "Solution2"],
      "why": "why CRS should target them now — link to attack signals where relevant",
      "outreach_angle": "one specific sentence",
      "urgency": "high/medium/low"
    }}
  ],
  "scored_contacts": [
    {{
      "name": "person name",
      "title": "job title",
      "company": "company",
      "crs_score": 1-10,
      "why_first": "one sentence",
      "linkedin": "url or null"
    }}
  ],
  "top_companies": ["name1","name2","name3","name4","name5"],
  "top_contacts":  ["name1","name2","name3"],
  "follow_up_actions": ["action 1","action 2","action 3"],
  "overall_market_signal": "2-3 sentences on what the African attack landscape tells CRS right now"
}}
"""
        try:
            stage2_raw = _call_ai(stage2_prompt)
            result     = json.loads(stage2_raw)
        except Exception as e:
            result = {"scored_companies": [], "scored_contacts": [],
                      "top_companies": [], "top_contacts": [],
                      "follow_up_actions": [], "overall_market_signal": str(e)}

        # Back-fill contact scores onto people list
        score_map_contacts = {c.get("name",""): c.get("crs_score")
                              for c in result.get("scored_contacts",[])}
        for p in people:
            p["crs_score"] = score_map_contacts.get(p.get("name",""))

        return result

    # ────────────────────────────────────────────────────────────────────────
    # RUN LEAD SEARCH
    # ────────────────────────────────────────────────────────────────────────
    if run_leads:
        with st.spinner("🔍 Gathering signals from Reddit, news, Apollo, and JSE data…"):

            # 1. Cyber attack signals — Africa-focused (Reddit + NewsAPI)
            all_signals = _search_attack_news(lead_countries)
            st.toast(f"📡 {len(all_signals)} African cyber attack signals collected")

            # 2. Apollo CRM contacts (contacts/search — searches your existing CRM)
            apollo_contacts = _apollo_search_contacts(job_titles, lead_countries)
            st.toast(f"👤 {len(apollo_contacts)} contacts found in Apollo CRM")

            # 3. Apollo org discovery (organizations/search — finds new target companies)
            apollo_orgs = _apollo_search_orgs(solution_focus, lead_countries)
            st.toast(f"🏢 {len(apollo_orgs)} organisations found via Apollo")

            # 4. For top Apollo orgs, get key decision-makers (organization_top_people)
            top_people = []
            for org in apollo_orgs[:3]:   # limit to top 3 orgs to avoid hammering API
                if org.get("apollo_id"):
                    people = _apollo_top_people(org["apollo_id"], job_titles)
                    for p in people:
                        p["company"] = org["name"]
                    top_people.extend(people)
            if top_people:
                st.toast(f"👥 {len(top_people)} key contacts found at Apollo orgs")

            # 5. JSE companies
            jse_list = _jse_ict_companies() if include_jse else []

            # 6. Optional org enrichment (costs 1 credit each)
            enriched = {}
            if enrich_orgs and credits_left > 0:
                enrich_limit = min(credits_left, 5)
                st.toast(f"🔍 Enriching top {enrich_limit} JSE companies (uses {enrich_limit} credits)…")
                for co in jse_list[:enrich_limit]:
                    enriched[co["name"]] = _apollo_enrich_org(co["domain"])

            # Merge all people sources for AI analysis
            all_people = apollo_contacts + top_people

            # 7. AI scoring and outreach recommendations
            try:
                ai_leads = _ai_score_leads(all_signals, all_people, jse_list + apollo_orgs, solution_focus)
            except Exception as e:
                st.error(f"AI analysis failed: {e}")
                ai_leads = {}

            # Merge with previous results — append new, don't overwrite
            prev = st.session_state.get("lead_results", {})
            def _merge_list(key, new_items, id_field="name"):
                """Append new items not already in previous list."""
                old_items = prev.get(key, [])
                existing = {str(x.get(id_field,""))[:60] for x in old_items}
                additions = [x for x in new_items
                             if str(x.get(id_field,""))[:60] not in existing]
                return old_items + additions

            merged_signals  = _merge_list("signals", all_signals, "title")
            merged_contacts = _merge_list("apollo_contacts", apollo_contacts)
            merged_orgs     = _merge_list("apollo_orgs", apollo_orgs)
            merged_people   = _merge_list("top_people", top_people)

            st.session_state["lead_results"] = {
                "signals":         merged_signals,
                "apollo_contacts": merged_contacts,
                "apollo_orgs":     merged_orgs,
                "top_people":      merged_people,
                "jse":             jse_list,
                "enriched":        {**prev.get("enriched",{}), **enriched},
                "ai":              ai_leads,
            }
            st.toast(f"✅ Appended: +{len(all_signals)} signals, +{len(apollo_contacts)} contacts, +{len(apollo_orgs)} orgs")

            # Persist scored companies to Supabase for history
            scored_cos = ai_leads.get("scored_companies", [])
            if scored_cos:
                try:
                    rows = [{
                        "company":            str(c.get("name",""))[:200],
                        "country":            str(c.get("country",""))[:100],
                        "lead_type":          str(c.get("lead_type",""))[:100],
                        "crs_score":          c.get("crs_score"),
                        "proposed_solutions": json.dumps(c.get("proposed_solutions",[])),
                        "why":                str(c.get("why",""))[:500],
                        "outreach_angle":     str(c.get("outreach_angle",""))[:500],
                        "urgency":            str(c.get("urgency",""))[:20],
                        "source":             "Lead Intelligence",
                    } for c in scored_cos if c.get("name")]
                    supabase.table("lead_intelligence_history").upsert(
                        rows, on_conflict="company,country"
                    ).execute()
                except Exception:
                    pass  # table may not exist yet

    # ────────────────────────────────────────────────────────────────────────
    # DISPLAY RESULTS
    # ────────────────────────────────────────────────────────────────────────
    if "lead_results" in st.session_state:
        res    = st.session_state["lead_results"]
        ai_out = res.get("ai", {})
        URGENCY = {"high": "🔴", "medium": "🟡", "low": "🟢"}

        # ── Summary metrics ──────────────────────────────────────────────
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Attack Signals",    len(res.get("signals",[])))
        m2.metric("Apollo CRM Contacts", len(res.get("apollo_contacts",[])))
        m3.metric("Apollo Orgs Found", len(res.get("apollo_orgs",[])))
        m4.metric("JSE Companies",     len(res.get("jse",[])))

        st.divider()

        # ── Market Signal Summary ────────────────────────────────────────
        market_signal = ai_out.get("overall_market_signal", "")
        if market_signal:
            st.info(f"🌍 **Market Signal:** {market_signal}")

        st.divider()

        # ── AI Scored Companies ──────────────────────────────────────────
        scored_cos = ai_out.get("scored_companies", [])
        if scored_cos:
            scored_cos_sorted = sorted(scored_cos, key=lambda x: x.get("crs_score",0), reverse=True)
            st.subheader(f"🏢 Companies — CRS Relevance Ranked ({len(scored_cos_sorted)})")
            LEAD_TYPE_ICON = {
                "System Integrator": "🔷",
                "MSP": "🟣",
                "VAR": "🟦",
                "End-user": "🏛️",
                "Training Provider": "🟩",
                "Consulting/Advisory": "🟧",
            }
            for co in scored_cos_sorted:
                score     = co.get("crs_score", 0)
                icon      = URGENCY.get(co.get("urgency","low"), "⚪")
                badge     = "🟢" if score >= 8 else "🟡" if score >= 5 else "🔴"
                lead_type = co.get("lead_type", "")
                lt_icon   = LEAD_TYPE_ICON.get(lead_type, "⚪")
                with st.expander(
                    f"{badge} **{co.get('name','')}** — {lt_icon} {lead_type}  |  Score {score}/10  {icon} {co.get('urgency','').capitalize()}"
                ):
                    # Lead type + solutions on one line
                    solutions = co.get("proposed_solutions", [])
                    c1, c2 = st.columns([1,2])
                    c1.write(f"**{lt_icon} Lead Type:** {lead_type}")
                    if solutions:
                        c2.write(f"**💡 Proposed:** {' · '.join(solutions)}")
                    st.write(f"**Why now:** {co.get('why','')}")
                    st.info(f"💬 Outreach angle: {co.get('outreach_angle','')}")

                    enr = res.get("enriched",{}).get(co.get("name",""), {})
                    copy_button(format_lead_card(co, enr), label="📋 Copy Lead Card",
                                key=f"cp_lead_{co.get('name','')[:25]}")
                    if enr:
                        ec1, ec2 = st.columns(2)
                        ec1.write(f"**Employees:** {enr.get('employees','?')}")
                        ec2.write(f"**Revenue:** {enr.get('revenue','?')}")
                        if enr.get("tech_stack"):
                            st.write(f"**Tech stack:** {', '.join(enr['tech_stack'])}")

        st.divider()

        # ── AI Scored Contacts ───────────────────────────────────────────
        scored_contacts = ai_out.get("scored_contacts", [])
        all_people = res.get("apollo_contacts",[]) + res.get("top_people",[])
        st.subheader(f"👤 Decision-Makers — CRS Relevance Ranked ({len(all_people)} found)")

        if scored_contacts:
            scored_contacts_sorted = sorted(scored_contacts, key=lambda x: x.get("crs_score",0), reverse=True)
            st.write("**🎯 AI-scored contacts — highest relevance first:**")
            for c in scored_contacts_sorted:
                score = c.get("crs_score", 0)
                badge = "🟢" if score >= 8 else "🟡" if score >= 5 else "🔴"
                with st.expander(
                    f"{badge} **{c.get('name','')}** — {c.get('title','')} at {c.get('company','')}  Score {score}/10"
                ):
                    st.write(f"**Why reach out:** {c.get('why_first','')}")
                    if c.get("linkedin"):
                        st.markdown(f"[🔗 LinkedIn]({c['linkedin']})")
                    _contact_txt = (
                        f"CONTACT: {c.get('name','N/A')}\n"
                        f"Title: {c.get('title','N/A')}\n"
                        f"Company: {c.get('company','N/A')}\n"
                        f"CRS Score: {c.get('crs_score','?')}/10\n"
                        f"Why Reach Out: {c.get('why_first','')}\n"
                        f"LinkedIn: {c.get('linkedin','N/A')}"
                    )
                    copy_button(_contact_txt, label="📋 Copy Contact",
                                key=f"cp_contact_{c.get('name','')[:25]}")

        if all_people:
            people_df = pd.DataFrame(all_people)
            show_cols = [c for c in ["crs_score","name","title","company","country","linkedin","email","email_status","source"]
                         if c in people_df.columns]
            if "crs_score" in people_df.columns:
                people_df = people_df.sort_values("crs_score", ascending=False, na_position="last")
            st.dataframe(
                people_df[show_cols].rename(columns={
                    "crs_score":"CRS Score","name":"Name","title":"Title","company":"Company",
                    "country":"Location","linkedin":"LinkedIn",
                    "email":"Email","email_status":"Email Status","source":"Source"
                }),
                use_container_width=True, hide_index=True
            )

        st.divider()

        # ── Apollo Orgs found ────────────────────────────────────────────
        if res.get("apollo_orgs"):
            st.subheader(f"🔍 Apollo Organisation Search Results ({len(res['apollo_orgs'])})")
            org_df = pd.DataFrame(res["apollo_orgs"])[
                [c for c in ["name","industry","employees","country","description","domain"]
                 if c in pd.DataFrame(res["apollo_orgs"]).columns]
            ]
            st.dataframe(org_df, use_container_width=True, hide_index=True)
            st.divider()

        # ── JSE Companies ────────────────────────────────────────────────
        if res.get("jse"):
            st.subheader(f"📈 JSE ICT Companies in Scope ({len(res['jse'])})")
            jse_df = pd.DataFrame(res["jse"])[["name","ticker","sector","domain"]]
            jse_df.columns = ["Company","Ticker","Sector","Domain"]
            st.dataframe(jse_df, use_container_width=True, hide_index=True)

        st.divider()

        # ── Buying signals ───────────────────────────────────────────────
        st.subheader(f"⚡ African Cyber Attack Signals ({len(res.get('signals',[]))})")
        st.caption("Each signal = a company that was attacked and likely needs CRS solutions now.")
        if res.get("signals"):
            sig_df = pd.DataFrame(res["signals"])
            # Sort by CRS score desc
            if "crs_score" in sig_df.columns:
                sig_df = sig_df.sort_values("crs_score", ascending=False, na_position="last")

            # Show attack-specific columns
            attack_cols = ["crs_score","victim_org","attack_type","contact_title","published","title","url"]
            show_cols = [c for c in attack_cols if c in sig_df.columns]
            display_sig_df = sig_df[show_cols].rename(columns={
                "crs_score":     "CRS Score",
                "victim_org":    "Victim Org",
                "attack_type":   "Attack Type",
                "contact_title": "Contact to Find",
                "published":     "Date",
                "title":         "Headline",
                "url":           "URL",
            })
            st.dataframe(display_sig_df, use_container_width=True, hide_index=True)

            # Expandable detail cards for high-score signals
            high_signals = [s for s in res["signals"] if (s.get("crs_score") or 0) >= 7]
            if high_signals:
                st.write(f"**🔴 {len(high_signals)} high-priority attack signals — expand for outreach angles:**")
                for s in high_signals:
                    badge = "🟢" if (s.get("crs_score") or 0) >= 9 else "🟡"
                    label = (
                        f"{badge} **{s.get('victim_org') or 'Unknown org'}** — "
                        f"{s.get('attack_type','').upper()}  |  Score {s.get('crs_score','?')}/10"
                    )
                    with st.expander(label):
                        st.write(f"**Headline:** {s.get('title','')}")
                        st.write(f"**Contact to find:** {s.get('contact_title','')}")
                        if s.get("outreach_angle"):
                            st.info(f"💬 {s['outreach_angle']}")
                        if s.get("url"):
                            st.markdown(f"[🔗 Source]({s['url']})")

                        # Quick Apollo contact search button for this specific org
                        btn_key = f"find_{s.get('victim_org','')[:20]}_{s.get('crs_score')}"
                        if s.get("victim_org") and st.button(
                            f"🔍 Find {s.get('contact_title','contact')} at {s.get('victim_org','')} in Apollo",
                            key=btn_key
                        ):
                            with st.spinner("Searching Apollo contacts…"):
                                found = _apollo_search_contacts(
                                    [s.get("contact_title","CISO")],
                                    lead_countries
                                )
                                # Filter to this org if possible
                                org_name = s.get("victim_org","").lower()
                                org_matches = [
                                    p for p in found
                                    if org_name and org_name[:10] in (p.get("company","")).lower()
                                ] or found[:5]

                            if org_matches:
                                st.write(f"**Found {len(org_matches)} contact(s):**")
                                for p in org_matches:
                                    cols = st.columns([3,2,2])
                                    cols[0].write(f"**{p.get('name','')}**")
                                    cols[1].write(p.get("title",""))
                                    if p.get("linkedin"):
                                        cols[2].markdown(f"[LinkedIn]({p['linkedin']})")
                            else:
                                st.info("No contacts found in Apollo CRM for this org — try the full contact search above.")
        else:
            st.info("No attack signals found. Add a NewsAPI key in secrets for best results (newsapi.org — free).")

        st.divider()

        # ── Follow-up actions ────────────────────────────────────────────
        actions = ai_out.get("follow_up_actions", [])
        if actions:
            st.subheader("✅ Recommended Actions This Week")
            for i, action in enumerate(actions, 1):
                st.write(f"**{i}.** {action}")

        st.divider()

        # ── Push to Apollo CRM ───────────────────────────────────────────
        st.subheader("🚀 Push to Apollo CRM")
        st.caption("Bulk-create target companies as Accounts, then add key contacts — all in one click.")
        push_col1, push_col2 = st.columns(2)

        with push_col1:
            if st.button("📤 Push Top Companies to Apollo Accounts", key="btn_apollo_companies"):
                push_cos = top_cos[:10] if top_cos else res.get("apollo_orgs",[])[:10]
                if push_cos:
                    with st.spinner("Creating accounts in Apollo…"):
                        id_map = _apollo_bulk_create_accounts(push_cos)
                    st.success(f"✅ {len(id_map)} companies added to Apollo as Accounts.")
                    st.session_state["apollo_account_ids"] = id_map
                else:
                    st.info("Run a lead search first to populate target companies.")

        with push_col2:
            if st.button("📤 Push Priority Contacts to Apollo CRM", key="btn_apollo_contacts"):
                _tc = ai_out.get("scored_contacts", []) if "lead_results" in st.session_state else []
                push_people = _tc if _tc else all_people[:10]
                if push_people:
                    saved = 0
                    account_ids = st.session_state.get("apollo_account_ids", {})
                    with st.spinner(f"Creating {len(push_people)} contacts in Apollo…"):
                        for person in push_people:
                            acct_id = account_ids.get(person.get("company",""))
                            if _apollo_create_contact(person, acct_id):
                                saved += 1
                    st.success(f"✅ {saved}/{len(push_people)} contacts pushed to Apollo CRM.")
                else:
                    st.info("Run a lead search first to populate contacts.")

        # ── Push to Monday ────────────────────────────────────────────────
        if _MONDAY_AVAILABLE and "lead_results" in st.session_state:
            res    = st.session_state["lead_results"]
            ai_out = res.get("ai", {})
            all_people = res.get("apollo_contacts",[]) + res.get("top_people",[])
            st.subheader("📋 Push to Monday.com")
            push_col1, push_col2, push_col3 = st.columns(3)

            with push_col1:
                if st.button("🚨 Push Attack Signals (≥7) to Monday", key="btn_mon_attack"):
                    signals = res.get("signals", [])
                    high_sigs = [s for s in signals if (s.get("crs_score") or 0) >= 7
                                 and s.get("victim_org")]
                    pushed = 0
                    for s in high_sigs:
                        try:
                            push_tender_to_monday({"title": s.get("title",""), "tender_number": f"ATK-{s.get('victim_org','')[:20]}", "department_name": s.get("victim_org",""), "description": s.get("outreach_angle",""), "ai_score": s.get("crs_score"), "ai_rationale": s.get("outreach_angle",""), "country": "Africa", "portal_link": s.get("url","")})
                            pushed += 1
                        except Exception:
                            pass
                    st.success(f"✅ {pushed} attack signal leads pushed")

            with push_col2:
                if st.button("👤 Push Apollo Contacts to Monday", key="btn_mon_contacts"):
                    contacts = all_people[:10]
                    pushed = 0
                    for p in contacts:
                        try:
                            push_tender_to_monday({"title": p.get("title",""), "tender_number": f"APL-{p.get('name','')[:20]}", "department_name": p.get("company",""), "description": p.get("title",""), "ai_score": p.get("crs_score"), "ai_rationale": f"Apollo contact: {p.get('name','')} | {p.get('title','')}", "country": p.get("country","South Africa")})
                            pushed += 1
                        except Exception:
                            pass
                    st.success(f"✅ {pushed} contacts pushed")

            with push_col3:
                if st.button("🏢 Push Target Companies (≥7) to Monday", key="btn_mon_companies"):
                    top_cos = ai_out.get("scored_companies", [])
                    pushed = 0
                    for co in [c for c in top_cos if (c.get("crs_score") or 0) >= 7]:
                        try:
                            push_tender_to_monday({
                                "title": co.get("name",""),
                                "tender_number": f"LED-{co.get('name','')[:20]}",
                                "department_name": co.get("name",""),
                                "description": co.get("why",""),
                                "ai_score": co.get("crs_score"),
                                "ai_rationale": co.get("outreach_angle",""),
                                "country": "Africa",
                            })
                            pushed += 1
                        except Exception:
                            pass
                    st.success(f"✅ {pushed} companies pushed")

        # ── Export CSV ────────────────────────────────────────────────────
        if "lead_results" in st.session_state:
            _lp = st.session_state["lead_results"].get("apollo_contacts",[]) +                   st.session_state["lead_results"].get("top_people",[])
            if _lp:
                csv = pd.DataFrame(_lp).to_csv(index=False)
                st.download_button(
                    "⬇️ Export All Contacts as CSV",
                    data=csv, file_name="crs_leads.csv", mime="text/csv"
                )

# ══════════════════════════════════════════════
# TAB 6 — PIPELINE & HEALTH
# ══════════════════════════════════════════════
with tab6:
    st.subheader("⚙️ Pipeline & Health")

    # ── GitHub Self-Deploy ────────────────────────────────────────────────────
    with st.expander("🚀 Push to GitHub", expanded=False):
        st.caption(
            "Pushes the running `streamlit_app.py` and `monday_client.py` directly "
            "to `Drys-CRS/CRS-Lead-Gen` on GitHub. "
            "Streamlit Cloud auto-deploys on commit."
        )

    # ── New provider keys needed ──────────────────────────────────────────────
    with st.expander("🔑 New Provider API Keys — add to Streamlit Secrets", expanded=False):
        st.markdown("""
Add these to your Streamlit Cloud secrets to enable the new AI providers:

```toml
# NVIDIA NIM — free 1000 credits on signup, 40 RPM, 100+ models
# Sign up at: https://build.nvidia.com/settings/api-keys
NVIDIA_API_KEY = "nvapi-..."

# DeepSeek — 5M free tokens on signup, very cheap after ($0.28/M input)
# Sign up at: https://platform.deepseek.com/api_keys
DEEPSEEK_API_KEY = "sk-..."
```

**Cascade order after adding keys:**
Groq → Cerebras → OpenRouter → GitHub → **NVIDIA** → **DeepSeek** → Gemini
        """)
        gh_msg = st.text_input(
            "Commit message (optional)",
            placeholder="e.g. feat: add partner classification",
            key="gh_commit_msg"
        )
        if st.button("🚀 Push to GitHub Now", key="btn_gh_push",
                     help="Commits and pushes both app files to GitHub main branch"):
            with st.spinner("Pushing to GitHub…"):
                result = github_push_self(gh_msg.strip() or None)
            if result["ok"]:
                st.success(result["message"])
                st.balloons()
            else:
                st.error(result["message"])
    st.divider()

    # ── Scheduler status ──────────────────────────────────────────────────────
    sched_status = st.session_state.get(_SCHEDULER_KEY)
    if not _APSCHEDULER_AVAILABLE:
        st.warning("APScheduler not installed — add `apscheduler` to requirements.txt to enable scheduled runs.")
    elif sched_status is True:
        st.success("✅ Scheduler running — daily pipeline fires at 02:00 SAST, usage resets at 00:01 SAST.")
    elif sched_status and str(sched_status).startswith("failed"):
        st.error(f"❌ Scheduler failed to start: {sched_status}")
    else:
        st.info("⏳ Scheduler not yet started — will start on next page load.")

    ka_status = "✅ Active" if _AUTOREFRESH_AVAILABLE else "⚠️ Not installed (add `streamlit-autorefresh`)"
    st.info(f"🔄 Keep-alive (3-hour reload): {ka_status}")

    st.divider()

    # ── Provider health ───────────────────────────────────────────────────────
    st.subheader("🩺 Provider Health")
    col_h1, col_h2 = st.columns([1, 3])
    with col_h1:
        if st.button("🔁 Re-check Now", key="btn_recheck_health"):
            with st.spinner("Pinging all providers…"):
                st.session_state["provider_health"] = check_provider_health()
            st.rerun()

    health = st.session_state.get("provider_health", {})
    if health:
        h_cols = st.columns(len(health))
        for i, (name, info) in enumerate(health.items()):
            with h_cols[i]:
                status = info.get("status", "error")
                latency = info.get("latency_ms")
                err = (info.get("error") or "")[:50]
                if status == "ok":
                    icon, delta = "✅ Online", f"{latency} ms"
                elif status == "quota":
                    icon, delta = "⚠️ Quota", err or "Rate limited"
                elif status == "no_key":
                    icon, delta = "⚪ No Key", "Add to secrets"
                else:
                    icon, delta = "❌ Error", err
                st.metric(name, icon, delta)
    else:
        st.caption("Click 'Check Provider Health' in the sidebar or 'Re-check Now' above.")

    # Recent health log from Supabase
    try:
        health_log = supabase.table("provider_health_log")             .select("*").order("checked_at", desc=True).limit(20).execute()
        if health_log.data:
            hl_df = pd.DataFrame(health_log.data)[
                ["checked_at","provider","available","latency_ms","error"]
            ]
            hl_df["checked_at"] = pd.to_datetime(hl_df["checked_at"]).dt.strftime("%Y-%m-%d %H:%M")
            st.dataframe(hl_df, use_container_width=True, hide_index=True)
    except Exception:
        pass

    st.divider()

    # ── Pipeline run history ──────────────────────────────────────────────────
    st.subheader("📋 Pipeline Run History")
    try:
        runs = supabase.table("pipeline_runs")             .select("*").order("run_at", desc=True).limit(10).execute()
        if runs.data:
            runs_df = pd.DataFrame(runs.data)[[
                "run_at","trigger","status","tenders_scraped",
                "tenders_scored","signals_found","partners_found","duration_secs"
            ]]
            runs_df["run_at"] = pd.to_datetime(runs_df["run_at"]).dt.strftime("%Y-%m-%d %H:%M")
            st.dataframe(runs_df, use_container_width=True, hide_index=True)

            # Show error log for last failed run
            failed = [r for r in runs.data if r.get("status") == "failed"]
            if failed:
                with st.expander(f"❌ Last failed run — {failed[0].get('run_at','')}"):
                    st.code(failed[0].get("error_log","no log"))
        else:
            st.info("No pipeline runs yet. Click 'Run Full Pipeline Now' in the sidebar to start.")
    except Exception as e:
        st.warning(f"Could not load run history: {e}")

    st.divider()

    # ── History tables ────────────────────────────────────────────────────────
    st.subheader("📊 Historical Data")
    hist_tabs = st.tabs(["Scored Tenders", "Attack Signals", "Partner Recommendations"])

    with hist_tabs[0]:
        try:
            rows = supabase.table("tender_score_history")                 .select("*").order("run_at", desc=True).limit(100).execute()
            if rows.data:
                df = pd.DataFrame(rows.data)
                df["run_at"] = pd.to_datetime(df["run_at"]).dt.strftime("%Y-%m-%d")
                show = [c for c in ["run_at","ai_score","country","title","department","closing_date"]
                        if c in df.columns]
                df = df[show].sort_values("ai_score", ascending=False, na_position="last")
                st.caption(f"{len(df)} scored tender records")
                st.dataframe(df, use_container_width=True, hide_index=True)
            else:
                st.info("No scored tender history yet.")
        except Exception as e:
            st.warning(f"Could not load: {e}")

    with hist_tabs[1]:
        try:
            rows = supabase.table("attack_signal_history")                 .select("*").order("run_at", desc=True).limit(200).execute()
            if rows.data:
                df = pd.DataFrame(rows.data)
                df["run_at"] = pd.to_datetime(df["run_at"]).dt.strftime("%Y-%m-%d")
                show = [c for c in ["run_at","crs_score","victim_org","attack_type",
                                     "contact_title","title","published"]
                        if c in df.columns]
                df = df[show].sort_values("crs_score", ascending=False, na_position="last")
                st.caption(f"{len(df)} attack signal records")
                st.dataframe(df, use_container_width=True, hide_index=True)
            else:
                st.info("No attack signal history yet.")
        except Exception as e:
            st.warning(f"Could not load: {e}")

    with hist_tabs[2]:
        try:
            rows = supabase.table("partner_recommendation_history")                 .select("*").order("run_at", desc=True).limit(100).execute()
            if rows.data:
                df = pd.DataFrame(rows.data)
                df["run_at"] = pd.to_datetime(df["run_at"]).dt.strftime("%Y-%m-%d")
                show = [c for c in ["run_at","urgency","company","country",
                                     "partnership_type","outreach_angle"]
                        if c in df.columns]
                st.caption(f"{len(df)} partner recommendation records")
                st.dataframe(df[show], use_container_width=True, hide_index=True)
            else:
                st.info("No partner recommendations yet.")
        except Exception as e:
            st.warning(f"Could not load: {e}")

    st.divider()

    # ── Monday.com column discovery ───────────────────────────────────────────
    if _MONDAY_AVAILABLE:
        st.subheader("🔍 Monday.com Column ID Discovery")
        st.caption("Use this to find the real column IDs for your boards before they're configured.")
        disc_board_id = st.text_input("Enter a Monday Board ID to inspect:", placeholder="1234567890")
        if st.button("🔍 Discover Column IDs", key="btn_discover_cols") and disc_board_id:
            try:
                # Column discovery via direct GraphQL
                cols = {}
                import requests as _req
                q = """query ($bid: ID!) { boards(ids:[$bid]) { columns { id title type } } }"""
                _key = st.secrets.get("MONDAY_API_KEY","")
                _r = _req.post("https://api.monday.com/v2",
                    json={"query": q, "variables": {"bid": disc_board_id}},
                    headers={"Authorization": _key, "Content-Type": "application/json", "API-Version": "2024-01"},
                    timeout=15)
                if _r.ok:
                    for c in _r.json().get("data",{}).get("boards",[{}])[0].get("columns",[]):
                        cols[c.get("title","")] = c.get("id","")
                st.write("**Column title → Column ID mapping:**")
                st.dataframe(
                    pd.DataFrame(list(cols.items()), columns=["Title","Column ID"]),
                    use_container_width=True, hide_index=True
                )
                st.caption("Copy these IDs into monday_client.py to match your actual board structure.")
            except Exception as e:
                st.error(f"Discovery failed: {e}")
        st.divider()

    # ── Manual pipeline trigger with progress ─────────────────────────────────
    st.subheader("🚀 Manual Pipeline Run")
    st.caption("Runs the full pipeline immediately: scrape → score → partner analysis → attack signals.")
    if st.button("▶️ Run Pipeline Now", key="pipeline_manual_tab"):
        log_container = st.empty()
        log_lines_tab = []
        def _tab_out(msg):
            log_lines_tab.append(msg)
            log_container.markdown("\n\n".join(log_lines_tab[-20:]))
        with st.spinner("Pipeline running…"):
            run_pipeline("manual")
        st.cache_data.clear()
        st.success("Done! Refresh the other tabs to see updated data.")