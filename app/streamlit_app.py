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
# 4. GEMINI CLIENT
# ─────────────────────────────────────────────
@st.cache_resource
def init_gemini():
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    return genai.GenerativeModel("gemini-1.5-pro")

ai = init_gemini()


def _call_ai(prompt: str) -> str:
    """Single helper to call Gemini and return text."""
    response = ai.generate_content(prompt)
    raw = response.text.strip()
    return re.sub(r"^```json\s*|^```\s*|```$", "", raw, flags=re.MULTILINE).strip()

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


def ai_match_tenders(open_df: pd.DataFrame) -> pd.DataFrame:
    """Score all unscored open tenders and return df sorted by score."""
    if open_df.empty:
        return open_df

    results = []
    progress = st.progress(0, text="Scoring tenders with AI…")

    for i, (_, row) in enumerate(open_df.iterrows()):
        progress.progress((i + 1) / len(open_df), text=f"Scoring {i+1}/{len(open_df)}: {row.get('tender_number', '')}")
        try:
            scored = ai_score_tender(row.to_dict())
            results.append({
                "tender_number": row["tender_number"],
                "ai_score": scored["score"],
                "ai_rationale": scored["rationale"]
            })
            # Persist to Supabase
            supabase.table("sa_tenders").update({
                "ai_score": scored["score"],
                "ai_rationale": scored["rationale"]
            }).eq("tender_number", row["tender_number"]).execute()
        except Exception as e:
            results.append({
                "tender_number": row["tender_number"],
                "ai_score": None,
                "ai_rationale": f"Scoring failed: {e}"
            })

    progress.empty()

    scores_df = pd.DataFrame(results)
    merged = open_df.merge(scores_df, on="tender_number", how="left", suffixes=("", "_new"))

    # Use new scores where computed, keep old otherwise
    if "ai_score_new" in merged.columns:
        merged["ai_score"] = merged["ai_score_new"].combine_first(merged.get("ai_score"))
        merged["ai_rationale"] = merged["ai_rationale_new"].combine_first(merged.get("ai_rationale"))
        merged.drop(columns=["ai_score_new", "ai_rationale_new"], inplace=True)

    return merged.sort_values("ai_score", ascending=False, na_position="last")


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
    ok = 0
    for r in records:
        try:
            supabase.table("sa_tenders").upsert(r, on_conflict="tender_number,department_name").execute()
            ok += 1
        except Exception as e:
            pass
    status_container(f"  ✅ {country} — {label}: {ok} records saved")
    return ok

def _get_json(url, params=None, headers=None, timeout=20):
    import requests
    h = {"User-Agent": "Mozilla/5.0", "X-Requested-With": "XMLHttpRequest",
         "Accept": "application/json"}
    if headers:
        h.update(headers)
    r = requests.get(url, params=params, headers=h, timeout=timeout)
    r.raise_for_status()
    return r.json()

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
    try:
        # Open tenders
        supabase.table("sa_tenders").delete().eq("status", "Open").eq("country", country).execute()
        data = _get_json("https://www.etenders.gov.za/Home/PaginatedTenderOpportunities",
            {"draw":"1","start":"0","length":"1000","status":"1",
             "search[value]":"","search[regex]":"false","order[0][column]":"2","order[0][dir]":"desc"})
        open_records = []
        for t in data.get("data", []):
            text = f"{t.get('description','')} {t.get('category','')}"
            if not _is_relevant(text): continue
            open_records.append({
                "tender_number": t.get("tender_No",""),
                "department_name": t.get("department",""),
                "title": str(t.get("description",""))[:200],
                "description": t.get("description",""),
                "category": t.get("category",""),
                "compliance_requirements": t.get("conditions","Not specified"),
                "portal_link": "https://www.etenders.gov.za/Home/opportunities?id=1",
                "issue_date": t.get("date_Published"),
                "closing_date": t.get("closing_Date"),
                "status": "Open", "award_status": "Published", "country": country,
            })
        _upsert(open_records, country, "Open", out)

        # Awarded tenders
        supabase.table("sa_tenders").delete().eq("status", "Awarded").eq("country", country).execute()
        data2 = _get_json("https://www.etenders.gov.za/Home/PaginatedTenderOpportunities",
            {"draw":"1","start":"0","length":"1000","status":"2"})
        awarded_records = []
        for t in data2.get("data", []):
            text = f"{t.get('description','')} {t.get('category','')}"
            if not _is_relevant(text): continue
            companies = t.get("company", [])
            winner, amount = "Not Disclosed", "Not Disclosed"
            if companies and isinstance(companies, list):
                winner = companies[0].get("company","Unknown")
                amount = companies[0].get("tenderAmount","Not Disclosed")
            if winner == "Not Disclosed":
                winner = t.get("bidders") or "Unknown"
                amount = t.get("tenderAmount") or "Not Disclosed"
            awarded_records.append({
                "tender_number": t.get("tender_No",""),
                "department_name": t.get("department",""),
                "title": str(t.get("description",""))[:200],
                "description": t.get("description",""),
                "status": "Awarded", "winning_bidder": winner,
                "award_value": str(amount), "country": country,
            })
        _upsert(awarded_records, country, "Awarded", out)
    except Exception as e:
        out(f"  ❌ {country} error: {e}")

