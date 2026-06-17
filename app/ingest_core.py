"""
ingest_core.py — Streamlit-free core for the CRS Lead-Gen pipeline.

This module contains the scraping + AI-scoring logic with NO dependency on
Streamlit, so it can run headless in GitHub Actions (or any cron) and write
the same Supabase tables the dashboard reads.

It is intentionally self-contained:
  • Secrets come from environment variables (not st.secrets).
  • The Supabase client + AI provider clients are module globals set by
    init_supabase() / init_ai().
  • Logging goes through a `log` callable (defaults to print), mirroring the
    `out(...)` callbacks the in-app scrapers already use.

Public entry point:  run_all(...)  — see scripts/daily_ingest.py

Tables written (same schema as the app):
  sa_tenders, awarded_tenders, tender_score_history,
  partner_recommendation_history, ai_usage_log, pipeline_runs
"""

import os
import io
import re
import gzip
import json
import time
import datetime as _dt
import collections as _collections

import requests

# ── BeautifulSoup is only needed by _get_html (currently unused by the active
#    scrapers, but kept for parity). Import lazily so the module loads even if
#    bs4 is absent.
try:
    from bs4 import BeautifulSoup  # noqa: F401
    _BS4 = True
except Exception:
    _BS4 = False


# ═══════════════════════════════════════════════════════════════════════════
# CONFIG / GLOBALS
# ═══════════════════════════════════════════════════════════════════════════
supabase = None          # set by init_supabase()

# AI provider client handles (set by init_ai())
groq_ai = None
cerebras_ai = None
openrouter_ai = None
github_ai = None
nvidia_ai = None
deepseek_ai = None
gemini_client = None     # google.genai Client

_GENAI_NEW = False       # True if the new google.genai SDK is available

_USAGE = {}              # {provider: count} for today
_USAGE_DATE = None       # iso date the counts belong to


def _log_default(msg: str):
    print(msg, flush=True)


def _env(*names: str, default: str = "") -> str:
    """First non-empty environment variable among `names`."""
    for n in names:
        v = os.environ.get(n)
        if v:
            return str(v).strip()
    return default


# ═══════════════════════════════════════════════════════════════════════════
# INIT
# ═══════════════════════════════════════════════════════════════════════════
def init_supabase():
    """Build the Supabase client from SUPABASE_URL / SUPABASE_KEY."""
    global supabase
    from supabase import create_client
    url = _env("SUPABASE_URL")
    key = _env("SUPABASE_KEY", "SUPABASE_SERVICE_KEY", "SUPABASE_ANON_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set in the environment.")
    supabase = create_client(url, key)
    return supabase


def init_ai(log=_log_default):
    """Initialise whichever AI providers have keys present. Mirrors the app's
    cascade: Groq → Cerebras → OpenRouter → GitHub → NVIDIA → DeepSeek → Gemini.
    Returns the list of provider names that came up."""
    global groq_ai, cerebras_ai, openrouter_ai, github_ai
    global nvidia_ai, deepseek_ai, gemini_client, _GENAI_NEW

    # Groq
    try:
        k = _env("GROQ_API_KEY")
        if k:
            from groq import Groq
            groq_ai = Groq(api_key=k)
    except Exception as e:
        log(f"  ⚠️ Groq init failed: {e}")

    # Cerebras
    try:
        k = _env("CEREBRAS_API_KEY")
        if k:
            from cerebras.cloud.sdk import Cerebras
            cerebras_ai = Cerebras(api_key=k)
    except Exception as e:
        log(f"  ⚠️ Cerebras init failed: {e}")

    # OpenRouter (OpenAI-compatible)
    try:
        k = _env("OPENROUTER_API_KEY")
        if k:
            from openai import OpenAI
            openrouter_ai = OpenAI(
                api_key=k,
                base_url="https://openrouter.ai/api/v1",
                default_headers={
                    "HTTP-Referer": "https://github.com/Drys-CRS/CRS-Lead-Gen",
                    "X-Title": "CRS Daily Ingest",
                },
            )
    except Exception as e:
        log(f"  ⚠️ OpenRouter init failed: {e}")

    # GitHub Models — token may arrive under several names. NB: a GitHub Actions
    # secret cannot be named GITHUB_TOKEN, so the workflow passes it as GH_PAT.
    try:
        k = _env("GITHUB_MODELS_TOKEN", "GH_MODELS_TOKEN", "GH_PAT", "GITHUB_TOKEN")
        if k:
            from openai import OpenAI
            github_ai = OpenAI(api_key=k, base_url="https://models.inference.ai.azure.com")
    except Exception as e:
        log(f"  ⚠️ GitHub Models init failed: {e}")

    # NVIDIA NIM
    try:
        k = _env("NVIDIA_API_KEY")
        if k:
            from openai import OpenAI
            nvidia_ai = OpenAI(api_key=k, base_url="https://integrate.api.nvidia.com/v1")
    except Exception as e:
        log(f"  ⚠️ NVIDIA init failed: {e}")

    # DeepSeek
    try:
        k = _env("DEEPSEEK_API_KEY")
        if k:
            from openai import OpenAI
            deepseek_ai = OpenAI(api_key=k, base_url="https://api.deepseek.com")
    except Exception as e:
        log(f"  ⚠️ DeepSeek init failed: {e}")

    # Gemini (new google.genai SDK)
    try:
        k = _env("GEMINI_API_KEY")
        if k:
            import google.genai as genai
            gemini_client = genai.Client(api_key=k)
            _GENAI_NEW = True
    except Exception as e:
        log(f"  ⚠️ Gemini init failed: {e}")

    available = [n for n, c in [
        ("Groq", groq_ai), ("Cerebras", cerebras_ai), ("OpenRouter", openrouter_ai),
        ("GitHub", github_ai), ("NVIDIA", nvidia_ai), ("DeepSeek", deepseek_ai),
        ("Gemini", gemini_client),
    ] if c]
    return available


