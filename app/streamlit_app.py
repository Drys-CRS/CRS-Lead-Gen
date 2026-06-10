import streamlit as st
import pandas as pd
import os
import json
import re
import google.generativeai as genai
from supabase import create_client

# ─────────────────────────────────────────────
# 1. PAGE CONFIG
# ─────────────────────────────────────────────
st.set_page_config(page_title="CRS Competitive Intelligence", layout="wide")

# ─────────────────────────────────────────────
# 2. CRS COMPANY PROFILE
#    Edit this to reflect your actual capabilities.
#    Gemini uses this when scoring and matching.
# ─────────────────────────────────────────────
CRS_PROFILE = """
Company: Cyber Retaliator Solutions (CRS)
Head Office: Centurion, South Africa. Training centres in Centurion, Midrand, Sandton, Cape Town.
Profile: Value Added Cyber Security Distributor and Authorized Training Delivery Partner
operating globally with 20+ years of experience. Serves reseller, managed services, and
system integration channels across Africa.

── TECHNICAL TRAINING (Authorized Delivery Partner) ──
- IBM Technical Training (incl. z/OS, IBM i, IBM Power, mainframe skills)
- Red Hat Learning (RHEL, OpenShift, certifications: RHCSA, RHCE)
- SUSE Technical Product Training
- CompTIA programmes (A+, Network+, Security+, CySA+ — recruiting, training, certifying students)
- Agile training
- AI / emerging technology training

── CYBER SECURITY SOLUTIONS (Distribution & Services) ──
- Vectra AI: XDR/NDR/ITDR/CDR — AI-powered network & identity threat detection and response,
  SOC enablement, M365/AWS/Azure AD attack detection
- vRx (Vicarius): vulnerability management + patch management, auto-remediation
- Strobes Security: CTEM platform — attack surface management, pentesting-as-a-service (PTaaS),
  risk-based vulnerability management, application security posture management
- Aikido: developer-first AppSec — SAST, DAST, SCA, secrets detection, IaC scanning,
  container scanning, cloud posture (CSPM), AI code review
- Flare: threat exposure management — dark web monitoring, leaked credential detection,
  brand protection, supply chain ransomware monitoring, takedown services
- BeachheadSecure / SMBsecure: endpoint encryption (BitLocker/FileVault), data access control,
  remote wipe, USB port control, MFA, POPIA compliance reporting
- Telivy: cyber risk discovery & attack surface management for MSSPs
- BlueFlag Security: identity-centric SDLC / software supply chain security
- Cyber Risk Essentials: phishing simulation & cyber awareness training
- VAPT services: third-party vulnerability and penetration testing through the channel

── TARGET MARKETS ──
Government, financial services, healthcare, education, enterprises across Africa.
Strong fit: tenders for cybersecurity solutions/services, technical training delivery
(especially IBM/RedHat/SUSE/CompTIA), SOC services, vulnerability management,
security awareness, and POPIA/ISO 27001 compliance support.
Weak fit: pure hardware supply, civil works, non-ICT goods.
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
# 4. AI CLIENTS  (Groq → Cerebras → Gemini cascade)
#
# Priority for scoring/parsing:
#   1. Groq        — 30 RPM free, fastest inference (~1s responses)
#   2. Cerebras    — 1M tokens/day free, fast, good fallback
#   3. Gemini      — 5 RPM free, kept for grounded web search (Discovery tab)
#
# Each key is optional — the cascade skips any provider whose key is missing.
# ─────────────────────────────────────────────
import time as _time

@st.cache_resource
def init_gemini():
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    return genai.GenerativeModel("gemini-2.5-flash")

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

ai         = init_gemini()
groq_ai    = init_groq()
cerebras_ai = init_cerebras()

# ── Provider status shown in sidebar ──
def _provider_status() -> str:
    parts = []
    parts.append("🟢 Groq"     if groq_ai     else "⚪ Groq (no key)")
    parts.append("🟢 Cerebras" if cerebras_ai else "⚪ Cerebras (no key)")
    parts.append("🟢 Gemini")
    return " · ".join(parts)

def _clean(raw: str) -> str:
    """Strip markdown fences from an AI response."""
    return re.sub(r"^```json\s*|^```\s*|```$", "", raw.strip(), flags=re.MULTILINE).strip()

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
    """Call Cerebras (llama3.1-70b). Raises on any error."""
    resp = cerebras_ai.chat.completions.create(
        model="llama3.1-70b",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=1500,
    )
    return _clean(resp.choices[0].message.content)

def _call_gemini(prompt: str, retries: int = 3) -> str:
    """Call Gemini with backoff. Raises after all retries."""
    delay = 20
    for attempt in range(retries):
        try:
            response = ai.generate_content(prompt)
            return _clean(response.text)
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
    Tries each provider in order; skips unavailable or rate-limited ones.
    Raises only if ALL providers fail."""
    providers = []
    if groq_ai:
        providers.append(("Groq", _call_groq))
    if cerebras_ai:
        providers.append(("Cerebras", _call_cerebras))
    providers.append(("Gemini", _call_gemini))

    last_err = None
    for name, fn in providers:
        try:
            result = fn(prompt)
            return result
        except Exception as e:
            last_err = e
            err_str = str(e)
            if _is_rate_limit(err_str):
                st.toast(f"⏳ {name} rate limit hit — trying next provider…")
                continue  # try next provider
            else:
                # Hard error (auth, model not found, etc.) — skip this provider
                st.toast(f"⚠️ {name} error: {err_str[:80]} — trying next provider…")
                continue
    raise RuntimeError(
        f"All AI providers failed. Last error: {last_err}\n"
        "Check your API keys in Streamlit secrets."
    )