# ── Kenya ─────────────────────────────────────────────────────────────────────
def scrape_kenya(out):
    country = "Kenya"
    out(f"🇰🇪 Scraping {country}…")
    try:
        supabase.table("sa_tenders").delete().eq("status", "Open").eq("country", country).execute()
        data = _get_json("https://tenders.go.ke/Home/PaginatedTenderOpportunities",
            {"draw":"1","start":"0","length":"500","status":"1",
             "search[value]":"","search[regex]":"false","order[0][column]":"2","order[0][dir]":"desc"})
        records = []
        for t in data.get("data", []):
            text = f"{t.get('description','')} {t.get('category','')}"
            if not _is_relevant(text): continue
            records.append({
                "tender_number": t.get("tenderNo") or t.get("tender_No",""),
                "department_name": t.get("procuringEntity") or t.get("department",""),
                "title": str(t.get("description",""))[:200],
                "description": t.get("description",""),
                "category": t.get("category",""),
                "compliance_requirements": t.get("conditions","Not specified"),
                "portal_link": "https://tenders.go.ke/tenders",
                "issue_date": t.get("datePublished") or t.get("date_Published"),
                "closing_date": t.get("closingDate") or t.get("closing_Date"),
                "status": "Open", "award_status": "Published", "country": country,
            })
        _upsert(records, country, "Open", out)

        supabase.table("sa_tenders").delete().eq("status", "Awarded").eq("country", country).execute()
        data2 = _get_json("https://tenders.go.ke/Home/PaginatedTenderOpportunities",
            {"draw":"1","start":"0","length":"500","status":"2"})
        awarded = []
        for t in data2.get("data", []):
            if not _is_relevant(f"{t.get('description','')} {t.get('category','')}"): continue
            companies = t.get("company", [])
            winner = companies[0].get("company","Unknown") if companies else t.get("bidders","Unknown")
            amount = companies[0].get("tenderAmount","Not Disclosed") if companies else t.get("tenderAmount","Not Disclosed")
            awarded.append({
                "tender_number": t.get("tenderNo") or t.get("tender_No",""),
                "department_name": t.get("procuringEntity") or t.get("department",""),
                "title": str(t.get("description",""))[:200],
                "description": t.get("description",""),
                "status": "Awarded", "winning_bidder": winner,
                "award_value": str(amount), "country": country,
            })
        _upsert(awarded, country, "Awarded", out)
    except Exception as e:
        out(f"  ❌ {country} error: {e}")

# ── Nigeria ───────────────────────────────────────────────────────────────────
def scrape_nigeria(out):
    country = "Nigeria"
    out(f"🇳🇬 Scraping {country}…")
    try:
        import requests
        supabase.table("sa_tenders").delete().eq("country", country).execute()
        # NoCoPo OCDS API
        page, records = 1, []
        while True:
            try:
                data = _get_json("https://nocopo.bpp.gov.ng/api/tenders",
                    {"page": page, "per_page": 100})
                batch = data.get("data", [])
                if not batch: break
                records.extend(batch)
                if page >= data.get("meta",{}).get("last_page", 1): break
                page += 1
            except: break

        relevant = []
        for t in records:
            title = t.get("title") or t.get("description","")
            if not _is_relevant(f"{title} {t.get('procurementCategory','')}"):  continue
            buyer = t.get("buyer",{})
            dept = buyer.get("name","") if isinstance(buyer, dict) else str(buyer)
            tp = t.get("tenderPeriod",{}) or {}
            relevant.append({
                "tender_number": t.get("ocid") or t.get("id",""),
                "department_name": dept,
                "title": str(title)[:200], "description": str(title),
                "category": t.get("procurementCategory",""),
                "portal_link": "https://nocopo.bpp.gov.ng",
                "issue_date": t.get("date") or tp.get("startDate"),
                "closing_date": tp.get("endDate"),
                "status": "Open", "award_status": "Published", "country": country,
            })
        _upsert(relevant, country, "Open", out)
    except Exception as e:
        out(f"  ❌ {country} error: {e}")

