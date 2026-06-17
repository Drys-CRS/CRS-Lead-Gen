"""
CRS Competitive Intelligence Dashboard — v2
4-tab dashboard. GitHub Action owns scraping + nightly scoring.
App adds on-demand AI scoring, partner analysis, and rich card views.
"""
import os
import sys
import json
import re
import time as _time
import threading
import datetime as _dt
import urllib.request as _urlreq
import urllib.parse as _urlparse
import xml.etree.ElementTree as _ET
import streamlit as st
import pandas as pd
from supabase import create_client, Client

try:
    import google.genai as genai
    _GENAI_NEW = True
except ImportError:
    import google.generativeai as genai
    _GENAI_NEW = False

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from monday_client import (
        push_tender_to_monday,
        push_partner_to_companies,
        sync_lead_to_monday,
        lookup_monday_crm,
        push_to_contacts_board,
        lookup_monday_company,
    )
    _MONDAY_OK = True
except ImportError:
    _MONDAY_OK = False

st.set_page_config(page_title="CRS Intelligence", page_icon="🛡️", layout="wide")

# ─────────────────────────────────────────────────────────────────────────────
# CRS PROFILE
# ─────────────────────────────────────────────────────────────────────────────
CRS_PROFILE = """
Company: Cyber Retaliator Solutions (CRS) — South African cybersecurity VAD and
IBM / Red Hat / SUSE / CompTIA training partner.
Head Office: Centurion. Training Centres: Centurion, Midrand, Sandton, Cape Town.

VENDOR PORTFOLIO:
• VECTRA AI — NDR/XDR/CDR/ITDR (AI-powered threat detection, SOC modernisation)
• vRx (Vicarius) — vulnerability & patch management (100+ endpoints)
• Strobes Security — CTEM/PTaaS/ASM (enterprise 1 000+ assets)
• Aikido — DevSecOps / AppSec (SAST, DAST, SCA, IaC, CSPM)
• Flare — dark web monitoring & threat intelligence
• BeachheadSecure — endpoint encryption, MFA, RiskResponder
• SMBsecure — all-in-one SMB cyber protection + POPIA cyber warranty
• Telivy — MSSP cyber audit platform
• BlueFlag Security — SDLC identity & supply chain security
• Standss/SendGuard — email GRC (confirm before send, DLP)
• Todyl — SASE/SIEM/MXDR/EDR/GRC consolidated platform
• Panorays — third-party/supply-chain cyber risk & attack surface mgmt (DORA)
• Cyber Risk Essentials / GoldPhish — phishing simulation + security awareness
• Own VAPT services (pentest, red team, web app, cloud config)

TRAINING: IBM, Red Hat, SUSE, CompTIA (A+/Network+/Security+/CySA+), Agile SAFe.

TARGET: Government (all African countries), financial services, healthcare,
education, telcos, mining, enterprises with dev teams.
Strong fit: cybersecurity, ICT, SOC/MDR, POPIA compliance, vulnerability management.
Weak fit: civil construction, catering, cleaning, pure hardware, non-ICT goods.
"""

# ─────────────────────────────────────────────────────────────────────────────
# SUPABASE
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_resource
def _get_supabase() -> Client:
    url = st.secrets.get("SUPABASE_URL") or os.getenv("SUPABASE_URL", "")
    key = st.secrets.get("SUPABASE_KEY") or os.getenv("SUPABASE_KEY", "")
    if not url or not key:
        st.error("Set SUPABASE_URL and SUPABASE_KEY in secrets.")
        st.stop()
    return create_client(url, key)

supabase = _get_supabase()

# ─────────────────────────────────────────────────────────────────────────────
# AI PROVIDERS
# ─────────────────────────────────────────────────────────────────────────────
_AI_DAILY_LIMITS = {
    "Groq": 14400, "Cerebras": 10000, "OpenRouter": 9999,
    "GitHub": 150, "NVIDIA": 40, "DeepSeek": 500, "Gemini": 20,
}

@st.cache_resource
def _init_gemini():
    key = st.secrets.get("GEMINI_API_KEY", "")
    if not key:
        return None
    try:
        if _GENAI_NEW:
            return genai.Client(api_key=key)
        genai.configure(api_key=key)
        return genai.GenerativeModel("gemini-2.5-flash")
    except Exception:
        return None

@st.cache_resource
def _init_groq():
    key = st.secrets.get("GROQ_API_KEY", "")
    if not key:
        return None
    try:
        from groq import Groq
        return Groq(api_key=key)
    except Exception:
        return None

@st.cache_resource
def _init_cerebras():
    key = st.secrets.get("CEREBRAS_API_KEY", "")
    if not key:
        return None
    try:
        from cerebras.cloud.sdk import Cerebras
        return Cerebras(api_key=key)
    except Exception:
        return None

@st.cache_resource
def _init_openrouter():
    key = st.secrets.get("OPENROUTER_API_KEY", "")
    if not key:
        return None
    try:
        from openai import OpenAI
        return OpenAI(api_key=key, base_url="https://openrouter.ai/api/v1",
                      default_headers={"HTTP-Referer": "https://github.com/Drys-CRS/CRS-Lead-Gen",
                                       "X-Title": "CRS Intelligence"})
    except Exception:
        return None

@st.cache_resource
def _init_github():
    for k in ("GITHUB_TOKEN", "GH_PAT"):
        key = st.secrets.get(k, "")
        if key:
            try:
                from openai import OpenAI
                return OpenAI(api_key=key, base_url="https://models.inference.ai.azure.com")
            except Exception:
                pass
    return None

@st.cache_resource
def _init_nvidia():
    key = st.secrets.get("NVIDIA_API_KEY", "")
    if not key:
        return None
    try:
        from openai import OpenAI
        return OpenAI(api_key=key, base_url="https://integrate.api.nvidia.com/v1")
    except Exception:
        return None

@st.cache_resource
def _init_deepseek():
    key = st.secrets.get("DEEPSEEK_API_KEY", "")
    if not key:
        return None
    try:
        from openai import OpenAI
        return OpenAI(api_key=key, base_url="https://api.deepseek.com")
    except Exception:
        return None

gemini_ai     = _init_gemini()
groq_ai       = _init_groq()
cerebras_ai   = _init_cerebras()
openrouter_ai = _init_openrouter()
github_ai     = _init_github()
nvidia_ai     = _init_nvidia()
deepseek_ai   = _init_deepseek()

_GITHUB_MODELS    = ["Llama-3.3-70B-Instruct", "gpt-4o-mini", "Mistral-Large-2411", "Phi-4"]
_OPENROUTER_MODELS = ["openrouter/free", "deepseek/deepseek-r1:free",
                      "deepseek/deepseek-v3:free", "meta-llama/llama-4-maverick:free"]

def _get_usage() -> dict:
    if "ai_usage" not in st.session_state:
        st.session_state["ai_usage"] = {k: 0 for k in _AI_DAILY_LIMITS}
    return st.session_state["ai_usage"]

def _inc(name): _get_usage()[name] = _get_usage().get(name, 0) + 1
def _ok(name):  return _get_usage().get(name, 0) < _AI_DAILY_LIMITS.get(name, 9999)

def _clean(raw):
    return re.sub(r"^```json[\s]*|^```[\s]*|```$", "", (raw or "").strip(), flags=re.MULTILINE).strip()

def _rl(e): return any(x in str(e).lower() for x in ["429", "quota", "rate limit", "too many", "throttl"])

def _call_groq(p):
    r = groq_ai.chat.completions.create(model="llama-3.3-70b-versatile",
        messages=[{"role":"user","content":p}], temperature=0.2, max_tokens=2000)
    return _clean(r.choices[0].message.content)

def _call_cerebras(p):
    for m in ["gpt-oss-120b","zai-glm-4.7"]:
        try:
            r = cerebras_ai.chat.completions.create(model=m,
                messages=[{"role":"user","content":p}], temperature=0.2, max_tokens=2000)
            t = (getattr(r.choices[0].message,"content",None) or
                 getattr(r.choices[0].message,"reasoning_content",None) or "").strip()
            if t: return _clean(t)
        except Exception as e:
            if any(x in str(e) for x in ["404","deprecated","unavailable","not found"]): continue
            raise
    raise ValueError("All Cerebras models unavailable")

def _call_openrouter(p):
    last = None
    for m in _OPENROUTER_MODELS:
        try:
            r = openrouter_ai.chat.completions.create(model=m,
                messages=[{"role":"user","content":p}], temperature=0.2, max_tokens=2000, timeout=30)
            t = (r.choices[0].message.content or "").strip()
            if t: return _clean(t)
        except Exception as e:
            last = e
            if _rl(str(e)): _time.sleep(3); continue
            if any(x in str(e).lower() for x in ["404","unavailable","not found"]): continue
            raise
    raise RuntimeError(f"OpenRouter failed: {last}")

def _call_github(p):
    last = None
    for m in _GITHUB_MODELS:
        try:
            r = github_ai.chat.completions.create(model=m,
                messages=[{"role":"user","content":p}], temperature=0.2, max_tokens=2000)
            t = (r.choices[0].message.content or "").strip()
            if t: return _clean(t)
        except Exception as e:
            last = e
            if any(x in str(e).lower() for x in ["404","not found"]): continue
            raise
    raise RuntimeError(f"GitHub Models failed: {last}")

def _call_nvidia(p):
    r = nvidia_ai.chat.completions.create(model="meta/llama-3.3-70b-instruct",
        messages=[{"role":"user","content":p}], temperature=0.2, max_tokens=2000)
    return _clean(r.choices[0].message.content)

def _call_deepseek(p):
    r = deepseek_ai.chat.completions.create(model="deepseek-chat",
        messages=[{"role":"user","content":p}], temperature=0.2, max_tokens=2000)
    return _clean(r.choices[0].message.content)

def _call_gemini(p, retries=3):
    if gemini_ai is None: raise RuntimeError("Gemini not initialised")
    for attempt in range(retries):
        try:
            resp = (gemini_ai.models.generate_content(model="gemini-2.5-flash", contents=p)
                    if _GENAI_NEW else gemini_ai.generate_content(p))
            return _clean(resp.text)
        except Exception as e:
            if _rl(str(e)) and attempt < retries-1: _time.sleep(20*(attempt+1))
            else: raise
    raise RuntimeError("Gemini quota exceeded.")

def _call_ai(prompt: str) -> str:
    providers = []
    if groq_ai       and _ok("Groq"):       providers.append(("Groq",       _call_groq))
    if cerebras_ai   and _ok("Cerebras"):   providers.append(("Cerebras",   _call_cerebras))
    if openrouter_ai:                        providers.append(("OpenRouter", _call_openrouter))
    if github_ai     and _ok("GitHub"):     providers.append(("GitHub",     _call_github))
    if nvidia_ai     and _ok("NVIDIA"):     providers.append(("NVIDIA",     _call_nvidia))
    if deepseek_ai   and _ok("DeepSeek"):   providers.append(("DeepSeek",   _call_deepseek))
    if gemini_ai     and _ok("Gemini"):     providers.append(("Gemini",     _call_gemini))
    if not providers: raise RuntimeError("All AI providers at daily limits.")
    last = None
    for name, fn in providers:
        try:
            result = fn(prompt); _inc(name); return result
        except Exception as e:
            last = e
            if _rl(str(e)): _inc(name)
            st.toast(f"⏳ {name}: {str(e)[:50]} — trying next…")
    raise RuntimeError(f"All providers failed: {last}")

def _provider_status():
    return " · ".join([
        "🟢 Groq"       if groq_ai       else "⚪ Groq",
        "🟢 Cerebras"   if cerebras_ai   else "⚪ Cerebras",
        "🟢 OpenRouter" if openrouter_ai  else "⚪ OpenRouter",
        "🟢 GitHub"     if github_ai      else "⚪ GitHub",
        "🟢 NVIDIA"     if nvidia_ai      else "⚪ NVIDIA",
        "🟢 DeepSeek"   if deepseek_ai   else "⚪ DeepSeek",
        "🟢 Gemini"     if gemini_ai      else "⚪ Gemini",
    ])

# ─────────────────────────────────────────────────────────────────────────────
# AI TASK FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────
def ai_score_tender(row: dict) -> dict:
    prompt = f"""You are a channel-partner strategist for Cyber Retaliator Solutions (CRS).
CRS does NOT respond to tenders directly — it sells through in-country channel partners.
Score this tender as a PARTNER OPPORTUNITY (1–10): how urgently should CRS activate a local partner?

{CRS_PROFILE}

TENDER:
Title:       {row.get('title','')}
Department:  {row.get('department_name','')}
Country:     {row.get('country','')}
Description: {str(row.get('description',''))[:600]}
Category:    {row.get('category','')}
Closing:     {row.get('closing_date','')}

SCORE GUIDE:
9-10 = CRS must urgently find/activate a local partner (clear ICT/security tender)
7-8  = Good fit — contact existing in-country partners
5-6  = Partial fit — one or two CRS solutions relevant
3-4  = Weak — mostly non-ICT but has a tech component
1-2  = Not relevant (construction, catering, stationery, vehicles)

Return ONLY valid JSON, no markdown:
{{"score":<1-10>,"rationale":"2-3 sentences on fit + which CRS solutions apply",\
"partner_type":"System Integrator|MSP|VAR|Training Provider|Consulting/Advisory",\
"proposed_solutions":["sol1","sol2"],\
"outreach_angle":"one sentence — what CRS tells a local partner to get them to respond"}}"""
    raw = _call_ai(prompt)
    try:
        parsed = json.loads(raw)
        return {"score": int(parsed.get("score", 5)),
                "rationale": parsed.get("rationale", ""),
                "partner_type": parsed.get("partner_type", ""),
                "proposed_solutions": parsed.get("proposed_solutions", []),
                "outreach_angle": parsed.get("outreach_angle", "")}
    except Exception:
        m = re.search(r'"score"\s*:\s*(\d+)', raw)
        return {"score": int(m.group(1)) if m else 5, "rationale": raw[:300],
                "partner_type": "", "proposed_solutions": [], "outreach_angle": ""}


def ai_analyse_partners(awarded_df: pd.DataFrame) -> list:
    df = awarded_df.dropna(subset=["winning_bidder"]).copy()
    if df.empty:
        return []
    agg = []
    for company, grp in df.groupby("winning_bidder", sort=False):
        company = str(company).strip()
        if not company or len(company) < 3:
            continue
        country = str(grp["country"].mode().iloc[0]) if "country" in grp else "Unknown"
        titles  = grp["title"].dropna().str[:80].tolist()[:5] if "title" in grp else []
        depts   = grp["department_name"].dropna().str[:50].unique().tolist()[:3] if "department_name" in grp else []
        vals    = grp["award_value"].dropna().tolist()[:3] if "award_value" in grp else []
        t_nums  = grp["tender_number"].dropna().str[:30].tolist()[:3] if "tender_number" in grp else []
        agg.append({"company": company[:80], "country": country[:50], "wins": len(grp),
                    "titles": " | ".join(titles), "depts": " | ".join(depts),
                    "values": " | ".join(str(v) for v in vals), "ref_nos": " | ".join(t_nums)})
    agg.sort(key=lambda x: x["wins"], reverse=True)

    lines = ["company|country|wins|sample_tenders|departments|values|ref_numbers"]
    for r in agg[:40]:
        lines.append(f"{r['company']}|{r['country']}|{r['wins']}|{r['titles']}|{r['depts']}|{r['values']}|{r['ref_nos']}")

    prompt = (
        "You are a channel-partner analyst for Cyber Retaliator Solutions (CRS), "
        "a South African cybersecurity VAD and IBM/RedHat/SUSE/CompTIA training partner.\n\n"
        "CRS PORTFOLIO: VECTRA (NDR/XDR), vRx (vuln/patch), Strobes (CTEM/PTaaS), "
        "Aikido (AppSec), Flare (dark web), BeachheadSecure (encryption/MFA), "
        "SMBsecure (SMB/POPIA), Telivy (MSSP audit), BlueFlag (SDLC), Todyl (SASE/SIEM/MXDR), "
        "Panorays (third-party/supply-chain risk), CRE/GoldPhish (awareness), IBM/RedHat/SUSE/CompTIA training, own VAPT.\n\n"
        "AWARDED TENDER WIN DATA (pipe-delimited):\n"
        + "\n".join(lines) +
        "\n\nIdentify the TOP 12 ICT/security companies CRS should approach as channel partners. "
        "Exclude government departments, construction, catering, cleaning, vehicles, stationery.\n\n"
        "Set 'tenders_won_summary' to 1-2 plain sentences describing what TYPES of tenders/work "
        "this company has won (inferred from sample tenders and departments).\n\n"
        "Return ONLY a JSON array (no markdown, no text before/after):\n"
        '[{"company":"...","country":"...","tenders_won":N,'
        '"partner_classification":"System Integrator|MSP|VAR|Training Provider|Consulting/Advisory",'
        '"proposed_solutions":["VECTRA","vRx"],'
        '"key_tenders":["RFQ/2024/001","ICT-2023-045"],'
        '"tenders_won_summary":"They win large ICT integration tenders...",'
        '"issuing_departments":["SAPS","Dept of Health"],'
        '"why_aligned":"...","outreach_angle":"...","urgency":"high|medium|low",'
        '"estimated_deal_size":"large|medium|small"}]'
    )

    raw = _call_ai(prompt)
    raw = re.sub(r"```json[\s]*|```[\s]*", "", raw.strip()).strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\[[\s\S]*\]", raw)
        parsed = json.loads(m.group(0)) if m else []
    if isinstance(parsed, dict):
        parsed = [parsed]
    return [p for p in parsed if isinstance(p, dict) and p.get("company")]


# ─────────────────────────────────────────────────────────────────────────────
# DATA LOADERS  (defined before sidebar so sidebar buttons can call them)
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def _load_tenders() -> pd.DataFrame:
    r = (supabase.table("sa_tenders").select("*")
         .neq("is_irrelevant", True)
         .order("closing_date", desc=False).limit(1000).execute())
    return pd.DataFrame(r.data or [])

@st.cache_data(ttl=300)
def _load_awarded() -> pd.DataFrame:
    r = (supabase.table("awarded_tenders").select("*")
         .order("created_at", desc=True).limit(2000).execute())
    return pd.DataFrame(r.data or [])

@st.cache_data(ttl=300)
def _load_partner_history() -> pd.DataFrame:
    r = (supabase.table("partner_recommendation_history").select("*")
         .order("run_at", desc=True).limit(500).execute())
    return pd.DataFrame(r.data or [])