def _call_ai_grounded(prompt: str) -> str:
    """Call Gemini WITH Google Search grounding so it can find current web results.
    Falls back to ungrounded if grounding is unavailable on this API tier/model."""
    grounded_attempts = [
        # Gemini 2.5 Flash with Google Search grounding (current SDK syntax)
        lambda: genai.GenerativeModel(
            "gemini-2.5-flash",
            tools=[{"google_search": {}}]
        ).generate_content(prompt),
        # Fallback: 2.5 Pro for higher quality grounded results
        lambda: genai.GenerativeModel(
            "gemini-2.5-pro",
            tools=[{"google_search": {}}]
        ).generate_content(prompt),
    ]
    for attempt in grounded_attempts:
        try:
            response = attempt()
            raw = response.text.strip()
            return re.sub(r"^```json\s*|^```\s*|```$", "", raw, flags=re.MULTILINE).strip()
        except Exception:
            continue
    # Ungrounded fallback — still useful (suggests known portals/companies) but not live
    return _call_ai(prompt)


def ai_analyse_partners(awarded_df) -> list:
    """Given a dataframe of awarded tenders, ask Gemini to identify which winning
    companies look like strong CRS channel partners and explain why."""
    # Build a concise data summary — cap at 60 rows to stay within token limits
    sample = awarded_df[["winning_bidder", "title", "country", "award_value"]].dropna(
        subset=["winning_bidder"]
    ).head(60)

    rows_text = sample.to_csv(index=False)

    prompt = f"""You are a channel-partner strategist for Cyber Retaliator Solutions (CRS).

CRS PROFILE:
{CRS_PROFILE}

Below is a CSV of companies that have been winning government and public-sector tenders
in Africa for technology, security, and ICT-related work. Your job is to identify which
of these companies CRS should approach as a channel partner, reseller, or systems
integrator — companies that are already winning deals in the right space but may be
missing CRS's vendor portfolio (Vectra, vRx, Aikido, Flare, SMBsecure, BeachheadSecure,
IBM/RedHat/SUSE/CompTIA training, VAPT services).

AWARDED TENDER DATA:
{rows_text}

For each recommended company, assess:
1. Why they align with CRS's portfolio based on the tenders they're winning
2. Partnership type that makes sense (reseller, referral, integration partner, training sub-contractor)
3. A realistic outreach angle in one sentence

Return ONLY a JSON array (no other text). Each element:
{{
  "company": "company name",
  "country": "country",
  "tenders_won": <integer — count from the data>,
  "partnership_type": "reseller / referral / integration partner / training sub-contractor",
  "why_aligned": "1-2 sentences on fit",
  "outreach_angle": "one sentence — what CRS should lead with",
  "urgency": "high / medium / low"
}}

Return the top 10-15 most promising companies. Exclude companies that only won
non-ICT tenders (construction, catering, stationery, vehicles, etc.).
Only return the JSON array.
"""
    raw = _call_ai(prompt)
    parsed = json.loads(raw)
    return parsed if isinstance(parsed, list) else []


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
    parsed = json.loads(raw)
    return parsed if isinstance(parsed, list) else []