# ── Ghana ─────────────────────────────────────────────────────────────────────
def scrape_ghana(out):
    country = "Ghana"
    out(f"🇬🇭 Scraping {country}…")
    try:
        from bs4 import BeautifulSoup
        supabase.table("sa_tenders").delete().eq("status", "Open").eq("country", country).execute()
        soup = _get_html("https://www.ghaneps.gov.gh/epps/app/viewTender.do?searchType=basic&selectedItem=viewTender.do")
        records = []
        for row in soup.select("table.dataTable tbody tr, table tbody tr"):
            cols = row.find_all("td")
            if len(cols) < 3: continue
            title = cols[1].get_text(strip=True) if len(cols) > 1 else ""
            if not _is_relevant(title): continue
            records.append({
                "tender_number": cols[0].get_text(strip=True),
                "department_name": cols[2].get_text(strip=True) if len(cols) > 2 else "",
                "title": title[:200], "description": title,
                "category": cols[3].get_text(strip=True) if len(cols) > 3 else "",
                "closing_date": cols[4].get_text(strip=True) if len(cols) > 4 else None,
                "compliance_requirements": "Not specified",
                "portal_link": "https://www.ghaneps.gov.gh",
                "status": "Open", "country": country,
            })
        _upsert(records, country, "Open", out)
    except Exception as e:
        out(f"  ❌ {country} error: {e}")

# ── Tanzania ──────────────────────────────────────────────────────────────────
def scrape_tanzania(out):
    country = "Tanzania"
    out(f"🇹🇿 Scraping {country}…")
    try:
        from bs4 import BeautifulSoup
        supabase.table("sa_tenders").delete().eq("status", "Open").eq("country", country).execute()
        records = []
        for cat in ["G", "W", "C", "N"]:
            try:
                soup = _get_html(f"https://nest.ppra.go.tz/tenders/published-tenders?category={cat}")
                for row in soup.select("table tbody tr"):
                    cols = row.find_all("td")
                    if len(cols) < 3: continue
                    desc = cols[2].get_text(strip=True) if len(cols) > 2 else cols[1].get_text(strip=True)
                    if not _is_relevant(desc): continue
                    records.append({
                        "tender_number": cols[0].get_text(strip=True),
                        "department_name": cols[1].get_text(strip=True),
                        "title": desc[:200], "description": desc,
                        "closing_date": cols[3].get_text(strip=True) if len(cols) > 3 else None,
                        "category": cat, "compliance_requirements": "Not specified",
                        "portal_link": "https://nest.ppra.go.tz",
                        "status": "Open", "country": country,
                    })
            except: continue
        _upsert(records, country, "Open", out)
    except Exception as e:
        out(f"  ❌ {country} error: {e}")

# ── Uganda ────────────────────────────────────────────────────────────────────
def scrape_uganda(out):
    country = "Uganda"
    out(f"🇺🇬 Scraping {country}…")
    try:
        from bs4 import BeautifulSoup
        supabase.table("sa_tenders").delete().eq("status", "Open").eq("country", country).execute()
        records = []
        for page in range(1, 6):
            try:
                soup = _get_html(f"https://gpp.ppda.go.ug/tenders?page={page}")
                rows = soup.select("table tbody tr")
                if not rows: break
                for row in rows:
                    cols = row.find_all("td")
                    if len(cols) < 2: continue
                    title = cols[1].get_text(strip=True)
                    if not _is_relevant(title): continue
                    records.append({
                        "tender_number": cols[0].get_text(strip=True),
                        "department_name": cols[2].get_text(strip=True) if len(cols) > 2 else "",
                        "title": title[:200], "description": title,
                        "category": cols[3].get_text(strip=True) if len(cols) > 3 else "",
                        "closing_date": cols[4].get_text(strip=True) if len(cols) > 4 else None,
                        "compliance_requirements": "Not specified",
                        "portal_link": "https://gpp.ppda.go.ug",
                        "status": "Open", "country": country,
                    })
            except: break
        _upsert(records, country, "Open", out)
    except Exception as e:
        out(f"  ❌ {country} error: {e}")

# ── Southern Africa (HTML scrapers) ──────────────────────────────────────────
def _scrape_html_portal(country, flag, url, out):
    out(f"{flag} Scraping {country}…")
    try:
        from bs4 import BeautifulSoup
        supabase.table("sa_tenders").delete().eq("status","Open").eq("country",country).execute()
        soup = _get_html(url)
        records = []
        for row in soup.select("table tbody tr"):
            cols = row.find_all("td")
            if len(cols) < 2: continue
            title = cols[1].get_text(strip=True) if len(cols) > 1 else cols[0].get_text(strip=True)
            if not _is_relevant(title): continue
            records.append({
                "tender_number": cols[0].get_text(strip=True),
                "department_name": cols[2].get_text(strip=True) if len(cols) > 2 else "",
                "title": title[:200], "description": title,
                "closing_date": cols[3].get_text(strip=True) if len(cols) > 3 else None,
                "compliance_requirements": "Not specified",
                "portal_link": url, "status": "Open", "country": country,
            })
        _upsert(records, country, "Open", out)
    except Exception as e:
        out(f"  ❌ {country} error: {e}")