# ═══════════════════════════════════════════════════════════════════════════
# RELEVANCE FILTER  (verbatim keyword set from the app)
# ═══════════════════════════════════════════════════════════════════════════
TARGET_KEYWORDS = [
    "ibm training", "ibm technical training", "ibm certification",
    "red hat training", "redhat training", "red hat certification", "rhcsa", "rhce",
    "suse training", "suse certification", "linux training", "linux certification",
    "comptia", "security+", "network+", "a+ certification", "cysa",
    "ai training", "artificial intelligence training", "machine learning training",
    "technical training", "ict training", "it training", "cybersecurity training",
    "cyber security training", "information security training", "security awareness training",
    "training and certification", "skills development", "capacity building ict",
    "learnership ict", "training provider", "accredited training",
    "z/os", "ibm i", "ibm power", "mainframe", "red hat", "redhat", "suse", "rhel",
    "ndr", "network detection and response", "xdr", "extended detection",
    "threat detection", "threat hunting", "attack detection", "intrusion detection",
    "cloud detection and response", "identity threat detection", "itdr",
    "managed detection", "mdr", "soc", "security operations centre", "security operations center",
    "vulnerability management", "vulnerability assessment", "vulnerability scanning",
    "patch management", "penetration testing", "pentest", "vapt",
    "attack surface management", "risk based vulnerability", "ctem",
    "threat exposure management", "security assessment", "security audit",
    "application security", "sast", "dast", "sca", "devsecops",
    "code security", "secure development", "software supply chain",
    "container security", "cloud security posture", "cspm", "secrets detection",
    "third party risk", "third-party risk", "tprm", "tpcrm", "vendor risk",
    "vendor risk management", "supply chain risk", "supply chain security",
    "vendor assessment", "vendor due diligence", "dora", "dora compliance",
    "cyber risk rating", "security ratings", "supplier risk", "nth party",
    "sase", "secure access service edge", "mxdr", "managed xdr",
    "grc", "governance risk and compliance", "governance risk compliance",
    "security platform", "managed security service", "mssp", "cmmc",
    "endpoint security", "endpoint protection", "edr", "encryption",
    "data protection", "data security", "data loss prevention", "dlp",
    "bitlocker", "mobile device management", "mdm", "popia compliance",
    "multi-factor authentication", "mfa", "access control",
    "threat intelligence", "cyber threat intelligence", "dark web monitoring",
    "digital risk protection", "brand protection", "credential monitoring",
    "leaked credentials", "ransomware", "takedown",
    "phishing simulation", "phishing awareness", "cyber awareness",
    "security culture", "awareness programme", "awareness program",
    "cyber", "cybersecurity", "cyber security", "cyber risk", "cyber defence", "cyber defense",
    "incident response", "cyber incident", "firewall", "siem",
    "security orchestration", "soar", "zero trust",
    "identity and access management", "iam", "network security", "cloud security",
    "information security", "infosec", "iso 27001", "nist",
    "information technology", "ict", "ict infrastructure",
    "software licence", "software license", "software procurement",
    "server", "cloud", "infrastructure", "data center", "data centre",
]

_KW_PATTERNS = []
for _kw in TARGET_KEYWORDS:
    _k = _kw.lower().strip()
    if len(_k) <= 5:
        _KW_PATTERNS.append(re.compile(r"\b" + re.escape(_k) + r"\b"))
    else:
        _KW_PATTERNS.append(re.compile(re.escape(_k)))


def _is_relevant(text: str) -> bool:
    lower = (text or "").lower()
    return any(p.search(lower) for p in _KW_PATTERNS)


# ═══════════════════════════════════════════════════════════════════════════
# UPSERT HELPERS
# ═══════════════════════════════════════════════════════════════════════════
def _upsert(records: list, country: str, label: str, log) -> int:
    if not records:
        return 0
    ok, failed, first_err = 0, 0, None
    for r in records:
        try:
            supabase.table("sa_tenders").upsert(
                r, on_conflict="tender_number,department_name"
            ).execute()
            ok += 1
        except Exception as e:
            failed += 1
            if first_err is None:
                first_err = str(e)[:200]
    msg = f"  ✅ {country} — {label}: {ok} saved"
    if failed:
        msg += f" | ❌ {failed} failed (first error: {first_err})"
    log(msg)
    return ok


def _upsert_awarded(records: list, country: str, label: str, log) -> int:
    if not records:
        return 0
    ok, failed, first_err = 0, 0, None
    for r in records:
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
    log(msg)
    return ok


# ═══════════════════════════════════════════════════════════════════════════
# HTTP HELPERS
# ═══════════════════════════════════════════════════════════════════════════
def _get_json(url, params=None, headers=None, timeout=20, retries=3):
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
                time.sleep(2 * (attempt + 1))
    raise last_err


def _get_html(url, timeout=20):
    if not _BS4:
        raise RuntimeError("beautifulsoup4 not installed")
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


# ═══════════════════════════════════════════════════════════════════════════
# OCDS REGISTRY
# ═══════════════════════════════════════════════════════════════════════════
OCDS_REGISTRY = {
    # National / federal publishers
    "South Africa":           (143, "🇿🇦"),
    "Kenya":                  (147, "🇰🇪"),
    "Nigeria":                (64,  "🇳🇬"),  # Bureau of Public Procurement (federal)
    "Ghana":                  (85,  "🇬🇭"),
    "Tanzania":               (152, "🇹🇿"),
    "Uganda":                 (130, "🇺🇬"),
    "Zambia":                 (3,   "🇿🇲"),
    "Rwanda":                 (145, "🇷🇼"),
    "Liberia":                (156, "🇱🇷"),  # PPCC — was 79 (incorrect), corrected to 156
    # Nigeria state-level publishers (all confirmed on data.open-contracting.org)
    "Nigeria (Abia)":         (107, "🇳🇬"),
    "Nigeria (Anambra)":      (127, "🇳🇬"),
    "Nigeria (Cross River)":  (105, "🇳🇬"),
    "Nigeria (Ebonyi)":       (86,  "🇳🇬"),
    "Nigeria (Edo)":          (102, "🇳🇬"),
    "Nigeria (Ekiti)":        (116, "🇳🇬"),
    "Nigeria (Enugu)":        (104, "🇳🇬"),
    "Nigeria (Gombe)":        (103, "🇳🇬"),
    "Nigeria (Osun)":         (118, "🇳🇬"),
    "Nigeria (Oyo)":          (106, "🇳🇬"),
    "Nigeria (Plateau)":      (125, "🇳🇬"),
}