# ─────────────────────────────────────────────
# 5. DATA FETCHING
# ─────────────────────────────────────────────
@st.cache_data(ttl=300)
def fetch_tenders():
    try:
        response = supabase.table("sa_tenders").select("*").execute()
        return pd.DataFrame(response.data)
    except Exception as e:
        st.error(f"Error fetching data: {e}")
        return pd.DataFrame()

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
    return json.loads(raw)


def ai_score_tender(tender: dict) -> dict:
    """Score a tender 1-10 for fit against CRS profile. Returns {score, rationale}."""
    prompt = f"""You are a bid/no-bid analyst for a South African technology and security company.

COMPANY PROFILE:
{CRS_PROFILE}

TENDER:
Title: {tender.get('title', 'N/A')}
Department: {tender.get('department_name', 'N/A')}
Description: {tender.get('description', 'N/A')}
Compliance Requirements: {tender.get('compliance_requirements', 'N/A')}
Closing Date: {tender.get('closing_date', 'N/A')}
Value: {tender.get('award_value', 'Unknown')}

Score this tender on fit for the company on a scale of 1–10, where:
- 10 = Perfect match, must bid
- 7–9 = Strong fit, worth serious consideration
- 4–6 = Partial fit, marginal opportunity
- 1–3 = Poor fit, likely not worth pursuing

Return ONLY a valid JSON object:
{{
  "score": <integer 1-10>,
  "rationale": "<2-3 sentence explanation covering fit, risks, and recommendation>"
}}

No text outside the JSON.
"""
    raw = _call_ai(prompt)
    return json.loads(raw)


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
            results.append({
                "tender_number": row["tender_number"],
                "ai_score": scored["score"],
                "ai_rationale": scored["rationale"],
            })
            supabase.table("sa_tenders").update({
                "ai_score": scored["score"],
                "ai_rationale": scored["rationale"],
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

    cutoff = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

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
                })
            start += len(batch)
            if start >= int(data2.get("recordsTotal", 0)):
                break
        # UPSERT only — never wipe awarded history
        _upsert(awarded_records, country, "Awarded (12-month)", out)

    except Exception as e:
        out(f"  ❌ {country} error: {e}")

# ── OCDS Registry scraper (Kenya, Ghana, Tanzania, Uganda, Nigeria, Zambia, Rwanda) ──
# Downloads standardised OCDS data from the Open Contracting Data Registry:
# https://data.open-contracting.org — one consistent JSONL format for all countries.