def scrape_botswana(out):
    _scrape_html_portal("Botswana","🇧🇼","https://www.ppadb.co.bw/index.php/bid-opportunities", out)

def scrape_namibia(out):
    _scrape_html_portal("Namibia","🇳🇦","https://www.cpb.org.na/tenders", out)

def scrape_zimbabwe(out):
    _scrape_html_portal("Zimbabwe","🇿🇼","https://www.praz.org.zw/tenders", out)

def scrape_zambia(out):
    _scrape_html_portal("Zambia","🇿🇲","https://www.zppa.org.zm/tenders", out)


def run_all_scrapers():
    """Run every country scraper with a live progress log in the main area."""
    st.subheader("🔄 Refreshing tender data across Africa…")
    log = st.empty()
    lines = []

    def out_write(msg):
        lines.append(msg)
        log.markdown("\n\n".join(lines))

    # Wrap each scraper so one failure never kills the rest
    scrapers = [
        scrape_south_africa,
        scrape_kenya,
        scrape_nigeria,
        scrape_ghana,
        scrape_tanzania,
        scrape_uganda,
        scrape_botswana,
        scrape_namibia,
        scrape_zimbabwe,
        scrape_zambia,
    ]
    for fn in scrapers:
        try:
            fn(out_write)
        except Exception as e:
            out_write(f"  ❌ {fn.__name__} crashed: {e}")

    out_write("\n✅ **All countries done!**")

# ─────────────────────────────────────────────
# 9. MAIN DASHBOARD
# ─────────────────────────────────────────────
st.title("🛡️ CRS Competitive Intelligence Dashboard")

# Sidebar
st.sidebar.header("Controls")
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

# Apply filters
df_filtered = tenders_df.copy()
if dept_search:
    df_filtered = df_filtered[
        df_filtered["department_name"].str.contains(dept_search, case=False, na=False)
    ]
if selected_countries and "country" in df_filtered.columns:
    df_filtered = df_filtered[df_filtered["country"].isin(selected_countries)]

# ─────────────────────────────────────────────
tab1, tab2, tab3 = st.tabs([
    "📢 Open Opportunities",
    "🏆 Competitive Intelligence",
    "🤖 AI Tender Parser"
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
            open_df = ai_match_tenders(open_df)
            st.cache_data.clear()
            st.success("Scoring complete — tenders sorted by AI fit score.")

    # Sort by score if available
    if "ai_score" in open_df.columns and open_df["ai_score"].notna().any():
        open_df = open_df.sort_values("ai_score", ascending=False, na_position="last")

    # Build display frame
    display_cols = ["country", "tender_number", "department_name", "title", "closing_date"]
    if open_df["ai_score"].notna().any():
        open_df["Fit Score"] = open_df["ai_score"].apply(score_badge)
        display_cols.append("Fit Score")

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
    st.subheader("Historical Awarded Tenders")
    awarded_df = df_filtered[df_filtered["status"] == "Awarded"].copy()

    if competitor_search:
        awarded_df = awarded_df[
            awarded_df["winning_bidder"].str.contains(competitor_search, case=False, na=False)
        ]

    if awarded_df.empty:
        st.info("No awarded tenders match your current filters.")
    else:
        # Clean currency
        awarded_df["clean_val"] = (
            awarded_df["award_value"].astype(str)
            .str.replace(r"[R\s,]", "", regex=True)
        )
        awarded_df["numeric_value"] = pd.to_numeric(awarded_df["clean_val"], errors="coerce").fillna(0)

        # Pivot — group by country + bidder so values can't be compared cross-currency
        pivot = awarded_df.pivot_table(
            values="numeric_value",
            index=["country", "winning_bidder"] if "country" in awarded_df.columns else "winning_bidder",
            aggfunc={"numeric_value": ["sum", "count"]}
        )
        pivot.columns = ["Tender Count", "Total Won (Value)"]
        pivot = pivot.sort_values("Total Won (Value)", ascending=False)

        st.subheader("Competitor Market Share")
        st.caption("⚠️ Values are in local currency per country — don't sum across countries.")
        st.dataframe(
            pivot.style.format({"Total Won (Value)": "{:,.0f}"}),
            use_container_width=True
        )

        st.divider()
        st.subheader("Award Detail")
        st.dataframe(
            awarded_df[["country", "tender_number", "department_name", "winning_bidder", "award_value", "title"]],
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