NON_OCDS_COUNTRIES = {
    "Angola": ("🇦🇴", "Southern Africa"), "Botswana": ("🇧🇼", "Southern Africa"),
    "Egypt": ("🇪🇬", "North Africa"), "Eritrea": ("🇪🇷", "East Africa"),
    "Eswatini": ("🇸🇿", "Southern Africa"), "Ethiopia": ("🇪🇹", "East Africa"),
    "The Gambia": ("🇬🇲", "West Africa"), "Lesotho": ("🇱🇸", "Southern Africa"),
    "Libya": ("🇱🇾", "North Africa"), "Malawi": ("🇲🇼", "East Africa"),
    "Mauritius": ("🇲🇺", "Indian Ocean"), "Mozambique": ("🇲🇿", "Southern Africa"),
    "Namibia": ("🇳🇦", "Southern Africa"),
    "Republic of South Sudan": ("🇸🇸", "East Africa"),
    "Seychelles": ("🇸🇨", "Indian Ocean"), "Sierra Leone": ("🇸🇱", "West Africa"),
    "Somalia": ("🇸🇴", "East Africa"), "Sudan": ("🇸🇩", "East Africa"),
    "Zimbabwe": ("🇿🇼", "Southern Africa"),
}


def _clean_ocds_date(s):
    s = (s or "")[:10]
    if len(s) != 10:
        return None
    try:
        y = int(s[:4])
        if y < 2000 or y > _dt.datetime.now().year + 1:
            return None
        _dt.datetime.strptime(s, "%Y-%m-%d")
        return s
    except Exception:
        return None


def _download_ocds_year(pub_id: int, year: int):
    url = (f"https://data.open-contracting.org/en/publication/{pub_id}"
           f"/download?name={year}.jsonl.gz")
    try:
        r = requests.get(url, timeout=180, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200 or len(r.content) < 100:
            return None
        with gzip.open(io.BytesIO(r.content), "rt", encoding="utf-8") as f:
            return f.readlines()
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════
# SCRAPERS
# ═══════════════════════════════════════════════════════════════════════════
def scrape_south_africa(log):
    country = "South Africa"
    log(f"🇿🇦 Scraping {country}…")
    cutoff = "2015-01-01"
    try:
        # OPEN — replace fully
        supabase.table("sa_tenders").delete().eq("status", "Open").eq("country", country).execute()
        open_records, start = [], 0
        while True:
            data = _get_json(
                "https://www.etenders.gov.za/Home/PaginatedTenderOpportunities",
                {"draw": "1", "start": str(start), "length": "500", "status": "1",
                 "search[value]": "", "search[regex]": "false",
                 "order[0][column]": "2", "order[0][dir]": "desc"},
            )
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
                    "contact_email":  str(t.get("contactEmail") or t.get("contact_email") or t.get("email") or "")[:200],
                    "contact_phone":  str(t.get("contactPhone") or t.get("contact_phone") or t.get("phone") or "")[:50],
                    "status": "Open", "award_status": "Published", "country": country,
                })
            start += len(batch)
            if start >= int(data.get("recordsTotal", 0)):
                break
        _upsert(open_records, country, "Open", log)

        # AWARDED — upsert back to cutoff
        log(f"  🇿🇦 Fetching awarded tenders back to {cutoff}…")
        awarded_records, start, stop_early = [], 0, False
        while not stop_early:
            data2 = _get_json(
                "https://www.etenders.gov.za/Home/PaginatedTenderOpportunities",
                {"draw": "1", "start": str(start), "length": "500", "status": "2"},
            )
            batch = data2.get("data", [])
            if not batch:
                break
            for t in batch:
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
                    "contact_email":  str(t.get("contactEmail") or t.get("contact_email") or t.get("email") or "")[:200],
                    "contact_phone":  str(t.get("contactPhone") or t.get("contact_phone") or t.get("phone") or "")[:50],
                })
            start += len(batch)
            if start >= int(data2.get("recordsTotal", 0)):
                break
        _upsert_awarded(awarded_records, country, "Awarded (all history)", log)
    except Exception as e:
        log(f"  ❌ {country} error: {e}")
        raise


def scrape_ocds_country(country: str, log, years_back: int = 3):
    if country not in OCDS_REGISTRY:
        log(f"  ⚠️ {country}: not in OCDS registry — skipped")
        return {"open": 0, "awarded": 0}

    pub_id, flag = OCDS_REGISTRY[country]
    now = _dt.datetime.now(_dt.timezone.utc)
    today = now.date().isoformat()
    current_year = now.year
    start_year = current_year - max(years_back - 1, 0)

    log(f"{flag} {country}: OCDS pub {pub_id}, downloading {start_year}–{current_year}…")

    open_records, awarded_records = [], []
    seen_awarded = set()
    total_lines = relevant_hits = years_with_data = 0

    for yr in range(current_year, start_year - 1, -1):
        yr_lines = _download_ocds_year(pub_id, yr)
        if not yr_lines:
            continue
        years_with_data += 1
        total_lines += len(yr_lines)

        for line in yr_lines:
            try:
                rel = json.loads(line)
            except Exception:
                continue

            tender = rel.get("tender") or {}
            title = tender.get("title") or ""
            desc = tender.get("description") or title
            category = tender.get("mainProcurementCategory") or ""

            if not _is_relevant(f"{title} {desc} {category}"):
                continue
            relevant_hits += 1

            buyer = ((rel.get("buyer") or {}).get("name")
                     or (tender.get("procuringEntity") or {}).get("name", ""))
            ocid = rel.get("ocid", "")
            tender_id = tender.get("id") or ocid
            period = tender.get("tenderPeriod") or {}
            end_date = _clean_ocds_date(period.get("endDate")) or ""
            start_date = _clean_ocds_date(period.get("startDate") or rel.get("date", "")) or ""
            awards = rel.get("awards") or []

            _cp, _ce, _ph = "", "", ""
            for party in (rel.get("parties") or []):
                if party.get("roles") and any(
                    r in ["buyer", "procuringEntity"] for r in party.get("roles", [])
                ):
                    cp = party.get("contactPoint") or {}
                    _cp = str(cp.get("name") or "")[:200]
                    _ce = str(cp.get("email") or "")[:200]
                    _ph = str(cp.get("telephone") or "")[:50]
                    break

            base = {
                "tender_number":   str(tender_id)[:100],
                "department_name": str(buyer)[:200],
                "title":           str(title or desc)[:200],
                "description":     str(desc),
                "category":        str(category),
                "portal_link":     f"https://data.open-contracting.org/en/publication/{pub_id}",
                "country":         country,
                "contact_person":  _cp, "contact_email": _ce, "contact_phone": _ph,
            }

            status = (tender.get("status") or "").lower()
            if end_date and end_date >= today and status not in ("cancelled", "unsuccessful", "withdrawn"):
                open_records.append({
                    **base,
                    "compliance_requirements": tender.get("submissionMethodDetails") or "See portal",
                    "issue_date": start_date or None,
                    "closing_date": end_date,
                    "status": "Open", "award_status": "Published",
                })

            for aw in awards:
                award_date = _clean_ocds_date(aw.get("date") or rel.get("date")) or ""
                suppliers = aw.get("suppliers") or []
                winner = suppliers[0].get("name", "Unknown") if suppliers else "Not Disclosed"
                val = aw.get("value") or {}
                amount = (f"{val.get('currency','')} {val.get('amount','')}".strip()
                          if val else "Not Disclosed")
                dedup_key = f"{tender_id}|{winner}"
                if dedup_key in seen_awarded:
                    continue
                seen_awarded.add(dedup_key)
                awarded_records.append({
                    **base, "status": "Awarded",
                    "winning_bidder": str(winner)[:200],
                    "award_value": amount or "Not Disclosed",
                    "issue_date": award_date or None,
                })

    if years_with_data == 0:
        log(f"  ❌ {country}: registry returned no downloadable files for "
            f"{start_year}–{current_year} (pub {pub_id})")
        return {"open": 0, "awarded": 0}

    supabase.table("sa_tenders").delete().eq("status", "Open").eq("country", country).execute()
    n_open = _upsert(open_records, country, "Open", log)
    n_awarded = _upsert_awarded(awarded_records, country, "Awarded", log)
    log(f"  📊 {country}: scanned {total_lines:,} records · {relevant_hits:,} relevant · "
        f"upserted {n_open} open + {n_awarded} awarded")
    return {"open": n_open, "awarded": n_awarded}