@st.cache_data(ttl=300)
def _load_lead_verifications() -> pd.DataFrame:
    r = (supabase.table("lead_verification_log").select("*")
         .order("run_at", desc=True).limit(500).execute())
    return pd.DataFrame(r.data or [])

@st.cache_data(ttl=120)
def _load_pipeline_runs() -> pd.DataFrame:
    r = (supabase.table("pipeline_runs").select("*")
         .order("run_at", desc=True).limit(10).execute())
    return pd.DataFrame(r.data or [])

@st.cache_data(ttl=30)
def _load_dork_leads_bulk(urls_tuple: tuple) -> dict:
    if not urls_tuple:
        return {}
    r = supabase.table("dork_leads").select("*").in_("linkedin_url", list(urls_tuple)).execute()
    return {row["linkedin_url"]: row for row in (r.data or [])}

def _upsert_dork_lead(data: dict) -> None:
    try:
        clean = {k: v for k, v in data.items() if v is not None}
        supabase.table("dork_leads").upsert(clean, on_conflict="linkedin_url").execute()
    except Exception:
        pass

# Filters live inside each tab; sidebar is control-only.
country_filter: list = []
min_score: int = 0

def _country(df, col="country"):
    if country_filter and col in df.columns:
        return df[df[col].isin(country_filter)]
    return df

def _score_filter(df):
    for col in ("ai_score", "crs_alignment_score"):
        if col in df.columns and min_score > 0:
            return df[pd.to_numeric(df[col], errors="coerce").fillna(0) >= min_score]
    return df

def _parse_rationale(raw) -> dict:
    if not raw or str(raw) in ("nan", "None", ""):
        return {}
    try:
        return json.loads(str(raw))
    except Exception:
        return {"rationale": str(raw)}

def _parse_list(raw) -> list:
    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    try:
        v = json.loads(str(raw))
        return v if isinstance(v, list) else []
    except Exception:
        return [s.strip() for s in str(raw).split(",") if s.strip()]

def _badge(urgency: str) -> str:
    u = str(urgency).lower()
    if u == "high":   return "🔴 High"
    if u == "medium": return "🟡 Medium"
    if u == "low":    return "🟢 Low"
    return urgency or "—"

def _copy_block(text: str, label: str = "📋 Copy", key: str = "") -> None:
    """Renders a collapsed expander with a copyable code block (native copy icon)."""
    with st.expander(label, expanded=False):
        st.code(text.strip(), language=None)

# ─────────────────────────────────────────────────────────────────────────────
# DORK / ENRICHMENT HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _parse_li_result(raw_title: str, snippet: str = "") -> dict:
    """Extract name, job_title, company from a LinkedIn search-result title."""
    t = re.sub(r"\s*\|\s*LinkedIn.*$", "", raw_title, flags=re.IGNORECASE).strip()
    t = re.sub(r"\s*[-–—]\s*LinkedIn.*$", "", t, flags=re.IGNORECASE).strip()
    parts = re.split(r"\s+[-–—]\s+", t, maxsplit=1)
    name = parts[0].strip() if parts else t
    job_title = company = ""
    if len(parts) == 2:
        role = parts[1].strip()
        m = re.match(r"^(.+?)\s+at\s+(.+)$", role, re.IGNORECASE)
        if m:
            job_title = m.group(1).strip()
            company   = m.group(2).strip()
        else:
            job_title = role
    if not company and snippet:
        m2 = re.search(r"(?:at|@)\s+([A-Z][^·|,\n]{2,50}?)(?:\s*[·|,]|\s*$)", snippet)
        if m2:
            company = m2.group(1).strip()
    return {"name": name, "job_title": job_title, "company": company}


def _dork_search(query: str, num: int = 10, start: int = 0) -> list:
    g_key = st.secrets.get("GOOGLE_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")
    g_cse = st.secrets.get("GOOGLE_CSE_ID", "") or os.getenv("GOOGLE_CSE_ID", "")
    s_key = st.secrets.get("SERPAPI_API_KEY", "") or os.getenv("SERPAPI_API_KEY", "")
    raw: list = []
    if g_key and g_cse:
        # Google CSE: 1-based start index, max 10 per page
        url = (f"https://www.googleapis.com/customsearch/v1"
               f"?key={g_key}&cx={g_cse}&q={_urlparse.quote(query)}"
               f"&num={min(num, 10)}&start={start + 1}")
        with _urlreq.urlopen(url, timeout=20) as r:
            raw = json.loads(r.read()).get("items", [])
    elif s_key:
        # SerpAPI: 0-based start index
        url = (f"https://serpapi.com/search"
               f"?engine=google&q={_urlparse.quote(query)}"
               f"&num={num}&start={start}&api_key={s_key}")
        with _urlreq.urlopen(url, timeout=20) as r:
            data = json.loads(r.read())
        raw = [{"link": x.get("link", ""), "title": x.get("title", ""),
                "snippet": x.get("snippet", "")} for x in data.get("organic_results", [])]
    else:
        raise RuntimeError("Set GOOGLE_API_KEY+GOOGLE_CSE_ID or SERPAPI_API_KEY in secrets")
    profiles = []
    for item in raw:
        u = item.get("link", "")
        if "linkedin.com/in/" not in u.lower():
            continue
        t       = item.get("title", "")
        snippet = item.get("snippet", "")
        parsed  = _parse_li_result(t, snippet)
        if not parsed["name"]:
            slug_m = re.search(r"linkedin\.com/in/([^/?&#]+)", u)
            parsed["name"] = slug_m.group(1).replace("-", " ").title() if slug_m else "Unknown"
        profiles.append({
            "name":      parsed["name"],
            "job_title": parsed["job_title"],
            "company":   parsed["company"],
            "url":       u,
            "snippet":   snippet,
        })
    return profiles


def _apollo_match(name: str, linkedin_url: str) -> dict:
    key = st.secrets.get("APOLLO_API_KEY", "") or os.getenv("APOLLO_API_KEY", "")
    if not key:
        return {}
    payload = json.dumps({"api_key": key, "name": name,
                          "linkedin_url": linkedin_url}).encode()
    req = _urlreq.Request(
        "https://api.apollo.io/api/v1/people/match",
        data=payload, headers={"Content-Type": "application/json"}, method="POST",
    )
    with _urlreq.urlopen(req, timeout=20) as r:
        return json.loads(r.read()).get("person") or {}


def _hunter_find(first: str, last: str, domain: str) -> dict:
    key = st.secrets.get("HUNTER_API_KEY", "") or os.getenv("HUNTER_API_KEY", "")
    if not key or not domain:
        return {}
    url = (f"https://api.hunter.io/v2/email-finder"
           f"?domain={_urlparse.quote(domain)}"
           f"&first_name={_urlparse.quote(first)}&last_name={_urlparse.quote(last)}"
           f"&api_key={key}")
    with _urlreq.urlopen(url, timeout=15) as r:
        return json.loads(r.read()).get("data") or {}


def _lusha_lookup(linkedin_url: str) -> dict:
    key = st.secrets.get("LUSHA_API_KEY", "") or os.getenv("LUSHA_API_KEY", "")
    if not key:
        return {}
    url = f"https://api.lusha.com/v2/person?linkedInUrl={_urlparse.quote(linkedin_url)}"
    req = _urlreq.Request(url, headers={"Api-Key": key})
    with _urlreq.urlopen(req, timeout=15) as r:
        return json.loads(r.read()) or {}


# ── Contact lookup helpers (Apollo search + Lusha prospecting) ────────────────

def _apollo_search_people(name: str = "", company: str = "",
                           num: int = 5, titles: list = None) -> list:
    """POST to Apollo mixed_people/search. Returns list of raw people dicts."""
    key = st.secrets.get("APOLLO_API_KEY", "") or os.getenv("APOLLO_API_KEY", "")
    if not key:
        return []
    payload: dict = {"api_key": key, "per_page": num, "page": 1}
    if name:
        payload["q_keywords"] = name
    if company:
        payload["q_organization_name"] = company
    if titles:
        payload["person_titles"] = titles
    req = _urlreq.Request(
        "https://api.apollo.io/api/v1/mixed_people/search",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Cache-Control": "no-cache"},
        method="POST",
    )
    with _urlreq.urlopen(req, timeout=20) as r:
        return json.loads(r.read()).get("people") or []


def _lusha_search_contacts(first_name: str = "", last_name: str = "",
                            company: str = "") -> list:
    """GET Lusha prospecting/contacts/search. Returns list of raw contact dicts."""
    key = st.secrets.get("LUSHA_API_KEY", "") or os.getenv("LUSHA_API_KEY", "")
    if not key:
        return []
    params: dict = {}
    if first_name:
        params["firstName"] = first_name
    if last_name:
        params["lastName"] = last_name
    if company:
        params["company"] = company
    if not params:
        return []
    qs = "&".join(f"{k}={_urlparse.quote(str(v))}" for k, v in params.items())
    req = _urlreq.Request(
        f"https://api.lusha.com/v2/prospecting/contacts/search?{qs}",
        headers={"Api-Key": key},
    )
    with _urlreq.urlopen(req, timeout=15) as r:
        data = json.loads(r.read())
    return data.get("data") or data.get("contacts") or []


def _norm_apollo(p: dict) -> dict:
    """Flatten an Apollo people-search result into a standard contact dict."""
    org    = p.get("organization") or {}
    phones = p.get("phone_numbers") or []
    phone  = ""
    if phones:
        ph0   = phones[0]
        phone = ((ph0.get("sanitized_number") or ph0.get("raw_number"))
                 if isinstance(ph0, dict) else str(ph0))
    return {
        "name":          p.get("name", ""),
        "title":         p.get("title", ""),
        "email":         p.get("email", ""),
        "email_status":  p.get("email_status", ""),
        "phone":         phone or "",
        "linkedin":      p.get("linkedin_url", ""),
        "company":       org.get("name") or p.get("organization_name", ""),
        "company_phone": org.get("phone", ""),
        "domain":        org.get("primary_domain", ""),
        "twitter":       p.get("twitter_url", ""),
        "source":        "Apollo",
    }


def _norm_lusha(c: dict) -> dict:
    """Flatten a Lusha prospecting result into a standard contact dict."""
    def _first(lst):
        if not lst: return ""
        h = lst[0]
        if isinstance(h, str): return h
        return h.get("validatedEmail") or h.get("internationalNumber") or ""
    co = c.get("company") or {}
    return {
        "name":          f"{c.get('firstName','')} {c.get('lastName','')}".strip(),
        "title":         c.get("jobTitle") or c.get("title", ""),
        "email":         _first(c.get("emailAddresses") or []),
        "email_status":  "lusha",
        "phone":         _first(c.get("phoneNumbers") or []),
        "linkedin":      c.get("linkedInUrl", ""),
        "company":       (co.get("name", "") if isinstance(co, dict) else str(co or "")),
        "company_phone": (co.get("phone", "") if isinstance(co, dict) else ""),
        "domain":        (co.get("domain", "") if isinstance(co, dict) else ""),
        "twitter":       c.get("twitterUrl", ""),
        "source":        "Lusha",
    }


def _calc_contact_confidence(email: str, email_sources: list, phone: str) -> int:
    score = 0
    if email:
        n = len(email_sources)
        if n >= 2:
            score += 75
        else:
            m = re.search(r"Hunter.*?(\d+)%", str(email_sources))
            if m:
                score += max(20, int(int(m.group(1)) * 0.85))
            elif any(s in str(email_sources) for s in ("Apollo", "Lusha")):
                score += 65
            else:
                score += 20
    if phone:
        score += 15
    return min(score, 100)


def _cascade_find_contact(name: str, linkedin_url: str,
                           company: str = "", domain_hint: str = "") -> dict:
    """Apollo → Hunter → Lusha → pattern-guess. Returns aggregated contact data + confidence."""
    email = phone = title = comp = domain = None
    email_srcs: list = []
    phone_srcs: list = []

    # ── Apollo (LinkedIn URL match) ─────────────────────────────────────────
    if st.secrets.get("APOLLO_API_KEY", "") or os.getenv("APOLLO_API_KEY", ""):
        try:
            apo = _apollo_match(name, linkedin_url)
            if apo.get("email"):
                email = apo["email"]; email_srcs.append("Apollo")
            _aph = apo.get("phone_numbers") or []
            if _aph:
                phone = _aph[0]; phone_srcs.append("Apollo")
            title  = apo.get("title") or None
            _org   = apo.get("organization") or {}
            comp   = _org.get("name") or apo.get("organization_name") or None
            domain = _org.get("primary_domain") or None
        except Exception:
            pass

    # ── Hunter (email finder — needs domain) ────────────────────────────────
    _eff_domain = domain or domain_hint or ""
    if (st.secrets.get("HUNTER_API_KEY", "") or os.getenv("HUNTER_API_KEY", "")) and _eff_domain:
        _np = name.split()
        try:
            hdata   = _hunter_find(_np[0] if _np else "", _np[-1] if len(_np) > 1 else "", _eff_domain)
            h_email = hdata.get("email", "")
            h_score = int(hdata.get("score") or 0)
            if h_email:
                label = f"Hunter ({h_score}%)"
                if not email:
                    email = h_email; email_srcs.append(label)
                else:
                    email_srcs.append(label)
                    if h_score > 85:
                        email = h_email
        except Exception:
            pass

    # ── Lusha ───────────────────────────────────────────────────────────────
    if st.secrets.get("LUSHA_API_KEY", "") or os.getenv("LUSHA_API_KEY", ""):
        try:
            ldata = _lusha_lookup(linkedin_url)
            _le = ldata.get("emailAddresses") or []
            _lp = ldata.get("phoneNumbers") or []
            if _le:
                _lem = _le[0] if isinstance(_le[0], str) else _le[0].get("validatedEmail", "")
                if _lem:
                    email_srcs.append("Lusha")
                    if not email:
                        email = _lem
            if _lp and not phone:
                _lph = _lp[0] if isinstance(_lp[0], str) else _lp[0].get("internationalNumber", "")
                if _lph:
                    phone = _lph; phone_srcs.append("Lusha")
        except Exception:
            pass

    # ── Pattern guesses (free, unverified) ──────────────────────────────────
    email_candidates: list = []
    if not email and _eff_domain:
        _np2 = name.split()
        _f   = _np2[0].lower() if _np2 else ""
        _l   = _np2[-1].lower() if len(_np2) > 1 else ""
        if _f and _l:
            email_candidates = [
                f"{_f}.{_l}@{_eff_domain}",
                f"{_f[0]}{_l}@{_eff_domain}",
                f"{_f}@{_eff_domain}",
                f"{_l}.{_f}@{_eff_domain}",
            ]

    return {
        "email":            email,
        "email_sources":    email_srcs,
        "phone":            phone,
        "phone_sources":    phone_srcs,
        "title":            title,
        "company":          comp or company or None,
        "domain":           _eff_domain or None,
        "email_candidates": email_candidates,
        "confidence":       _calc_contact_confidence(email, email_srcs, phone),
    }


# ─────────────────────────────────────────────────────────────────────────────
# BACKGROUND PULL — module-level so it survives across Streamlit reruns
# ─────────────────────────────────────────────────────────────────────────────
_PULL_STATE: dict = {"status": "idle", "logs": [], "result": None,
                     "progress": 0.0, "current_country": ""}

# Countries available for on-demand scraping (mirrors ingest_core.OCDS_REGISTRY keys)
_PULL_OCDS_COUNTRIES = [
    "South Africa", "Kenya", "Nigeria", "Ghana", "Tanzania", "Uganda",
    "Zambia", "Rwanda", "Liberia",
    "Nigeria (Abia)", "Nigeria (Anambra)", "Nigeria (Cross River)",
    "Nigeria (Ebonyi)", "Nigeria (Edo)", "Nigeria (Ekiti)", "Nigeria (Enugu)",
    "Nigeria (Gombe)", "Nigeria (Osun)", "Nigeria (Oyo)", "Nigeria (Plateau)",
]
_PULL_NON_OCDS_KEY = "Non-OCDS (World Bank / UNDP)"
_PULL_ALL_COUNTRIES = _PULL_OCDS_COUNTRIES + [_PULL_NON_OCDS_KEY]

def _pull_worker(env_overrides: dict, countries_sel: list | None = None) -> None:
    _PULL_STATE.update({"status": "running", "logs": [], "result": None,
                        "progress": 0.0, "current_country": "starting…"})
    for k, v in env_overrides.items():
        if not os.environ.get(k):
            os.environ[k] = v
    def _log(m: str) -> None:
        _PULL_STATE["logs"].append(str(m)[:200])

    def _prog_cb(fraction: float, country: str) -> None:
        _PULL_STATE["progress"]        = fraction
        _PULL_STATE["current_country"] = country

    # Separate OCDS countries from the Non-OCDS toggle
    _ocds_filter: list | None = None
    _non_ocds = True
    if countries_sel is not None:
        _non_ocds    = _PULL_NON_OCDS_KEY in countries_sel
        _ocds_filter = [c for c in countries_sel if c != _PULL_NON_OCDS_KEY] or None

    try:
        import ingest_core as _ic  # type: ignore[import-not-found]
        _ic.init_supabase()
        _ic.init_ai(log=lambda _: None)
        result = _ic.run_all(
            years_back=3, max_score=300, do_partner=True,
            score_time_budget_s=3000, trigger="manual_app",
            countries_filter=_ocds_filter, include_non_ocds=_non_ocds,
            parallel_workers=4, progress_cb=_prog_cb,
            log=_log,
        )
        _PULL_STATE.update({"status": "done", "result": result,
                            "progress": 1.0, "current_country": ""})
    except Exception as _e:
        _PULL_STATE.update({"status": "failed", "result": {"error": str(_e)}})

# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR — Navigation + health check + action buttons
# ─────────────────────────────────────────────────────────────────────────────

_NAV_PAGES = [
    "🏠 Overview",
    "📢 Opportunities",
    "🤝 Partners",
    "✅ Lead Verification",
    "🔍 LinkedIn Dork",
    "🛡️ Lead Intelligence",
]

