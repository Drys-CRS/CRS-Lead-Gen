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
import urllib.request as _urlreq
import urllib.parse as _urlparse
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

# ─────────────────────────────────────────────────────────────────────────────
# DORK / ENRICHMENT HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _dork_search(query: str, num: int = 10) -> list:
    g_key = st.secrets.get("GOOGLE_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")
    g_cse = st.secrets.get("GOOGLE_CSE_ID", "") or os.getenv("GOOGLE_CSE_ID", "")
    s_key = st.secrets.get("SERPER_API_KEY", "") or os.getenv("SERPER_API_KEY", "")
    raw: list = []
    if g_key and g_cse:
        url = (f"https://www.googleapis.com/customsearch/v1"
               f"?key={g_key}&cx={g_cse}&q={_urlparse.quote(query)}&num={min(num, 10)}")
        with _urlreq.urlopen(url, timeout=20) as r:
            raw = json.loads(r.read()).get("items", [])
    elif s_key:
        req = _urlreq.Request(
            "https://google.serper.dev/search",
            data=json.dumps({"q": query, "num": num}).encode(),
            headers={"X-API-KEY": s_key, "Content-Type": "application/json"},
            method="POST",
        )
        with _urlreq.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
        raw = [{"link": x.get("link", ""), "title": x.get("title", ""),
                "snippet": x.get("snippet", "")} for x in data.get("organic", [])]
    else:
        raise RuntimeError("Set GOOGLE_API_KEY+GOOGLE_CSE_ID or SERPER_API_KEY in secrets")
    profiles = []
    for item in raw:
        u = item.get("link", "")
        if "linkedin.com/in/" not in u.lower():
            continue
        t = item.get("title", "")
        name = re.sub(r"\s*[|–—-].*$", "", t).strip()
        if not name:
            m = re.search(r"linkedin\.com/in/([^/?&#]+)", u)
            name = m.group(1).replace("-", " ").title() if m else "Unknown"
        profiles.append({"name": name, "url": u, "snippet": item.get("snippet", "")})
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


# ─────────────────────────────────────────────────────────────────────────────
# BACKGROUND PULL — module-level so it survives across Streamlit reruns
# ─────────────────────────────────────────────────────────────────────────────
_PULL_STATE: dict = {"status": "idle", "logs": [], "result": None}

def _pull_worker(env_overrides: dict) -> None:
    _PULL_STATE.update({"status": "running", "logs": [], "result": None})
    for k, v in env_overrides.items():
        if not os.environ.get(k):
            os.environ[k] = v
    def _log(m: str) -> None:
        _PULL_STATE["logs"].append(str(m)[:200])
    try:
        import ingest_core as _ic  # type: ignore[import-not-found]
        _ic.init_supabase()
        _ic.init_ai(log=lambda _: None)
        result = _ic.run_all(
            years_back=3, max_score=300, do_partner=True,
            score_time_budget_s=3000, trigger="manual_app", log=_log,
        )
        _PULL_STATE.update({"status": "done", "result": result})
    except Exception as _e:
        _PULL_STATE.update({"status": "failed", "result": {"error": str(_e)}})

# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR — Health check + action buttons only
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    _logo = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "crs_logo.png")
    if os.path.exists(_logo):
        st.image(_logo, width=160)
    st.title("CRS Intelligence")
    st.caption("v2 · scrape on-demand or via nightly schedule")
    st.divider()

    # ── Health Check ──────────────────────────────────────────────────────────
    st.markdown("**Health Check**")

    for part in _provider_status().split(" · "):
        st.caption(part)

    monday_active = _MONDAY_OK and bool(
        st.secrets.get("MONDAY_API_KEY") if hasattr(st, "secrets") else "")
    st.caption("🟢 Monday.com" if monday_active else "⚪ Monday.com (key not set)")

    try:
        _lr = (supabase.table("pipeline_runs").select("run_at,status,tenders_scraped")
               .order("run_at", desc=True).limit(1).execute()).data
        if _lr:
            _r0 = _lr[0]
            _ts = str(_r0.get("run_at", ""))[:16]
            _st = _r0.get("status", "—")
            _dot = "🟢" if _st == "success" else "🔴"
            st.caption(f"{_dot} Last run: {_ts} — {_st}")
            st.caption(f"   Scraped: {_r0.get('tenders_scraped', '—')}")
        else:
            st.caption("⚪ No pipeline runs yet")
    except Exception:
        st.caption("⚪ Pipeline status unavailable")

    st.divider()

    # ── Actions ───────────────────────────────────────────────────────────────
    st.markdown("**Actions**")

    if st.button("🔄 Refresh data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    _ps = _PULL_STATE["status"]
    if st.button("📥 Pull all tenders", use_container_width=True,
                 disabled=(_ps == "running"),
                 help="Scrapes all open & awarded tenders across English-speaking Africa in the background"):
        if _ps != "running":
            _env_ov: dict = {}
            for _k in ("SUPABASE_URL", "SUPABASE_KEY", "GROQ_API_KEY", "CEREBRAS_API_KEY",
                       "OPENROUTER_API_KEY", "GH_PAT", "GITHUB_TOKEN", "NVIDIA_API_KEY",
                       "DEEPSEEK_API_KEY", "GEMINI_API_KEY"):
                if not os.environ.get(_k):
                    _v = st.secrets.get(_k, "")
                    if _v:
                        _env_ov[_k] = _v
            threading.Thread(target=_pull_worker, args=(_env_ov,), daemon=True).start()
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

# ─────────────────────────────────────────────────────────────────────────────
# TABS
# ─────────────────────────────────────────────────────────────────────────────
tab_overview, tab_opps, tab_partners, tab_leads, tab_dork = st.tabs([
    "🏠 Overview", "📢 Opportunities", "🤝 Partners", "✅ Lead Verification", "🔍 LinkedIn Dork",
])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — OVERVIEW
# ══════════════════════════════════════════════════════════════════════════════
with tab_overview:
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
# TAB 2 — OPPORTUNITIES
# ══════════════════════════════════════════════════════════════════════════════
with tab_opps:
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
                    ).eq("id", int(_row["id"])).execute()
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
                            }).eq("id", int(_row["id"])).execute()
                            st.cache_data.clear()
                            st.rerun()
                        except Exception as _se:
                            st.error(f"Scoring failed: {_se}")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — PARTNERS