def scrape_non_ocds_countries(log):
    """World Bank + UNDP procurement notices for countries without OCDS feeds."""
    today = _dt.datetime.now(_dt.timezone.utc).date().isoformat()

    WB_COUNTRY_CODES = {
        "Angola": "AO", "Botswana": "BW", "Egypt": "EG", "Eritrea": "ER",
        "Eswatini": "SZ", "Ethiopia": "ET", "The Gambia": "GM", "Lesotho": "LS",
        "Libya": "LY", "Malawi": "MW", "Mauritius": "MU", "Mozambique": "MZ",
        "Namibia": "NA", "Republic of South Sudan": "SS", "Seychelles": "SC",
        "Sierra Leone": "SL", "Somalia": "SO", "Sudan": "SD", "Zimbabwe": "ZW",
        "Kenya": "KE", "Nigeria": "NG", "Ghana": "GH", "Tanzania": "TZ",
        "Uganda": "UG", "Zambia": "ZM", "Rwanda": "RW",
    }

    total_open, total_awarded = 0, 0

    for country, wb_code in WB_COUNTRY_CODES.items():
        # ── World Bank Procurement Notices ──────────────────────────────────
        try:
            wb_url = "https://search.worldbank.org/api/v2/procnotices"
            params = {
                "format": "json",
                "fl": ("id,project_name,project_id,notice_type,deadline_date,"
                       "submission_date,contact_country,procurement_method,"
                       "description,contact_organization,status"),
                "fq": f"contact_country:{wb_code}",
                "rows": 200, "sort": "submission_date desc",
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
                    portal = ("https://projects.worldbank.org/en/projects-operations/"
                              f"procurement/procnotices/{n.get('id','')}")
                    base = {
                        "tender_number": tender_no[:100],
                        "department_name": org, "title": title, "description": title,
                        "category": notice_type, "portal_link": portal, "country": country,
                        "contact_person": str(n.get("contact_name") or "")[:200],
                        "contact_email": str(n.get("contact_email") or "")[:200],
                        "contact_phone": str(n.get("contact_phone") or "")[:50],
                    }
                    status = str(n.get("status") or "").lower()
                    if status in ("awarded", "contract signed"):
                        awarded_batch.append({**base, "winning_bidder": "Not Disclosed",
                                              "award_value": "Not Disclosed", "issue_date": deadline})
                    elif deadline >= today or not deadline:
                        open_batch.append({
                            **base,
                            "compliance_requirements": n.get("procurement_method") or "See portal",
                            "closing_date": deadline or None,
                            "status": "Open", "award_status": "Published",
                        })

                if open_batch:
                    supabase.table("sa_tenders").delete() \
                        .eq("country", country).like("tender_number", "WB-%").execute()
                    _upsert(open_batch, country, "WB Open", log)
                    total_open += len(open_batch)
                if awarded_batch:
                    _upsert_awarded(awarded_batch, country, "WB Awarded", log)
                    total_awarded += len(awarded_batch)
        except Exception:
            pass  # non-fatal per country

        # ── UNDP Procurement Notices ────────────────────────────────────────
        try:
            undp_url = "https://procurement-notices.undp.org/search.cfm"
            params2 = {"op": "search", "country": country, "type": "all",
                       "output": "json", "rows": 50}
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
                        "tender_number": f"UNDP-{n.get('id','')}",
                        "department_name": str(n.get("agency") or "UNDP")[:200],
                        "title": title, "description": title,
                        "category": str(n.get("type") or ""),
                        "portal_link": str(n.get("url") or "https://procurement-notices.undp.org"),
                        "closing_date": deadline or None, "country": country,
                        "compliance_requirements": "See UNDP portal",
                        "status": "Open", "award_status": "Published",
                        "contact_person": str(n.get("contact_name") or n.get("contact") or "")[:200],
                        "contact_email": str(n.get("contact_email") or n.get("email") or "")[:200],
                        "contact_phone": str(n.get("contact_phone") or n.get("phone") or "")[:50],
                    })
                if undp_open:
                    _upsert(undp_open, country, "UNDP Open", log)
                    total_open += len(undp_open)
        except Exception:
            pass

    log(f"  🌍 Non-OCDS countries: {total_open} open + {total_awarded} awarded tenders collected")


# ═══════════════════════════════════════════════════════════════════════════
# ANNOTATION SNAPSHOT / RESTORE  (preserve AI scores across the open-delete)
# ═══════════════════════════════════════════════════════════════════════════
def _snapshot_open_annotations() -> dict:
    snap = {}
    try:
        step, start = 1000, 0
        while True:
            rows = (supabase.table("sa_tenders")
                    .select("tender_number, ai_score, ai_rationale, is_irrelevant")
                    .eq("status", "Open")
                    .range(start, start + step - 1).execute().data) or []
            for r in rows:
                tn = r.get("tender_number")
                if tn and (r.get("ai_score") is not None or r.get("is_irrelevant")):
                    snap[tn] = {
                        "ai_score": r.get("ai_score"),
                        "ai_rationale": r.get("ai_rationale"),
                        "is_irrelevant": r.get("is_irrelevant"),
                    }
            if len(rows) < step:
                break
            start += step
    except Exception:
        pass
    return snap