with st.sidebar:
    _logo = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "crs_logo.png")
    if os.path.exists(_logo):
        st.image(_logo, width=160)
    st.title("CRS Intelligence")
    st.caption("v2 · scrape on-demand or via nightly schedule")
    st.divider()

    # ── Navigation (menu-style buttons) ──────────────────────────────────────
    if "_active_page" not in st.session_state:
        st.session_state["_active_page"] = _NAV_PAGES[0]
    for _nav_p in _NAV_PAGES:
        _is_active = st.session_state["_active_page"] == _nav_p
        if st.button(
            _nav_p,
            key=f"nav_{_nav_p}",
            use_container_width=True,
            type="primary" if _is_active else "secondary",
        ):
            st.session_state["_active_page"] = _nav_p
            st.rerun()
    _page = st.session_state["_active_page"]
    st.divider()

    # ── Pipeline status ───────────────────────────────────────────────────────
    _gh_running = False
    _gh_started = ""
    try:
        _lr = (supabase.table("pipeline_runs").select("run_at,status,tenders_scraped,trigger")
               .order("run_at", desc=True).limit(1).execute()).data
        if _lr:
            _r0 = _lr[0]
            _ts = str(_r0.get("run_at", ""))[:16]
            _st = _r0.get("status", "—")
            if _st == "running":
                _gh_running = True
                _gh_started = _ts
                st.warning(f"⏳ Pipeline running since {_ts}  \n(trigger: {_r0.get('trigger','?')})\n\nDo not press Pull again — a run is already in progress.", icon="⚠️")
            else:
                _dot = "🟢" if _st in ("success", "complete") else "🔴"
                st.caption(f"{_dot} Last run: {_ts} — {_st}")
                st.caption(f"   Scraped: {_r0.get('tenders_scraped', '—')}")
        else:
            st.caption("⚪ No pipeline runs yet")
    except Exception:
        st.caption("⚪ Pipeline status unavailable")

    # ── Health Check ──────────────────────────────────────────────────────────
    with st.expander("API health", expanded=False):
        for part in _provider_status().split(" · "):
            st.caption(part)
        monday_active = _MONDAY_OK and bool(
            st.secrets.get("MONDAY_API_KEY") if hasattr(st, "secrets") else "")
        st.caption("🟢 Monday.com" if monday_active else "⚪ Monday.com (key not set)")

    st.divider()

    # ── Actions ───────────────────────────────────────────────────────────────
    st.markdown("**Actions**")

    if st.button("🔄 Refresh data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    _ps = _PULL_STATE["status"]
    _pull_blocked = (_ps == "running") or _gh_running

    # ── In-process pull progress ──────────────────────────────────────────────
    if _ps == "running":
        _prog  = float(_PULL_STATE.get("progress", 0.0))
        _curr  = _PULL_STATE.get("current_country", "")
        _ptext = f"Scraping {_curr}…" if _curr and _curr != "starting…" else "Starting…"
        st.progress(_prog, text=_ptext)
        for _ll in _PULL_STATE["logs"][-4:]:
            st.caption(_ll)
        if st.button("🔄 Refresh status", key="pull_refresh_btn", use_container_width=True):
            st.rerun()
    elif _ps == "done":
        _r = _PULL_STATE.get("result") or {}
        st.success(f"✅ Scraped {_r.get('tenders_scraped', '?')} tenders")
    elif _ps == "failed":
        _r = _PULL_STATE.get("result") or {}
        st.error(str(_r.get("error", "Unknown error"))[:120])

    # ── Country selector ──────────────────────────────────────────────────────
    if "pull_countries" not in st.session_state:
        st.session_state["pull_countries"] = []
    with st.expander("🌍 Countries to pull", expanded=False):
        _ca, _cb = st.columns(2)
        with _ca:
            if st.button("Select all", key="pull_ctry_all", use_container_width=True):
                st.session_state["pull_countries"] = _PULL_ALL_COUNTRIES[:]
                st.rerun()
        with _cb:
            if st.button("Clear", key="pull_ctry_none", use_container_width=True):
                st.session_state["pull_countries"] = []
                st.rerun()
        _pull_countries = st.multiselect(
            "Countries",
            _PULL_ALL_COUNTRIES,
            key="pull_countries",
            label_visibility="collapsed",
        )

    if not _pull_countries:
        _pull_label = "📥 Pull all tenders"
        _pull_help  = "No countries selected — will scrape all"
    elif len(_pull_countries) == len(_PULL_ALL_COUNTRIES):
        _pull_label = "📥 Pull all tenders"
        _pull_help  = "Scrapes all countries"
    else:
        _pull_label = f"📥 Pull ({len(_pull_countries)} countries)"
        _pull_help  = ", ".join(_pull_countries[:6]) + ("…" if len(_pull_countries) > 6 else "")
    if st.button(_pull_label, use_container_width=True,
                 disabled=_pull_blocked, type="primary",
                 help=_pull_help):
        if _ps != "running":
            _env_ov: dict = {}
            for _k in ("SUPABASE_URL", "SUPABASE_KEY", "GROQ_API_KEY", "CEREBRAS_API_KEY",
                       "OPENROUTER_API_KEY", "GH_PAT", "GITHUB_TOKEN", "NVIDIA_API_KEY",
                       "DEEPSEEK_API_KEY", "GEMINI_API_KEY"):
                if not os.environ.get(_k):
                    _v = st.secrets.get(_k, "")
                    if _v:
                        _env_ov[_k] = _v
            _sel = _pull_countries if _pull_countries else None
            threading.Thread(
                target=_pull_worker, args=(_env_ov, _sel), daemon=True
            ).start()
            st.rerun()

    if _ps == "running":
        _n = len(_PULL_STATE["logs"])
        _last = _PULL_STATE["logs"][-1] if _PULL_STATE["logs"] else "Starting…"
        st.caption(f"🔄 Running — {_n} steps completed")
        st.caption(_last[:90])
        if st.button("↻ Check progress", use_container_width=True):
            st.rerun()
    elif _ps == "done":
        _r = _PULL_STATE.get("result") or {}
        st.success(f"✅ {_r.get('tenders_scraped', 0):,} scraped · {_r.get('tenders_scored', 0)} scored")
        _PULL_STATE["status"] = "idle"
        st.cache_data.clear()
    elif _ps == "failed":
        _r = _PULL_STATE.get("result") or {}
        st.error(f"❌ {str(_r.get('error', 'Unknown'))[:150]}")
        _PULL_STATE["status"] = "idle"

    if st.button("🤖 Score unscored tenders", use_container_width=True,
                 help="AI-scores up to 30 unscored open tenders now"):
        with st.spinner("Fetching unscored tenders…"):
            try:
                _unscored = (supabase.table("sa_tenders").select("*")
                             .is_("ai_score", "null").limit(30).execute()).data or []
            except Exception as _e:
                st.error(f"Fetch failed: {_e}")
                _unscored = []
        if not _unscored:
            st.info("No unscored tenders found.")
        else:
            _prog = st.progress(0, text=f"Scoring 0/{len(_unscored)}…")
            _errs = 0
            for _i, _row in enumerate(_unscored):
                try:
                    _sc = ai_score_tender(_row)
                    _blob = json.dumps({
                        "rationale": _sc["rationale"],
                        "partner_type": _sc["partner_type"],
                        "proposed_solutions": _sc["proposed_solutions"],
                        "outreach_angle": _sc["outreach_angle"],
                    })
                    supabase.table("sa_tenders").update(
                        {"ai_score": _sc["score"], "ai_rationale": _blob}
                    ).eq("id", _row["id"]).execute()
                except Exception:
                    _errs += 1
                _prog.progress((_i + 1) / len(_unscored),
                               text=f"Scoring {_i+1}/{len(_unscored)}…")
            _prog.empty()
            st.cache_data.clear()
            st.success(f"Scored {len(_unscored) - _errs}/{len(_unscored)} tenders.")

    if st.button("🤝 Run partner analysis", use_container_width=True,
                 help="AI partner analysis from awarded tender data"):
        _df_aw_sb = _load_awarded()
        if _df_aw_sb.empty:
            st.warning("No awarded tender data to analyse.")
        else:
            with st.spinner(f"Analysing {len(_df_aw_sb):,} awarded tenders…"):
                try:
                    _presults = ai_analyse_partners(_df_aw_sb)
                    if _presults:
                        def _js_sb(v):
                            return json.dumps(v) if isinstance(v, (list, dict)) else str(v or "")
                        _pins = [{
                            "company":             str(p.get("company",""))[:200],
                            "country":             str(p.get("country",""))[:100],
                            "crs_score":           p.get("tenders_won"),
                            "why":                 str(p.get("why_aligned",""))[:1000],
                            "outreach_angle":      str(p.get("outreach_angle",""))[:1000],
                            "urgency":             str(p.get("urgency",""))[:20],
                            "partnership_type":    str(p.get("partner_classification",""))[:100],
                            "tenders_won":         p.get("tenders_won"),
                            "proposed_solutions":  _js_sb(p.get("proposed_solutions",[])),
                            "key_tenders":         _js_sb(p.get("key_tenders",[])),
                            "tenders_won_summary": str(p.get("tenders_won_summary",""))[:2000],
                            "issuing_departments": _js_sb(p.get("issuing_departments",[])),
                            "estimated_deal_size": str(p.get("estimated_deal_size",""))[:50],
                        } for p in _presults]
                        supabase.table("partner_recommendation_history").insert(_pins).execute()
                        st.cache_data.clear()
                        st.success(f"Found {len(_presults)} partner candidates — saved.")
                    else:
                        st.warning("AI returned no partner candidates.")
                except Exception as _e:
                    st.error(f"Analysis failed: {_e}")

# ══════════════════════════════════════════════════════════════════════════════
# PAGE 1 — OVERVIEW
# ══════════════════════════════════════════════════════════════════════════════
if _page == "🏠 Overview":
    st.subheader("CRS Tender Intelligence — Overview")
    st.caption("Africa-wide government tender intelligence — active tenders, historical awards, and AI partner intelligence.")

    df_t   = _load_tenders()
    df_aw  = _load_awarded()
    df_run = _load_pipeline_runs()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Open tenders",     len(df_t))
    c2.metric("Awarded tenders",  len(df_aw))
    c3.metric("Countries (open)", df_t["country"].nunique() if "country" in df_t.columns else 0)
    last = df_run.iloc[0].to_dict() if not df_run.empty else {}
    c4.metric("Last pipeline", last.get("status", "—"))

    st.divider()
    st.markdown("#### Top-scored open tenders")
    if df_t.empty:
        st.info("No open tenders found. The nightly pipeline populates this.")
    else:
        score_col = "ai_score" if "ai_score" in df_t.columns else None
        if score_col:
            top = (df_t.assign(_s=pd.to_numeric(df_t[score_col], errors="coerce"))
                   .sort_values("_s", ascending=False).drop(columns="_s").head(15))
        else:
            top = df_t.head(15)
        show = [c for c in ["tender_number", "department_name", "title",
                             "country", "closing_date", "ai_score"] if c in top.columns]
        st.dataframe(top[show], use_container_width=True, hide_index=True)

    if not df_run.empty:
        st.divider()
        st.markdown("#### Recent pipeline runs")
        show_r = [c for c in ["run_at", "trigger", "status",
                               "tenders_scraped", "tenders_scored", "duration_secs"]
                  if c in df_run.columns]
        st.dataframe(df_run[show_r] if show_r else df_run,
                     use_container_width=True, hide_index=True)
        with st.expander("Last run error log"):
            st.text(last.get("error_log") or "—")

# ══════════════════════════════════════════════════════════════════════════════
# PAGE 2 — OPPORTUNITIES
# ══════════════════════════════════════════════════════════════════════════════
if _page == "📢 Opportunities":
    st.subheader("Open Opportunities")

    _df_all = _load_tenders()
    _unscored_n = int(_df_all["ai_score"].isna().sum()) if "ai_score" in _df_all.columns else len(_df_all)

    # ── Score-all button ──────────────────────────────────────────────────────
    _sb1, _sb2 = st.columns([3, 2])
    with _sb1:
        _do_score = st.button(
            f"🤖 Score all open tenders  ({_unscored_n} unscored)",
            type="primary", use_container_width=True,
        )
    with _sb2:
        st.caption(f"{len(_df_all):,} total open tenders loaded")

    if _do_score:
        _to_score = (supabase.table("sa_tenders").select("*")
                     .is_("ai_score", "null").neq("is_irrelevant", True)
                     .limit(300).execute()).data or []
        if not _to_score:
            st.info("All tenders are already scored.")
        else:
            _sp = st.progress(0, text=f"Scoring 0 / {len(_to_score)}…")
            _serr = 0
            for _si, _srow in enumerate(_to_score):
                try:
                    _sc = ai_score_tender(_srow)
                    supabase.table("sa_tenders").update({
                        "ai_score": _sc["score"],
                        "ai_rationale": json.dumps({
                            "rationale": _sc["rationale"],
                            "partner_type": _sc["partner_type"],
                            "proposed_solutions": _sc["proposed_solutions"],
                            "outreach_angle": _sc["outreach_angle"],
                        }),
                    }).eq("id", _srow["id"]).execute()
                except Exception:
                    _serr += 1
                _sp.progress((_si + 1) / len(_to_score),
                             text=f"Scoring {_si + 1} / {len(_to_score)}…")
            _sp.empty()
            st.cache_data.clear()
            st.success(f"✅ Scored {len(_to_score) - _serr} / {len(_to_score)} tenders.")
            _df_all = _load_tenders()

    st.divider()

    # ── Filters ───────────────────────────────────────────────────────────────
    _fc1, _fc2, _fc3 = st.columns([2, 3, 1])
    with _fc1:
        _ctries = sorted(_df_all["country"].dropna().unique().tolist()) if "country" in _df_all.columns else []
        if st.checkbox("Select all", key="opp_countries_all"):
            st.session_state["opp_countries"] = _ctries[:]
        elif not st.session_state.get("opp_countries_all"):
            st.session_state.setdefault("opp_countries", [])
        _sel_ctry = st.multiselect("Country", _ctries, key="opp_countries")
    with _fc2:
        _q = st.text_input("Search title / department", key="opp_search",
                           placeholder="type to filter…")
    with _fc3:
        _min_s = st.number_input("Min score", 0, 10, 0, key="opp_min_score", step=1)

    _df = _df_all.copy()
    if _sel_ctry and "country" in _df.columns:
        _df = _df[_df["country"].isin(_sel_ctry)]
    if _q:
        _qm = pd.Series(False, index=_df.index)
        for _qc in ("title", "department_name", "description"):
            if _qc in _df.columns:
                _qm |= _df[_qc].str.contains(_q, case=False, na=False)
        _df = _df[_qm]
    if _min_s > 0 and "ai_score" in _df.columns:
        _df = _df[pd.to_numeric(_df["ai_score"], errors="coerce").fillna(0) >= _min_s]
    if "ai_score" in _df.columns:
        _df = (_df.assign(_s=pd.to_numeric(_df["ai_score"], errors="coerce"))
               .sort_values("_s", ascending=False).drop(columns="_s"))
    _df = _df.reset_index(drop=True)

    _mc1, _mc2, _mc3 = st.columns(3)
    _mc1.metric("Shown", len(_df))
    if "country" in _df.columns:
        _mc2.metric("Countries", _df["country"].nunique())
    if "ai_score" in _df.columns:
        _avg = pd.to_numeric(_df["ai_score"], errors="coerce").mean()
        _mc3.metric("Avg score", f"{_avg:.1f}" if pd.notna(_avg) else "—")

    if _df.empty:
        st.info("No tenders match the current filters.")
    else:
        st.divider()
        st.markdown("#### Tender review queue")

        # ── Card navigation ───────────────────────────────────────────────────
        _total = len(_df)

        # Reset card index when filter set changes
        _filter_sig = f"{_sel_ctry}|{_q}|{_min_s}"
        if st.session_state.get("opp_filter_sig") != _filter_sig:
            st.session_state["opp_filter_sig"] = _filter_sig
            st.session_state["opp_card_idx"] = 0

        _idx = max(0, min(st.session_state.get("opp_card_idx", 0), _total - 1))
        st.session_state["opp_card_idx"] = _idx

        _nav1, _nav2, _nav3 = st.columns([1, 4, 1])
        with _nav1:
            if st.button("← Prev", disabled=(_idx == 0), use_container_width=True, key="opp_prev"):
                st.session_state["opp_card_idx"] = _idx - 1
                st.rerun()
        with _nav2:
            st.markdown(
                f"<p style='text-align:center;padding-top:6px;color:grey'>"
                f"Tender {_idx + 1} of {_total}</p>",
                unsafe_allow_html=True,
            )
        with _nav3:
            if st.button("Next →", disabled=(_idx >= _total - 1), use_container_width=True, key="opp_next"):
                st.session_state["opp_card_idx"] = _idx + 1
                st.rerun()

        # ── Card body ─────────────────────────────────────────────────────────
        _row = _df.iloc[_idx]
        _rat = _parse_rationale(_row.get("ai_rationale"))
        _score_raw = _row.get("ai_score")
        _score_num = pd.to_numeric(_score_raw, errors="coerce")

        with st.container(border=True):
            # Score badge
            if pd.notna(_score_num):
                _col = ("#b71c1c" if _score_num >= 8 else
                        "#e65100" if _score_num >= 6 else
                        "#2e7d32" if _score_num >= 4 else "#616161")
                st.markdown(
                    f"<span style='background:{_col};color:#fff;padding:3px 14px;"
                    f"border-radius:12px;font-weight:700;font-size:0.95rem'>"
                    f"Score {int(_score_num)}/10</span>",
                    unsafe_allow_html=True,
                )
                st.write("")

            st.markdown(f"### {_row.get('title', 'Untitled')}")

            _meta1, _meta2, _meta3 = st.columns(3)
            with _meta1:
                st.markdown(f"**Department**  \n{_row.get('department_name', '—')}")
            with _meta2:
                st.markdown(f"**Country**  \n{_row.get('country', '—')}")
            with _meta3:
                st.markdown(f"**Closes**  \n{str(_row.get('closing_date', '—'))[:10]}")

            _ref = _row.get("tender_number") or _row.get("source_url")
            if _ref and str(_ref) not in ("nan", "None", ""):
                st.caption(f"Ref: {_ref}")

            st.divider()

            # Description
            _desc = str(_row.get("description") or "").strip()
            if _desc and _desc not in ("nan", "None"):
                with st.expander("Description", expanded=False):
                    st.write(_desc[:1500])

            # AI rationale block
            if _rat.get("rationale"):
                st.markdown("**AI Rationale**")
                st.info(_rat["rationale"])

            _ai1, _ai2 = st.columns(2)
            with _ai1:
                if _rat.get("partner_type"):
                    st.markdown(f"**Partner type:** {_rat['partner_type']}")
                _sols = _rat.get("proposed_solutions", [])
                if _sols:
                    _sl = _sols if isinstance(_sols, list) else [_sols]
                    st.markdown("**Solutions:** " + "  ".join(f"`{s}`" for s in _sl))
            with _ai2:
                if _rat.get("outreach_angle"):
                    st.markdown("**Outreach angle**")
                    st.success(_rat["outreach_angle"])

            # Contact info
            _contacts = [(f.replace("contact_", "").title(), _row.get(f))
                         for f in ("contact_person", "contact_email", "contact_phone")
                         if _row.get(f) and str(_row.get(f)) not in ("nan", "None", "")]
            if _contacts:
                st.markdown("**Contact:** " + "  ·  ".join(f"{k}: {v}" for k, v in _contacts))

            st.divider()

            # Action buttons
            _a1, _a2, _a3 = st.columns(3)
            with _a1:
                if monday_active:
                    if st.button("📋 Push to Monday", key=f"opp_push_{_idx}",
                                 use_container_width=True, type="primary"):
                        with st.spinner("Pushing…"):
                            _res = push_tender_to_monday(_row.to_dict())
                        st.success(f"Ticket: {_res.get('ticket_action')} · Lead: {_res.get('lead_action')}")
                else:
                    st.caption("Add MONDAY_API_KEY to enable push")
            with _a2:
                if st.button("🚫 Mark irrelevant", key=f"opp_irrel_{_idx}",
                             use_container_width=True):
                    supabase.table("sa_tenders").update(
                        {"is_irrelevant": True}
                    ).eq("id", str(_row["id"])).execute()
                    st.cache_data.clear()
                    st.session_state["opp_card_idx"] = max(0, _idx - 1)
                    st.rerun()
            with _a3:
                _btn_label = "🤖 Score this" if pd.isna(_score_num) else "🔄 Re-score"
                if st.button(_btn_label, key=f"opp_score_{_idx}", use_container_width=True):
                    with st.spinner("Scoring…"):
                        try:
                            _sc2 = ai_score_tender(_row.to_dict())
                            supabase.table("sa_tenders").update({
                                "ai_score": _sc2["score"],
                                "ai_rationale": json.dumps({
                                    "rationale": _sc2["rationale"],
                                    "partner_type": _sc2["partner_type"],
                                    "proposed_solutions": _sc2["proposed_solutions"],
                                    "outreach_angle": _sc2["outreach_angle"],
                                }),
                            }).eq("id", str(_row["id"])).execute()
                            st.cache_data.clear()
                            st.rerun()
                        except Exception as _se:
                            st.error(f"Scoring failed: {_se}")

            # ── Copy ──────────────────────────────────────────────────────────
            _opp_copy_lines = [
                f"TENDER: {_row.get('title', '')}",
                f"Department: {_row.get('department_name', '—')}",
                f"Country: {_row.get('country', '—')}",
                f"Closes: {str(_row.get('closing_date', '—'))[:10]}",
                f"Ref: {_row.get('tender_number', '') or _row.get('source_url', '') or '—'}",
                f"Score: {int(_score_num)}/10" if pd.notna(_score_num) else "Score: —",
            ]
            if _rat.get("rationale"):
                _opp_copy_lines.append(f"Rationale: {_rat['rationale']}")
            _sols_list = _rat.get("proposed_solutions", [])
            if _sols_list:
                _opp_copy_lines.append("Solutions: " + ", ".join(
                    _sols_list if isinstance(_sols_list, list) else [str(_sols_list)]))
            if _rat.get("outreach_angle"):
                _opp_copy_lines.append(f"Outreach: {_rat['outreach_angle']}")
            for _lbl2, _fld2 in [("Contact", "contact_person"),
                                  ("Email",   "contact_email"),
                                  ("Phone",   "contact_phone")]:
                _fv = _row.get(_fld2)
                if _fv and str(_fv) not in ("nan", "None", ""):
                    _opp_copy_lines.append(f"{_lbl2}: {_fv}")
            _copy_block("\n".join(_opp_copy_lines), key=f"opp_copy_{_idx}")

# ══════════════════════════════════════════════════════════════════════════════
# PAGE 3 — PARTNERS
# ══════════════════════════════════════════════════════════════════════════════
if _page == "🤝 Partners":
    st.subheader("Partner Recommendations")
    st.caption("Companies CRS should approach as channel partners, derived from awarded tender data.")

    df_p = _country(_load_partner_history())
    df_aw = _load_awarded()

    # ── On-demand analysis button ────────────────────────────────────────────
    col_btn, col_info = st.columns([2, 3])
    with col_btn:
        run_analysis = st.button("Run partner analysis now", key="partner_run",
                                 type="primary")
    with col_info:
        if not df_aw.empty:
            st.caption(f"Will analyse {len(df_aw):,} awarded tenders from {df_aw['country'].nunique() if 'country' in df_aw.columns else '?'} countries.")

    if run_analysis:
        if df_aw.empty:
            st.warning("No awarded tender data to analyse.")
        else:
            with st.spinner(f"Analysing {len(df_aw):,} awarded tenders for partner candidates…"):
                try:
                    results = ai_analyse_partners(df_aw)
                    if results:
                        def _js(v):
                            return json.dumps(v) if isinstance(v, (list, dict)) else str(v or "")
                        rows_to_insert = [{
                            "company":              str(p.get("company",""))[:200],
                            "country":              str(p.get("country",""))[:100],
                            "crs_score":            p.get("tenders_won"),
                            "why":                  str(p.get("why_aligned",""))[:1000],
                            "outreach_angle":       str(p.get("outreach_angle",""))[:1000],
                            "urgency":              str(p.get("urgency",""))[:20],
                            "partnership_type":     str(p.get("partner_classification",""))[:100],
                            "tenders_won":          p.get("tenders_won"),
                            "proposed_solutions":   _js(p.get("proposed_solutions",[])),
                            "key_tenders":          _js(p.get("key_tenders",[])),
                            "tenders_won_summary":  str(p.get("tenders_won_summary",""))[:2000],
                            "issuing_departments":  _js(p.get("issuing_departments",[])),
                            "estimated_deal_size":  str(p.get("estimated_deal_size",""))[:50],
                        } for p in results]
                        supabase.table("partner_recommendation_history").insert(rows_to_insert).execute()
                        st.cache_data.clear()
                        st.success(f"Found {len(results)} partner candidates — saved.")
                        df_p = pd.DataFrame(results)
                except Exception as e:
                    st.error(f"Analysis failed: {e}")

    st.divider()

    # ── Score filter ─────────────────────────────────────────────────────────
    urgency_filter = st.selectbox("Filter by urgency", ["All", "high", "medium", "low"],
                                  key="partner_urg")

    if df_p.empty:
        st.info("No partner recommendations yet. Click 'Run partner analysis now' or wait for the nightly pipeline.")
    else:
        if urgency_filter != "All" and "urgency" in df_p.columns:
            df_p = df_p[df_p["urgency"].str.lower() == urgency_filter]

        # Deduplicate: keep the most recent row per company (run_at is already desc)
        if "company" in df_p.columns:
            df_p = df_p.drop_duplicates(subset=["company"], keep="first").reset_index(drop=True)

        st.markdown(f"**{len(df_p)} partner candidates**")

        # ── Partner cards ────────────────────────────────────────────────────
        for card_idx, pr in df_p.iterrows():
            urgency = str(pr.get("urgency", "")).lower()
            badge = _badge(urgency)
            company = pr.get("company", "Unknown")
            country  = pr.get("country", "")
            p_type   = pr.get("partnership_type", "")
            deal     = pr.get("estimated_deal_size", "")
            sols     = _parse_list(pr.get("proposed_solutions"))
            key_t    = _parse_list(pr.get("key_tenders"))
            depts    = _parse_list(pr.get("issuing_departments"))
            why      = pr.get("why", "") or pr.get("why_aligned", "")
            angle    = pr.get("outreach_angle", "")
            summary  = pr.get("tenders_won_summary", "")
            wins     = pr.get("tenders_won")

            with st.container(border=True):
                h1, h2, h3 = st.columns([3, 2, 1])
                with h1:
                    st.markdown(f"### {company}")
                    st.caption(f"{country}  ·  {p_type}")
                with h2:
                    if wins:
                        st.metric("Tenders won", wins)
                with h3:
                    st.markdown(badge)
                    if deal:
                        st.caption(f"Deal size: **{deal}**")

                if summary:
                    st.caption(summary)

                c_left, c_right = st.columns(2)
                with c_left:
                    if why:
                        st.markdown("**Why CRS should partner:**")
                        st.write(why)
                    if sols:
                        st.markdown("**Proposed solutions:**  " +
                                    "  ".join(f"`{s}`" for s in sols))
                with c_right:
                    if angle:
                        st.markdown("**Outreach angle:**")
                        st.info(angle)

                # Tenders won — pull matching rows from awarded_tenders
                if key_t or company:
                    with st.expander(f"Tenders won by {company}"):
                        if not df_aw.empty:
                            mask = df_aw.get("winning_bidder", pd.Series(dtype=str))\
                                        .str.contains(company, case=False, na=False)
                            won_rows = df_aw[mask].head(20)
                            if not won_rows.empty:
                                cols_to_show = [c for c in ["tender_number","title",
                                                             "department_name","country",
                                                             "award_value","closing_date"]
                                                if c in won_rows.columns]
                                st.dataframe(won_rows[cols_to_show],
                                             use_container_width=True, hide_index=True)
                            else:
                                st.caption("No matching awarded tenders found in loaded data.")
                        if key_t:
                            st.markdown("**Key tender references:** " +
                                        ", ".join(f"`{t}`" for t in key_t))
                        if depts:
                            st.markdown("**Issuing departments:** " +
                                        ", ".join(depts))

                if monday_active:
                    if st.button("Push to Companies board", key=f"push_{card_idx}_{company[:30]}"):
                        with st.spinner("Pushing…"):
                            res_p = push_partner_to_companies(pr.to_dict())
                        st.success(f"Action: **{res_p.get('action')}** | ID: {res_p.get('item_id')}")

                # ── Copy ──────────────────────────────────────────────────────
                _p_copy_lines = [
                    f"COMPANY: {company}",
                    f"Country: {country}",
                    f"Type: {p_type}" if p_type else "",
                    f"Tenders won: {wins}" if wins else "",
                    f"Deal size: {deal}" if deal else "",
                    f"Urgency: {urgency}" if urgency else "",
                    f"Summary: {summary}" if summary else "",
                    f"Why CRS: {why}" if why else "",
                    ("Solutions: " + ", ".join(sols)) if sols else "",
                    f"Outreach: {angle}" if angle else "",
                ]
                _copy_block("\n".join(l for l in _p_copy_lines if l),
                            key=f"partner_copy_{card_idx}")

    st.divider()
    st.markdown("#### Awarded tender context")
    if not df_aw.empty:
        aw_filtered = _country(df_aw)
        col_aw1, col_aw2 = st.columns([3, 1])
        with col_aw1:
            aw_search = st.text_input("Search bidder / title", key="aw_search")
        with col_aw2:
            aw_countries = sorted(df_aw["country"].dropna().unique().tolist()) if "country" in df_aw.columns else []
            aw_country = st.selectbox("Country", ["All"] + aw_countries, key="aw_country")

        if aw_search:
            mask2 = pd.Series(False, index=aw_filtered.index)
            for col in ("winning_bidder","title","department_name"):
                if col in aw_filtered.columns:
                    mask2 |= aw_filtered[col].str.contains(aw_search, case=False, na=False)
            aw_filtered = aw_filtered[mask2]
        if aw_country != "All" and "country" in aw_filtered.columns:
            aw_filtered = aw_filtered[aw_filtered["country"] == aw_country]

        st.caption(f"{len(aw_filtered):,} awarded tenders")
        show_aw = [c for c in ["tender_number","department_name","title",
                                "country","winning_bidder","award_value","closing_date"]
                   if c in aw_filtered.columns]
        st.dataframe(aw_filtered[show_aw].head(500) if show_aw else aw_filtered.head(500),
                     use_container_width=True, hide_index=True)
    else:
        st.info("No awarded tenders loaded.")

# ══════════════════════════════════════════════════════════════════════════════
# PAGE 4 — LEAD VERIFICATION
# ══════════════════════════════════════════════════════════════════════════════
if _page == "✅ Lead Verification":
    st.subheader("Lead Verification")

    # ══════════════════════════════════════════════════════════════════════════
    # CONTACT LOOKUP — name + company → Monday CRM → Apollo + Lusha enrichment
    # ══════════════════════════════════════════════════════════════════════════
    st.markdown("### 🔍 Contact Lookup")
    st.caption(
        "Search by name and/or company. "
        "Checks Monday CRM first; if not found, enrich via Apollo + Lusha. "
        "Company-only search surfaces key decision makers."
    )

    _lk1, _lk2, _lk3 = st.columns([3, 3, 1])
    with _lk1:
        _lk_name = st.text_input("👤 Person name (optional)",
                                  key="lk_name", placeholder="e.g. John Smith")
    with _lk2:
        _lk_company = st.text_input("🏢 Company (optional)",
                                     key="lk_company", placeholder="e.g. Absa Bank")
    with _lk3:
        st.write(""); st.write("")
        _lk_run = st.button("🔍 Search", key="lk_run",
                             type="primary", use_container_width=True)

    if _lk_run:
        _n = st.session_state.get("lk_name", "").strip()
        _c = st.session_state.get("lk_company", "").strip()
        if not _n and not _c:
            st.warning("Enter a name, company, or both.")
        else:
            for _k0 in ("lk_crm", "lk_co", "lk_enrich", "lk_dm"):
                st.session_state.pop(_k0, None)
            if monday_active and _n:
                with st.spinner("Checking Monday CRM…"):
                    try:
                        st.session_state["lk_crm"] = lookup_monday_crm(
                            {"name": _n, "email": "", "linkedin": ""})
                    except Exception:
                        st.session_state["lk_crm"] = {"on_crm": False}
            if monday_active and _c:
                with st.spinner("Checking Monday Companies board…"):
                    try:
                        st.session_state["lk_co"] = lookup_monday_company(_c)
                    except Exception:
                        st.session_state["lk_co"] = {"found": False}

    # ── CRM person result ─────────────────────────────────────────────────────
    _lk_crm_r = st.session_state.get("lk_crm")
    if _lk_crm_r is not None:
        _lk_n_disp = st.session_state.get("lk_name", "")
        if _lk_crm_r.get("on_crm"):
            with st.container(border=True):
                _lk_ra, _lk_rb = st.columns([4, 2])
                with _lk_ra:
                    st.success(f"✅ **{_lk_n_disp}** found on **{_lk_crm_r['crm_board']}** board")
                    for _lk_fld, _lk_ico in [
                        ("crm_title",       "💼"),
                        ("crm_email",       "📧"),
                        ("crm_phone",       "📞"),
                        ("crm_linkedin",    "🔗"),
                        ("crm_authority",   "🎯"),
                        ("crm_heat",        "🔥"),
                    ]:
                        _v0 = _lk_crm_r.get(_lk_fld, "")
                        if _v0 and str(_v0) not in ("", "nan", "None"):
                            st.markdown(f"{_lk_ico} {_v0}")
                    _lm = _lk_crm_r.get("crm_last_method", "")
                    _ld = _lk_crm_r.get("crm_last_date", "")
                    if _lm or _ld:
                        st.caption(f"Last contact: {(_lm + ' ' + _ld).strip()}")
                    if _lk_crm_r.get("crm_notes"):
                        st.caption(f"📝 {_lk_crm_r['crm_notes'][:150]}")
                with _lk_rb:
                    if _lk_crm_r.get("crm_url"):
                        st.markdown(f"[Open in Monday →]({_lk_crm_r['crm_url']})")
        else:
            st.warning(f"❌ **{_lk_n_disp}** not found in Monday CRM")
            _has_apo = bool(st.secrets.get("APOLLO_API_KEY", "") or os.getenv("APOLLO_API_KEY", ""))
            _has_lsh = bool(st.secrets.get("LUSHA_API_KEY",  "") or os.getenv("LUSHA_API_KEY",  ""))
            if _has_apo or _has_lsh:
                if st.button("🔍 Enrich via Apollo + Lusha", key="lk_enrich_btn",
                             type="primary"):
                    _enr: list = []
                    _en  = st.session_state.get("lk_name", "").strip()
                    _ec  = st.session_state.get("lk_company", "").strip()
                    if _has_apo:
                        with st.spinner("Searching Apollo…"):
                            try:
                                _enr += [_norm_apollo(p)
                                         for p in _apollo_search_people(
                                             name=_en, company=_ec, num=5)]
                            except Exception as _ae:
                                st.toast(f"Apollo: {str(_ae)[:80]}")
                    if _has_lsh:
                        with st.spinner("Enriching via Lusha…"):
                            _np0 = _en.split()
                            try:
                                _l_raw = _lusha_search_contacts(
                                    first_name=_np0[0] if _np0 else "",
                                    last_name=_np0[-1] if len(_np0) > 1 else "",
                                    company=_ec,
                                )
                                _apo_names = {x["name"].lower() for x in _enr}
                                for _lc in _l_raw:
                                    _ln = _norm_lusha(_lc)
                                    if _ln["name"].lower() in _apo_names:
                                        for _ex in _enr:
                                            if _ex["name"].lower() == _ln["name"].lower():
                                                if not _ex["email"] and _ln["email"]:
                                                    _ex["email"] = _ln["email"]
                                                    _ex["email_status"] = "lusha"
                                                if not _ex["phone"] and _ln["phone"]:
                                                    _ex["phone"] = _ln["phone"]
                                                if not _ex["company_phone"] and _ln["company_phone"]:
                                                    _ex["company_phone"] = _ln["company_phone"]
                                                if "Lusha" not in _ex["source"]:
                                                    _ex["source"] += " + Lusha"
                                    else:
                                        _enr.append(_ln)
                            except Exception as _le:
                                st.toast(f"Lusha: {str(_le)[:80]}")
                    st.session_state["lk_enrich"] = _enr
                    if not _enr:
                        st.info("No results found. Try the LinkedIn Dork tab for manual search.")
            else:
                st.info("Add APOLLO_API_KEY or LUSHA_API_KEY to enable enrichment.")

    # ── Companies board result ────────────────────────────────────────────────
    _lk_co_r = st.session_state.get("lk_co")
    if _lk_co_r is not None:
        _lk_c_disp = st.session_state.get("lk_company", "")
        if _lk_co_r.get("found"):
            with st.container(border=True):
                _co_a, _co_b = st.columns([4, 2])
                with _co_a:
                    st.success(f"✅ **{_lk_c_disp}** on Monday Companies board")
                    if _lk_co_r.get("office_number"):
                        st.markdown(f"📞 {_lk_co_r['office_number']}")
                    if _lk_co_r.get("website"):
                        st.markdown(f"🌐 {_lk_co_r['website']}")
                    if _lk_co_r.get("linkedin"):
                        st.markdown(f"🔗 {_lk_co_r['linkedin']}")
                with _co_b:
                    if _lk_co_r.get("company_url"):
                        st.markdown(f"[Open in Monday →]({_lk_co_r['company_url']})")
        else:
            st.info(f"ℹ️ **{_lk_c_disp}** not on Monday Companies board")

        if bool(st.secrets.get("APOLLO_API_KEY", "") or os.getenv("APOLLO_API_KEY", "")):
            if st.button("👥 Find key decision makers at this company",
                         key="lk_dm_btn", use_container_width=True):
                with st.spinner(f"Searching Apollo for decision makers at {_lk_c_disp}…"):
                    try:
                        _dm_raw = _apollo_search_people(
                            company=_lk_c_disp, num=8,
                            titles=["CISO", "CTO", "CIO", "CEO", "IT Director",
                                    "Head of IT", "IT Manager", "ICT Manager",
                                    "Security Manager", "Head of Cybersecurity",
                                    "VP Technology", "Group IT Manager"],
                        )
                        _dm_list = [_norm_apollo(p) for p in _dm_raw]
                        st.session_state["lk_dm"] = _dm_list
                        if not _dm_list:
                            st.warning("No decision makers found via Apollo — "
                                       "try the LinkedIn Dork tab for manual search.")
                    except Exception as _dme:
                        st.error(f"Apollo error: {_dme}")

    # ── Contact cards (enrichment + decision makers) ──────────────────────────
    def _render_contact_cards(cards: list, card_set_key: str) -> None:
        if not cards:
            return
        for _ci, _cc in enumerate(cards):
            if not _cc.get("name"):
                continue
            with st.container(border=True):
                _cc_a, _cc_b = st.columns([3, 2])
                with _cc_a:
                    st.markdown(f"### 👤 {_cc['name']}")
                    _role_parts = [x for x in [_cc.get("title"), _cc.get("company")] if x]
                    if _role_parts:
                        st.caption("💼 " + "  ·  ".join(_role_parts))
                    if _cc.get("email"):
                        _ev = " ✓" if _cc.get("email_status") in ("verified",) else ""
                        st.markdown(f"📧 **{_cc['email']}**{_ev}")
                    if _cc.get("phone"):
                        st.markdown(f"📞 **{_cc['phone']}**")
                    if _cc.get("company_phone"):
                        st.markdown(f"🏢 **{_cc['company_phone']}** (company)")
                    if _cc.get("linkedin"):
                        st.markdown(f"[LinkedIn →]({_cc['linkedin']})")
                    if _cc.get("twitter"):
                        st.caption(f"Twitter: {_cc['twitter']}")
                with _cc_b:
                    st.caption(f"Source: {_cc.get('source', '—')}")
                    if _cc.get("domain"):
                        st.caption(f"Domain: {_cc['domain']}")
                    if monday_active:
                        _crm_sk = f"lk_cc_crm_{card_set_key}_{_ci}"
                        if st.button("🔍 Check CRM",
                                     key=f"lk_crm_btn_{card_set_key}_{_ci}",
                                     use_container_width=True):
                            with st.spinner("Checking Monday…"):
                                try:
                                    _cc_crm = lookup_monday_crm({
                                        "name":    _cc.get("name", ""),
                                        "email":   _cc.get("email", ""),
                                        "linkedin":_cc.get("linkedin", ""),
                                    })
                                    st.session_state[_crm_sk] = _cc_crm
                                except Exception:
                                    st.session_state[_crm_sk] = {"on_crm": False}
                        _cc_crm_r = st.session_state.get(_crm_sk)
                        if _cc_crm_r is not None:
                            if _cc_crm_r.get("on_crm"):
                                st.success(f"✅ {_cc_crm_r['crm_board']}")
                                if _cc_crm_r.get("crm_url"):
                                    st.markdown(f"[Open →]({_cc_crm_r['crm_url']})")
                            else:
                                st.warning("❌ Not in CRM")

                if monday_active:
                    _pb1, _pb2 = st.columns(2)
                    _push_pl = {
                        "name":           _cc.get("name", ""),
                        "title":          _cc.get("title", ""),
                        "company":        _cc.get("company", ""),
                        "email":          _cc.get("email", ""),
                        "phone":          _cc.get("phone", ""),
                        "linkedin":       _cc.get("linkedin", ""),
                        "company_phone":  _cc.get("company_phone", ""),
                        "twitter":        _cc.get("twitter", ""),
                        "provider_chain": _cc.get("source", "Apollo/Lusha"),
                    }
                    with _pb1:
                        if st.button("📋 Push to Leads",
                                     key=f"lk_push_lead_{card_set_key}_{_ci}",
                                     use_container_width=True):
                            with st.spinner("Pushing to Leads board…"):
                                try:
                                    _res_l = sync_lead_to_monday(_push_pl)
                                    st.success(f"{_res_l.get('action','done').title()} · "
                                               f"ID {_res_l.get('item_id')}")
                                except Exception as _ple:
                                    st.error(f"Push failed: {_ple}")
                    with _pb2:
                        if st.button("🏢 Push to Contacts",
                                     key=f"lk_push_contact_{card_set_key}_{_ci}",
                                     use_container_width=True, type="primary"):
                            with st.spinner("Pushing to Contacts board…"):
                                try:
                                    _res_c = push_to_contacts_board(_push_pl)
                                    st.success(f"{_res_c.get('action','done').title()} · "
                                               f"ID {_res_c.get('item_id')}")
                                except Exception as _pce:
                                    st.error(f"Push failed: {_pce}")

                _lk_copy = [
                    f"CONTACT: {_cc.get('name','')}",
                    f"Title: {_cc.get('title','')}"         if _cc.get("title")         else "",
                    f"Company: {_cc.get('company','')}"     if _cc.get("company")       else "",
                    f"Email: {_cc.get('email','')}"         if _cc.get("email")         else "",
                    f"Phone: {_cc.get('phone','')}"         if _cc.get("phone")         else "",
                    f"Company Ph: {_cc.get('company_phone','')}" if _cc.get("company_phone") else "",
                    f"LinkedIn: {_cc.get('linkedin','')}"   if _cc.get("linkedin")      else "",
                    f"Twitter: {_cc.get('twitter','')}"     if _cc.get("twitter")       else "",
                    f"Domain: {_cc.get('domain','')}"       if _cc.get("domain")        else "",
                    f"Source: {_cc.get('source','')}",
                ]
                _copy_block("\n".join(l for l in _lk_copy if l),
                            key=f"lk_copy_{card_set_key}_{_ci}")

    for _set_key, _set_label in [("lk_enrich", "Enrichment results"),
                                  ("lk_dm",     "Decision makers found")]:
        _cards = st.session_state.get(_set_key)
        if _cards:
            st.divider()
            st.markdown(f"**{len(_cards)} {_set_label}**")
            _render_contact_cards(_cards, _set_key)

    # ══════════════════════════════════════════════════════════════════════════
    # PIPELINE VERIFICATION LOG
    # ══════════════════════════════════════════════════════════════════════════
    st.divider()
    st.markdown("### 📋 Pipeline Verification Log")
    st.caption("Contacts verified or quarantined by the pipeline cascade.")

    df_lv = _load_lead_verifications()

    col_lf1, col_lf2 = st.columns([2, 3])
    with col_lf1:
        lv_status_opts = ["All"] + (sorted(df_lv["status"].dropna().unique().tolist())
                                    if not df_lv.empty and "status" in df_lv.columns else [])
        lv_status = st.selectbox("Status", lv_status_opts, key="lv_status")
        if lv_status != "All" and "status" in df_lv.columns:
            df_lv = df_lv[df_lv["status"] == lv_status]
    with col_lf2:
        lv_search = st.text_input("Search name / company", key="lv_search")
        if lv_search:
            mask = pd.Series(False, index=df_lv.index)
            for col in ("contact_name", "company", "email"):
                if col in df_lv.columns:
                    mask |= df_lv[col].str.contains(lv_search, case=False, na=False)
            df_lv = df_lv[mask]

    if df_lv.empty:
        st.info("No verified leads yet.")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Shown", len(df_lv))
        if "status" in df_lv.columns:
            c2.metric("Verified", int((df_lv["status"].str.lower() == "verified").sum()))
        if "accuracy_score" in df_lv.columns:
            avg_acc = pd.to_numeric(df_lv["accuracy_score"], errors="coerce").mean()
            c3.metric("Avg accuracy", f"{avg_acc:.0f}%" if pd.notna(avg_acc) else "—")

        show_lv = [c for c in ["contact_name","contact_title","company","email",
                                "phone","authority","accuracy_score","status",
                                "provider_chain","country","run_at"] if c in df_lv.columns]
        st.dataframe(df_lv[show_lv] if show_lv else df_lv,
                     use_container_width=True, hide_index=True)

        name_col = "contact_name" if "contact_name" in df_lv.columns else None
        if name_col:
            st.divider()
            sel_lead = st.selectbox("Select contact to push / look up",
                                    ["—"] + df_lv[name_col].dropna().tolist(), key="lv_sel")
            if sel_lead != "—":
                row_l = df_lv[df_lv[name_col] == sel_lead].iloc[0].to_dict()

                with st.expander("Contact detail", expanded=False):
                    for field in ["contact_name","contact_title","company","email",
                                  "phone","linkedin","authority","accuracy_score",
                                  "provider_chain","status","country"]:
                        val = row_l.get(field)
                        if val and str(val) not in ("", "nan", "None"):
                            st.markdown(f"**{field.replace('_',' ').title()}:** {val}")
                    # Copy block
                    _lv_copy_lines = []
                    for _lv_f in ["contact_name","contact_title","company","email",
                                  "phone","linkedin","authority","accuracy_score",
                                  "provider_chain","country"]:
                        _lv_v = row_l.get(_lv_f)
                        if _lv_v and str(_lv_v) not in ("", "nan", "None"):
                            _lv_copy_lines.append(
                                f"{_lv_f.replace('_',' ').title()}: {_lv_v}")
                    _copy_block("\n".join(_lv_copy_lines), key=f"lv_copy_{sel_lead[:30]}")

                contact_payload = {
                    "name":           row_l.get("contact_name", ""),
                    "title":          row_l.get("contact_title", ""),
                    "company":        row_l.get("company", ""),
                    "email":          row_l.get("email", ""),
                    "phone":          row_l.get("phone", ""),
                    "linkedin":       row_l.get("linkedin", ""),
                    "authority":      row_l.get("authority", ""),
                    "accuracy_score": row_l.get("accuracy_score", ""),
                    "provider_chain": row_l.get("provider_chain", ""),
                    "country":        row_l.get("country", ""),
                }

                if monday_active:
                    col_push, col_crm = st.columns(2)
                    with col_push:
                        if st.button("Push to Monday Leads", key="lv_push"):
                            with st.spinner("Pushing…"):
                                res_l = sync_lead_to_monday(contact_payload)
                            st.success(f"Action: **{res_l.get('action')}** | ID: {res_l.get('item_id')}")
                    with col_crm:
                        if st.button("Check Monday CRM", key="lv_crm"):
                            with st.spinner("Looking up CRM…"):
                                crm = lookup_monday_crm(contact_payload)
                            if crm.get("on_crm"):
                                st.info(f"Found on **{crm['crm_board']}** — "
                                        f"[{crm.get('crm_title', sel_lead)}]"
                                        f"({crm.get('crm_url', '')})")
                            else:
                                st.warning("Not found in Monday CRM.")
                else:
                    st.info("Add MONDAY_API_KEY to enable push.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 5 — LINKEDIN DORK
# ══════════════════════════════════════════════════════════════════════════════
def _as_list(v) -> list:
    if isinstance(v, list): return v
    if not v: return []
    try: return json.loads(v)
    except Exception: return []

if _page == "🔍 LinkedIn Dork":
    st.subheader("LinkedIn Lead Discovery")
    st.caption(
        "Dork LinkedIn profiles, cache all enrichment in Supabase, "
        "check Monday CRM automatically, find contact info via Apollo / Hunter / Lusha, "
        "edit fields, then push or update the Monday Leads board."
    )

    _DORK_SOLUTIONS = {
        "Cybersecurity (general)":         "cybersecurity information security",
        "NDR / XDR — VECTRA AI":           "network detection response NDR XDR threat detection",
        "Vulnerability Mgmt — vRx":        "vulnerability management patch management",
        "CTEM / PTaaS — Strobes":          "CTEM continuous threat exposure penetration testing",
        "AppSec / DevSecOps — Aikido":     "application security DevSecOps SAST DAST",
        "Dark Web / Threat Intel — Flare": "dark web threat intelligence monitoring",
        "SASE / SIEM / MDR — Todyl":       "SASE SIEM MDR security operations",
        "Supply Chain Risk — Panorays":    "third-party risk supply chain cyber",
        "POPIA / GRC / Compliance":        "POPIA GDPR compliance GRC governance risk",
        "Endpoint / Encryption — Beachhead": "endpoint security encryption MFA",
        "IBM / Red Hat Training":          "IBM Red Hat Linux training certification",
        "CompTIA Training":                "CompTIA Security+ Network+ training certification",
        "VAPT / Pentest":                  "penetration testing VAPT red team ethical hacking",
        "SOC / MDR":                       "SOC security operations centre MDR managed detection",
    }

    _DORK_TITLES = [
        "CISO", "Chief Information Security Officer", "IT Manager", "Head of IT",
        "ICT Manager", "Security Manager", "IT Director", "CTO",
        "SOC Manager", "Head of Cybersecurity", "IT Governance Manager",
        "Group IT Manager", "Head of Security", "Cybersecurity Manager",
        "Information Security Officer", "Network Manager",
    ]

    _DORK_COUNTRIES = [
        "South Africa", "Nigeria", "Kenya", "Ghana", "Tanzania",
        "Uganda", "Zimbabwe", "Zambia", "Botswana", "Namibia",
        "Rwanda", "Mozambique", "Ethiopia", "Senegal", "Ivory Coast",
    ]

    # ── Search builder ────────────────────────────────────────────────────────
    _dc1, _dc2, _dc3 = st.columns(3)
    with _dc1:
        _d_sol_key = st.selectbox("Solution focus", list(_DORK_SOLUTIONS.keys()), key="dork_sol")
    with _dc2:
        if st.checkbox("Select all", key="dork_titles_all"):
            st.session_state["dork_titles"] = _DORK_TITLES[:]
        elif not st.session_state.get("dork_titles_all"):
            st.session_state.setdefault("dork_titles", ["CISO", "IT Manager", "Head of IT"])
        _d_titles = st.multiselect("Job titles (OR)", _DORK_TITLES, key="dork_titles")
    with _dc3:
        if st.checkbox("Select all", key="dork_countries_all"):
            st.session_state["dork_countries"] = _DORK_COUNTRIES[:]
        elif not st.session_state.get("dork_countries_all"):
            st.session_state.setdefault("dork_countries", ["South Africa"])
        _d_countries = st.multiselect("Countries (OR)", _DORK_COUNTRIES, key="dork_countries")

    _sol_kw    = _DORK_SOLUTIONS[_d_sol_key]
    _title_kw  = " OR ".join(f'"{t}"' for t in _d_titles)  if _d_titles   else ""
    _ctry_kw   = " OR ".join(f'"{c}"' for c in _d_countries) if _d_countries else ""
    _auto_q    = f"site:linkedin.com/in/ {_sol_kw}"
    if _title_kw:  _auto_q += f" ({_title_kw})"
    if _ctry_kw:   _auto_q += f" ({_ctry_kw})"

    _d_query = st.text_input("Dork query — auto-built, override freely",
                              value=_auto_q, key="dork_query")

    _dg1, _dg2 = st.columns([3, 1])
    with _dg1:
        _d_run = st.button("🔍 Search LinkedIn", type="primary", use_container_width=True)
    with _dg2:
        _d_num = st.number_input("# results", 5, 20, 10, step=5, key="dork_num")

    # API availability indicators
    _has_google = bool(
        (st.secrets.get("GOOGLE_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")) and
        (st.secrets.get("GOOGLE_CSE_ID",  "") or os.getenv("GOOGLE_CSE_ID",  ""))
    )
    _has_serper = bool(st.secrets.get("SERPAPI_API_KEY", "") or os.getenv("SERPAPI_API_KEY", ""))
    _has_apollo = bool(st.secrets.get("APOLLO_API_KEY", "") or os.getenv("APOLLO_API_KEY", ""))
    _has_hunter = bool(st.secrets.get("HUNTER_API_KEY", "") or os.getenv("HUNTER_API_KEY", ""))
    _has_lusha  = bool(st.secrets.get("LUSHA_API_KEY",  "") or os.getenv("LUSHA_API_KEY",  ""))

    st.caption(" · ".join([
        "🟢 Google CSE" if _has_google else "⚪ Google CSE (need GOOGLE_API_KEY+GOOGLE_CSE_ID)",
        "🟢 SerpAPI"    if _has_serper else "⚪ SerpAPI",
        "🟢 Apollo"     if _has_apollo else "⚪ Apollo",
        "🟢 Hunter"     if _has_hunter else "⚪ Hunter",
        "🟢 Lusha"      if _has_lusha  else "⚪ Lusha",
    ]))

    # ── Execute search ────────────────────────────────────────────────────────
    def _run_crm_check(profiles: list) -> None:
        """Write CRM fields for a list of profiles to dork_leads."""
        if not (profiles and _MONDAY_OK and monday_active):
            return
        _crm_bar = st.progress(0, text="Checking CRM…")
        for _ci2, _pf2 in enumerate(profiles):
            try:
                _cr = lookup_monday_crm({"name": _pf2["name"], "linkedin": _pf2["url"]})
                _crm_upd: dict = {"linkedin_url": _pf2["url"],
                                  "on_crm": _cr.get("on_crm", False)}
                if _cr.get("on_crm"):
                    _crm_upd.update({
                        "crm_board":       _cr.get("crm_board") or None,
                        "crm_item_id":     str(_cr.get("crm_item_id") or ""),
                        "crm_url":         _cr.get("crm_url") or None,
                        "crm_email":       _cr.get("crm_email") or None,
                        "crm_phone":       _cr.get("crm_phone") or None,
                        "crm_title":       _cr.get("crm_title") or None,
                        "crm_authority":   _cr.get("crm_authority") or None,
                        "crm_heat":        _cr.get("crm_heat") or None,
                        "crm_last_method": _cr.get("crm_last_method") or None,
                        "crm_last_date":   _cr.get("crm_last_date") or None,
                        "crm_notes":       _cr.get("crm_notes") or None,
                        "company":         _cr.get("crm_account_type") or None,
                    })
                _upsert_dork_lead(_crm_upd)
            except Exception:
                pass
            _crm_bar.progress((_ci2 + 1) / len(profiles),
                              text=f"CRM check {_ci2 + 1}/{len(profiles)}…")
        _crm_bar.empty()

    _now_iso = _dt.datetime.now(_dt.timezone.utc).isoformat()

    if _d_run:
        if not _has_google and not _has_serper:
            st.error("Add GOOGLE_API_KEY + GOOGLE_CSE_ID, or SERPAPI_API_KEY to search.")
        else:
            with st.spinner("Searching…"):
                try:
                    _found = _dork_search(_d_query, int(_d_num), start=0)
                    # Clear per-card editable field state from previous search
                    for _k in list(st.session_state.keys()):
                        if _k.startswith("dl_"):
                            del st.session_state[_k]
                    st.session_state["dork_results"] = _found
                    st.session_state["dork_search_start"] = int(_d_num)
                    # Upsert new profiles (preserves existing enrichment)
                    for _pf in _found:
                        _upsert_dork_lead({
                            "linkedin_url":     _pf["url"],
                            "name":             _pf["name"],
                            "job_title":        _pf.get("job_title") or None,
                            "company":          _pf.get("company") or None,
                            "snippet":          _pf.get("snippet") or None,
                            "last_searched_at": _now_iso,
                        })
                    if not _found:
                        st.warning("No LinkedIn profiles found — try broadening the query.")
                except Exception as _de:
                    st.error(f"Search error: {_de}")
                    _found = []
            _run_crm_check(st.session_state.get("dork_results", []))
            st.cache_data.clear()

    # ── Results ───────────────────────────────────────────────────────────────
    _d_profiles = st.session_state.get("dork_results", [])

    if not _d_profiles:
        if not _d_run:
            st.info("Configure a search above and click **🔍 Search LinkedIn**.")
    else:
        # Bulk-load all DB rows for this result set
        _db_cache = _load_dork_leads_bulk(tuple(p["url"] for p in _d_profiles))

        st.markdown(f"**{len(_d_profiles)} profiles**  ·  "
                    f"{sum(1 for p in _d_profiles if (_db_cache.get(p['url']) or {}).get('on_crm'))} on CRM  ·  "
                    f"{sum(1 for p in _d_profiles if (_db_cache.get(p['url']) or {}).get('email'))} with email")
        st.divider()

        for _pi, _prof in enumerate(_d_profiles):
            _pkey   = _prof["url"]
            _db_row = _db_cache.get(_pkey) or {}
            _sk     = f"dl_{_pi}"
            _on_crm = _db_row.get("on_crm")

            with st.container(border=True):
                # ── Header ────────────────────────────────────────────────────
                _ph1, _ph2 = st.columns([5, 2])
                with _ph1:
                    st.markdown(f"### 👤 {_prof['name']}")
                    _rl = [x for x in [
                        _db_row.get("crm_title") or _db_row.get("job_title") or _prof.get("job_title", ""),
                        _db_row.get("company") or _prof.get("company", ""),
                    ] if x]
                    if _rl:
                        st.caption("💼 " + "  ·  ".join(_rl))
                    st.markdown(f"[{_pkey}]({_pkey})")
                    if _prof.get("snippet"):
                        st.caption(_prof["snippet"][:220])
                with _ph2:
                    if _on_crm is None:
                        st.caption("⚪ CRM not checked")
                    elif _on_crm:
                        st.success("✅ On CRM")
                        if _db_row.get("crm_board"):
                            st.caption(_db_row["crm_board"])
                    else:
                        st.warning("❌ Not in CRM")
                    if _db_row.get("monday_leads_item_id"):
                        st.caption(f"📋 Lead #{_db_row['monday_leads_item_id']}")

                st.divider()

                # ── CRM contact panel (if on CRM) ─────────────────────────────
                if _on_crm:
                    def _val(f: str) -> str:
                        v = _db_row.get(f, "")
                        return str(v) if v and str(v) not in ("", "nan", "None") else ""

                    _ci1, _ci2 = st.columns(2)
                    with _ci1:
                        if _val("crm_email"):
                            st.markdown(f"📧 **{_val('crm_email')}**")
                        else:
                            st.caption("📧 Email: not in CRM")
                        if _val("crm_phone"):
                            st.markdown(f"📞 **{_val('crm_phone')}**")
                        else:
                            st.caption("📞 Phone: not in CRM")
                        if _val("crm_title"):
                            st.markdown(f"💼 **{_val('crm_title')}**")
                        # Company — populated from crm_account_type (lookup board)
                        # or the company field stored on the profile
                        _co = _val("company") or _prof.get("company", "")
                        if _co:
                            st.markdown(f"🏢 **{_co}**")
                        if _val("crm_authority"):
                            st.caption(f"Authority: {_val('crm_authority')}")
                    with _ci2:
                        if _val("crm_heat"):
                            st.caption(f"🔥 Heat: {_val('crm_heat')}")
                        _lm = _val("crm_last_method")
                        _ld = _val("crm_last_date")
                        if _lm or _ld:
                            st.caption(f"Last contact: {(_lm + ' ' + _ld).strip()}")
                        if _val("crm_notes"):
                            st.caption(f"📝 {_val('crm_notes')[:130]}")
                        if _db_row.get("crm_url"):
                            st.markdown(f"[Open in Monday →]({_db_row['crm_url']})")
                        # Per-card refresh button
                        if st.button("↻ Refresh from Monday", key=f"{_sk}_crm_refresh",
                                     use_container_width=True):
                            with st.spinner("Checking Monday…"):
                                try:
                                    _rfr = lookup_monday_crm(
                                        {"name": _prof["name"], "linkedin": _pkey})
                                    _rfr_upd: dict = {"linkedin_url": _pkey,
                                                      "on_crm": _rfr.get("on_crm", False)}
                                    if _rfr.get("on_crm"):
                                        _rfr_upd.update({
                                            "crm_board":       _rfr.get("crm_board") or None,
                                            "crm_item_id":     str(_rfr.get("crm_item_id") or ""),
                                            "crm_url":         _rfr.get("crm_url") or None,
                                            "crm_email":       _rfr.get("crm_email") or None,
                                            "crm_phone":       _rfr.get("crm_phone") or None,
                                            "crm_title":       _rfr.get("crm_title") or None,
                                            "crm_authority":   _rfr.get("crm_authority") or None,
                                            "crm_heat":        _rfr.get("crm_heat") or None,
                                            "crm_last_method": _rfr.get("crm_last_method") or None,
                                            "crm_last_date":   _rfr.get("crm_last_date") or None,
                                            "crm_notes":       _rfr.get("crm_notes") or None,
                                            "company": _rfr.get("crm_account_type") or None,
                                        })
                                    _upsert_dork_lead(_rfr_upd)
                                    st.cache_data.clear()
                                    st.rerun()
                                except Exception as _rfe:
                                    st.error(f"Refresh failed: {_rfe}")

                # ── Editable contact fields + enrichment (not on CRM) ─────────
                else:
                    _ef1, _ef2 = st.columns(2)

                    # Init session_state from DB on first render of this card
                    if f"{_sk}_email" not in st.session_state:
                        st.session_state[f"{_sk}_email"]   = _db_row.get("email") or ""
                        st.session_state[f"{_sk}_phone"]   = _db_row.get("phone") or ""
                        st.session_state[f"{_sk}_title"]   = (_db_row.get("job_title") or
                                                               _prof.get("job_title") or "")
                        st.session_state[f"{_sk}_company"] = (_db_row.get("company") or
                                                               _prof.get("company") or "")

                    with _ef1:
                        _edit_email   = st.text_input("📧 Email",     key=f"{_sk}_email")
                        _edit_phone   = st.text_input("📞 Phone",     key=f"{_sk}_phone")
                        _edit_title   = st.text_input("💼 Job Title", key=f"{_sk}_title")
                        _edit_company = st.text_input("🏢 Company",   key=f"{_sk}_company")

                    with _ef2:
                        _conf = int(_db_row.get("confidence") or 0)
                        if _conf > 0:
                            # Show enrichment summary
                            _bar2 = "█" * (_conf // 10) + "░" * (10 - _conf // 10)
                            st.markdown(f"**Confidence: `{_bar2}` {_conf}%**")
                            _esrcs2 = _as_list(_db_row.get("email_sources"))
                            if _esrcs2:
                                st.caption("📧 ↳ " + ", ".join(_esrcs2))
                            _psrcs2 = _as_list(_db_row.get("phone_sources"))
                            if _psrcs2:
                                st.caption("📞 ↳ " + ", ".join(_psrcs2))
                            if _db_row.get("domain"):
                                st.caption(f"Domain: {_db_row['domain']}")
                            _ecands2 = _as_list(_db_row.get("email_candidates"))
                            if _ecands2 and not _db_row.get("email"):
                                st.caption("Pattern guesses:")
                                for _ec2 in _ecands2[:2]:
                                    st.code(_ec2, language=None)
                        else:
                            # No enrichment yet — domain + cascade button
                            _dom_hint2 = st.text_input(
                                "Company domain (helps Hunter)",
                                key=f"{_sk}_dom",
                                placeholder="e.g. nedbank.co.za",
                            )
                            if st.button("🔍 Find contact info", key=f"{_sk}_casc",
                                         use_container_width=True, type="primary"):
                                with st.spinner("Searching across sources…"):
                                    try:
                                        _casc2 = _cascade_find_contact(
                                            _prof["name"], _pkey,
                                            company=_prof.get("company", ""),
                                            domain_hint=_dom_hint2.strip(),
                                        )
                                        _upsert_dork_lead({
                                            "linkedin_url":     _pkey,
                                            "email":            _casc2.get("email"),
                                            "phone":            _casc2.get("phone"),
                                            "job_title":        _casc2.get("title") or _prof.get("job_title"),
                                            "company":          _casc2.get("company") or _prof.get("company"),
                                            "domain":           _casc2.get("domain"),
                                            "email_sources":    json.dumps(_casc2.get("email_sources", [])),
                                            "phone_sources":    json.dumps(_casc2.get("phone_sources", [])),
                                            "confidence":       _casc2.get("confidence", 0),
                                            "email_candidates": json.dumps(_casc2.get("email_candidates", [])),
                                            "last_enriched_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
                                        })
                                        # Reset editable field state so they re-init from DB
                                        for _sf2 in ["email", "phone", "title", "company"]:
                                            st.session_state.pop(f"{_sk}_{_sf2}", None)
                                    except Exception as _ce3:
                                        st.error(f"Cascade failed: {_ce3}")
                                st.cache_data.clear()
                                st.rerun()

                    # ── Save + Push actions ────────────────────────────────────
                    _ba1, _ba2 = st.columns(2)
                    with _ba1:
                        if st.button("💾 Save changes", key=f"{_sk}_save",
                                     use_container_width=True):
                            _upsert_dork_lead({
                                "linkedin_url": _pkey,
                                "email":        _edit_email.strip() or None,
                                "phone":        _edit_phone.strip() or None,
                                "job_title":    _edit_title.strip() or None,
                                "company":      _edit_company.strip() or None,
                            })
                            st.cache_data.clear()
                            st.toast("Saved.")
                    with _ba2:
                        if monday_active:
                            _btn_lbl = ("📋 Update Monday" if _db_row.get("monday_leads_item_id")
                                        else "📋 Add to Monday Leads")
                            if st.button(_btn_lbl, key=f"{_sk}_push",
                                         use_container_width=True, type="primary"):
                                _esrc_str = " → ".join(
                                    _as_list(_db_row.get("email_sources")) +
                                    _as_list(_db_row.get("phone_sources"))
                                ) or "LinkedIn Dork"
                                _push3 = {
                                    "name":           _prof["name"],
                                    "title":          _edit_title,
                                    "company":        _edit_company,
                                    "email":          _edit_email,
                                    "phone":          _edit_phone,
                                    "linkedin":       _pkey,
                                    "accuracy_score": str(int(_db_row.get("confidence") or 0)),
                                    "provider_chain": _esrc_str,
                                }
                                with st.spinner("Syncing to Monday…"):
                                    try:
                                        _mres = sync_lead_to_monday(_push3)
                                        _upsert_dork_lead({
                                            "linkedin_url":         _pkey,
                                            "monday_leads_item_id": str(_mres.get("item_id") or ""),
                                            "email":   _edit_email or None,
                                            "phone":   _edit_phone or None,
                                            "job_title": _edit_title or None,
                                            "company": _edit_company or None,
                                        })
                                        st.cache_data.clear()
                                        st.success(f"{_mres.get('action', 'done').title()} · "
                                                   f"ID: {_mres.get('item_id')}")
                                    except Exception as _pe3:
                                        st.error(f"Push failed: {_pe3}")
                        else:
                            st.caption("Add MONDAY_API_KEY to push")

                # ── Copy ──────────────────────────────────────────────────────
                _dk_email = _db_row.get("crm_email") or _db_row.get("email") or ""
                _dk_phone = _db_row.get("crm_phone") or _db_row.get("phone") or ""
                _dk_title = (_db_row.get("crm_title") or _db_row.get("job_title")
                             or _prof.get("job_title", ""))
                _dk_co    = _db_row.get("company") or _prof.get("company", "")
                _dk_conf  = int(_db_row.get("confidence") or 0)
                _dk_lines = [
                    f"CONTACT: {_prof['name']}",
                    f"Title: {_dk_title}" if _dk_title else "",
                    f"Company: {_dk_co}" if _dk_co else "",
                    f"Email: {_dk_email}" if _dk_email else "",
                    f"Phone: {_dk_phone}" if _dk_phone else "",
                    f"LinkedIn: {_pkey}",
                    f"Confidence: {_dk_conf}%" if _dk_conf else "",
                    (f"CRM: Yes — {_db_row.get('crm_board', '')}") if _on_crm else "CRM: Not found",
                ]
                _copy_block("\n".join(l for l in _dk_lines if l),
                            key=f"dork_copy_{_pi}")

        # ── Next page ─────────────────────────────────────────────────────────
        st.divider()
        _next_start = st.session_state.get("dork_search_start", int(_d_num))
        if st.button(f"➡ Next {int(_d_num)} results  (offset {_next_start})",
                     key="dork_next", use_container_width=True):
            with st.spinner(f"Fetching results {_next_start + 1}–{_next_start + int(_d_num)}…"):
                try:
                    _more = _dork_search(_d_query, int(_d_num), start=_next_start)
                    _existing_urls = {p["url"] for p in st.session_state.get("dork_results", [])}
                    _new_profs = [p for p in _more if p["url"] not in _existing_urls]
                    for _pf3 in _new_profs:
                        _upsert_dork_lead({
                            "linkedin_url":     _pf3["url"],
                            "name":             _pf3["name"],
                            "job_title":        _pf3.get("job_title") or None,
                            "company":          _pf3.get("company") or None,
                            "snippet":          _pf3.get("snippet") or None,
                            "last_searched_at": _now_iso,
                        })
                    st.session_state["dork_results"] = (
                        st.session_state.get("dork_results", []) + _new_profs
                    )
                    st.session_state["dork_search_start"] = _next_start + int(_d_num)
                    _run_crm_check(_new_profs)
                    st.cache_data.clear()
                    if not _new_profs:
                        st.warning("No new profiles found at this offset.")
                except Exception as _ne:
                    st.error(f"Next page error: {_ne}")
            st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# TAB 6 — LEAD INTELLIGENCE
# ══════════════════════════════════════════════════════════════════════════════

# ── Flare.io helpers ──────────────────────────────────────────────────────────
@st.cache_data(ttl=3300)
def _flare_token() -> str | None:
    api_key   = st.secrets.get("FLARE_API_KEY",   "") or os.getenv("FLARE_API_KEY",   "")
    tenant_id = st.secrets.get("FLARE_TENANT_ID", "") or os.getenv("FLARE_TENANT_ID", "")
    if not api_key:
        return None
    try:
        body = json.dumps({"tenant_id": int(tenant_id)}).encode() if tenant_id else b"{}"
        req  = _urlreq.Request(
            "https://api.flare.io/tokens/generate",
            data=body,
            headers={"Authorization": api_key, "Content-Type": "application/json"},
            method="POST",
        )
        with _urlreq.urlopen(req, timeout=15) as r:
            return json.loads(r.read()).get("token")
    except Exception:
        return None


def _flare_search(query: str, event_types: list, days_back: int = 30,
                  size: int = 20) -> list:
    token = _flare_token()
    if not token:
        return []
    from_ts = (_dt.datetime.now(_dt.timezone.utc)
               - _dt.timedelta(days=days_back)).isoformat()
    body = json.dumps({
        "query": {"query_string": query, "type": "query_string"},
        "filter": {
            "types": event_types,
            "estimated_created_at": {"gte": from_ts},
        },
        "size": size,
        "order": "desc",
    }).encode()
    req = _urlreq.Request(
        "https://api.flare.io/global/_search",
        data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with _urlreq.urlopen(req, timeout=25) as r:
        return json.loads(r.read()).get("items", [])


def _news_search(query: str, num: int = 10) -> list:
    """Google/SerpAPI news search. Returns [{title, url, snippet}]."""
    s_key = st.secrets.get("SERPAPI_API_KEY", "") or os.getenv("SERPAPI_API_KEY", "")
    g_key = st.secrets.get("GOOGLE_API_KEY",  "") or os.getenv("GOOGLE_API_KEY",  "")
    g_cse = st.secrets.get("GOOGLE_CSE_ID",   "") or os.getenv("GOOGLE_CSE_ID",   "")
    if s_key:
        url = (f"https://serpapi.com/search?engine=google_news"
               f"&q={_urlparse.quote(query)}&num={num}&api_key={s_key}")
        with _urlreq.urlopen(url, timeout=20) as r:
            data = json.loads(r.read())
        items = data.get("news_results") or data.get("organic_results", [])
        return [{"title": x.get("title",""), "url": x.get("link",""),
                 "snippet": x.get("snippet",""), "date": x.get("date","")}
                for x in items[:num]]
    if g_key and g_cse:
        url = (f"https://www.googleapis.com/customsearch/v1"
               f"?key={g_key}&cx={g_cse}&q={_urlparse.quote(query)}&num={min(num,10)}")
        with _urlreq.urlopen(url, timeout=20) as r:
            items = json.loads(r.read()).get("items", [])
        return [{"title": x.get("title",""), "url": x.get("link",""),
                 "snippet": x.get("snippet",""), "date": ""}
                for x in items]
    return []


def _intel_ai_rate(company: str, country: str, event_type: str,
                   description: str, source_count: int = 1,
                   all_sources: list | None = None,
                   combined_description: str = "") -> dict:
    context = (combined_description or description)[:1200]
    src_line = (f"{source_count} source{'s' if source_count > 1 else ''}: "
                f"{', '.join(all_sources or [])}")
    prompt = f"""You are a sales intelligence AI for CRS (Cyber Retaliator Solutions),
an African IBM Security / Red Hat / SUSE / CompTIA training & distribution partner.

Rate this African company as a CRS lead. Use ALL sources provided — more sources
mean higher confidence. Also extract any named individuals mentioned.

Company: {company}
Country: {country}
Event type: {event_type}
Sources: {src_line}
Cross-referenced context:
{context}

Reply ONLY with valid JSON (no markdown fences):
{{
  "score": <integer 0-100>,
  "sector": "<detected sector, e.g. Banking, Government, Healthcare>",
  "urgency": "<high|medium|low>",
  "crs_solutions": ["solution1", "solution2"],
  "outreach_angle": "<1-2 sentence personalised cold-outreach hook>",
  "rationale": "<2-3 sentences why this is a strong/weak lead for CRS>",
  "persons_mentioned": [{{"name": "Full Name", "title": "Job Title or role"}}]
}}"""
    try:
        raw = _call_ai(prompt)
        raw = re.sub(r"```[a-z]*\n?", "", raw).strip().rstrip("`")
        return json.loads(raw)
    except Exception:
        return {"score": 0, "sector": "", "urgency": "low", "crs_solutions": [],
                "outreach_angle": "", "rationale": "AI rating unavailable.",
                "persons_mentioned": []}


@st.cache_data(ttl=3600)
def _intel_enrich_card(company: str, country: str, description: str) -> dict:
    """Follow-up targeted searches for a specific company to get more context + named people."""
    out: dict = {"snippets": [], "persons": [], "extra_urls": []}
    all_text = description

    # Two passes: incident context + leadership/security contacts
    queries = [
        f'"{company}" ({country} OR Africa) "cyber" OR "breach" OR "ransomware" OR "attack"',
        f'"{company}" {country} CISO OR "IT Director" OR "Head of IT" OR "Chief Security" OR "IT Manager"',
    ]
    seen_urls: set = set()
    for q in queries:
        try:
            for h in _news_search(q, num=5):
                combined = f"{h.get('title','')} {h.get('snippet','')}".strip()
                all_text += "\n" + combined
                u = h.get("url", "")
                if u and u not in seen_urls:
                    seen_urls.add(u)
                    out["snippets"].append({
                        "title":   h.get("title", ""),
                        "url":     u,
                        "snippet": h.get("snippet", ""),
                        "date":    h.get("date", ""),
                    })
                    out["extra_urls"].append(u)
        except Exception:
            pass

    # Also scan African RSS feeds for the specific company
    for _fn, _fu in _AFRICAN_FEEDS.items():
        try:
            _rss_hits = _fetch_rss_feed(
                _fn, _fu,
                keywords=(company.lower(),),
                days_back=90,
            )
            for _rh in _rss_hits[:3]:
                _rt = f"{_rh.get('title','')} {_rh.get('snippet','')}".strip()
                all_text += "\n" + _rt
                u2 = _rh.get("url", "")
                if u2 and u2 not in seen_urls:
                    seen_urls.add(u2)
                    out["snippets"].append({
                        "title":   _rh.get("title", ""),
                        "url":     u2,
                        "snippet": _rh.get("snippet", ""),
                        "date":    _rh.get("date", ""),
                        "source":  _fn,
                    })
        except Exception:
            pass

    out["persons"] = _extract_names(all_text)
    out["snippets"] = out["snippets"][:10]
    return out


def _dedupe_persons(persons: list) -> list:
    """Deduplicate a list of {name, title} dicts by name."""
    seen: set = set()
    result: list = []
    for p in persons:
        n = (p.get("name") or "").strip().lower()
        if n and n not in seen:
            seen.add(n)
            result.append(p)
    return result[:10]


@st.cache_data(ttl=1800)
def _fetch_rss_feed(feed_name: str, feed_url: str,
                    keywords: tuple, days_back: int = 30) -> list:
    """Fetch an RSS/Atom feed and return items matching any keyword."""
    try:
        req = _urlreq.Request(
            feed_url,
            headers={"User-Agent": "CRSIntel/2.0 (cybersecurity research)"},
        )
        with _urlreq.urlopen(req, timeout=12) as r:
            raw = r.read()
        root = _ET.fromstring(raw)
        # Detect Atom vs RSS
        _atom_ns = "http://www.w3.org/2005/Atom"
        is_atom = root.tag.startswith(f"{{{_atom_ns}}}")
        cutoff = (_dt.datetime.now(_dt.timezone.utc)
                  - _dt.timedelta(days=days_back))
        results: list = []
        items = (root.findall(f".//{{{_atom_ns}}}entry")
                 if is_atom else root.findall(".//item"))
        for item in items:
            def _txt(tag: str) -> str:
                el = item.find(tag)
                return (el.text or "").strip() if el is not None else ""

            if is_atom:
                title   = _txt(f"{{{_atom_ns}}}title")
                link_el = item.find(f"{{{_atom_ns}}}link")
                link    = (link_el.get("href", "") if link_el is not None else "")
                desc    = _txt(f"{{{_atom_ns}}}summary") or _txt(f"{{{_atom_ns}}}content")
                pub     = _txt(f"{{{_atom_ns}}}published") or _txt(f"{{{_atom_ns}}}updated")
            else:
                title = _txt("title")
                link  = _txt("link")
                desc  = _txt("description")
                pub   = _txt("pubDate")

            # Strip HTML tags from description
            desc = re.sub(r"<[^>]+>", " ", desc).strip()
            desc = re.sub(r"\s{2,}", " ", desc)

            # Date filter
            pub_date = ""
            if pub:
                try:
                    # ISO format (Atom)
                    pub_dt = _dt.datetime.fromisoformat(pub.replace("Z", "+00:00"))
                    if pub_dt.tzinfo is None:
                        pub_dt = pub_dt.replace(tzinfo=_dt.timezone.utc)
                    if pub_dt < cutoff:
                        continue
                    pub_date = pub_dt.strftime("%Y-%m-%d")
                except ValueError:
                    try:
                        # RFC 2822 (RSS pubDate)
                        from email.utils import parsedate_to_datetime
                        pub_dt = parsedate_to_datetime(pub)
                        if pub_dt.astimezone(_dt.timezone.utc) < cutoff:
                            continue
                        pub_date = pub_dt.strftime("%Y-%m-%d")
                    except Exception:
                        pass

            # Keyword filter
            text_lc = (title + " " + desc).lower()
            if not any(kw in text_lc for kw in keywords):
                continue

            results.append({
                "title":   title,
                "url":     link,
                "snippet": desc[:300],
                "date":    pub_date,
                "source":  feed_name,
            })

        return results
    except Exception:
        return []


def _search_african_feeds(country: str, days_back: int = 30,
                          max_per_feed: int = 3) -> list:
    """Search all African feeds for cyber events mentioning a country."""
    _cyber_kw = (
        "breach", "ransomware", "hack", "cyber", "attack", "leak",
        "credential", "malware", "phishing", "data",
    )
    results: list = []
    for feed_name, feed_url in _AFRICAN_FEEDS.items():
        try:
            items = _fetch_rss_feed(
                feed_name, feed_url,
                keywords=(country.lower(), *_cyber_kw),
                days_back=days_back,
            )
            for item in items[:max_per_feed]:
                # Must mention both the country AND a cyber keyword
                text_lc = (item["title"] + " " + item["snippet"]).lower()
                has_country = country.lower() in text_lc
                has_cyber   = any(k in text_lc for k in _cyber_kw)
                if has_country and has_cyber:
                    results.append(item)
        except Exception:
            pass
    return results


def _extract_company_from_news(title: str, snippet: str, country: str) -> str:
    """Best-effort company name extraction from a news headline or snippet."""
    _stop = {w.lower() for w in country.split()} | {
        "south", "north", "east", "west", "african", "africa", "the", "a", "an",
        "data", "breach", "cyber", "attack", "hack", "ransomware", "leaked",
    }
    for src in (title, snippet):
        for pat in [
            r"^([A-Z][A-Za-z0-9 &',./-]{2,60}?)\s+(?:suffer|hit|target|report|disclose|confirm|face|warn)",
            r"^([A-Z][A-Za-z0-9 &',./-]{2,60}?)\s+(?:data breach|ransomware|cyber attack|hacked|leaked)",
            r"([A-Z][A-Za-z0-9 &',./-]{2,60}?)\s+(?:data breach|ransomware|cyber attack|hacked|leaked)",
            r"(?:breach|attack|hack)\s+at\s+([A-Z][A-Za-z0-9 &',./-]{2,60}?)(?:\s*[,:]|\s*$)",
            r"([A-Z][A-Za-z0-9 &',./-]{2,60}?)\s+(?:customers?|clients?|employees?)\s+(?:data|records?)",
        ]:
            m = re.search(pat, src, re.IGNORECASE)
            if m:
                name = m.group(1).strip().rstrip(" ,-")
                # Strip trailing country-name words
                name_words = [w for w in name.split()
                              if w.lower().rstrip(",:;") not in _stop]
                if name_words:
                    return " ".join(name_words[:6])
    # Fall back to first capitalised run (skip stop words)
    caps = []
    for w in title.split():
        wc = w.rstrip(",:;")
        if wc and wc[0].isupper() and wc.lower() not in _stop:
            caps.append(wc)
        elif caps:
            break
    return " ".join(caps[:5]) if caps else title[:60]


def _extract_names(text: str) -> list:
    """Extract named individuals with titles from incident/news text."""
    _title_words = (
        r"CEO|CTO|CFO|CIO|CISO|COO|MD|Director|Head|Manager|Spokesperson|"
        r"President|Chairman|Secretary|Minister|VP|Executive|Officer|spokesperson"
    )
    seen: set = set()
    results: list = []
    for pat in [
        # "CISO John Smith" / "Director Jane Doe"
        rf'\b({_title_words})\s+([A-Z][a-z]{{2,}}(?:\s+[A-Z][a-z]{{2,}}){{1,2}})',
        # "John Smith, CISO" / "Jane Doe, Director"
        rf'\b([A-Z][a-z]{{2,}}(?:\s+[A-Z][a-z]{{2,}}){{1,2}}),?\s+({_title_words})',
        # "said John Smith" / "told John Smith"
        r'\b(?:said|told|according to|confirmed by)\s+([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,}){1,2})',
    ]:
        for m in re.finditer(pat, text):
            groups = m.groups()
            # Determine which group is the name
            name = groups[1] if len(groups) > 1 and groups[1][0].isupper() else groups[0]
            title_str = groups[0] if name == groups[-1] else (groups[-1] if len(groups) > 1 else "")
            name = name.strip()
            if len(name) < 5 or name.lower() in seen:
                continue
            seen.add(name.lower())
            results.append({"name": name, "title": title_str.strip()})
            if len(results) >= 8:
                break
        if len(results) >= 8:
            break
    return results


# African cybersecurity / tech news RSS feeds
_AFRICAN_FEEDS: dict = {
    "IT Web Security":   "https://itweb.co.za/rss/security.rss",
    "MyBroadband":       "https://mybroadband.co.za/news/category/security/feed/",
    "TechCentral":       "https://techcentral.co.za/feed/",
    "IT News Africa":    "https://itnewsafrica.com/feed/",
    "BusinessTech":      "https://businesstech.co.za/news/feed/",
    "TechCabal":         "https://techcabal.com/feed/",
    "TechPoint Africa":  "https://techpoint.africa/feed/",
    "Daily Maverick":    "https://dailymaverick.co.za/dmx/feed/",
}

# site: restriction for Africa-focused Google pass
_AFRICAN_SITES_GOOGLE = (
    "site:itweb.co.za OR site:mybroadband.co.za OR site:techcentral.co.za "
    "OR site:itnewsafrica.com OR site:businesstech.co.za OR site:techcabal.com "
    "OR site:techpoint.africa OR site:dailymaverick.co.za"
)

_INTEL_COUNTRIES = [
    "South Africa", "Kenya", "Nigeria", "Ghana", "Tanzania", "Uganda",
    "Zambia", "Rwanda", "Botswana", "Namibia", "Zimbabwe", "Malawi",
    "Ethiopia", "Egypt", "Mozambique", "Mauritius", "Lesotho", "Eswatini",
    "Sierra Leone", "The Gambia", "Liberia", "Cameroon", "Senegal",
]

_INTEL_EVENT_TYPES = {
    "Ransomware":         "ransomleak",
    "Credential Leak":    "credential",
    "Dark Web Mention":   "chat_message",
    "Paste / Dump":       "paste",
    "Stealer Log":        "stealer_log",
}

_INTEL_GOOGLE_TERMS = (
    '"data breach" OR "ransomware" OR "cyber attack" OR "hacked" OR '
    '"credential leak" OR "data leak" OR "security incident"'
)

if _page == "🛡️ Lead Intelligence":
    st.subheader("Cyber Event Lead Intelligence")
    st.caption(
        "Surface African companies hit by ransomware, breaches, or dark-web exposure. "
        "AI-rates each as a CRS lead, then lets you find the right contacts."
    )

    _ii1, _ii2, _ii3, _ii4 = st.columns([3, 2, 1, 1])
    with _ii1:
        if st.checkbox("Select all", key="intel_ctry_all"):
            st.session_state["intel_countries"] = _INTEL_COUNTRIES[:]
        elif not st.session_state.get("intel_ctry_all"):
            st.session_state.setdefault("intel_countries",
                                        ["South Africa", "Kenya", "Nigeria", "Ghana"])
        _i_countries = st.multiselect("Countries", _INTEL_COUNTRIES, key="intel_countries")

    with _ii2:
        if st.checkbox("Select all", key="intel_evt_all"):
            st.session_state["intel_evt_types"] = list(_INTEL_EVENT_TYPES.keys())
        elif not st.session_state.get("intel_evt_all"):
            st.session_state.setdefault("intel_evt_types",
                                        ["Ransomware", "Credential Leak", "Dark Web Mention"])
        _i_evt_labels = st.multiselect("Event types", list(_INTEL_EVENT_TYPES.keys()),
                                       key="intel_evt_types")

    with _ii3:
        _i_days = st.selectbox("Days back", [7, 14, 30, 60, 90], index=2, key="intel_days")

    with _ii4:
        _i_per_ctry = st.number_input("Results / country", 3, 20, 5, step=1,
                                      key="intel_per_ctry")

    _i_src_flare  = bool(st.secrets.get("FLARE_API_KEY","")  or os.getenv("FLARE_API_KEY",""))
    _i_src_google = bool(
        (st.secrets.get("SERPAPI_API_KEY","") or os.getenv("SERPAPI_API_KEY","")) or
        (st.secrets.get("GOOGLE_API_KEY","")  and st.secrets.get("GOOGLE_CSE_ID",""))
    )
    st.caption("Sources: " + "  ·  ".join([
        "🟢 Flare.io"    if _i_src_flare  else "⚪ Flare.io (add FLARE_API_KEY)",
        "🟢 Google News" if _i_src_google else "⚪ Google News (add SERPAPI_API_KEY)",
    ]))

    _i_run = st.button("🔍 Find cyber-event leads", type="primary",
                       use_container_width=True, key="intel_run")

    if _i_run:
        if not _i_countries:
            st.warning("Select at least one country.")
        elif not (_i_src_flare or _i_src_google):
            st.error("Add FLARE_API_KEY or SERPAPI_API_KEY to search.")
        else:
            _flare_types = [_INTEL_EVENT_TYPES[l] for l in _i_evt_labels
                            if l in _INTEL_EVENT_TYPES]
            _intel_raw: list = []

            _ipb = st.progress(0, text="Searching…")
            _n_sources = len(_i_countries)
            for _ic_idx, _ic in enumerate(_i_countries):
                _ipb.progress(
                    (_ic_idx + 1) / _n_sources,
                    text=f"Searching {_ic} — Flare · Google · RSS…",
                )

                # ── Flare.io ────────────────────────────────────────────────
                if _i_src_flare and _flare_types:
                    try:
                        _fevts = _flare_search(
                            f'"{_ic}"', _flare_types,
                            days_back=int(_i_days), size=int(_i_per_ctry),
                        )
                        for _fe in _fevts:
                            _meta  = _fe.get("metadata") or _fe
                            _body  = _fe.get("body") or _fe
                            _desc  = str(
                                _body.get("content") or _body.get("text") or
                                _body.get("description") or _meta.get("title") or ""
                            )[:600]
                            _co    = str(
                                _meta.get("source_name") or _meta.get("domain") or
                                _meta.get("company") or "Unknown"
                            )[:120]
                            _etype = str(
                                _meta.get("type") or _meta.get("event_type") or
                                (_flare_types[0] if _flare_types else "unknown")
                            )
                            _intel_raw.append({
                                "company":       _co,
                                "country":       _ic,
                                "event_type":    _etype,
                                "date":          str(_meta.get("estimated_created_at") or
                                                     _meta.get("created_at") or "")[:10],
                                "description":   _desc,
                                "url":           str(_meta.get("url") or
                                                     _meta.get("source_url") or ""),
                                "source":        "Flare.io",
                                "persons_found": _extract_names(_desc),
                            })
                    except Exception as _fe2:
                        st.toast(f"Flare error for {_ic}: {str(_fe2)[:80]}")

                # ── Google News (broad African context) ─────────────────────
                if _i_src_google:
                    try:
                        _gq = f'"{_ic}" Africa {_INTEL_GOOGLE_TERMS}'
                        for _gn in _news_search(_gq, num=int(_i_per_ctry)):
                            _co2      = _extract_company_from_news(
                                _gn["title"], _gn["snippet"], _ic)
                            _full_desc = f"{_gn['title']} — {_gn['snippet']}"
                            _intel_raw.append({
                                "company":       _co2,
                                "country":       _ic,
                                "event_type":    "news",
                                "date":          _gn.get("date", ""),
                                "description":   _full_desc,
                                "url":           _gn["url"],
                                "source":        "Google News",
                                "persons_found": _extract_names(_full_desc),
                            })
                    except Exception as _ge:
                        st.toast(f"Google error for {_ic}: {str(_ge)[:80]}")

                # ── Google — African publications only ──────────────────────
                if _i_src_google:
                    try:
                        _gq2 = f'({_AFRICAN_SITES_GOOGLE}) "{_ic}" {_INTEL_GOOGLE_TERMS}'
                        for _gn2 in _news_search(_gq2, num=int(_i_per_ctry)):
                            _co3      = _extract_company_from_news(
                                _gn2["title"], _gn2["snippet"], _ic)
                            _fd2      = f"{_gn2['title']} — {_gn2['snippet']}"
                            _src_name = (next(
                                (s for s in _AFRICAN_FEEDS
                                 if s.split()[0].lower() in _gn2["url"].lower()),
                                "African Press",
                            ))
                            _intel_raw.append({
                                "company":       _co3,
                                "country":       _ic,
                                "event_type":    "news",
                                "date":          _gn2.get("date", ""),
                                "description":   _fd2,
                                "url":           _gn2["url"],
                                "source":        _src_name,
                                "persons_found": _extract_names(_fd2),
                            })
                    except Exception:
                        pass

                # ── African RSS feeds ────────────────────────────────────────
                try:
                    for _rss_item in _search_african_feeds(
                        _ic, days_back=int(_i_days), max_per_feed=int(_i_per_ctry)
                    ):
                        _rfd = f"{_rss_item['title']} — {_rss_item['snippet']}"
                        _rco = _extract_company_from_news(
                            _rss_item["title"], _rss_item["snippet"], _ic)
                        _intel_raw.append({
                            "company":       _rco,
                            "country":       _ic,
                            "event_type":    "news",
                            "date":          _rss_item.get("date", ""),
                            "description":   _rfd,
                            "url":           _rss_item["url"],
                            "source":        _rss_item.get("source", "RSS"),
                            "persons_found": _extract_names(_rfd),
                        })
                except Exception:
                    pass

            _ipb.empty()

            # ── Cross-reference: group by (company_key, country) ────────────
            _groups: dict = {}
            for _ev in _intel_raw:
                _ck = (_ev["company"].lower()[:35], _ev["country"])
                if _ev["company"] in ("Unknown", ""):
                    continue
                if _ck not in _groups:
                    _groups[_ck] = {
                        "best":         _ev,
                        "sources":      set(),
                        "descriptions": [],
                        "persons":      [],
                    }
                g = _groups[_ck]
                g["sources"].add(_ev["source"])
                g["descriptions"].append(f"[{_ev['source']}] {_ev['description']}")
                g["persons"].extend(_ev.get("persons_found") or [])
                # Keep richest description as the "best" representative
                if len(_ev.get("description", "")) > len(g["best"].get("description", "")):
                    g["best"] = _ev

            # Flatten groups → merged result list, sorted by source count
            _intel_dedup: list = []
            for _ck2, g2 in _groups.items():
                _merged = dict(g2["best"])
                _merged["source_count"]          = len(g2["sources"])
                _merged["all_sources"]           = sorted(g2["sources"])
                _merged["combined_description"]  = "\n".join(g2["descriptions"])[:1500]
                _merged["persons_found"]         = _dedupe_persons(g2["persons"])
                _intel_dedup.append(_merged)

            _intel_dedup.sort(key=lambda x: -x["source_count"])

            st.session_state["intel_results"] = _intel_dedup
            if not _intel_dedup:
                st.warning("No events found — try more countries, a longer date range, or check API keys.")

    # ── Results ───────────────────────────────────────────────────────────────
    _intel_results = st.session_state.get("intel_results", [])

    if not _intel_results:
        if not _i_run:
            st.info("Select countries and event types above, then click **Find cyber-event leads**.")
    else:
        st.markdown(f"**{len(_intel_results)} companies** with recent cyber events")
        st.divider()

        for _ir_idx, _ir in enumerate(_intel_results):
            _ir_key = f"ir_{_ir_idx}"
            _urgency_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(
                st.session_state.get(f"{_ir_key}_urgency", "low"), "⚪")

            _ir_src_count  = _ir.get("source_count", 1)
            _ir_all_srcs   = _ir.get("all_sources", [_ir.get("source", "")])
            _ir_combined   = _ir.get("combined_description", "")

            with st.container(border=True):
                _ch1, _ch2 = st.columns([5, 2])
                with _ch1:
                    st.markdown(f"### {_urgency_icon} {_ir['company']}")
                    # Source-count confidence badge
                    if _ir_src_count > 1:
                        _src_badge_col = "#1565c0" if _ir_src_count >= 3 else "#2e7d32"
                        st.markdown(
                            f"<span style='background:{_src_badge_col};color:#fff;"
                            f"padding:2px 10px;border-radius:10px;font-size:0.8rem;'>"
                            f"✔ {_ir_src_count} sources</span>  "
                            + "  ·  ".join(_ir_all_srcs),
                            unsafe_allow_html=True,
                        )
                    _tags = "  ·  ".join(filter(None, [
                        _ir.get("country", ""),
                        _ir.get("event_type", "").replace("_", " ").title(),
                        _ir.get("date", "")[:10],
                        (f"via {_ir.get('source','')}" if _ir_src_count == 1 else ""),
                    ]))
                    st.caption(_tags)
                    if _ir.get("description"):
                        st.caption(_ir["description"][:280])
                    if _ir.get("url"):
                        st.markdown(f"[Source →]({_ir['url']})")
                with _ch2:
                    _rated = st.session_state.get(f"{_ir_key}_rated")
                    if _rated:
                        _sc = int(_rated.get("score") or 0)
                        _bar3 = "█" * (_sc // 10) + "░" * (10 - _sc // 10)
                        st.markdown(f"**AI Score: `{_bar3}` {_sc}%**")
                        _urg = _rated.get("urgency", "low")
                        st.session_state[f"{_ir_key}_urgency"] = _urg
                        _urg_lbl = {"high": "🔴 High", "medium": "🟡 Medium",
                                    "low": "🟢 Low"}.get(_urg, _urg)
                        st.caption(f"Urgency: {_urg_lbl}")
                        if _rated.get("sector"):
                            st.caption(f"Sector: {_rated['sector']}")
                    else:
                        st.caption("⚪ Not yet rated")
                        if st.button("🤖 Rate lead", key=f"{_ir_key}_rate",
                                     use_container_width=True):
                            with st.spinner("AI rating…"):
                                try:
                                    _r2 = _intel_ai_rate(
                                        _ir["company"], _ir["country"],
                                        _ir["event_type"], _ir["description"],
                                        source_count=_ir_src_count,
                                        all_sources=_ir_all_srcs,
                                        combined_description=_ir_combined,
                                    )
                                    st.session_state[f"{_ir_key}_rated"] = _r2
                                    st.rerun()
                                except Exception as _ae:
                                    st.error(f"AI error: {_ae}")
                    # Enrich button always visible
                    if not st.session_state.get(f"{_ir_key}_enriched"):
                        if st.button("🔎 Enrich card", key=f"{_ir_key}_enrich",
                                     use_container_width=True,
                                     help="Search web for more context, news, and named contacts"):
                            with st.spinner("Searching for more context…"):
                                try:
                                    _enr_data = _intel_enrich_card(
                                        _ir["company"], _ir["country"],
                                        _ir.get("description", ""))
                                    st.session_state[f"{_ir_key}_enriched"] = _enr_data
                                    st.rerun()
                                except Exception as _ene:
                                    st.error(f"Enrichment error: {_ene}")

                # ── AI detail (if rated) ───────────────────────────────────
                _rated2 = st.session_state.get(f"{_ir_key}_rated")
                if _rated2:
                    st.divider()
                    _rd1, _rd2 = st.columns(2)
                    with _rd1:
                        if _rated2.get("crs_solutions"):
                            st.markdown("**CRS solutions:**  " +
                                        "  ".join(f"`{s}`" for s in _rated2["crs_solutions"]))
                        if _rated2.get("outreach_angle"):
                            st.info(_rated2["outreach_angle"])
                    with _rd2:
                        if _rated2.get("rationale"):
                            st.caption(_rated2["rationale"])

                # ── Named persons (from initial search + AI rating) ────────
                _init_persons = _ir.get("persons_found") or []
                _ai_persons   = (_rated2 or {}).get("persons_mentioned") or []
                # Merge, deduplicate by name
                _all_persons: list = []
                _seen_pnames: set  = set()
                for _p in _init_persons + _ai_persons:
                    _pn = (_p.get("name") or "").strip()
                    if _pn and _pn.lower() not in _seen_pnames:
                        _seen_pnames.add(_pn.lower())
                        _all_persons.append(_p)
                if _all_persons:
                    st.divider()
                    st.markdown("**Named individuals mentioned:**")
                    for _np in _all_persons:
                        _np_name  = _np.get("name", "")
                        _np_title = _np.get("title", "")
                        _np_lbl   = f"👤 **{_np_name}**" + (f"  ·  {_np_title}" if _np_title else "")
                        _npc1, _npc2 = st.columns([3, 2])
                        with _npc1:
                            st.markdown(_np_lbl)
                        with _npc2:
                            _np_q = (f'site:linkedin.com/in "{_np_name}" '
                                     f'"{_ir["company"]}" "{_ir["country"]}"')
                            if st.button("🔍 Find on LinkedIn",
                                         key=f"{_ir_key}_np_{_np_name[:20]}",
                                         use_container_width=True):
                                with st.spinner(f"Searching LinkedIn for {_np_name}…"):
                                    try:
                                        _np_profs = _dork_search(_np_q, num=3)
                                        if _np_profs:
                                            # Prepend to contacts list
                                            _existing = st.session_state.get(
                                                f"{_ir_key}_contacts", [])
                                            _new_urls = {p["url"] for p in _existing}
                                            for _np2 in _np_profs:
                                                if _np2["url"] not in _new_urls:
                                                    _existing.append(_np2)
                                                    _upsert_dork_lead({
                                                        "linkedin_url":     _np2["url"],
                                                        "name":             _np2["name"],
                                                        "job_title":        _np_title or _np2.get("job_title"),
                                                        "company":          _ir["company"],
                                                        "last_searched_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
                                                    })
                                            st.session_state[f"{_ir_key}_contacts"] = _existing
                                            st.rerun()
                                        else:
                                            st.toast(f"No LinkedIn profiles found for {_np_name}")
                                    except Exception as _npe:
                                        st.error(f"Search failed: {_npe}")

                # ── Enrichment panel ───────────────────────────────────────
                _enriched = st.session_state.get(f"{_ir_key}_enriched")
                if _enriched:
                    st.divider()
                    # Extra persons from enrichment (merge with already-shown)
                    _enr_persons = [p for p in (_enriched.get("persons") or [])
                                    if p.get("name","").lower() not in _seen_pnames]
                    if _enr_persons:
                        st.markdown("**Additional named individuals (enrichment):**")
                        for _ep in _enr_persons:
                            _ep_name  = _ep.get("name", "")
                            _ep_title = _ep.get("title", "")
                            _epc1, _epc2 = st.columns([3, 2])
                            with _epc1:
                                st.markdown(f"👤 **{_ep_name}**" +
                                            (f"  ·  {_ep_title}" if _ep_title else ""))
                            with _epc2:
                                _ep_q = (f'site:linkedin.com/in "{_ep_name}" '
                                         f'"{_ir["company"]}" "{_ir["country"]}"')
                                if st.button("🔍 Find on LinkedIn",
                                             key=f"{_ir_key}_ep_{_ep_name[:20]}",
                                             use_container_width=True):
                                    with st.spinner(f"Searching for {_ep_name}…"):
                                        try:
                                            _ep_profs = _dork_search(_ep_q, num=3)
                                            if _ep_profs:
                                                _existing2 = st.session_state.get(
                                                    f"{_ir_key}_contacts", [])
                                                _ex_urls2 = {p["url"] for p in _existing2}
                                                for _ep2 in _ep_profs:
                                                    if _ep2["url"] not in _ex_urls2:
                                                        _existing2.append(_ep2)
                                                        _upsert_dork_lead({
                                                            "linkedin_url":     _ep2["url"],
                                                            "name":             _ep2["name"],
                                                            "job_title":        _ep_title or _ep2.get("job_title"),
                                                            "company":          _ir["company"],
                                                            "last_searched_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
                                                        })
                                                st.session_state[f"{_ir_key}_contacts"] = _existing2
                                                st.rerun()
                                        except Exception as _epe:
                                            st.error(f"Search failed: {_epe}")
                    # Extra news snippets
                    _enr_snips = _enriched.get("snippets") or []
                    if _enr_snips:
                        with st.expander(f"📰 {len(_enr_snips)} additional sources", expanded=False):
                            for _es in _enr_snips:
                                st.markdown(f"**[{_es.get('title','—')}]({_es.get('url','#')})**")
                                if _es.get("snippet"):
                                    st.caption(_es["snippet"][:200])
                                if _es.get("date"):
                                    st.caption(_es["date"])
                                st.write("")

                st.divider()

                # ── Contact discovery (LinkedIn dork) ──────────────────────
                _contacts_found = st.session_state.get(f"{_ir_key}_contacts", [])
                if _contacts_found:
                    st.markdown(f"**{len(_contacts_found)} LinkedIn contacts found:**")
                    for _cf_idx, _cf in enumerate(_contacts_found):
                        _cfk = f"{_ir_key}_cf_{_cf_idx}"
                        with st.expander(f"👤 {_cf.get('name','')}  ·  {_cf.get('job_title','')}",
                                         expanded=False):
                            _cx1, _cx2 = st.columns(2)
                            with _cx1:
                                st.markdown(f"[LinkedIn]({_cf['url']})")
                                if _cf.get("company"):
                                    st.caption(f"🏢 {_cf['company']}")
                            with _cx2:
                                _cf_enr = st.session_state.get(f"{_cfk}_enr", {})
                                if _cf_enr.get("email"):
                                    st.markdown(f"📧 **{_cf_enr['email']}**")
                                if _cf_enr.get("phone"):
                                    st.markdown(f"📞 **{_cf_enr['phone']}**")
                                _cf_conf = int(_cf_enr.get("confidence") or 0)
                                if _cf_conf:
                                    st.caption(f"Confidence: {_cf_conf}%")
                            if not _cf_enr:
                                if st.button("🔍 Find contact info",
                                             key=f"{_cfk}_casc", use_container_width=True):
                                    with st.spinner("Enriching…"):
                                        try:
                                            _enr2 = _cascade_find_contact(
                                                _cf["name"], _cf["url"],
                                                company=_cf.get("company", ""))
                                            st.session_state[f"{_cfk}_enr"] = _enr2
                                            _upsert_dork_lead({
                                                "linkedin_url":    _cf["url"],
                                                "name":            _cf["name"],
                                                "job_title":       _cf.get("job_title"),
                                                "company":         _cf.get("company"),
                                                "email":           _enr2.get("email"),
                                                "phone":           _enr2.get("phone"),
                                                "confidence":      _enr2.get("confidence", 0),
                                                "email_sources":   json.dumps(_enr2.get("email_sources", [])),
                                                "phone_sources":   json.dumps(_enr2.get("phone_sources", [])),
                                                "last_searched_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
                                            })
                                            st.rerun()
                                        except Exception as _ee:
                                            st.error(f"Enrichment failed: {_ee}")
                            if monday_active and (_cf_enr.get("email") or _cf.get("url")):
                                if st.button("📋 Push to Monday Leads",
                                             key=f"{_cfk}_push", use_container_width=True,
                                             type="primary"):
                                    _intel_push = {
                                        "name":           _cf["name"],
                                        "title":          _cf.get("job_title", ""),
                                        "company":        _cf.get("company", ""),
                                        "email":          _cf_enr.get("email", ""),
                                        "phone":          _cf_enr.get("phone", ""),
                                        "linkedin":       _cf["url"],
                                        "accuracy_score": str(int(_cf_enr.get("confidence") or 0)),
                                        "provider_chain": "Lead Intelligence",
                                    }
                                    with st.spinner("Pushing…"):
                                        try:
                                            _mr3 = sync_lead_to_monday(_intel_push)
                                            st.success(f"{_mr3.get('action','done').title()} · "
                                                       f"ID: {_mr3.get('item_id')}")
                                        except Exception as _pe4:
                                            st.error(f"Push failed: {_pe4}")

                else:
                    # Find contacts button (no contacts yet)
                    _fc1b, _fc2b = st.columns(2)
                    with _fc1b:
                        _i_title_hint = st.text_input(
                            "Job title to search", value="CISO IT Manager",
                            key=f"{_ir_key}_title_hint",
                            placeholder="CISO, IT Director…")
                    with _fc2b:
                        st.write("")
                        st.write("")
                        if st.button("🔍 Find contacts at this company",
                                     key=f"{_ir_key}_find_contacts",
                                     use_container_width=True, type="primary"):
                            _dork_q2 = (
                                f'site:linkedin.com/in "{_ir["company"]}" '
                                f'({_i_title_hint}) "{_ir["country"]}"'
                            )
                            with st.spinner("Dorking LinkedIn…"):
                                try:
                                    _cprofs = _dork_search(_dork_q2, num=5)
                                    st.session_state[f"{_ir_key}_contacts"] = _cprofs
                                    for _cp2 in _cprofs:
                                        _upsert_dork_lead({
                                            "linkedin_url":     _cp2["url"],
                                            "name":             _cp2["name"],
                                            "job_title":        _cp2.get("job_title"),
                                            "company":          _cp2.get("company") or _ir["company"],
                                            "last_searched_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
                                        })
                                    if not _cprofs:
                                        st.warning("No LinkedIn profiles found — try a different title.")
                                    else:
                                        st.rerun()
                                except Exception as _dce:
                                    st.error(f"Contact search failed: {_dce}")

                # ── Copy ──────────────────────────────────────────────────────
                _ir_rated3 = st.session_state.get(f"{_ir_key}_rated") or {}
                _ir_lines = [
                    f"COMPANY: {_ir['company']}",
                    f"Country: {_ir.get('country', '')}",
                    f"Event: {_ir.get('event_type', '').replace('_', ' ').title()}",
                    f"Date: {_ir.get('date', '')[:10]}" if _ir.get("date") else "",
                    f"Source: {_ir.get('source', '')}",
                    f"Description: {_ir.get('description', '')[:300]}" if _ir.get("description") else "",
                    f"URL: {_ir.get('url', '')}" if _ir.get("url") else "",
                ]
                if _ir_rated3:
                    _ir_lines += [
                        f"AI Score: {_ir_rated3.get('score', '—')}%",
                        f"Urgency: {_ir_rated3.get('urgency', '—')}",
                        f"Sector: {_ir_rated3.get('sector', '—')}",
                        ("Solutions: " + ", ".join(_ir_rated3["crs_solutions"])
                         ) if _ir_rated3.get("crs_solutions") else "",
                        f"Outreach: {_ir_rated3.get('outreach_angle', '')}" if _ir_rated3.get("outreach_angle") else "",
                    ]
                _copy_block("\n".join(l for l in _ir_lines if l),
                            key=f"intel_copy_{_ir_idx}")