# ══════════════════════════════════════════════════════════════════════════════
with tab_partners:
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
# TAB 4 — LEAD VERIFICATION
# ══════════════════════════════════════════════════════════════════════════════
with tab_leads:
    st.subheader("Lead Verification")
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
with tab_dork:
    st.subheader("LinkedIn Lead Discovery")
    st.caption(
        "Google-dork LinkedIn profiles matching CRS solutions, "
        "check Monday CRM, and surface reachability data via Apollo / Hunter / Lusha."
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
        _d_titles = st.multiselect("Job titles (OR)", _DORK_TITLES,
                                   default=["CISO", "IT Manager", "Head of IT"], key="dork_titles")
    with _dc3:
        _d_countries = st.multiselect("Countries (OR)", _DORK_COUNTRIES,
                                      default=["South Africa"], key="dork_countries")

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
    _has_serper = bool(st.secrets.get("SERPER_API_KEY", "") or os.getenv("SERPER_API_KEY", ""))
    _has_apollo = bool(st.secrets.get("APOLLO_API_KEY", "") or os.getenv("APOLLO_API_KEY", ""))
    _has_hunter = bool(st.secrets.get("HUNTER_API_KEY", "") or os.getenv("HUNTER_API_KEY", ""))
    _has_lusha  = bool(st.secrets.get("LUSHA_API_KEY",  "") or os.getenv("LUSHA_API_KEY",  ""))

    st.caption(" · ".join([
        "🟢 Google CSE" if _has_google else "⚪ Google CSE (need GOOGLE_API_KEY+GOOGLE_CSE_ID)",
        "🟢 Serper"     if _has_serper else "⚪ Serper",
        "🟢 Apollo"     if _has_apollo else "⚪ Apollo",
        "🟢 Hunter"     if _has_hunter else "⚪ Hunter",
        "🟢 Lusha"      if _has_lusha  else "⚪ Lusha",
    ]))

    # ── Execute search ────────────────────────────────────────────────────────
    if _d_run:
        if not _has_google and not _has_serper:
            st.error("Add GOOGLE_API_KEY + GOOGLE_CSE_ID, or SERPER_API_KEY to search.")
        else:
            with st.spinner("Searching…"):
                try:
                    _found = _dork_search(_d_query, int(_d_num))
                    st.session_state["dork_results"] = _found
                    st.session_state.pop("dork_crm",    None)
                    st.session_state.pop("dork_enrich", None)
                    if not _found:
                        st.warning("No LinkedIn profiles in results — try broadening the query.")
                except Exception as _de:
                    st.error(f"Search error: {_de}")

    # ── Results ───────────────────────────────────────────────────────────────
    _d_profiles = st.session_state.get("dork_results", [])

    if not _d_profiles:
        if not _d_run:
            st.info("Configure a search above and click **🔍 Search LinkedIn**.")
    else:
        st.markdown(f"**{len(_d_profiles)} profiles found**")
        st.divider()

        for _pi, _prof in enumerate(_d_profiles):
            _pkey    = _prof["url"]
            _crm_res = st.session_state.get("dork_crm",    {}).get(_pkey)
            _enr_res = st.session_state.get("dork_enrich", {}).get(_pkey, {})

            with st.container(border=True):
                _ph1, _ph2 = st.columns([5, 2])
                with _ph1:
                    st.markdown(f"### 👤 {_prof['name']}")
                    st.markdown(f"[{_prof['url']}]({_prof['url']})")
                    if _prof.get("snippet"):
                        st.caption(_prof["snippet"][:250])
                with _ph2:
                    # CRM check button / badge
                    if _crm_res is None:
                        if _MONDAY_OK and monday_active:
                            if st.button("🔍 Check CRM", key=f"dcrm_{_pi}",
                                         use_container_width=True):
                                with st.spinner("Checking Monday CRM…"):
                                    try:
                                        _cres = lookup_monday_crm(
                                            {"name": _prof["name"], "linkedin": _prof["url"]})
                                        st.session_state.setdefault("dork_crm", {})[_pkey] = _cres
                                    except Exception as _ce:
                                        st.session_state.setdefault("dork_crm", {})[_pkey] = {
                                            "on_crm": False, "error": str(_ce)}
                                st.rerun()
                        else:
                            st.caption("⚪ Monday not configured")
                    elif _crm_res.get("on_crm"):
                        st.success("✅ On CRM")
                    else:
                        st.warning("❌ Not in CRM")

                # ── CRM detail ────────────────────────────────────────────────
                if _crm_res and _crm_res.get("on_crm"):
                    with st.expander("CRM Details", expanded=True):
                        for _cf in ["crm_board", "crm_title", "contact_title",
                                    "company", "email", "phone", "status"]:
                            _cv = _crm_res.get(_cf)
                            if _cv and str(_cv) not in ("", "nan", "None"):
                                st.markdown(f"**{_cf.replace('_',' ').title()}:** {_cv}")
                        if _crm_res.get("crm_url"):
                            st.markdown(f"[Open in Monday]({_crm_res['crm_url']})")

                # ── Reachability (not on CRM yet) ─────────────────────────────
                elif _crm_res is not None:
                    st.markdown("**Reachability**")
                    _apo = _enr_res.get("apollo")
                    _hun = _enr_res.get("hunter")
                    _lus = _enr_res.get("lusha")

                    # Apollo
                    if _apo is None:
                        if _has_apollo:
                            if st.button("🚀 Enrich with Apollo", key=f"dapo_{_pi}",
                                         use_container_width=True):
                                with st.spinner("Apollo match…"):
                                    try:
                                        _ad = _apollo_match(_prof["name"], _prof["url"])
                                        st.session_state.setdefault("dork_enrich", {}).setdefault(_pkey, {})["apollo"] = _ad
                                    except Exception as _ae:
                                        st.session_state.setdefault("dork_enrich", {}).setdefault(_pkey, {})["apollo"] = {"error": str(_ae)}
                                st.rerun()
                        else:
                            st.caption("⚪ Apollo (add APOLLO_API_KEY)")
                    elif _apo.get("error"):
                        st.caption(f"Apollo ❌ {_apo['error'][:100]}")
                    else:
                        _apo_org = _apo.get("organization") or {}
                        st.markdown("**Apollo:**")
                        for _af, _al in [("email", "Email"), ("title", "Title"),
                                         ("organization_name", "Company"),
                                         ("city", "City"), ("country", "Country")]:
                            _av = _apo.get(_af)
                            if _av:
                                st.markdown(f"  **{_al}:** {_av}")
                        _apo_phones = _apo.get("phone_numbers") or []
                        if _apo_phones:
                            st.markdown(f"  **Phone:** {_apo_phones[0]}")
                        if _apo_org.get("primary_domain"):
                            st.caption(f"Domain: {_apo_org['primary_domain']}")
                        if _apo_org.get("estimated_num_employees"):
                            st.caption(f"Employees: ~{_apo_org['estimated_num_employees']}")

                    # Hunter — needs a company domain
                    _inferred_domain = ""
                    if _apo and not _apo.get("error"):
                        _inferred_domain = (_apo.get("organization") or {}).get("primary_domain", "")

                    if _hun is None and _has_hunter:
                        _dom_in = st.text_input(
                            "Company domain (for Hunter email finder)",
                            value=_inferred_domain,
                            key=f"ddom_{_pi}",
                            placeholder="e.g. nedbank.co.za",
                        )
                        if st.button("📧 Find email (Hunter)", key=f"dhun_{_pi}",
                                     use_container_width=True,
                                     disabled=not bool(_dom_in)):
                            _parts = _prof["name"].split()
                            with st.spinner("Hunter lookup…"):
                                try:
                                    _hd = _hunter_find(
                                        _parts[0] if _parts else "",
                                        _parts[-1] if len(_parts) > 1 else "",
                                        _dom_in,
                                    )
                                    st.session_state.setdefault("dork_enrich", {}).setdefault(_pkey, {})["hunter"] = _hd
                                except Exception as _he:
                                    st.session_state.setdefault("dork_enrich", {}).setdefault(_pkey, {})["hunter"] = {"error": str(_he)}
                            st.rerun()
                    elif _hun and not _hun.get("error"):
                        _he = _hun.get("email")
                        if _he:
                            st.markdown(f"**Hunter email:** `{_he}` (confidence: {_hun.get('score', '—')})")
                    elif _hun and _hun.get("error"):
                        st.caption(f"Hunter ❌ {_hun['error'][:100]}")
                    elif not _has_hunter:
                        st.caption("⚪ Hunter (add HUNTER_API_KEY)")

                    # Lusha
                    if _lus is None and _has_lusha:
                        if st.button("💼 Lusha lookup", key=f"dlus_{_pi}",
                                     use_container_width=True):
                            with st.spinner("Lusha lookup…"):
                                try:
                                    _ld = _lusha_lookup(_prof["url"])
                                    st.session_state.setdefault("dork_enrich", {}).setdefault(_pkey, {})["lusha"] = _ld
                                except Exception as _le:
                                    st.session_state.setdefault("dork_enrich", {}).setdefault(_pkey, {})["lusha"] = {"error": str(_le)}
                            st.rerun()
                    elif _lus and not _lus.get("error"):
                        _le2 = _lus.get("emailAddresses") or []
                        _lp2 = _lus.get("phoneNumbers") or []
                        if _le2:
                            _lem = _le2[0] if isinstance(_le2[0], str) else _le2[0].get("validatedEmail", str(_le2[0]))
                            st.markdown(f"**Lusha email:** `{_lem}`")
                        if _lp2:
                            _lph = _lp2[0] if isinstance(_lp2[0], str) else _lp2[0].get("internationalNumber", str(_lp2[0]))
                            st.markdown(f"**Lusha phone:** `{_lph}`")
                    elif _lus and _lus.get("error"):
                        st.caption(f"Lusha ❌ {_lus['error'][:100]}")
                    elif not _has_lusha:
                        st.caption("⚪ Lusha (add LUSHA_API_KEY)")

                    # Push to Monday Leads
                    if monday_active:
                        st.divider()
                        _apo_phones2 = (_apo or {}).get("phone_numbers") or []
                        _lus_phones2 = (_lus or {}).get("phoneNumbers") or []
                        def _pick_phone(lst):
                            if not lst: return ""
                            p = lst[0]
                            return p if isinstance(p, str) else (p.get("internationalNumber") or "")
                        _push_payload = {
                            "name":           _prof["name"],
                            "title":          (_apo or {}).get("title", ""),
                            "company":        (_apo or {}).get("organization_name", ""),
                            "email":          ((_apo or {}).get("email") or
                                               (_hun or {}).get("email") or
                                               (_lem if _lus and not _lus.get("error") and _le2 else "")),
                            "phone":          (_pick_phone(_apo_phones2) or
                                               _pick_phone(_lus_phones2)),
                            "linkedin":       _prof["url"],
                            "authority":      "",
                            "accuracy_score": "",
                            "provider_chain": "LinkedIn Dork",
                            "country":        (_apo or {}).get("country", ""),
                        }
                        if st.button("📋 Add to Monday Leads", key=f"dpush_{_pi}",
                                     use_container_width=True, type="primary"):
                            with st.spinner("Pushing to Monday…"):
                                try:
                                    _pr = sync_lead_to_monday(_push_payload)
                                    st.success(f"Action: {_pr.get('action')} · ID: {_pr.get('item_id')}")
                                except Exception as _pe:
                                    st.error(f"Push failed: {_pe}")