def _restore_open_annotations(snap: dict, log=None) -> int:
    if not snap:
        return 0
    restored = 0
    for tn, vals in snap.items():
        payload = {k: v for k, v in vals.items() if v is not None}
        if not payload:
            continue
        try:
            res = (supabase.table("sa_tenders").update(payload)
                   .eq("tender_number", tn).eq("status", "Open").execute())
            if res.data:
                restored += len(res.data)
        except Exception:
            pass
    if log and restored:
        log(f"  ♻️ Restored AI scores/flags on {restored} tender(s) that survived the refresh.")
    return restored


# ═══════════════════════════════════════════════════════════════════════════
# COUNTS
# ═══════════════════════════════════════════════════════════════════════════
def _count_rows(table: str, **filters) -> int:
    try:
        q = supabase.table(table).select("id", count="exact")
        for k, v in filters.items():
            q = q.eq(k, v)
        return q.execute().count or 0
    except Exception:
        return 0


# ═══════════════════════════════════════════════════════════════════════════
# AI USAGE TRACKING  (persists to ai_usage_log, same as the app)
# ═══════════════════════════════════════════════════════════════════════════
_AI_DAILY_LIMITS = {
    "Groq": 1000, "Cerebras": 500, "OpenRouter": 200, "GitHub": 150,
    "NVIDIA": 200, "DeepSeek": 500, "Gemini": 20,
}


def _today_str() -> str:
    return _dt.date.today().isoformat()


def _get_usage() -> dict:
    global _USAGE, _USAGE_DATE
    today = _today_str()
    if _USAGE_DATE != today:
        _USAGE = {p: 0 for p in _AI_DAILY_LIMITS}
        _USAGE_DATE = today
        try:
            row = supabase.table("ai_usage_log").select("*").eq("usage_date", today).execute()
            for entry in (row.data or []):
                p = entry.get("provider", "")
                if p in _USAGE:
                    _USAGE[p] = entry.get("count", 0)
        except Exception:
            pass
    return _USAGE


def _increment_usage(provider: str):
    usage = _get_usage()
    usage[provider] = usage.get(provider, 0) + 1
    try:
        supabase.table("ai_usage_log").upsert(
            {"usage_date": _today_str(), "provider": provider, "count": usage[provider]},
            on_conflict="usage_date,provider",
        ).execute()
    except Exception:
        pass


def _provider_budget_ok(provider: str) -> bool:
    return _get_usage().get(provider, 0) < _AI_DAILY_LIMITS.get(provider, 999)


# ═══════════════════════════════════════════════════════════════════════════
# AI CASCADE  (env-keyed, no Streamlit — mirrors the app's models + order)
# ═══════════════════════════════════════════════════════════════════════════
_GITHUB_FREE_MODELS = [
    "Llama-3.3-70B-Instruct", "gpt-4o-mini", "Mistral-Large-2411", "Phi-4",
]
_OPENROUTER_FREE_MODELS = [
    "openrouter/free", "deepseek/deepseek-r1:free",
    "deepseek/deepseek-v3:free", "meta-llama/llama-4-maverick:free",
]


def _clean(raw: str) -> str:
    return re.sub(r"^```json[\s]*|^```[\s]*|```$", "", (raw or "").strip(),
                  flags=re.MULTILINE).strip()


def _is_rate_limit(err: str) -> bool:
    return any(x in (err or "").lower()
               for x in ["429", "quota", "rate limit", "too many", "throttl"])


def _safe_json(raw: str, expect_list: bool = True):
    raw = re.sub(r"^```json[\s]*|^```[\s]*|```$", "", (raw or "").strip(),
                 flags=re.MULTILINE).strip()
    pattern = r"\[.*\]" if expect_list else r"\{.*\}"
    m = re.search(pattern, raw, re.DOTALL)
    if m:
        raw = m.group(0)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        objects = re.findall(r'\{[^{}]+\}', raw, re.DOTALL)
        results = []
        for obj in objects:
            try:
                results.append(json.loads(obj))
            except Exception:
                pass
        if expect_list:
            return results
        return results[0] if results else {}


def _call_groq(prompt, max_tokens=2000):
    resp = groq_ai.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2, max_tokens=max_tokens)
    return _clean(resp.choices[0].message.content)


def _call_cerebras(prompt, max_tokens=2000):
    for model in ["gpt-oss-120b", "zai-glm-4.7"]:
        try:
            resp = cerebras_ai.chat.completions.create(
                model=model, messages=[{"role": "user", "content": prompt}],
                temperature=0.2, max_tokens=max_tokens)
            msg = resp.choices[0].message
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
    raise ValueError("All Cerebras models unavailable")


def _call_openrouter(prompt, max_tokens=2000):
    last_err = None
    for model in _OPENROUTER_FREE_MODELS:
        try:
            resp = openrouter_ai.chat.completions.create(
                model=model, messages=[{"role": "user", "content": prompt}],
                temperature=0.2, max_tokens=max_tokens, timeout=30)
            text = (resp.choices[0].message.content or "").strip()
            if text:
                return _clean(text)
        except Exception as e:
            last_err = e
            es = str(e)
            if _is_rate_limit(es):
                time.sleep(3)
                continue
            if any(x in es.lower() for x in ["404", "unavailable", "does not exist", "not found"]):
                continue
            raise
    raise RuntimeError(f"All OpenRouter free models failed. Last: {last_err}")


def _call_github(prompt, max_tokens=2000):
    last_err = None
    for model in _GITHUB_FREE_MODELS:
        try:
            resp = github_ai.chat.completions.create(
                model=model, messages=[{"role": "user", "content": prompt}],
                temperature=0.2, max_tokens=max_tokens)
            text = (resp.choices[0].message.content or "").strip()
            if text:
                return _clean(text)
        except Exception as e:
            last_err = e
            if any(x in str(e).lower() for x in ["404", "not found", "does not exist"]):
                continue
            if _is_rate_limit(str(e)):
                time.sleep(2)
                continue
            raise
    raise RuntimeError(f"All GitHub Models failed. Last: {last_err}")