OCDS_REGISTRY = {
    # country: (publication_id, flag)
    # South Africa included as FALLBACK only — live eTenders API is primary
    "South Africa": (143, "🇿🇦"),
    "Kenya":    (147, "🇰🇪"),
    "Ghana":    (85,  "🇬🇭"),
    "Tanzania": (152, "🇹🇿"),
    "Uganda":   (130, "🇺🇬"),
    "Nigeria":  (64,  "🇳🇬"),
    "Zambia":   (3,   "🇿🇲"),
    "Rwanda":   (145, "🇷🇼"),
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
    """Pull 12 months of open + awarded tenders for one country from the OCDS registry.
    - Downloads current year AND previous year files and merges them.
    - Open records replace existing ones (stale tenders close daily).
    - Awarded records are UPSERTED only — history is never wiped.
    - Awards older than 12 months are filtered out before upserting.
    """
    import json as _json
    from datetime import datetime, timezone, timedelta

    pub_id, flag = OCDS_REGISTRY[country]
    out(f"{flag} Scraping {country} (OCDS — 12 months)…")

    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    cutoff = (now - timedelta(days=365)).date().isoformat()
    current_year = now.year

    # Collect lines from both years so we span the full 12-month window
    all_lines = []
    for yr in [current_year, current_year - 1]:
        yr_lines = _download_ocds_year(pub_id, yr)
        if yr_lines:
            all_lines.extend(yr_lines)
            out(f"  ℹ️ {country} {yr}: {len(yr_lines):,} records downloaded")
        else:
            out(f"  ℹ️ {country}: no data for {yr}")

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

        base = {
            "tender_number":   str(tender_id)[:100],
            "department_name": str(buyer)[:200],
            "title":           str(title or desc)[:200],
            "description":     str(desc),
            "category":        str(category),
            "portal_link":     f"https://data.open-contracting.org/en/publication/{pub_id}",
            "country":         country,
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

    # Awarded records: UPSERT only — never wipe, history accumulates
    _upsert(awarded_records, country, f"Awarded (12-month, {len(awarded_records)} records)", out)


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

    # All other countries: OCDS registry (one robust source, consistent format)
    for country in OCDS_REGISTRY:
        if country == "South Africa":
            continue  # handled above with live API + fallback
        try:
            scrape_ocds_country(country, out_write)
        except Exception as e:
            out_write(f"  ❌ {country} crashed: {e}")

    out_write("\n✅ **All countries done!**")

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
if st.sidebar.button("🔄 Refresh All Countries"):
    run_all_scrapers()
    st.cache_data.clear()
    st.rerun()

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
selected_countries = st.sidebar.multiselect(
    "Filter by Country",
    options=all_countries,
    default=all_countries,
    help="Select one or more countries to show"
)

# Date range filter for awarded tenders (12-month history)
st.sidebar.header("Awarded Date Range")
from datetime import date, timedelta
default_from = date.today() - timedelta(days=365)
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
tab1, tab2, tab3, tab4 = st.tabs([
    "📢 Open Opportunities",
    "🏆 Competitive Intelligence",
    "🤖 AI Tender Parser",
    "🔎 AI Discovery (Private Sector)"
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
        if st.button("🤖 Score All with AI", help="Run AI fit scoring on all open tenders"):
            ai_match_tenders(open_df)   # scores are written to Supabase inside
            st.cache_data.clear()
            st.success("Scoring complete! Reloading…")
            st.rerun()  # reload from DB so table shows fresh scores

    # Sort by score if available
    if "ai_score" in open_df.columns and open_df["ai_score"].notna().any():
        open_df = open_df.sort_values("ai_score", ascending=False, na_position="last")

    # Build display frame — Fit Score column is always shown (⚪ — when unscored)
    open_df["Fit Score"] = open_df["ai_score"].apply(score_badge)
    display_cols = ["Fit Score", "country", "tender_number", "department_name", "title", "closing_date"]

    event = st.dataframe(
        open_df[display_cols],
        use_container_width=True,
        selection_mode="single-row",
        on_select="rerun",
        hide_index=True,
    )

    # Detail panel
    if event.selection.rows:
        idx = event.selection.rows[0]
        t = open_df.iloc[idx]

        st.divider()
        header_col, score_col = st.columns([4, 1])
        with header_col:
            st.subheader(f"📄 {t['tender_number']} — {t.get('title', '')}")
        with score_col:
            if pd.notna(t.get("ai_score")):
                st.metric("AI Fit Score", score_badge(t["ai_score"]))

        st.write(f"**Country:** {t.get('country', 'N/A')}  |  **Department:** {t.get('department_name', 'N/A')}")
        st.write(f"**Description:** {t.get('description', 'N/A')}")
        st.write(f"**Compliance Requirements:** {t.get('compliance_requirements', 'N/A')}")
        st.write(f"**Closing Date:** {t.get('closing_date', 'N/A')}")

        # AI rationale
        if pd.notna(t.get("ai_rationale")):
            with st.expander("🤖 AI Analysis", expanded=True):
                st.info(t["ai_rationale"])
        else:
            if st.button("🤖 Score This Tender", key=f"score_{t['tender_number']}"):
                with st.spinner("Scoring…"):
                    try:
                        result = ai_score_tender(t.to_dict())
                        supabase.table("sa_tenders").update({
                            "ai_score": result["score"],
                            "ai_rationale": result["rationale"]
                        }).eq("tender_number", t["tender_number"]).execute()
                        st.cache_data.clear()
                        st.rerun()
                    except Exception as e:
                        st.error(f"Scoring failed: {e}")

        # Actions
        action_col1, action_col2 = st.columns(2)
        with action_col1:
            st.link_button("🌐 View on eTenders", "https://www.etenders.gov.za/Home/opportunities")
        with action_col2:
            if st.button("🗑️ Mark as Irrelevant", key=f"del_{t['tender_number']}"):
                supabase.table("sa_tenders").delete().eq("tender_number", t["tender_number"]).execute()
                st.cache_data.clear()
                st.rerun()


# ══════════════════════════════════════════════
# TAB 2 — COMPETITIVE INTELLIGENCE
# ══════════════════════════════════════════════
with tab2:
    st.subheader("🤝 Potential CRS Channel Partners")
    st.write(
        "These companies are winning ICT and security tenders across Africa. "
        "Gemini analyses their win patterns to recommend which ones CRS should approach "
        "as resellers, integration partners, or training sub-contractors."
    )

    awarded_df = df_filtered[df_filtered["status"] == "Awarded"].copy()

    # Apply 12-month date range filter
    if "issue_date" in awarded_df.columns:
        try:
            # Convert sidebar date objects and df column all to pd.Timestamp for safe comparison
            _from_ts = pd.Timestamp(awarded_date_from)
            _to_ts   = pd.Timestamp(awarded_date_to)
            _dates   = pd.to_datetime(awarded_df["issue_date"], errors="coerce")
            awarded_df = awarded_df[_dates.isna() | ((_dates >= _from_ts) & (_dates <= _to_ts))]
        except Exception:
            pass  # if date filtering fails, show all records rather than crash

    if competitor_search:
        awarded_df = awarded_df[
            awarded_df["winning_bidder"].str.contains(competitor_search, case=False, na=False)
        ]

    if awarded_df.empty:
        st.info("No awarded tenders in the current filters. Run a data refresh to populate this tab.")
    else:
        # ── AI Partner Analysis ──────────────────────────────────────────────
        col_run, col_info = st.columns([2, 5])
        with col_run:
            run_analysis = st.button(
                "🤖 Analyse Partners with AI",
                help="Gemini reviews all awarded tender winners and recommends partner candidates"
            )
        with col_info:
            st.caption(
                f"Based on {len(awarded_df[awarded_df['winning_bidder'].notna()])} awarded tenders "
                f"across {awarded_df['country'].nunique() if 'country' in awarded_df.columns else '?'} countries."
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
                ptype = p.get("partnership_type", "")
                company = p.get("company", "Unknown")
                country = p.get("country", "")
                wins = p.get("tenders_won", "?")

                with st.expander(
                    f"{urgency_icon} **{company}** — {country}  |  {wins} wins  |  {ptype}"
                ):
                    st.write(f"**Why aligned:** {p.get('why_aligned', '')}")
                    st.info(f"💬 Outreach angle: {p.get('outreach_angle', '')}")

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

    if st.button("🔍 Parse Tender", disabled=not raw_input.strip()):
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
                st.metric("Fit Score", score_badge(scored["score"]))
                st.info(scored["rationale"])

            except json.JSONDecodeError:
                st.error("Gemini returned an unexpected format. Try again or simplify the input text.")
            except Exception as e:
                st.error(f"Parsing failed: {e}")

    # Save button — only show after a successful parse
    if "parsed_tender" in st.session_state:
        st.divider()
        if st.button("💾 Save to Database"):
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

    if st.button("🔎 Discover Tenders", disabled=not disc_countries):
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
            if st.button("💾 Save All to Database"):
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
            if st.button("🗑️ Discard Results"):
                del st.session_state["discovered"]
                st.rerun()