def _call_nvidia(prompt, max_tokens=2000):
    for model in ["meta/llama-3.3-70b-instruct", "mistralai/mistral-large-2411",
                  "nvidia/llama-3.3-nemotron-super-49b-v1"]:
        try:
            resp = nvidia_ai.chat.completions.create(
                model=model, messages=[{"role": "user", "content": prompt}],
                temperature=0.2, max_tokens=max_tokens)
            text = (resp.choices[0].message.content or "").strip()
            if text:
                return _clean(text)
        except Exception as e:
            if any(x in str(e) for x in ["404", "not found", "unknown", "unavailable"]):
                continue
            raise
    raise RuntimeError("All NVIDIA NIM models failed")


def _call_deepseek(prompt, max_tokens=2000):
    for model in ["deepseek-chat", "deepseek-reasoner"]:
        try:
            resp = deepseek_ai.chat.completions.create(
                model=model, messages=[{"role": "user", "content": prompt}],
                temperature=0.2, max_tokens=max_tokens)
            text = (resp.choices[0].message.content or "").strip()
            if text:
                return _clean(text)
        except Exception as e:
            if any(x in str(e) for x in ["404", "not found", "unknown", "insufficient"]):
                continue
            raise
    raise RuntimeError("All DeepSeek models failed")


def _call_gemini(prompt, max_tokens=2000, retries=3):
    if gemini_client is None:
        raise RuntimeError("Gemini not initialised")
    delay = 20
    for attempt in range(retries):
        try:
            response = gemini_client.models.generate_content(
                model="gemini-2.5-flash", contents=prompt)
            return _clean(response.text)
        except Exception as e:
            if _is_rate_limit(str(e)) and attempt < retries - 1:
                time.sleep(delay * (attempt + 1))
            else:
                raise
    raise RuntimeError("Gemini quota exceeded after retries.")


def any_ai_available() -> bool:
    return any([groq_ai, cerebras_ai, openrouter_ai, github_ai,
                nvidia_ai, deepseek_ai, gemini_client])


def _call_ai(prompt: str, max_tokens: int = 2000, log=_log_default) -> str:
    """Smart cascade. Skips providers over daily budget. Raises if all fail."""
    providers = []
    if groq_ai and _provider_budget_ok("Groq"):
        providers.append(("Groq", _call_groq))
    if cerebras_ai and _provider_budget_ok("Cerebras"):
        providers.append(("Cerebras", _call_cerebras))
    if openrouter_ai:
        providers.append(("OpenRouter", _call_openrouter))
    if github_ai and _provider_budget_ok("GitHub"):
        providers.append(("GitHub", _call_github))
    if nvidia_ai and _provider_budget_ok("NVIDIA"):
        providers.append(("NVIDIA", _call_nvidia))
    if deepseek_ai and _provider_budget_ok("DeepSeek"):
        providers.append(("DeepSeek", _call_deepseek))
    if gemini_client and _provider_budget_ok("Gemini"):
        providers.append(("Gemini", _call_gemini))

    if not providers:
        raise RuntimeError("All AI providers have hit their daily limits or have no key.")

    last_err = None
    for name, fn in providers:
        try:
            result = fn(prompt, max_tokens)
            _increment_usage(name)
            return result
        except Exception as e:
            last_err = e
            if _is_rate_limit(str(e)):
                _increment_usage(name)
            continue
    raise RuntimeError(f"All AI providers failed. Last error: {last_err}")


# ═══════════════════════════════════════════════════════════════════════════
# SCORING  (prompt verbatim from the app for score consistency)
# ═══════════════════════════════════════════════════════════════════════════
def ai_score_tender(tender: dict, log=_log_default) -> dict:
    country = tender.get("country", "South Africa")
    title = tender.get("title", "N/A")
    dept = tender.get("department_name", "N/A")
    desc = tender.get("description", "N/A")
    value = tender.get("award_value", "Unknown")
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
        "Todyl (SASE/SIEM/MXDR/EDR/GRC consolidated platform), "
        "Panorays (third-party/supply-chain cyber risk & attack surface mgmt, DORA), "
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

    raw = _call_ai(prompt, log=log)
    try:
        result = _safe_json(raw, expect_list=False)
        if not isinstance(result, dict):
            result = {}
    except Exception:
        result = {}

    if "score" not in result:
        m = re.search(r'"score"[\s]*:[\s]*(\d+)', raw or "")
        result["score"] = int(m.group(1)) if m else 5
    if "rationale" not in result:
        result["rationale"] = (raw or "")[:300] or "No rationale returned."
    return result


def _fetch_unscored_open(log) -> list:
    """All Open, non-irrelevant, unscored tenders. Paginated."""
    rows, step, start = [], 1000, 0
    while True:
        try:
            batch = (supabase.table("sa_tenders").select("*")
                     .eq("status", "Open").neq("is_irrelevant", True)
                     .range(start, start + step - 1).execute().data) or []
        except Exception as e:
            log(f"  ❌ Could not fetch open tenders: {e}")
            break
        rows.extend(batch)
        if len(batch) < step:
            break
        start += step
    return [r for r in rows if r.get("ai_score") in (None, "")]


def run_scoring(log, max_score: int = 300, time_budget_s: int = 3000) -> int:
    """Score unscored open tenders. Soonest-closing first. Writes ai_score +
    ai_rationale (JSON blob, same shape the app's Score-All produces) and
    appends to tender_score_history. Returns count scored."""
    if not any_ai_available():
        log("  ⚠️ No AI providers configured — skipping scoring.")
        return 0

    unscored = _fetch_unscored_open(log)
    if not unscored:
        log("  ✅ No unscored open tenders — scoring up to date.")
        return 0

    def _cd_key(r):
        s = str(r.get("closing_date") or "")[:10]
        return s if len(s) == 10 else "9999-12-31"
    unscored.sort(key=_cd_key)

    batch = unscored[:max(int(max_score), 0)]
    log(f"  Scoring {len(batch)} of {len(unscored)} unscored open tender(s)…")

    t0 = time.time()
    scored_n = 0
    history_rows = []
    for row in batch:
        if time.time() - t0 > time_budget_s:
            log(f"  ⏱️ Scoring time budget ({time_budget_s}s) reached — stopping early.")
            break
        tn = row.get("tender_number")
        if not tn:
            continue
        try:
            scored = ai_score_tender(row, log=log)
            rationale_blob = json.dumps({
                "rationale": scored.get("rationale", ""),
                "partner_type": scored.get("partner_type", ""),
                "proposed_solutions": scored.get("proposed_solutions", []),
                "outreach_angle": scored.get("outreach_angle", ""),
            })
            supabase.table("sa_tenders").update(
                {"ai_score": scored["score"], "ai_rationale": rationale_blob}
            ).eq("tender_number", tn).execute()
            history_rows.append({
                "tender_number": str(tn)[:100],
                "department": str(row.get("department_name", ""))[:200],
                "title": str(row.get("title", ""))[:200],
                "country": str(row.get("country", "")),
                "closing_date": (str(row.get("closing_date") or "")[:10] or None),
                "ai_score": scored["score"],
                "ai_rationale": rationale_blob[:2000],
                "status": "Open",
            })
            scored_n += 1
            time.sleep(1)  # throttle to respect free-tier RPM
        except Exception as e:
            log(f"  Scoring error {tn}: {e}")

    if history_rows:
        try:
            supabase.table("tender_score_history").insert(history_rows).execute()
        except Exception as e:
            log(f"  History insert error: {e}")

    remaining = len(unscored) - scored_n
    if remaining > 0:
        log(f"  ℹ️ Scored {scored_n} · {remaining} still unscored (next run continues).")
    else:
        log(f"  ✅ Scored all {scored_n} open tender(s).")
    return scored_n


# ═══════════════════════════════════════════════════════════════════════════
# PARTNER ANALYSIS  (pure-python aggregation — no pandas; prompt verbatim)
# ═══════════════════════════════════════════════════════════════════════════
def _fetch_awarded(log) -> list:
    rows, step, start = [], 1000, 0
    while True:
        try:
            batch = (supabase.table("awarded_tenders").select("*")
                     .range(start, start + step - 1).execute().data) or []
        except Exception as e:
            log(f"  ❌ Could not fetch awarded tenders: {e}")
            break
        rows.extend(batch)
        if len(batch) < step:
            break
        start += step
    return rows


def ai_analyse_partners(awarded_rows: list, log=_log_default) -> list:
    rows = [r for r in awarded_rows if r.get("winning_bidder")]
    if not rows:
        return []

    groups = _collections.OrderedDict()
    for r in rows:
        groups.setdefault(str(r["winning_bidder"]).strip(), []).append(r)

    agg = []
    for company, grp in groups.items():
        if not company or len(company) < 3:
            continue
        countries = _collections.Counter(str(g.get("country") or "Unknown") for g in grp)
        country = countries.most_common(1)[0][0] if countries else "Unknown"
        titles = [str(g.get("title") or "")[:80] for g in grp if g.get("title")][:5]
        depts = list(dict.fromkeys(
            str(g.get("department_name") or "")[:50] for g in grp if g.get("department_name")))[:2]
        t_nums = [str(g.get("tender_number") or "")[:30] for g in grp if g.get("tender_number")][:2]
        agg.append({"company": company[:80], "country": country[:50], "wins": len(grp),
                    "titles": " | ".join(titles), "depts": " | ".join(depts),
                    "ref_nos": " | ".join(t_nums)})

    agg.sort(key=lambda x: x["wins"], reverse=True)
    agg = agg[:40]

    lines = ["company|country|wins|sample_tenders|departments|ref_numbers"]
    for r in agg:
        lines.append(f"{r['company']}|{r['country']}|{r['wins']}|{r['titles']}|{r['depts']}|{r['ref_nos']}")
    table_text = "\n".join(lines)

    schema_example = (
        '{"company":"Acme Tech","country":"South Africa","tenders_won":5,'
        '"partner_classification":"System Integrator",'
        '"proposed_solutions":["VECTRA","vRx"],'
        '"key_tenders":["RFQ/2024/001","ICT-2023-045"],'
        '"tenders_won_summary":"Mostly large-scale network and security infrastructure '
        'contracts for national government and policing - supply, installation, monitoring and support.",'
        '"issuing_departments":["SAPS","Dept of Health"],'
        '"why_aligned":"Wins large ICT integration tenders for government clients.",'
        '"outreach_angle":"Lead with VECTRA NDR - they won the SAPS network monitoring tender.",'
        '"urgency":"high","estimated_deal_size":"large"}'
    )

    prompt = (
        "You are a channel-partner analyst for Cyber Retaliator Solutions (CRS), "
        "a cyber security distributor and IBM/RedHat/SUSE/CompTIA training partner in South Africa.\n\n"
        "CRS VENDOR PORTFOLIO: VECTRA (NDR/XDR), vRx (vuln/patch), Strobes (CTEM/PTaaS), "
        "Aikido (AppSec), Flare (dark web intel), BeachheadSecure (encryption/MFA), "
        "SMBsecure (SMB/POPIA), Telivy (MSSP audit), BlueFlag (SDLC), Standss/SendGuard (email GRC), "
        "Todyl (SASE/SIEM/MXDR/EDR/GRC platform), Panorays (third-party/supply-chain cyber risk, attack surface), "
        "CRE/GoldPhish (cyber awareness), VAPT services, IBM/RedHat/SUSE/CompTIA/Agile training.\n\n"
        "PARTNER TYPES: System Integrator | MSP | VAR | Training Provider | Consulting/Advisory | End-user\n\n"
        "AGGREGATED TENDER WIN DATA (pipe-delimited):\n"
        + table_text +
        "\n\nIdentify the TOP 12 companies CRS should approach as channel partners or resellers. "
        "Focus on ICT/security companies — exclude government departments, construction, catering, "
        "cleaning, vehicles, stationery.\n\n"
        "For each company, set 'tenders_won_summary' to a concise 1–2 sentence plain-English "
        "description of the TYPES of tenders/work that company has won — inferred from its sample "
        "tenders and the departments it serves.\n\n"
        "Return ONLY a valid JSON array — no markdown fences, no explanation. "
        "Array must start with [ and end with ]. Each element must follow this exact schema:\n"
        "[" + schema_example + ", ...]"
    )

    raw = _call_ai(prompt, max_tokens=6000, log=log)
    raw = re.sub(r"```json[\s]*|```[\s]*", "", (raw or "").strip()).strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\[[\s\S]*\]", raw)
        parsed = []
        if m:
            try:
                parsed = json.loads(m.group(0))
            except json.JSONDecodeError:
                for obj in re.findall(r"\{[^{}]+\}", raw):
                    try:
                        parsed.append(json.loads(obj))
                    except Exception:
                        pass
    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list):
        parsed = []
    return [p for p in parsed if isinstance(p, dict) and p.get("company")]


def run_partner_analysis(log) -> int:
    if not any_ai_available():
        log("  ⚠️ No AI providers configured — skipping partner analysis.")
        return 0
    awarded = _fetch_awarded(log)
    if not awarded:
        log("  ℹ️ No awarded tenders to analyse.")
        return 0
    log(f"  Analysing {len(awarded):,} awarded rows for partner candidates…")
    try:
        partners = ai_analyse_partners(awarded, log=log)
    except Exception as e:
        log(f"  Partner analysis error: {e}")
        return 0

    def _js(v):
        """Serialise list/dict to JSON string; pass strings through."""
        if v is None:
            return None
        if isinstance(v, (list, dict)):
            return json.dumps(v)
        return str(v)

    rows = []
    for p in partners:
        if not isinstance(p, dict) or not p.get("company"):
            continue
        rows.append({
            "company":              str(p.get("company", ""))[:200],
            "country":              str(p.get("country", ""))[:100],
            "crs_score":            p.get("tenders_won"),          # count of wins as proxy score
            "why":                  str(p.get("why_aligned", ""))[:1000],
            "outreach_angle":       str(p.get("outreach_angle", ""))[:1000],
            "urgency":              str(p.get("urgency", ""))[:20],
            "partnership_type":     str(p.get("partner_classification", ""))[:100],
            "tenders_won":          p.get("tenders_won"),
            "proposed_solutions":   _js(p.get("proposed_solutions", [])),
            "key_tenders":          _js(p.get("key_tenders", [])),
            "tenders_won_summary":  str(p.get("tenders_won_summary", ""))[:2000],
            "issuing_departments":  _js(p.get("issuing_departments", [])),
            "estimated_deal_size":  str(p.get("estimated_deal_size", ""))[:50],
        })

    if rows:
        try:
            supabase.table("partner_recommendation_history").insert(rows).execute()
        except Exception as e:
            log(f"  Partner history insert error: {e}")
    log(f"  ✅ {len(rows)} partner candidate(s) written.")
    return len(rows)


# ═══════════════════════════════════════════════════════════════════════════
# ORCHESTRATION
# ═══════════════════════════════════════════════════════════════════════════
def run_scrape(log, years_back: int = 3,
               countries_filter: list | None = None,
               include_non_ocds: bool = True) -> dict:
    """Full Africa scrape, preserving AI annotations across the open-delete.

    countries_filter: if provided, only scrape those country names.
    include_non_ocds: if False, skip the World Bank / UNDP pass.
    Passing neither argument reproduces the original full-scrape behaviour.
    """
    _cf = set(countries_filter) if countries_filter else None
    before_open = _count_rows("sa_tenders", status="Open")
    before_awarded = _count_rows("awarded_tenders")
    log(f"📦 Start state — {before_open:,} open, {before_awarded:,} awarded in Supabase.")

    snap = _snapshot_open_annotations()
    if snap:
        log(f"💾 Saved AI scores/flags for {len(snap)} tender(s) to re-apply after scraping.")

    # South Africa — live API, OCDS fallback
    if _cf is None or "South Africa" in _cf:
        try:
            scrape_south_africa(log)
        except Exception as e:
            log(f"  ⚠️ SA live API failed ({e}) — falling back to OCDS registry…")
            try:
                scrape_ocds_country("South Africa", log, years_back)
            except Exception as e2:
                log(f"  ❌ SA OCDS fallback also failed: {e2}")

    # Other OCDS countries
    for country in OCDS_REGISTRY:
        if country == "South Africa":
            continue
        if _cf is not None and country not in _cf:
            continue
        try:
            scrape_ocds_country(country, log, years_back)
        except Exception as e:
            log(f"  ❌ {country} crashed: {e}")

    # Non-OCDS via World Bank + UNDP
    if include_non_ocds:
        try:
            log("🌍 Scraping non-OCDS countries via World Bank & UNDP…")
            scrape_non_ocds_countries(log)
        except Exception as e:
            log(f"  ❌ Non-OCDS scraper crashed: {e}")

    _restore_open_annotations(snap, log)

    after_open = _count_rows("sa_tenders", status="Open")
    after_awarded = _count_rows("awarded_tenders")
    log(f"✅ Scrape complete — open {before_open:,}→{after_open:,} "
        f"({after_open - before_open:+,}), awarded {before_awarded:,}→{after_awarded:,} "
        f"({max(after_awarded - before_awarded, 0):+,} new).")
    return {"open": after_open, "awarded": after_awarded,
            "new_open": after_open - before_open,
            "new_awarded": max(after_awarded - before_awarded, 0)}


def run_all(years_back: int = 3, max_score: int = 300, do_partner: bool = True,
            score_time_budget_s: int = 3000, trigger: str = "github_action",
            countries_filter: list | None = None, include_non_ocds: bool = True,
            log=_log_default) -> dict:
    """End-to-end nightly run: scrape → score → (optional) partner analysis.
    Logs a pipeline_runs record so the dashboard's Tab 6 history shows it."""
    t0 = time.time()
    run_id = None
    try:
        rec = supabase.table("pipeline_runs").insert(
            {"trigger": trigger, "status": "running"}).execute()
        run_id = rec.data[0]["id"]
    except Exception as e:
        log(f"Could not create pipeline_runs record: {e}")

    counters = {"tenders_scraped": 0, "tenders_scored": 0, "partners_found": 0}
    log("════════ CRS daily ingest ════════")

    try:
        log("─ 1. Scrape ─")
        scrape_res = run_scrape(log, years_back,
                                countries_filter=countries_filter,
                                include_non_ocds=include_non_ocds)
        counters["tenders_scraped"] = scrape_res.get("open", 0)

        log("─ 2. AI scoring ─")
        counters["tenders_scored"] = run_scoring(log, max_score, score_time_budget_s)

        if do_partner:
            log("─ 3. Partner analysis ─")
            counters["partners_found"] = run_partner_analysis(log)

        status = "success"
        err_log = None
    except Exception as e:
        status = "failed"
        err_log = str(e)[:5000]
        log(f"❌ Run failed: {e}")

    duration = int(time.time() - t0)
    if run_id:
        try:
            supabase.table("pipeline_runs").update({
                "status": status if status != "running" else "complete",
                "tenders_scraped": counters["tenders_scraped"],
                "tenders_scored": counters["tenders_scored"],
                "partners_found": counters["partners_found"],
                "duration_secs": duration,
                "error_log": err_log,
            }).eq("id", run_id).execute()
        except Exception:
            pass

    log(f"════════ Done in {duration}s — scored {counters['tenders_scored']}, "
        f"partners {counters['partners_found']} ════════")
    counters["status"] = status
    counters["duration_secs"] = duration
    return counters