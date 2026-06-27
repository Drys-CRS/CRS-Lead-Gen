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
import urllib.error as _urlerr
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

try:
    from streamlit_extras.colored_header import colored_header as _colored_header
    from streamlit_extras.metric_cards import style_metric_cards as _style_metric_cards
    _EXTRAS_OK = True
except ImportError:
    _EXTRAS_OK = False
    def _colored_header(label="", description="", color_name="blue-70", **_kw):
        st.subheader(label)
        if description:
            st.caption(description)
    def _style_metric_cards(**_kw):
        pass

st.set_page_config(page_title="CRS Intelligence", page_icon="🛡️", layout="wide")

# ── Global UI polish ──────────────────────────────────────────────────────────
st.markdown("""
<style>
/* ── Cards — rounded corners + lift on hover ─────────────────────────── */
div[data-testid="stVerticalBlockBorderWrapper"] {
    border-radius: 12px !important;
    box-shadow: 0 1px 4px rgba(0,0,0,0.08) !important;
    transition: box-shadow 0.2s ease, transform 0.15s ease !important;
}
div[data-testid="stVerticalBlockBorderWrapper"]:hover {
    box-shadow: 0 4px 16px rgba(0,0,0,0.14) !important;
    transform: translateY(-1px) !important;
}

/* ── Metric containers ───────────────────────────────────────────────── */
div[data-testid="metric-container"] {
    border-radius: 10px !important;
    padding: 0.75rem 1rem !important;
    background: rgba(99, 102, 241, 0.06) !important;
    border: 1px solid rgba(99, 102, 241, 0.15) !important;
}
div[data-testid="metric-container"] label {
    font-size: 0.75rem !important;
    letter-spacing: 0.04em !important;
    text-transform: uppercase !important;
}

/* ── Buttons — rounder + smooth hover ───────────────────────────────── */
div.stButton > button {
    border-radius: 8px !important;
    font-weight: 500 !important;
    transition: all 0.15s ease !important;
}
div.stButton > button:hover {
    transform: translateY(-1px) !important;
    box-shadow: 0 4px 12px rgba(0,0,0,0.18) !important;
}
div.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%) !important;
    border: none !important;
    color: #fff !important;
}
div.stButton > button[kind="primary"]:hover {
    background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%) !important;
}

/* ── Expanders — tighter radius ─────────────────────────────────────── */
div[data-testid="stExpander"] > details {
    border-radius: 10px !important;
    overflow: hidden !important;
}
div[data-testid="stExpander"] > details > summary {
    border-radius: 10px !important;
    padding: 0.6rem 0.8rem !important;
    font-weight: 500 !important;
}

/* ── Inputs / selects ────────────────────────────────────────────────── */
div[data-testid="stTextInput"] > div > div > input,
div[data-testid="stTextArea"] > div > div > textarea {
    border-radius: 8px !important;
}
div[data-baseweb="select"] > div {
    border-radius: 8px !important;
}

/* ── Sidebar — slightly deeper background ────────────────────────────── */
section[data-testid="stSidebar"] {
    border-right: 1px solid rgba(100, 116, 139, 0.18) !important;
}
section[data-testid="stSidebar"] .stButton > button {
    border-radius: 8px !important;
    text-align: left !important;
    justify-content: flex-start !important;
}

/* ── Dataframe ───────────────────────────────────────────────────────── */
div[data-testid="stDataFrame"] > div {
    border-radius: 10px !important;
    overflow: hidden !important;
}

/* ── Tabs (st.tabs) ─────────────────────────────────────────────────── */
div[data-testid="stTabs"] > div > div[role="tablist"] {
    gap: 4px !important;
}
button[role="tab"] {
    border-radius: 8px 8px 0 0 !important;
    font-weight: 500 !important;
}

/* ── Caption style ───────────────────────────────────────────────────── */
div[data-testid="stCaptionContainer"] p {
    font-size: 0.8rem !important;
    opacity: 0.75 !important;
}

/* ── Code blocks (copy panels) ───────────────────────────────────────── */
div[data-testid="stCode"] {
    border-radius: 8px !important;
}
div[data-testid="stCode"] pre {
    border-radius: 8px !important;
}
</style>
""", unsafe_allow_html=True)

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
    "GitHub": 150, "NVIDIA": 40, "DeepSeek": 500, "Gemini": 20, "HF": 1000,
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

@st.cache_resource
def _init_hf():
    token = st.secrets.get("HF_TOKEN", "") or os.getenv("HF_TOKEN", "")
    if not token:
        return None
    try:
        from huggingface_hub import InferenceClient
        return InferenceClient(token=token)
    except ImportError:
        return None

gemini_ai     = _init_gemini()
groq_ai       = _init_groq()
cerebras_ai   = _init_cerebras()
openrouter_ai = _init_openrouter()
github_ai     = _init_github()
nvidia_ai     = _init_nvidia()
deepseek_ai   = _init_deepseek()
hf_ai         = _init_hf()

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

def _call_hf(prompt: str) -> str:
    r = hf_ai.chat_completion(
        model="Qwen/Qwen2.5-7B-Instruct",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1024,
    )
    return _clean(r.choices[0].message.content)

def _hf_embed(text: str) -> list:
    """Generate 384-dim embedding using all-MiniLM-L6-v2. Returns [] on failure."""
    if not hf_ai:
        return []
    try:
        resp = hf_ai.feature_extraction(
            text[:2000],
            model="sentence-transformers/all-MiniLM-L6-v2",
        )
        # resp may be nested list (batch) or flat list
        flat = resp[0] if (resp and isinstance(resp[0], (list, float))) else resp
        if isinstance(flat[0], list):
            flat = flat[0]
        return [float(x) for x in flat[:384]]
    except Exception:
        return []

_TENDER_CATEGORIES = [
    "IT security software", "cybersecurity training", "IT hardware",
    "networking & connectivity", "cloud services", "managed services",
    "compliance & audit", "software development", "other IT & telecoms",
]

def _hf_classify_tender(text: str) -> str:
    """Zero-shot classify a tender into a CRS-relevant category. Returns '' on failure."""
    if not hf_ai:
        return ""
    try:
        result = hf_ai.zero_shot_classification(
            text[:512],
            labels=_TENDER_CATEGORIES,
            model="facebook/bart-large-mnli",
        )
        labels = result.get("labels") if isinstance(result, dict) else getattr(result, "labels", [])
        return labels[0] if labels else ""
    except Exception:
        return ""

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
    if hf_ai         and _ok("HF"):         providers.append(("HF",         _call_hf))
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
        "🟢 HF"         if hf_ai          else "⚪ HF",
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
def _sb_execute(query, retries: int = 2):
    """Execute a Supabase query with one retry on HTTP/2 connection drop."""
    import time as _time
    for attempt in range(retries):
        try:
            return query.execute()
        except Exception as _e:
            if attempt < retries - 1:
                _time.sleep(1.5)
            else:
                raise

@st.cache_data(ttl=300)
def _load_tenders() -> pd.DataFrame:
    r = _sb_execute(supabase.table("sa_tenders").select("*")
         .neq("is_irrelevant", True)
         .order("closing_date", desc=False).limit(1000))
    return pd.DataFrame(r.data or [])

@st.cache_data(ttl=300)
def _load_awarded() -> pd.DataFrame:
    r = _sb_execute(supabase.table("awarded_tenders").select("*")
         .order("created_at", desc=True).limit(2000))
    return pd.DataFrame(r.data or [])

@st.cache_data(ttl=300)
def _load_partner_history() -> pd.DataFrame:
    r = _sb_execute(supabase.table("partner_recommendation_history").select("*")
         .order("run_at", desc=True).limit(500))
    return pd.DataFrame(r.data or [])

@st.cache_data(ttl=300)
def _load_lead_verifications() -> pd.DataFrame:
    r = _sb_execute(supabase.table("lead_verification_log").select("*")
         .order("run_at", desc=True).limit(500))
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

def _copy_block(text: str, label: str = "📋 Copy", key: str = "",
                flat: bool = False) -> None:
    """Copyable code block. flat=True skips the expander (use when already inside one)."""
    if flat:
        st.code(text.strip(), language=None)
    else:
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


# ── Apollo REST helpers ────────────────────────────────────────────────────────

def _apollo_key() -> str:
    return st.secrets.get("APOLLO_API_KEY", "") or os.getenv("APOLLO_API_KEY", "")


def _apollo_post(endpoint: str, payload: dict) -> dict:
    key = _apollo_key()
    if not key:
        raise RuntimeError("APOLLO_API_KEY not configured")
    # Truncate any company/keyword strings that can trigger Cloudflare 520
    _clean = {}
    for k, v in payload.items():
        if isinstance(v, str) and len(v) > 120:
            _clean[k] = v[:120]
        else:
            _clean[k] = v
    body_with_key = {**_clean, "api_key": key}
    req = _urlreq.Request(
        f"https://api.apollo.io/api/v1/{endpoint}",
        data=json.dumps(body_with_key).encode(),
        headers={"Content-Type": "application/json",
                 "Cache-Control": "no-cache", "X-Api-Key": key},
        method="POST",
    )
    try:
        with _urlreq.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except _urlerr.HTTPError as e:
        body = ""
        try: body = e.read().decode("utf-8", errors="ignore")[:300]
        except Exception: pass
        if e.code == 520:
            raise RuntimeError(
                "Apollo 520: Cloudflare error — try a shorter or simpler company name"
            ) from e
        raise RuntimeError(f"Apollo {e.code}: {body or e.reason}") from e


def _apollo_match(name: str = "", linkedin_url: str = "",
                  company: str = "", email: str = "",
                  apollo_id: str = "") -> dict:
    """People enrichment — 1 credit per matched person."""
    # reveal_phone_number requires a webhook URL (async delivery) — not usable
    # in a synchronous Streamlit call, so we omit it and extract whatever phone
    # data Apollo returns naturally in phone_numbers / mobile_phone.
    payload: dict = {"reveal_personal_emails": True}
    if apollo_id:
        # Apollo ID is sufficient — don't also send potentially obfuscated
        # name/company strings, which cause a 400 Bad Request.
        payload["id"] = apollo_id
    else:
        if name:         payload["name"]              = name
        if linkedin_url: payload["linkedin_url"]      = linkedin_url
        if company:      payload["organization_name"] = company
        if email:        payload["email"]             = email
    return _apollo_post("people/match", payload).get("person") or {}


def _enrich_contact(apollo_id: str = "", name: str = "",
                    linkedin: str = "", company: str = "") -> dict:
    """Enrich via Apollo people/match (reveals email + phone).
    Returns full _norm_apollo dict plus sources list and optional _apollo_err."""
    result: dict = {"name": "", "email": "", "work_email": "", "personal_email": "",
                    "phone": "", "sources": []}
    try:
        raw = _apollo_match(apollo_id=apollo_id, name=name,
                            linkedin_url=linkedin, company=company)
        n = _norm_apollo(raw)
        result.update(n)   # carry through all org/company fields
        if n.get("name") and "***" not in n["name"]:
            result["name"] = n["name"]
        if n.get("email"):
            result["sources"].append("Apollo")
        if n.get("phone"):
            result["sources"].append("Apollo (phone)")
    except Exception as _ae:
        result["_apollo_err"] = str(_ae)
    return result


_APOLLO_REVEALED_LIST = "CRS Revealed"


def _apollo_reveal_and_save(apollo_id: str) -> dict:
    """Full reveal + save to Apollo CRM list.
    people/match (email + inline phone) → POST /contacts with label 'CRS Revealed'.
    Returns {"person": norm_dict, "contact": raw_dict, "error": str}"""
    result: dict = {"person": {}, "contact": {}, "error": ""}
    if not apollo_id:
        result["error"] = "No Apollo ID"
        return result

    # Reveal: people/match costs 1 export credit; gets work email + personal emails.
    try:
        raw = _apollo_post("people/match", {
            "id": apollo_id,
            "reveal_personal_emails": True,
        })
        person_raw = raw.get("person") or {}
        n = _norm_apollo(person_raw)
        result["person"] = n
    except Exception as _e:
        result["error"] = f"Reveal failed: {_e}"
        return result

    # Save to Apollo CRM contacts + label — no extra export credit.
    try:
        name_parts = (n.get("name") or "").split(" ", 1)
        contact_payload: dict = {"label_names": [_APOLLO_REVEALED_LIST]}
        if name_parts:             contact_payload["first_name"]        = name_parts[0]
        if len(name_parts) > 1:    contact_payload["last_name"]         = name_parts[1]
        em = n.get("work_email") or n.get("email") or ""
        if em:                     contact_payload["email"]             = em
        if n.get("company"):       contact_payload["organization_name"] = n["company"]
        if n.get("title"):         contact_payload["title"]             = n["title"]
        if n.get("linkedin"):      contact_payload["linkedin_url"]      = n["linkedin"]
        if n.get("phone"):         contact_payload["direct_phone"]      = n["phone"]
        resp = _apollo_post("contacts", contact_payload)
        result["contact"] = resp.get("contact") or {}
    except Exception as _e:
        result["error"] = f"Saved reveal but list-save failed: {_e}"

    return result


def _apollo_list_contacts(list_name: str = _APOLLO_REVEALED_LIST,
                           per_page: int = 25, page: int = 1) -> tuple:
    """Return (contacts_list, total_count) for the named Apollo label/list."""
    try:
        resp = _apollo_post("contacts/search", {
            "label_names": [list_name],
            "per_page": per_page,
            "page": page,
        })
        total = int((resp.get("pagination") or {}).get("total_entries", 0) or 0)
        return (resp.get("contacts") or []), total
    except Exception:
        return [], 0


@st.cache_data(ttl=300)
def _apollo_credits() -> dict:
    """Fetch Apollo credit balance from /users/api_profile. Cached 5 min."""
    key = _apollo_key()
    if not key:
        return {}
    req = _urlreq.Request(
        "https://api.apollo.io/api/v1/users/api_profile?include_credit_usage=true",
        headers={"X-Api-Key": key, "Cache-Control": "no-cache",
                 "Content-Type": "application/json"},
        method="GET",
    )
    try:
        with _urlreq.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
    except Exception:
        return {}
    # API returns data at top level (no "user" wrapper).
    # Actual field names from the v1 API:
    lead_left  = int(data.get("num_credits_remaining") or 0)
    lead_total = int(data.get("effective_num_lead_credits") or 0)
    lead_used  = int(data.get("num_lead_credits_used") or 0)
    dial_left  = int(data.get("effective_num_direct_dial_credits") or 0)
    dial_used  = int(data.get("num_direct_dial_credits_used") or 0)
    return {
        "lead_left":  lead_left,
        "lead_total": lead_total,
        "lead_used":  lead_used,
        "dial_left":  dial_left,
        "dial_used":  dial_used,
    }


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


# ── Contact lookup helpers ────────────────────────────────────────────────────

def _apollo_search_people(name: str = "", company: str = "",
                           num: int = 5, titles: list = None,
                           locations: list = None,
                           org_id: str = "", domain: str = "") -> list:
    """Search Apollo people. Uses org ID > domain > company keyword, in that order."""
    payload: dict = {"per_page": min(num, 25), "page": 1}
    # Company scoping — use the most precise filter available
    if org_id:
        payload["organization_ids"] = [org_id]
    elif domain:
        _d = domain.replace("https://", "").replace("http://", "").split("/")[0].strip()
        if _d:
            payload["q_organization_domains_list"] = [_d]
    elif company:
        payload["q_keywords"] = company[:120]
    # Name keyword (on top of company filter)
    if name:
        payload["q_keywords"] = (payload.get("q_keywords", "") + " " + name).strip()
    if titles:    payload["person_titles"]    = titles
    if locations: payload["person_locations"] = locations
    return _apollo_post("mixed_people/api_search", payload).get("people") or []


def _apollo_search_companies(keywords: str = "", locations: list = None,
                              employee_ranges: list = None,
                              industries: list = None,
                              intent_topics: list = None,
                              intent_scores: list = None,
                              page: int = 1,
                              num: int = 25) -> tuple[list, int]:
    """Search Apollo for organizations. Returns (orgs list, total_count)."""
    payload: dict = {"per_page": min(num, 25), "page": page}
    if keywords:        payload["q_keywords"]                        = keywords
    if locations:       payload["organization_locations"]            = locations
    if employee_ranges: payload["organization_num_employees_ranges"] = employee_ranges
    if industries:      payload["q_organization_keyword_tags"]       = industries
    if intent_topics:   payload["q_organization_intent_topics"]      = intent_topics
    if intent_scores:   payload["organization_intent_scores"]        = intent_scores
    resp = _apollo_post("mixed_companies/search", payload)
    total = int(resp.get("pagination", {}).get("total_entries", 0) or 0)
    return (resp.get("organizations") or []), total


def _norm_org(o: dict) -> dict:
    """Flatten an Apollo organization dict into a standard company dict."""
    tech_raw = o.get("technologies") or []
    tech_names = [
        (t.get("name") or t.get("uid") or "")
        for t in tech_raw if isinstance(t, dict)
    ]
    return {
        "id":          o.get("id", ""),
        "name":        o.get("name", ""),
        "domain":      o.get("primary_domain") or o.get("website_url", ""),
        "industry":    o.get("industry", ""),
        "employees":   o.get("estimated_num_employees"),
        "country":     o.get("country", ""),
        "city":        o.get("city", ""),
        "phone":       o.get("phone", ""),
        "linkedin":    o.get("linkedin_url", ""),
        "description": o.get("short_description", ""),
        "keywords":    o.get("keywords") or [],
        "tech":        [t for t in tech_names if t],
    }


# ── Tech-stack → CRS opportunity map ─────────────────────────────────────────
# Keys are lowercase substrings matched against Apollo technology names.
# Values: crs_fit bonus (added to base score) + opportunity text + solution tag.
_TECH_OPP: dict[str, dict] = {
    # Active security tooling → overlay / upgrade opportunities
    "crowdstrike":     {"pts": 22, "sol": "VECTRA AI",         "why": "EDR in place → VECTRA NDR/XDR network layer gap"},
    "sentinelone":     {"pts": 20, "sol": "VECTRA AI",         "why": "EDR buyer → VECTRA AI XDR overlay"},
    "cylance":         {"pts": 18, "sol": "VECTRA AI",         "why": "Legacy AV → VECTRA AI NDR upgrade"},
    "carbon black":    {"pts": 18, "sol": "VECTRA AI",         "why": "VMware Carbon Black → VECTRA AI"},
    "microsoft defender": {"pts": 15, "sol": "VECTRA AI / Todyl", "why": "MS Defender → VECTRA ITDR + Todyl SIEM"},
    "palo alto":       {"pts": 20, "sol": "Todyl SASE",        "why": "NGFW/Prisma → Todyl SASE consolidation"},
    "fortinet":        {"pts": 18, "sol": "Todyl SASE",        "why": "FortiGate → Todyl SASE/SIEM upgrade"},
    "checkpoint":      {"pts": 18, "sol": "Todyl SASE",        "why": "CheckPoint → Todyl SASE consolidation"},
    "cisco meraki":    {"pts": 15, "sol": "Todyl SASE",        "why": "Cisco → Todyl SASE modernisation"},
    "splunk":          {"pts": 22, "sol": "Todyl MXDR",        "why": "Splunk SIEM → Todyl MXDR cost reduction"},
    "qradar":          {"pts": 22, "sol": "Todyl / IBM training", "why": "QRadar → IBM training + Todyl SIEM"},
    "arcsight":        {"pts": 18, "sol": "Todyl MXDR",        "why": "Legacy SIEM → Todyl MXDR"},
    "qualys":          {"pts": 22, "sol": "vRx / Strobes",     "why": "Vuln scanner → vRx patch mgmt + Strobes CTEM"},
    "tenable":         {"pts": 22, "sol": "vRx / Strobes",     "why": "Tenable → vRx/Strobes CTEM upgrade"},
    "nessus":          {"pts": 20, "sol": "vRx / Strobes",     "why": "Nessus → vRx patch management"},
    "rapid7":          {"pts": 18, "sol": "Strobes PTaaS",     "why": "Rapid7 VM → Strobes PTaaS"},
    "github":          {"pts": 18, "sol": "Aikido / BlueFlag", "why": "GitHub repos → Aikido DevSecOps + BlueFlag SDLC"},
    "gitlab":          {"pts": 18, "sol": "Aikido / BlueFlag", "why": "GitLab → Aikido SAST/DAST + BlueFlag"},
    "jira":            {"pts": 12, "sol": "Aikido",            "why": "Dev team → Aikido AppSec integration"},
    "jenkins":         {"pts": 15, "sol": "Aikido",            "why": "CI/CD pipeline → Aikido DevSecOps scanning"},
    "aws":             {"pts": 15, "sol": "Aikido / Strobes",  "why": "AWS cloud → Aikido CSPM + Strobes ASM"},
    "azure":           {"pts": 15, "sol": "Aikido / Strobes",  "why": "Azure → Aikido CSPM + Strobes ASM"},
    "google cloud":    {"pts": 12, "sol": "Aikido",            "why": "GCP → Aikido CSPM"},
    "okta":            {"pts": 15, "sol": "VECTRA ITDR",       "why": "Okta IAM → VECTRA ITDR identity threat layer"},
    "active directory":{"pts": 12, "sol": "VECTRA ITDR",       "why": "AD env → VECTRA ITDR lateral movement detection"},
    "sailpoint":       {"pts": 15, "sol": "VECTRA ITDR",       "why": "IGA in place → VECTRA ITDR complement"},
    "cyberark":        {"pts": 18, "sol": "VECTRA ITDR",       "why": "PAM user → VECTRA ITDR + BlueFlag"},
    "office 365":      {"pts": 12, "sol": "Standss SendGuard", "why": "O365 email → SendGuard GRC + DLP"},
    "microsoft 365":   {"pts": 12, "sol": "Standss SendGuard", "why": "M365 → SendGuard confirm-before-send"},
    "salesforce":      {"pts": 10, "sol": "Panorays",          "why": "SaaS-heavy → Panorays 3rd-party risk"},
    "servicenow":      {"pts": 10, "sol": "Panorays / Telivy", "why": "Enterprise ITSM → Telivy audit + Panorays TPRM"},
    "vmware":          {"pts": 12, "sol": "BeachheadSecure",   "why": "VMware VMs → BeachheadSecure endpoint encryption"},
    "bitlocker":       {"pts": 10, "sol": "BeachheadSecure",   "why": "BitLocker → BeachheadSecure RiskResponder upgrade"},
    "knowbe4":         {"pts": 18, "sol": "GoldPhish",         "why": "Phishing training → GoldPhish replacement/supplement"},
    "proofpoint":      {"pts": 15, "sol": "Standss / GoldPhish", "why": "Proofpoint → Standss email GRC + GoldPhish"},
    "red hat":         {"pts": 12, "sol": "IBM/Red Hat training", "why": "Red Hat infra → Red Hat/IBM training demand"},
    "ansible":         {"pts": 10, "sol": "Red Hat training",  "why": "Ansible → Red Hat Ansible training"},
    "openshift":       {"pts": 12, "sol": "Red Hat training",  "why": "OpenShift platform → Red Hat training"},
}


def _score_org_for_crs(
    industry: str, country: str, employees: int | None, tech: list[str],
    keywords: list[str] | None = None, description: str = "",
) -> tuple[int, list[str], list[str], str]:
    """Returns (score 0-100, matched_tech_names, opportunity_angles, rationale).

    Scoring bands:
      Sector fit  : 0 / 14 (medium) / 28 (strong)
      Geography   : 0 / 6 (non-Africa) / 18 (Africa)
      Size        : 0 / 8 (SMB <50) / 14 (50-500) / 10 (501-5k) / 6 (>5k)
      Tech stack  : 0-30 (additive from _TECH_OPP)
    Max theoretical = 28 + 18 + 14 + 30 = 90 (capped at 100)
    """
    score   = 0
    matched: list[str] = []
    angles:  list[str] = []
    reason: list[str] = []

    ind  = (industry or "").lower()
    ctr  = (country  or "").lower()
    emp  = employees or 0
    kws  = " ".join((k or "").lower() for k in (keywords or []))
    desc = (description or "").lower()
    # Combined text used for sector matching — richer than industry alone
    combined = f"{ind} {kws} {desc}"

    # ── Sector fit ─────────────────────────────────────────────────────────
    _STRONG_EXT = _CRS_STRONG_SECTORS | {
        # Apollo-style industry labels that are strong CRS fits
        "computer & network", "network security", "cybersecurity",
        "cyber security", "information security", "security software",
        "it security", "managed security", "computer security",
        "government administration", "government relations",
        "financial services", "capital markets", "investment management",
        "insurance", "banking", "hospital & health", "health care",
        "oil & energy", "oil & gas", "electric power", "utilities",
    }
    _MEDIUM_EXT = _CRS_MEDIUM_SECTORS | {
        "software", "internet", "computer", "it service", "ict",
        "saas", "cloud computing", "managed service", "consulting",
        "professional service", "information technology",
        "wireless", "mobile", "semiconductor", "e-learning",
        "e-commerce", "outsourcing",
    }

    if any(sk in combined for sk in _STRONG_EXT):
        score += 28
        _hit = next((sk for sk in _STRONG_EXT if sk in combined), "")
        reason.append(f"Strong-fit sector ({industry or _hit})")
    elif any(sk in combined for sk in _MEDIUM_EXT):
        score += 14
        reason.append(f"Moderate-fit sector ({industry or 'technology'})")
    else:
        reason.append("Sector not a primary CRS target")

    # ── Geography ──────────────────────────────────────────────────────────
    _AFRICAN = {
        "south africa", "nigeria", "kenya", "ghana", "tanzania",
        "uganda", "zimbabwe", "zambia", "botswana", "namibia",
        "rwanda", "ethiopia", "mozambique", "senegal", "ivory coast",
        "egypt", "mauritius", "madagascar", "cameroon", "sierra leone",
        "the gambia", "liberia", "malawi", "lesotho", "eswatini",
        "angola", "democratic republic of the congo", "cote d'ivoire",
        "gabon", "niger", "mali", "burkina faso", "benin", "togo",
    }
    if ctr in _AFRICAN:
        score += 18
        reason.append(f"African HQ — {country}")
    elif "africa" in ctr or "african" in ctr:
        # Catches "South African", "East Africa", etc.
        score += 18
        reason.append("African region")
    elif ctr:
        score += 6
        reason.append(f"Non-African HQ ({country})")
    else:
        reason.append("Location unknown")

    # ── Company size (CRS sweet spot 50–5 000 employees) ──────────────────
    if 50 <= emp <= 500:
        score += 14
        reason.append(f"{emp:,} employees — ideal SMB/mid-market range")
    elif 501 <= emp <= 5_000:
        score += 10
        reason.append(f"{emp:,} employees — enterprise account")
    elif emp > 5_000:
        score += 6
        reason.append(f"{emp:,} employees — large enterprise")
    elif 10 <= emp < 50:
        score += 8
        reason.append(f"{emp:,} employees — small business")
    else:
        reason.append("Employee count unknown")

    # ── Tech-stack signals ─────────────────────────────────────────────────
    tech_lower = [t.lower() for t in tech]
    added_pts  = 0
    seen_sols: set[str] = set()
    for kw, opp in _TECH_OPP.items():
        if any(kw in t for t in tech_lower):
            matched.append(kw.title())
            if opp["sol"] not in seen_sols:
                angles.append(f"{opp['sol']}: {opp['why']}")
                seen_sols.add(opp["sol"])
            pts = opp["pts"]
            if added_pts + pts <= 30:
                score += pts
                added_pts += pts
    if matched:
        reason.append(f"Tech signals: {', '.join(matched[:4])}")
    else:
        reason.append("No tech-stack data available")

    rationale = "  ·  ".join(reason)
    return min(score, 100), matched, angles, rationale


def _norm_apollo(p: dict) -> dict:
    """Flatten an Apollo search or enrichment result into a standard contact dict."""
    org = p.get("organization") or {}

    # ── Phone — try every field Apollo uses ──────────────────────────────────
    phone = ""
    for ph in (p.get("phone_numbers") or []):
        if isinstance(ph, dict):
            phone = ph.get("sanitized_number") or ph.get("raw_number") or ph.get("number", "")
        else:
            phone = str(ph)
        if phone:
            break
    if not phone:
        phone = (p.get("mobile_phone") or p.get("direct_dial_number")
                 or p.get("sanitized_phone") or p.get("phone") or "")

    # ── Email — prefer business/work email; keep personal separately ─────────
    # p["email"] is Apollo's primary (usually work) email.
    # p["personal_emails"] are revealed personal emails (e.g. Gmail).
    work_email     = p.get("email") or ""
    personal_emails = p.get("personal_emails") or []
    personal_email  = personal_emails[0] if personal_emails else ""
    # Strip obfuscated placeholder that Apollo returns before credit is spent
    if work_email and "***" in work_email:
        work_email = ""
    if personal_email and "***" in personal_email:
        personal_email = ""
    email = work_email or personal_email
    email_status = p.get("email_status", "")

    # ── Name ─────────────────────────────────────────────────────────────────
    # Show the best available form, even if partially obfuscated (e.g. "Wedlock C***").
    # _enrich_contact will overwrite session state with the fully revealed name.
    name = p.get("name") or ""
    if not name:
        fn = p.get("first_name", "")
        ln = p.get("last_name") or p.get("last_name_obfuscated", "")
        name = f"{fn} {ln}".strip()

    has_phone_raw = p.get("has_direct_phone", "")
    has_phone = ("yes"   if str(has_phone_raw).lower().startswith("yes")
                 else "maybe" if str(has_phone_raw).lower().startswith("maybe")
                 else "")

    # ── Company / org enrichment ─────────────────────────────────────────────
    tech_raw   = org.get("technologies") or []
    tech_names = [t.get("name") or t.get("uid", "") for t in tech_raw
                  if isinstance(t, dict)][:10]
    keywords   = (org.get("keywords") or [])[:8]

    return {
        "id":             p.get("id", ""),
        "name":           name,
        "title":          p.get("title", ""),
        # emails
        "email":          email,
        "work_email":     work_email,
        "personal_email": personal_email,
        "email_status":   email_status,
        "has_email":      bool(p.get("has_email")),
        # phone
        "phone":          phone or "",
        "has_phone":      has_phone,
        # social
        "linkedin":       p.get("linkedin_url", ""),
        "twitter":        p.get("twitter_url", ""),
        # company
        "company":        org.get("name") or p.get("organization_name", ""),
        "company_phone":  org.get("phone", ""),
        "company_linkedin": org.get("linkedin_url", ""),
        "domain":         org.get("primary_domain", ""),
        "description":    org.get("short_description", ""),
        "employees":      org.get("estimated_num_employees"),
        "revenue":        org.get("annual_revenue_printed") or "",
        "industry":       org.get("industry", ""),
        "city":           org.get("city", ""),
        "country":        org.get("country", ""),
        "founded_year":   org.get("founded_year"),
        "keywords":       keywords,
        "tech_count":     len(tech_raw),
        "tech_names":     tech_names,
        "source":         "Apollo",
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
            elif "Apollo" in str(email_sources):
                score += 65
            else:
                score += 20
    if phone:
        score += 15
    return min(score, 100)


def _auto_crm_check(name: str, email: str, linkedin: str, state_key: str) -> dict | None:
    """Check Monday CRM once per contact; result cached in session state.
    Returns the CRM dict (with on_crm flag) or None if Monday not active."""
    if not monday_active:
        return None
    if state_key in st.session_state:
        return st.session_state[state_key]
    if not (name or email or linkedin):
        return None
    try:
        result = lookup_monday_crm({"name": name, "email": email, "linkedin": linkedin})
    except Exception:
        result = {"on_crm": False}
    st.session_state[state_key] = result
    return result


def _cascade_find_contact(name: str, linkedin_url: str,
                           company: str = "", domain_hint: str = "") -> dict:
    """Apollo → Hunter → pattern-guess. Returns aggregated contact data + confidence."""
    email = phone = title = comp = domain = None
    email_srcs: list = []
    phone_srcs: list = []

    # ── Apollo (LinkedIn URL match) ─────────────────────────────────────────
    if st.secrets.get("APOLLO_API_KEY", "") or os.getenv("APOLLO_API_KEY", ""):
        try:
            apo = _apollo_match(name, linkedin_url)
            n   = _norm_apollo(apo)
            if n.get("email"):
                email = n["email"]; email_srcs.append("Apollo")
            if n.get("phone"):
                phone = n["phone"]; phone_srcs.append("Apollo")
            title  = n.get("title") or None
            comp   = n.get("company") or None
            domain = n.get("domain") or None
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
            years_back=1, max_score=100, do_partner=True,
            score_time_budget_s=1800, trigger="manual_app",
            countries_filter=_ocds_filter, include_non_ocds=_non_ocds,
            skip_state_publishers=True,
            parallel_workers=4, progress_cb=_prog_cb,
            log=_log,
        )

        # ── Tender Intelligence Agent ──────────────────────────────────
        _log("🤖 Starting Tender Intelligence Agent (web search + enrichment)…")
        _PULL_STATE["current_country"] = "Agent: web search…"
        try:
            import tender_agent as _ta  # type: ignore[import-not-found]
            _ta.init_supabase()
            _ta.init_ai(log=lambda _: None)
            _agent_stats = _ta.run_agent(log=_log)
            result["agent_tenders"]        = _agent_stats.get("tenders", 0)
            result["agent_attack_signals"] = _agent_stats.get("attack_signals", 0)
            result["agent_partners"]       = _agent_stats.get("partners", 0)
            result["agent_contacts"]       = _agent_stats.get("contacts", 0)
            _log(f"🤖 Agent done — {_agent_stats.get('tenders',0)} tenders · "
                 f"{_agent_stats.get('attack_signals',0)} signals · "
                 f"{_agent_stats.get('partners',0)} partners · "
                 f"{_agent_stats.get('contacts',0)} contacts")
        except Exception as _ae:
            _log(f"⚠️ Agent phase error: {str(_ae)[:120]}")

        _PULL_STATE.update({"status": "done", "result": result,
                            "progress": 1.0, "current_country": ""})
    except Exception as _e:
        _PULL_STATE.update({"status": "failed", "result": {"error": str(_e)}})

# ─────────────────────────────────────────────────────────────────────────────
# CRS PORTFOLIO — decision-maker title maps (used by Lead Verification DM
# search and the Weekly Leads tab)
# ─────────────────────────────────────────────────────────────────────────────

_CRS_DM_TITLES: dict[str, list[str]] = {
    "All CRS products": [
        "CISO", "Chief Information Security Officer",
        "CTO", "CIO", "IT Director", "Head of IT", "IT Manager",
        "ICT Manager", "Group IT Manager", "Head of Cybersecurity",
        "Security Manager", "Information Security Manager",
        "Head of Security", "Cybersecurity Manager", "SOC Manager",
    ],
    "NDR / XDR / SOC — VECTRA AI": [
        "CISO", "SOC Manager", "Head of Security Operations",
        "VP Security", "Security Architect", "Head of Cybersecurity",
        "Information Security Manager", "Security Operations Manager",
        "Head of SOC", "Threat Intelligence Lead",
    ],
    "Vulnerability Mgmt — vRx / Strobes": [
        "CISO", "IT Manager", "Head of IT", "Security Manager",
        "IT Security Lead", "Head of Vulnerability Management",
        "Patch Management Lead", "IT Risk Manager",
    ],
    "AppSec / DevSecOps — Aikido / BlueFlag": [
        "CTO", "Head of Engineering", "Head of Software Development",
        "DevOps Lead", "Application Security Lead", "VP Engineering",
        "CISO", "Head of Development", "Software Architect",
    ],
    "GRC / Compliance / POPIA — Panorays / Telivy": [
        "CIO", "CISO", "Head of Compliance", "Risk Manager",
        "IT Governance Manager", "Data Protection Officer",
        "Head of Risk & Compliance", "Chief Risk Officer",
        "Privacy Officer", "Compliance Manager",
    ],
    "Dark Web / Threat Intel — Flare": [
        "CISO", "Head of Cybersecurity", "Threat Intelligence Manager",
        "Security Operations Manager", "SOC Manager",
        "Information Security Manager",
    ],
    "SASE / SIEM / MDR — Todyl": [
        "CISO", "IT Manager", "Head of IT", "Network Manager",
        "Head of Infrastructure", "IT Operations Manager",
        "Network Security Manager", "SOC Manager",
    ],
    "Endpoint / Encryption — BeachheadSecure / SMBsecure": [
        "IT Manager", "Head of IT", "Head of Infrastructure",
        "Systems Administrator", "IT Operations Manager",
        "IT Security Manager", "Desktop Manager",
    ],
    "Phishing Sim / Awareness — GoldPhish": [
        "CIO", "CISO", "L&D Manager", "Head of Learning",
        "HR Director", "Training Manager", "IT Security Manager",
        "Information Security Manager",
    ],
    "IBM / Red Hat / SUSE Training": [
        "L&D Manager", "Training Manager", "Head of Learning",
        "IT Skills Manager", "HR Director",
        "Head of IT", "IT Manager", "CIO",
    ],
    "CompTIA Training": [
        "L&D Manager", "Training Manager", "Head of Learning",
        "IT Skills Manager", "HR Director", "Head of IT", "IT Manager",
    ],
    "VAPT / Pentest — CRS Services": [
        "CISO", "Head of Cybersecurity", "IT Manager",
        "Risk Manager", "IT Governance Manager",
        "Head of IT Audit", "Information Security Manager",
    ],
}

# Strong-fit sectors: financial services, government, healthcare, telco, mining
_CRS_STRONG_SECTORS = {
    "bank", "financ", "insur", "govern", "public sector", "municipal",
    "health", "hospital", "clinic", "telecom", "telco", "network",
    "mining", "energy", "utility", "utilities", "defence", "defense",
    "revenue service", "treasury",
}
_CRS_MEDIUM_SECTORS = {
    "retail", "manufactur", "logistics", "transport", "education",
    "university", "law firm", "legal", "media", "broadcast",
    "property", "construction ict", "technology",
}

# Titles that indicate a genuine security/IT decision-maker
_CRS_DM_KEYWORDS = {
    "ciso", "information security", "cybersecurity", "cyber security",
    "soc manager", "head of security", "security manager",
    "it director", "head of it", "ict manager", "group it",
    "cto", "cio", "it manager", "it governance", "data protection officer",
    "risk manager", "compliance manager", "devops", "application security",
    "threat intelligence", "vulnerability", "pentest",
}


def _crs_fit_score(title: str, company_sector: str,
                   country: str, has_email: bool, has_phone: bool) -> int:
    """Deterministic CRS-fit score for an Apollo contact (0–100)."""
    score = 0
    t = title.lower()
    s = (company_sector or "").lower()
    c = (country or "").lower()

    # Title fit
    if any(kw in t for kw in _CRS_DM_KEYWORDS):
        score += 35
    elif any(x in t for x in ("manager", "director", "head", "officer", "lead")):
        score += 18

    # Sector fit
    if any(sk in s for sk in _CRS_STRONG_SECTORS):
        score += 30
    elif any(sk in s for sk in _CRS_MEDIUM_SECTORS):
        score += 15

    # Geography — African priority
    african_countries = {"south africa", "nigeria", "kenya", "ghana", "tanzania",
                         "uganda", "zimbabwe", "zambia", "botswana", "namibia",
                         "rwanda", "ethiopia", "mozambique", "senegal", "ivory coast"}
    if c in african_countries:
        score += 20
    elif c:
        score += 8

    # Contact availability
    if has_email:  score += 8
    if has_phone:  score += 7

    return min(score, 100)


# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR — Navigation + health check + action buttons
# ─────────────────────────────────────────────────────────────────────────────

def _queue_dm_and_go(company: str, solution: str, org_id: str = "",
                     domain: str = "", location: str = "",
                     industry: str = "", country: str = "",
                     num: int = 8, source: str = "") -> None:
    """Push a DM search request to the central queue and navigate to the Decision Makers tab."""
    titles = _CRS_DM_TITLES.get(solution, _CRS_DM_TITLES["All CRS products"])
    _key = f"{company.strip().lower()}|{solution}"
    queue: list = st.session_state.setdefault("dm_queue", [])
    for _e in queue:
        if _e["key"] == _key:
            _e.update({"org_id": org_id, "domain": domain, "location": location,
                       "titles": titles, "num": num, "source": source,
                       "industry": industry, "country": country})
            break
    else:
        queue.append({"key": _key, "company": company.strip(), "solution": solution,
                      "org_id": org_id, "domain": domain, "location": location,
                      "industry": industry, "country": country,
                      "titles": titles, "num": num, "source": source})
    st.session_state["_active_page"] = "👥 Decision Makers"
    st.rerun()

# ─────────────────────────────────────────────────────────────────────────────
# CRS INTELLIGENCE AGENT — helpers
# ─────────────────────────────────────────────────────────────────────────────

_CRS_AGENT_SYSTEM = (
    "You are the Chief Intelligence Agent for Cyber Retaliator Solutions (CRS), "
    "a South African cybersecurity VAD and IBM/Red Hat/SUSE/CompTIA training partner.\n\n"
    "MISSION: Grow the CRS pipeline by identifying, qualifying, and enriching high-value "
    "leads and strategic partners across Africa.\n\n"
    "CRS PORTFOLIO: Vectra AI (NDR/XDR/ITDR), vRx (vuln/patch), Strobes (CTEM/PTaaS), "
    "Aikido (DevSecOps/AppSec), Flare (dark web), BeachheadSecure (encryption/MFA), "
    "SMBsecure (SMB/POPIA), Telivy (MSSP audit), BlueFlag (SDLC), Todyl (SASE/SIEM/MXDR), "
    "Panorays (TPRM/DORA), GoldPhish/CRE (phishing awareness), Standss SendGuard (email GRC), "
    "IBM/Red Hat/SUSE/CompTIA training, own VAPT services.\n\n"
    "TARGETS: Government (all African countries), financial services, healthcare, education, "
    "telcos, mining, enterprises with dev teams.\n"
    "STRONG FIT: cybersecurity, ICT, SOC/MDR, POPIA compliance, vulnerability management.\n"
    "WEAK FIT: civil construction, catering, cleaning, pure hardware, non-ICT goods.\n\n"
    "RULES:\n"
    "1. ACCURACY: Flag missing enrichment as 'Partial' — never guess or hallucinate.\n"
    "2. WATERFALL: Apollo → LinkedIn Dork → Company website → Web search before giving up.\n"
    "3. MEMORY: Flag companies previously scored to avoid duplicate research.\n"
    "4. THRESHOLD: Score ≥5 → recommend Monday.com push. Score <5 → Market Trends log.\n"
    "5. ENRICHMENT: Always include Revenue, Employee Count, Tech Stack when available.\n"
    "6. OUTREACH: Map a specific CRS solution to the lead's confirmed pain point."
)


def _fetch_url_content(url: str) -> str:
    """Fetch URL and return stripped visible text, capped at 8 000 chars."""
    try:
        req = _urlreq.Request(url, headers={"User-Agent": "Mozilla/5.0 CRS-Intel/1.0"})
        with _urlreq.urlopen(req, timeout=15) as r:
            raw = r.read().decode("utf-8", errors="ignore")
        raw = re.sub(r"<script[^>]*>[\s\S]*?</script>", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"<style[^>]*>[\s\S]*?</style>",  "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"<[^>]+>", " ", raw)
        return re.sub(r"\s+", " ", raw).strip()[:8000]
    except Exception as e:
        return f"[Fetch failed: {e}]"


@st.cache_data(ttl=300)
def _load_knowledge_base() -> pd.DataFrame:
    try:
        r = _sb_execute(supabase.table("knowledge_base").select("*")
                        .order("created_at", desc=True).limit(100))
        return pd.DataFrame(r.data or [])
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300)
def _load_market_trends() -> pd.DataFrame:
    try:
        r = _sb_execute(supabase.table("market_trends").select("*")
                        .order("created_at", desc=True).limit(200))
        return pd.DataFrame(r.data or [])
    except Exception:
        return pd.DataFrame()


def _agent_analyse_signal(signal: str, signal_type: str = "General") -> dict:
    """Run the CRS Chief Intelligence Agent against a raw signal string."""
    kb_df = _load_knowledge_base()
    kb_ctx = ""
    if not kb_df.empty and "summary" in kb_df.columns:
        kb_ctx = "\n\nKNOWLEDGE BASE:\n" + "\n".join(
            f"- [{r.get('source','')}]: {str(r.get('summary',''))[:200]}"
            for _, r in kb_df.head(5).iterrows()
        )
    prompt = (
        f"{_CRS_AGENT_SYSTEM}{kb_ctx}\n\n"
        f"SIGNAL TYPE: {signal_type}\n"
        f"SIGNAL:\n{signal[:3000]}\n\n"
        "Return ONLY valid JSON (no markdown):\n"
        '{"lead_type":"Company Lead|Opportunity|Contact Lead|Irrelevant",'
        '"company":"name or Unknown","country":"country or Unknown",'
        '"score":<1-10>,'
        '"rationale":"2-3 sentences explaining why this was flagged as a CRS lead",'
        '"proposed_solutions":["sol1","sol2"],'
        '"pain_points":["pain1"],'
        '"outreach_note":"2-3 sentence sales brief: what triggered this lead, '
        'which specific CRS product addresses the confirmed pain point, '
        'and the recommended opening hook for the first email or call",'
        '"enrichment_status":"Complete|Partial|Missing",'
        '"next_action":"Push to Monday|Market Trends|Discard|Enrich First"}'
    )
    raw = _call_ai(prompt)
    try:
        return json.loads(raw)
    except Exception:
        m = re.search(r'\{[\s\S]*\}', raw)
        if m:
            try: return json.loads(m.group(0))
            except Exception: pass
    return {"lead_type": "Unknown", "company": "Unknown", "country": "Unknown",
            "score": 0, "rationale": raw[:300], "proposed_solutions": [],
            "pain_points": [], "outreach_note": "",
            "enrichment_status": "Missing", "next_action": "Discard"}


def _agent_enrich_company(company: str, country: str = "") -> dict:
    """Apollo enrichment cascade: org data + decision-maker contacts."""
    result: dict = {"company": company, "country": country,
                    "org": {}, "contacts": [], "enrichment_status": "Missing"}
    if not (st.secrets.get("APOLLO_API_KEY","") or os.getenv("APOLLO_API_KEY","")):
        result["enrichment_status"] = "Partial — APOLLO_API_KEY not configured"
        return result
    try:
        orgs, _ = _apollo_search_companies(
            keywords=company,
            locations=[country] if country and country.lower() not in ("unknown","") else None,
            num=3,
        )
        if orgs:
            org = _norm_org(orgs[0])
            result["org"] = org
            raw_contacts = _apollo_search_people(
                company=company, num=5,
                titles=["CISO","Chief Information Security Officer","CTO",
                        "Head of IT","IT Director","Security Manager","ICT Manager"],
                org_id=org.get("id",""), domain=org.get("domain",""),
            )
            result["contacts"] = [_norm_apollo(p) for p in raw_contacts]
            result["enrichment_status"] = (
                "Complete" if result["contacts"]
                else "Partial — no decision-maker contacts found in Apollo"
            )
        else:
            result["enrichment_status"] = "Partial — company not found in Apollo"
    except Exception as e:
        result["enrichment_status"] = f"Failed: {str(e)[:100]}"
    return result


@st.cache_data(ttl=60)
def _load_agent_leads(statuses: tuple = ("pending",)) -> pd.DataFrame:
    try:
        q = (supabase.table("agent_leads").select("*")
             .in_("status", list(statuses))
             .order("score", desc=True)
             .order("created_at", desc=True)
             .limit(500))
        r = _sb_execute(q)
        return pd.DataFrame(r.data or [])
    except Exception:
        return pd.DataFrame()


def _run_agent_batch(sources: list, limit: int = 20) -> tuple:
    """Pull from selected sources, analyse each unprocessed record, insert into agent_leads.
    Returns (inserted, skipped, errors)."""
    inserted = skipped = errors = 0
    try:
        existing_raw = supabase.table("agent_leads").select("source_type,source_id").execute().data or []
    except Exception:
        existing_raw = []
    existing = {(r["source_type"], str(r.get("source_id", ""))) for r in existing_raw}

    items: list = []  # (source_type, source_id, signal_text, signal_type, extra_fields)

    if "tenders" in sources:
        try:
            rows = _sb_execute(
                supabase.table("sa_tenders").select("*")
                .gte("ai_score", 6).neq("is_irrelevant", True)
                .order("ai_score", desc=True).limit(limit)
            ).data or []
        except Exception:
            rows = []
        for r in rows:
            sid = str(r.get("id", ""))
            if ("tender", sid) in existing:
                skipped += 1
                continue
            sig = (f"Tender title: {r.get('title','')}\n"
                   f"Department: {r.get('department_name','')}\n"
                   f"Country: {r.get('country','')}\n"
                   f"Description: {str(r.get('description',''))[:500]}\n"
                   f"AI score: {r.get('ai_score')}/10  Rationale: {r.get('ai_rationale','')}")
            items.append(("tender", sid, sig, "Tender",
                          {"company": r.get("department_name", "") or r.get("title", ""),
                           "country": r.get("country", ""),
                           "lead_type": "Opportunity"}))

    if "partner_recs" in sources:
        try:
            rows = _sb_execute(
                supabase.table("partner_recommendation_history").select("*")
                .order("run_at", desc=True).limit(limit * 4)
            ).data or []
        except Exception:
            rows = []
        seen: set = set()
        for r in rows:
            company = str(r.get("company", "")).strip()
            if not company or company in seen:
                continue
            seen.add(company)
            sid = str(r.get("id", ""))
            if ("partner_rec", sid) in existing:
                skipped += 1
                continue
            sig = (f"Company: {company}\nCountry: {r.get('country','')}\n"
                   f"Why aligned: {str(r.get('why','') or r.get('why_aligned',''))[:400]}\n"
                   f"Urgency: {r.get('urgency','')}  Deal size: {r.get('estimated_deal_size','')}")
            items.append(("partner_rec", sid, sig, "Partner Recommendation",
                          {"company": company, "country": str(r.get("country", "")),
                           "lead_type": "Company Lead"}))
            if len(items) >= limit:
                break

    if "awarded_companies" in sources:
        try:
            rows = _sb_execute(
                supabase.table("awarded_tenders")
                .select("winning_bidder,country,title,department_name,award_value")
                .neq("winning_bidder", None)
                .order("created_at", desc=True).limit(limit * 6)
            ).data or []
        except Exception:
            rows = []
        seen_aw: set = set()
        for r in rows:
            company = str(r.get("winning_bidder", "")).strip()
            if not company or len(company) < 3 or company in seen_aw:
                continue
            seen_aw.add(company)
            sid = f"aw_{company[:60]}"
            if ("awarded_company", sid) in existing:
                skipped += 1
                continue
            sig = (f"Company: {company}\nCountry: {r.get('country','')}\n"
                   f"Won tender: {r.get('title','')[:200]}\n"
                   f"Dept: {r.get('department_name','')}  Value: {r.get('award_value','')}")
            items.append(("awarded_company", sid, sig, "Awarded Tender",
                          {"company": company, "country": str(r.get("country", "")),
                           "lead_type": "Company Lead"}))
            if len(items) >= limit:
                break

    if "dork_leads" in sources:
        try:
            rows = _sb_execute(
                supabase.table("dork_leads").select("*")
                .is_("monday_item_id", "null")
                .order("created_at", desc=True).limit(limit)
            ).data or []
        except Exception:
            rows = []
        for r in rows:
            sid = str(r.get("linkedin_url", "") or r.get("id", ""))
            if ("dork_lead", sid) in existing:
                skipped += 1
                continue
            sig = (f"Name: {r.get('name','')}\nTitle: {r.get('job_title','')}\n"
                   f"Company: {r.get('company','')}\nLinkedIn: {sid}")
            items.append(("dork_lead", sid, sig, "LinkedIn Contact",
                          {"company": r.get("company", ""), "country": r.get("country", ""),
                           "lead_type": "Contact Lead",
                           "contact_name": r.get("name", ""),
                           "contact_title": r.get("job_title", ""),
                           "contact_linkedin": sid,
                           "contact_email": r.get("email", ""),
                           "contact_phone": r.get("phone", "")}))

    prog = st.progress(0, text="Analysing leads…")
    total = max(len(items), 1)
    for idx, (src_type, src_id, signal, sig_type, extra) in enumerate(items):
        prog.progress((idx + 1) / total,
                      text=f"Analysing {idx+1}/{total}: {extra.get('company','')[:40]}…")
        try:
            result = _agent_analyse_signal(signal, sig_type)
            score = int(result.get("score", 0) or 0)
            record = {
                "source_type": src_type,
                "source_id": src_id,
                "company": extra.get("company", "") or result.get("company", "Unknown"),
                "country": extra.get("country", "") or result.get("country", ""),
                "lead_type": extra.get("lead_type", "") or result.get("lead_type", "Company Lead"),
                "score": score,
                "rationale": result.get("rationale", ""),
                "outreach_note": result.get("outreach_note", ""),
                "proposed_solutions": json.dumps(result.get("proposed_solutions", [])),
                "pain_points": json.dumps(result.get("pain_points", [])),
            }
            for cf in ("contact_name", "contact_title", "contact_linkedin",
                       "contact_email", "contact_phone"):
                if extra.get(cf):
                    record[cf] = extra[cf]
            supabase.table("agent_leads").insert(record).execute()
            inserted += 1
        except Exception as _be:
            errors += 1
            st.toast(f"⚠️ Skipped {extra.get('company','?')}: {str(_be)[:80]}", icon="⚠️")

    prog.empty()
    _load_agent_leads.clear()
    return inserted, skipped, errors


_NAV_PAGES = [
    "✅ Lead Verification",
    "🔥 Intent Leads",
    "📢 Opportunities",
    "🤝 Partners",
    "🔍 LinkedIn Dork",
    "🛡️ Lead Intelligence",
    "💡 Weekly Leads",
    "🎯 End-User Targets",
    "👥 Decision Makers",
    "🤖 Intelligence Agent",
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

    # ── Apollo credit meter ───────────────────────────────────────────────────
    if bool(st.secrets.get("APOLLO_API_KEY","") or os.getenv("APOLLO_API_KEY","")):
        _cr = _apollo_credits()
        if _cr:
            _ll = _cr.get("lead_left", 0)
            _lt = _cr.get("lead_total", 0)
            _dl = _cr.get("dial_left", 0)
            _pct = (_ll / _lt) if _lt else 0
            _ico = "🟢" if _pct > 0.3 else "🟡" if _pct > 0.1 else "🔴"
            st.caption(
                f"{_ico} Apollo leads: **{_ll:,}** / {_lt:,}"
                + (f"  •  📞 **{_dl:,}** dials" if _dl else "")
            )
        else:
            st.caption("⚪ Apollo credits unavailable")
        st.divider()

    # ── Pipeline status ───────────────────────────────────────────────────────
    _gh_running = False
    _gh_started = ""
    _stale_run_id = None
    try:
        _lr = (supabase.table("pipeline_runs")
               .select("id,run_at,status,tenders_scraped,trigger")
               .order("run_at", desc=True).limit(1).execute()).data
        if _lr:
            _r0 = _lr[0]
            _ts = str(_r0.get("run_at", ""))[:16]
            _st = _r0.get("status", "—")
            if _st == "running":
                # Auto-expire runs that have been stuck for > 2 hours
                try:
                    _run_dt = _dt.datetime.fromisoformat(
                        str(_r0.get("run_at", "")).replace("Z", "+00:00")
                    )
                    _age_h = (_dt.datetime.now(_dt.timezone.utc) - _run_dt).total_seconds() / 3600
                except Exception:
                    _age_h = 0
                if _age_h > 2:
                    _stale_run_id = _r0.get("id")
                    # Mark it timed_out so Pull unblocks automatically
                    try:
                        supabase.table("pipeline_runs").update(
                            {"status": "timed_out",
                             "error_log": f"Auto-expired after {_age_h:.1f}h with no completion"}
                        ).eq("id", _stale_run_id).execute()
                    except Exception:
                        pass
                    st.caption(f"⚠️ Last run timed out after {_age_h:.1f}h — cleared")
                else:
                    _gh_running = True
                    _gh_started = _ts
                    st.warning(
                        f"⏳ Pipeline running since {_ts}  \n"
                        f"(trigger: {_r0.get('trigger','?')})\n\n"
                        "Do not press Pull again — a run is already in progress.",
                        icon="⚠️",
                    )
                    if st.button("🛑 Force cancel stuck run", key="force_cancel_run",
                                 use_container_width=True):
                        try:
                            supabase.table("pipeline_runs").update(
                                {"status": "timed_out",
                                 "error_log": "Manually cancelled via dashboard"}
                            ).eq("id", _r0["id"]).execute()
                            st.success("Run marked as timed_out — Pull is now unblocked.")
                            st.rerun()
                        except Exception as _fce:
                            st.error(f"Could not cancel: {_fce}")
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
            for _k in (
                "SUPABASE_URL", "SUPABASE_KEY",
                "GROQ_API_KEY", "CEREBRAS_API_KEY", "OPENROUTER_API_KEY",
                "GH_PAT", "GITHUB_TOKEN", "NVIDIA_API_KEY",
                "DEEPSEEK_API_KEY", "GEMINI_API_KEY",
                # Search backends for the Tender Intelligence Agent
                "SERPER_API_KEY", "SERPAPI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_CSE_ID",
                # Enrichment
                "APOLLO_API_KEY",
            ):
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
        _ag_t = _r.get("agent_tenders", 0)
        _ag_a = _r.get("agent_attack_signals", 0)
        _ag_p = _r.get("agent_partners", 0)
        _ag_c = _r.get("agent_contacts", 0)
        if any((_ag_t, _ag_a, _ag_p, _ag_c)):
            st.info(f"🤖 Agent: {_ag_t} tenders · {_ag_a} attack signals · {_ag_p} partners · {_ag_c} contacts")
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
# PAGE — OPPORTUNITIES
# ══════════════════════════════════════════════════════════════════════════════
if _page == "📢 Opportunities":
    _colored_header(label="Open Opportunities", description="Live tenders scored for CRS portfolio fit — filter, review rationale, push to Monday.", color_name="orange-70")

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

            # ── Category badge (HF zero-shot) ─────────────────────────────────
            _cat = str(_row.get("category") or "").strip()
            if not _cat or _cat in ("nan", "None"):
                if hf_ai:
                    _cat_key = f"opp_cat_{_row.get('id', _idx)}"
                    if _cat_key not in st.session_state:
                        _cat_text = f"{_row.get('title','')} {str(_row.get('description',''))[:300]}"
                        with st.spinner("Classifying…"):
                            _cat_result = _hf_classify_tender(_cat_text)
                        st.session_state[_cat_key] = _cat_result
                        if _cat_result:
                            try:
                                supabase.table("sa_tenders").update(
                                    {"category": _cat_result}
                                ).eq("id", str(_row["id"])).execute()
                            except Exception:
                                pass
                    _cat = st.session_state.get(_cat_key, "")
            if _cat and _cat not in ("nan", "None"):
                st.markdown(
                    f"<span style='background:#1565c0;color:#fff;padding:2px 10px;"
                    f"border-radius:10px;font-size:0.8rem'>🏷️ {_cat}</span>",
                    unsafe_allow_html=True,
                )
                st.write("")

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

            # ── Semantic similarity search ─────────────────────────────────────
            if hf_ai:
                _sim_key = f"opp_sim_{_row.get('id', _idx)}"
                if st.button("🔍 Find similar tenders", key=f"opp_sim_btn_{_idx}",
                             use_container_width=True):
                    _embed_text = f"{_row.get('title','')} {str(_row.get('description',''))[:800]}"
                    with st.spinner("Generating embedding…"):
                        _qvec = _hf_embed(_embed_text)
                    if _qvec:
                        # Store embedding on this tender if missing
                        try:
                            if not _row.get("embedding"):
                                supabase.table("sa_tenders").update(
                                    {"embedding": _qvec}
                                ).eq("id", str(_row["id"])).execute()
                        except Exception:
                            pass
                        # Query similar tenders via pgvector RPC
                        with st.spinner("Searching…"):
                            try:
                                _sim_rows = supabase.rpc("match_tenders", {
                                    "query_embedding": _qvec,
                                    "match_threshold": 0.4,
                                    "match_count": 5,
                                    "exclude_id": str(_row["id"]),
                                }).execute().data or []
                                st.session_state[_sim_key] = _sim_rows
                            except Exception as _se2:
                                st.error(f"Similarity search: {_se2}")
                                st.session_state[_sim_key] = []
                    else:
                        st.warning("HF embedding failed — check HF_TOKEN.")

                _sim_results = st.session_state.get(_sim_key, [])
                if _sim_results:
                    st.markdown("**Similar tenders**")
                    for _sr in _sim_results:
                        _sscore = int(_sr.get("ai_score") or 0)
                        _ssim   = float(_sr.get("similarity") or 0)
                        st.caption(
                            f"{'🔴' if _sscore >= 8 else '🟡' if _sscore >= 5 else '⚪'} "
                            f"**{_sr.get('title','?')}**  ·  {_sr.get('country','?')}"
                            f"  ·  score {_sscore}  ·  {_ssim:.0%} similar"
                        )
                elif _sim_key in st.session_state and not _sim_results:
                    st.caption("No similar tenders found yet — embed more tenders first.")

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
    _colored_header(label="Partner Recommendations", description="Companies CRS should approach as channel partners, derived from awarded tender data.", color_name="green-70")

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

                # ── Apollo contact finder ─────────────────────────────────────
                _p_has_apo = bool(st.secrets.get("APOLLO_API_KEY","") or os.getenv("APOLLO_API_KEY",""))
                _p_apo_key = f"p_apo_contacts_{card_idx}"
                if _p_has_apo:
                    with st.expander(f"👥 Find contacts at {company}", expanded=False):
                        _pa1, _pa2 = st.columns([3, 2])
                        with _pa1:
                            _p_sol = st.selectbox(
                                "Solution focus",
                                list(_CRS_DM_TITLES.keys()),
                                key=f"p_sol_{card_idx}",
                                index=0,
                            )
                        with _pa2:
                            _p_dm_num = st.number_input(
                                "Max", 5, 15, 8, step=5, key=f"p_dm_num_{card_idx}",
                            )
                        _p_titles = _CRS_DM_TITLES[_p_sol]
                        st.caption(", ".join(_p_titles[:6]) + (f" +{len(_p_titles)-6} more" if len(_p_titles)>6 else ""))
                        if st.button("🔍 Search", key=f"p_apo_search_{card_idx}",
                                     type="primary", use_container_width=True):
                            with st.spinner(f"Apollo: {_p_sol} at {company}…"):
                                try:
                                    _p_raw = _apollo_search_people(
                                        company=company, num=int(_p_dm_num),
                                        titles=_p_titles,
                                    )
                                    _p_normed = []
                                    for _pr2 in _p_raw:
                                        _pn = _norm_apollo(_pr2)
                                        _pn["crs_fit"] = _crs_fit_score(
                                            _pn.get("title",""), p_type or "",
                                            country, _pn.get("has_email",False),
                                            bool(_pn.get("has_phone")),
                                        )
                                        _p_normed.append(_pn)
                                    _p_normed.sort(key=lambda z: -z.get("crs_fit",0))
                                    st.session_state[_p_apo_key] = _p_normed
                                except Exception as _pae:
                                    st.error(f"Apollo error: {_pae}")

                        _p_contacts = st.session_state.get(_p_apo_key, [])
                        if _p_contacts:
                            st.markdown(f"**{len(_p_contacts)} contacts found:**")
                            for _pci, _pcc in enumerate(_p_contacts):
                                _pc_crm_k = f"p_crm_{card_idx}_{_pci}"
                                _pc_em_k  = f"p_em_{card_idx}_{_pci}"
                                _pc_ph_k  = f"p_ph_{card_idx}_{_pci}"
                                _pc_crm = _auto_crm_check(
                                    _pcc.get("name",""), _pcc.get("email",""),
                                    _pcc.get("linkedin",""), _pc_crm_k,
                                )
                                _pc_mon_email = (_pc_crm.get("crm_email","") if _pc_crm and _pc_crm.get("on_crm") else "")
                                _pc_mon_phone = (_pc_crm.get("crm_phone","") if _pc_crm and _pc_crm.get("on_crm") else "")
                                _pc_email = st.session_state.get(_pc_em_k) or _pc_mon_email or _pcc.get("email","")
                                _pc_phone = st.session_state.get(_pc_ph_k) or _pc_mon_phone or _pcc.get("phone","")
                                _pc_fit   = _pcc.get("crs_fit", 0)
                                _pc_name  = _pcc.get("name") or f"Contact {_pci+1}"
                                _pc_badge = "🟢" if _pc_fit >= 70 else "🟡" if _pc_fit >= 45 else "🔴"
                                with st.container(border=True):
                                    _pca, _pcb = st.columns([3, 2])
                                    with _pca:
                                        _pc_hdr = f"**{_pc_badge} {_pc_name}**"
                                        if _pc_crm and _pc_crm.get("on_crm"):
                                            _pc_hdr += "  `✓ CRM`"
                                        st.markdown(_pc_hdr)
                                        if _pcc.get("title"):
                                            st.caption(_pcc["title"])
                                        if _pcc.get("linkedin"):
                                            st.markdown(f"[LinkedIn]({_pcc['linkedin']})")
                                    with _pcb:
                                        st.caption(f"Fit: {_pc_fit}%")
                                        if _pc_email:
                                            st.markdown(f"📧 `{_pc_email}`")
                                        elif _pcc.get("has_email"):
                                            st.caption("📧 available (enrich)")
                                        if _pc_phone:
                                            st.markdown(f"📞 `{_pc_phone}`")
                                        elif _pcc.get("has_phone"):
                                            st.caption("📞 available (enrich)")
                                    _pcc1, _pcc2, _pcc3 = st.columns(3)
                                    with _pcc1:
                                        if not _pc_email and _pcc.get("id") and not st.session_state.get(_pc_em_k):
                                            if st.button("💳 Enrich", key=f"p_enrich_{card_idx}_{_pci}",
                                                         use_container_width=True):
                                                with st.spinner("Enriching…"):
                                                    try:
                                                        _pen = _enrich_contact(
                                                            apollo_id=_pcc.get("id",""),
                                                            name=_pc_name,
                                                            linkedin=_pcc.get("linkedin",""),
                                                            company=company,
                                                        )
                                                        if _pen.get("name"):
                                                            st.session_state[f"p_nm_{card_idx}_{_pci}"] = _pen["name"]
                                                        st.session_state[_pc_em_k] = _pen.get("email","")
                                                        st.session_state[_pc_ph_k] = _pen.get("phone","")
                                                        st.rerun()
                                                    except Exception as _pee:
                                                        st.error(f"Enrich failed: {_pee}")
                                    with _pcc2:
                                        if monday_active:
                                            _pc_push_lbl = ("♻️ Update" if _pc_crm and _pc_crm.get("on_crm") else "📋 Push")
                                            if st.button(_pc_push_lbl, key=f"p_push_{card_idx}_{_pci}",
                                                         use_container_width=True,
                                                         type="secondary" if (_pc_crm and _pc_crm.get("on_crm")) else "primary"):
                                                with st.spinner("Syncing…"):
                                                    try:
                                                        _pmr = sync_lead_to_monday({
                                                            "name":           _pc_name,
                                                            "title":          _pcc.get("title",""),
                                                            "company":        company,
                                                            "email":          _pc_email,
                                                            "phone":          _pc_phone,
                                                            "linkedin":       _pcc.get("linkedin",""),
                                                            "accuracy_score": str(_pc_fit),
                                                            "provider_chain": f"Partners tab · {_p_sol}",
                                                        })
                                                        st.success(f"{_pmr.get('action','done').title()} · ID: {_pmr.get('item_id')}")
                                                        del st.session_state[_pc_crm_k]
                                                    except Exception as _ppe:
                                                        st.error(f"Push failed: {_ppe}")
                                    with _pcc3:
                                        _copy_block(
                                            "\n".join(l for l in [
                                                f"NAME: {_pc_name}",
                                                f"Title: {_pcc.get('title','')}",
                                                f"Company: {company}",
                                                f"Email: {_pc_email}",
                                                f"Phone: {_pc_phone}",
                                                f"LinkedIn: {_pcc.get('linkedin','')}",
                                            ] if l),
                                            key=f"pc_copy_{card_idx}_{_pci}",
                                            flat=True,
                                        )

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
    _colored_header(label="Lead Verification", description="Dork, enrich, and score B2B contacts — then push verified leads to Monday CRM.", color_name="blue-70")

    # ══════════════════════════════════════════════════════════════════════════
    # CONTACT LOOKUP — Apollo primary, Monday as tag
    # ══════════════════════════════════════════════════════════════════════════
    st.markdown("### 🔍 Contact Lookup")
    st.caption(
        "Apollo search is primary. "
        "Monday CRM shown as a tag on each card. "
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

    # ── CRS Revealed List (Apollo contacts saved via Reveal All) ───────────────
    with st.expander(f"📋 '{_APOLLO_REVEALED_LIST}' — contacts saved to Apollo"):
        _rl_col1, _rl_col2 = st.columns([1, 4])
        with _rl_col1:
            if st.button("Load list", key="lk_load_revealed", use_container_width=True):
                with st.spinner("Fetching from Apollo…"):
                    _rl_contacts, _rl_total = _apollo_list_contacts()
                st.session_state["lk_revealed_contacts"] = _rl_contacts
                st.session_state["lk_revealed_total"] = _rl_total
        with _rl_col2:
            if "lk_revealed_total" in st.session_state:
                st.caption(f"{st.session_state['lk_revealed_total']} contacts in list")
        _rl_list = st.session_state.get("lk_revealed_contacts")
        if _rl_list is not None:
            if not _rl_list:
                st.info("No contacts in the list yet — reveal a contact above to populate it.")
            else:
                _rl_q = st.text_input("🔍 Filter by name, company, email or phone",
                                      key="lk_revealed_search", placeholder="Search…")
                _rl_q_lower = _rl_q.strip().lower()
                for _rlc in _rl_list:
                    _rl_name  = (_rlc.get("name") or
                                 f"{_rlc.get('first_name','')} {_rlc.get('last_name','')}".strip()
                                 or "Unknown")
                    _rl_title = _rlc.get("title") or ""
                    _rl_org   = (_rlc.get("organization_name") or
                                 (_rlc.get("organization") or {}).get("name",""))
                    _rl_email = (_rlc.get("email") or
                                 ((_rlc.get("contact_emails") or [{}])[0]).get("email",""))
                    _rl_phone = (_rlc.get("direct_phone") or _rlc.get("mobile_phone") or
                                 ((_rlc.get("phone_numbers") or [{}])[0]).get("sanitized_number",""))
                    _rl_li    = _rlc.get("linkedin_url","")
                    _rl_aid   = _rlc.get("id","")
                    if _rl_q_lower and not any(
                        _rl_q_lower in (s or "").lower()
                        for s in [_rl_name, _rl_org, _rl_email, _rl_phone, _rl_title]
                    ):
                        continue
                    with st.container(border=True):
                        _rla, _rlb = st.columns([3, 2])
                        with _rla:
                            st.markdown(f"**{_rl_name}**")
                            _rl_sub = [x for x in [_rl_title, _rl_org] if x]
                            if _rl_sub: st.caption("  ·  ".join(_rl_sub))
                            if _rl_li: st.markdown(f"[LinkedIn →]({_rl_li})")
                        with _rlb:
                            if _rl_email: st.markdown(f"📧 `{_rl_email}`")
                            if _rl_phone: st.markdown(f"📞 `{_rl_phone}`")
                            if _rl_aid:   st.caption(f"Apollo ID: {_rl_aid}")

    if _lk_run:
        _n = st.session_state.get("lk_name", "").strip()
        _c = st.session_state.get("lk_company", "").strip()
        if not _n and not _c:
            st.warning("Enter a name, company, or both.")
        else:
            for _k0 in list(st.session_state.keys()):
                if _k0 in ("lk_results","lk_co","lk_dm",
                            "lk_revealed_contacts","lk_revealed_total","lk_revealed_search") or \
                   _k0.startswith(("lk_crm_","lk_phone_","lk_email_","lk_xref_",
                                   "lk_rev_saved_","lk_reveal_all_","lk_enrich_")):
                    del st.session_state[_k0]
            _results: list = []
            with st.spinner("Searching Apollo…"):
                try:
                    _results = [_norm_apollo(p) for p in
                                _apollo_search_people(name=_n, company=_c, num=8)]
                except Exception as _ae:
                    st.toast(f"Apollo: {str(_ae)[:80]}")
            if monday_active and _c:
                with st.spinner("Checking Monday Companies…"):
                    try:
                        st.session_state["lk_co"] = lookup_monday_company(_c)
                    except Exception:
                        st.session_state["lk_co"] = {"found": False}
            st.session_state["lk_results"] = _results

    # ── Companies board banner ────────────────────────────────────────────────
    _lk_co_r = st.session_state.get("lk_co")
    if _lk_co_r and _lk_co_r.get("found"):
        _lk_c_disp = st.session_state.get("lk_company", "")
        with st.container(border=True):
            _co_a, _co_b = st.columns([4, 2])
            with _co_a:
                st.success(f"🏢 **{_lk_c_disp}** on Monday Companies board")
                if _lk_co_r.get("office_number"): st.markdown(f"📞 {_lk_co_r['office_number']}")
                if _lk_co_r.get("website"):       st.markdown(f"🌐 {_lk_co_r['website']}")
                if _lk_co_r.get("linkedin"):      st.markdown(f"🔗 {_lk_co_r['linkedin']}")
            with _co_b:
                if _lk_co_r.get("company_url"):
                    st.markdown(f"[Open in Monday →]({_lk_co_r['company_url']})")

    # ── Results ───────────────────────────────────────────────────────────────
    _lk_results = st.session_state.get("lk_results")
    if _lk_results is not None:
        _lk_c_val = st.session_state.get("lk_company", "")
        _has_apo  = bool(st.secrets.get("APOLLO_API_KEY","") or os.getenv("APOLLO_API_KEY",""))

        if not _lk_results:
            st.info("No results found. Try the LinkedIn Dork tab for manual search.")
        else:
            st.markdown(f"**{len(_lk_results)} contacts found**")

        def _render_lk_cards(cards: list, key_prefix: str) -> None:
            for _ci, _cc in enumerate(cards):
                _apo_id  = _cc.get("id", "")
                _crm_sk  = f"lk_crm_{key_prefix}_{_ci}"
                _ph_sk   = f"lk_phone_{key_prefix}_{_ci}"
                _em_sk   = f"lk_email_{key_prefix}_{_ci}"
                _nm_sk   = f"lk_name_{key_prefix}_{_ci}"
                _xref_sk = f"lk_xref_{key_prefix}_{_ci}"
                # Revealed name overrides obfuscated search result
                _disp_name = (st.session_state.get(_nm_sk)
                              or _cc.get("name") or f"Contact {_ci+1}")

                # ── Auto CRM check (fires once, cached in session state) ──
                _crm_r = _auto_crm_check(
                    _cc.get("name",""), _cc.get("email",""),
                    _cc.get("linkedin",""), _crm_sk,
                )
                # Pull any free contact data from Monday
                _mon_email = (_crm_r.get("crm_email","") if _crm_r and _crm_r.get("on_crm") else "")
                _mon_phone = (_crm_r.get("crm_phone","") if _crm_r and _crm_r.get("on_crm") else "")

                with st.container(border=True):
                    _hA, _hB = st.columns([4, 2])
                    with _hA:
                        st.markdown(f"### 👤 {_disp_name}")
                        _rp = [x for x in [_cc.get("title"), _cc.get("company")] if x]
                        if _rp: st.caption("💼 " + "  ·  ".join(_rp))
                        if _cc.get("domain"):   st.caption(f"🌐 {_cc['domain']}")
                        if _cc.get("linkedin"): st.markdown(f"[LinkedIn →]({_cc['linkedin']})")
                        if _cc.get("twitter"):  st.caption(f"Twitter: {_cc['twitter']}")
                    with _hB:
                        st.caption(f"🔵 {_cc.get('source','Apollo')}")
                        # Monday CRM badge — auto-populated
                        if _crm_r:
                            if _crm_r.get("on_crm"):
                                st.success(f"📋 {_crm_r['crm_board']}")
                                if _crm_r.get("crm_url"):
                                    st.markdown(f"[Open →]({_crm_r['crm_url']})")
                            else:
                                st.caption("📋 Not in CRM")

                    # ── Email + Phone ──────────────────────────────────────
                    _enr_sk  = f"lk_enriched_{key_prefix}_{_ci}"
                    _enr_data = st.session_state.get(_enr_sk, {})

                    # Business email — prefer work_email, fall back to email
                    _em_val = (_cc.get("work_email") or _cc.get("email") or _mon_email
                               or _enr_data.get("work_email") or _enr_data.get("email")
                               or st.session_state.get(_em_sk, {}).get("email",""))
                    _em_src = ("Apollo" if (_cc.get("work_email") or _cc.get("email"))
                               else "Monday" if _mon_email else "Apollo")
                    # Personal email (secondary, shown if different from business)
                    _em_personal = (_cc.get("personal_email") or _enr_data.get("personal_email",""))

                    _ph_val = (_cc.get("phone") or _mon_phone
                               or _enr_data.get("phone")
                               or st.session_state.get(_ph_sk, {}).get("phone",""))
                    _ph_src = ("Apollo" if (_cc.get("phone") or _enr_data.get("phone"))
                               else "Monday" if _mon_phone else "")

                    _fA, _fB = st.columns(2)
                    with _fA:
                        if _em_val:
                            st.markdown(f"📧 **{_em_val}**")
                            st.caption(f"Business · via {_em_src}")
                            if _em_personal and _em_personal != _em_val:
                                st.markdown(f"📧 `{_em_personal}`")
                                st.caption("Personal · via Apollo")
                        else:
                            _hp_em = _cc.get("has_email")
                            st.caption("📧 Available · ⚡ 1 credit" if _hp_em else "📧 Not flagged")
                    with _fB:
                        if _ph_val:
                            st.markdown(f"📞 **{_ph_val}**")
                            st.caption(f"Mobile · via {_ph_src}" if _ph_src else "Mobile · via Apollo")
                        elif _apo_id:
                            _hp = _cc.get("has_phone","")
                            st.caption("📞 Direct dial available" if _hp == "yes"
                                       else "📞 May be available" if _hp == "maybe"
                                       else "📞 Use Reveal All below")
                        else:
                            st.caption("📞 No Apollo ID")
                        _cph = _cc.get("company_phone") or _enr_data.get("company_phone","")
                        if _cph:
                            st.markdown(f"🏢 **{_cph}** (company)")

                    # ── Reveal All & Save to Apollo List ───────────────────
                    _enrich_done = bool(_em_val and _ph_val)
                    _reveal_saved_sk = f"lk_rev_saved_{key_prefix}_{_ci}"
                    if _has_apo and _apo_id and not _enrich_done:
                        _rv_lbl = (
                            "🔓 Reveal All & Save to Apollo List"
                            if not st.session_state.get(_reveal_saved_sk)
                            else "🔄 Re-reveal & Update List"
                        )
                        if st.button(_rv_lbl, key=f"lk_reveal_all_{key_prefix}_{_ci}",
                                     use_container_width=True, type="primary"):
                            with st.spinner(f"Revealing via Apollo — saving to '{_APOLLO_REVEALED_LIST}'…"):
                                _rv2 = _apollo_reveal_and_save(_apo_id)
                            if _rv2["error"] and not _rv2["person"]:
                                st.error(f"Apollo: {_rv2['error'][:140]}")
                            else:
                                _rn = _rv2["person"]
                                _card_list_key = "lk_results" if key_prefix == "main" else "lk_dm"
                                if _rn.get("name") and "***" not in _rn["name"]:
                                    st.session_state[_nm_sk] = _rn["name"]
                                    if _card_list_key in st.session_state:
                                        st.session_state[_card_list_key][_ci]["name"] = _rn["name"]
                                if _rn.get("work_email") or _rn.get("email"):
                                    _best = _rn.get("work_email") or _rn["email"]
                                    st.session_state[_em_sk] = {"email": _best, "source": "Apollo"}
                                    if _card_list_key in st.session_state:
                                        st.session_state[_card_list_key][_ci]["work_email"] = _best
                                        st.session_state[_card_list_key][_ci]["email"] = _best
                                        if _rn.get("personal_email"):
                                            st.session_state[_card_list_key][_ci]["personal_email"] = _rn["personal_email"]
                                _rc = _rv2.get("contact") or {}
                                # Phone: people/match only reveals phone with a
                                # separate credit; fall back to whatever Apollo
                                # already stores in the CRM contact record.
                                _revealed_phone = (
                                    _rn.get("phone") or
                                    _rc.get("direct_phone") or
                                    _rc.get("mobile_phone") or
                                    ((_rc.get("phone_numbers") or [{}])[0]).get("sanitized_number","")
                                )
                                if _revealed_phone:
                                    st.session_state[_ph_sk] = {"phone": _revealed_phone, "source": "Apollo"}
                                    if _card_list_key in st.session_state:
                                        st.session_state[_card_list_key][_ci]["phone"] = _revealed_phone
                                if _rn.get("linkedin"):
                                    if _card_list_key in st.session_state:
                                        st.session_state[_card_list_key][_ci]["linkedin"] = _rn["linkedin"]
                                st.session_state[_enr_sk] = _rn
                                st.session_state[_reveal_saved_sk] = True
                                if _rv2["error"]:
                                    st.warning(f"Revealed — list save failed: {_rv2['error'][:80]}")
                                elif _rc.get("id"):
                                    st.success(f"Saved to '{_APOLLO_REVEALED_LIST}' · Apollo ID: {_rc['id']}")
                                else:
                                    st.success(f"Revealed · added to '{_APOLLO_REVEALED_LIST}' list")
                                if not _rn.get("email") and not _rn.get("work_email") and not _revealed_phone:
                                    st.toast("Nothing revealed — contact may lack Apollo data")
                                st.rerun()

                    # ── Company insights ───────────────────────────────────
                    _co_src = _enr_data if _enr_data.get("description") else _cc
                    _co_desc = _co_src.get("description","")
                    _co_rev  = _co_src.get("revenue","")
                    _co_emp  = _co_src.get("employees")
                    _co_ind  = _co_src.get("industry","")
                    _co_kw   = _co_src.get("keywords") or []
                    _co_tech = _co_src.get("tech_count", 0)
                    _co_yr   = _co_src.get("founded_year")
                    _co_cph  = _co_src.get("company_phone","")
                    _co_city = _co_src.get("city","")
                    _co_ctry = _co_src.get("country","")
                    if any([_co_desc, _co_rev, _co_emp, _co_ind, _co_kw, _co_tech]):
                        with st.expander("🏢 Company insights"):
                            if _co_desc:
                                st.caption(_co_desc[:300] + ("…" if len(_co_desc) > 300 else ""))
                            _ci1, _ci2, _ci3 = st.columns(3)
                            if _co_rev:   _ci1.metric("Revenue", _co_rev)
                            if _co_emp:   _ci2.metric("Employees", f"{_co_emp:,}" if isinstance(_co_emp, int) else _co_emp)
                            if _co_yr:    _ci3.metric("Founded", _co_yr)
                            if _co_ind:   st.caption(f"**Industry:** {_co_ind}")
                            loc_parts = [x for x in [_co_city, _co_ctry] if x]
                            if loc_parts: st.caption(f"**Location:** {', '.join(loc_parts)}")
                            if _co_cph:   st.caption(f"**Office:** {_co_cph}")
                            if _co_kw:    st.caption("**Keywords:** " + " · ".join(_co_kw))
                            if _co_tech:  st.caption(f"**Technologies tracked:** {_co_tech}")

                    # ── Monday CRM expanded data ───────────────────────────
                    if _crm_r and _crm_r.get("on_crm"):
                        with st.expander("📋 All Monday CRM data"):
                            _md1, _md2 = st.columns(2)
                            for _mfi, (_mfk, _mfl) in enumerate([
                                ("crm_title","Title"),("crm_email","Email"),
                                ("crm_phone","Phone"),("crm_linkedin","LinkedIn"),
                                ("crm_authority","Authority"),("crm_heat","Heat"),
                            ]):
                                _mfv = _crm_r.get(_mfk,"")
                                if _mfv and str(_mfv) not in ("","nan","None"):
                                    (_md1 if _mfi % 2 == 0 else _md2).markdown(
                                        f"**{_mfl}:** {_mfv}")
                            _lm2 = _crm_r.get("crm_last_method","")
                            _ld2 = _crm_r.get("crm_last_date","")
                            if _lm2 or _ld2:
                                st.caption(f"Last contact: {(_lm2+' '+_ld2).strip()}")
                            if _crm_r.get("crm_notes"):
                                st.caption(f"📝 {_crm_r['crm_notes'][:200]}")

                            # Cross-reference with Apollo
                            if _has_apo:
                                if st.button("↔ Cross-reference with Apollo",
                                             key=f"lk_xref_btn_{key_prefix}_{_ci}"):
                                    with st.spinner("Apollo enrichment…"):
                                        try:
                                            _xr = _apollo_match(
                                                apollo_id=_apo_id,
                                                name=_crm_r.get("crm_name", _cc.get("name","")),
                                                linkedin_url=_crm_r.get("crm_linkedin",""),
                                                email=_crm_r.get("crm_email",""),
                                            )
                                            if _xr:
                                                st.session_state[_xref_sk] = _norm_apollo(_xr)
                                        except Exception as _xe:
                                            st.error(f"Apollo: {str(_xe)[:80]}")
                            _xref_r = st.session_state.get(_xref_sk)
                            if _xref_r:
                                st.markdown("**Apollo vs Monday:**")
                                _diffs = [(lbl, _xref_r.get(ak,""), _crm_r.get(ck,""))
                                          for lbl,ak,ck in [
                                              ("Email","email","crm_email"),
                                              ("Phone","phone","crm_phone"),
                                              ("Title","title","crm_title"),
                                              ("LinkedIn","linkedin","crm_linkedin"),
                                          ] if _xref_r.get(ak) and _xref_r.get(ak) != _crm_r.get(ck)]
                                if _diffs:
                                    for _dl, _dav, _dcv in _diffs:
                                        _da, _db = st.columns(2)
                                        _da.markdown(f"Apollo **{_dl}:** {_dav}")
                                        _db.markdown(f"Monday **{_dl}:** {_dcv or '—'}")
                                else:
                                    st.caption("✅ Apollo and Monday data match")

                    # ── Actions ───────────────────────────────────────────
                    if monday_active:
                        _src_n = st.session_state.get("lk_name","").strip()
                        _src_c = st.session_state.get("lk_company","").strip()
                        _src_ctx = "Lead Verification tab"
                        if _src_n: _src_ctx += f" | search: \"{_src_n}\""
                        if _src_c: _src_ctx += f" | company: \"{_src_c}\""
                        if key_prefix == "dm": _src_ctx += " | decision maker search"
                        _push_pl = {
                            "name":           _cc.get("name",""),
                            "title":          _cc.get("title",""),
                            "company":        _cc.get("company",""),
                            "email":          _cc.get("email","") or _mon_email or st.session_state.get(_em_sk,{}).get("email",""),
                            "phone":          _cc.get("phone","") or _mon_phone or st.session_state.get(_ph_sk,{}).get("phone",""),
                            "linkedin":       _cc.get("linkedin",""),
                            "company_phone":  _cc.get("company_phone",""),
                            "twitter":        _cc.get("twitter",""),
                            "provider_chain": _cc.get("source","Apollo"),
                            "source_context": _src_ctx,
                        }
                        _pa, _pb, _pc = st.columns(3)
                        with _pa:
                            if st.button("📋 Push to Leads",
                                         key=f"lk_push_lead_{key_prefix}_{_ci}",
                                         use_container_width=True):
                                with st.spinner("Pushing…"):
                                    try:
                                        _rl = sync_lead_to_monday(_push_pl)
                                        st.success(f"{_rl.get('action','done').title()} · {_rl.get('item_id')}")
                                    except Exception as _ple: st.error(str(_ple))
                        with _pb:
                            if st.button("🏢 Push to Contacts",
                                         key=f"lk_push_contact_{key_prefix}_{_ci}",
                                         use_container_width=True, type="primary"):
                                with st.spinner("Pushing…"):
                                    try:
                                        _rc2 = push_to_contacts_board(_push_pl)
                                        st.success(f"{_rc2.get('action','done').title()} · {_rc2.get('item_id')}")
                                    except Exception as _pce: st.error(str(_pce))
                        with _pc:
                            _copy_block("\n".join(l for l in [
                                f"CONTACT: {_cc.get('name','')}",
                                f"Title: {_cc.get('title','')}"     if _cc.get("title")     else "",
                                f"Company: {_cc.get('company','')}" if _cc.get("company")   else "",
                                f"Email: {_push_pl['email']}"       if _push_pl["email"]    else "",
                                f"Phone: {_push_pl['phone']}"       if _push_pl["phone"]    else "",
                                f"Co Phone: {_cc.get('company_phone','')}" if _cc.get("company_phone") else "",
                                f"LinkedIn: {_cc.get('linkedin','')}" if _cc.get("linkedin") else "",
                                f"Source: {_cc.get('source','')}",
                            ] if l), key=f"lk_copy_{key_prefix}_{_ci}")

        if _lk_results:
            _render_lk_cards(_lk_results, "main")

        # ── Decision-maker search — separate section below contact results ──
        if _has_apo and _lk_c_val.strip():
            st.divider()
            st.markdown("#### 👥 Find Decision Makers")
            _lv_sol_col, _lv_btn_col = st.columns([3, 2])
            with _lv_sol_col:
                _lv_dm_sol = st.selectbox(
                    "CRS solution focus",
                    list(_CRS_DM_TITLES.keys()),
                    key="lv_dm_sol",
                )
            with _lv_btn_col:
                st.write(""); st.write("")
                if st.button("👥 Find decision makers →", key="lv_dm_go",
                             type="primary", use_container_width=True):
                    _queue_dm_and_go(
                        company=_lk_c_val, solution=_lv_dm_sol,
                        num=10, source="✅ Lead Verification",
                    )

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
# TAB — INTENT LEADS
# ══════════════════════════════════════════════════════════════════════════════

# Apollo Bombora intent topics relevant to the CRS portfolio
_CRS_INTENT_TOPICS: list[str] = [
    "Certified Information Systems Security Professional (CISSP)",
    "Active Cyber Defense",
    "Cyber & Intelligence",
    "Career Training Program",
    "Chief Information Security Officer (CISO)",
    "Cyber Essentials (CE)",
    "Cybersecurity",
    "Network Security",
    "Information Security",
    "Endpoint Security",
    "Cloud Security",
    "Vulnerability Management",
    "Penetration Testing",
    "Security Operations",
    "Threat Intelligence",
    "Data Loss Prevention",
    "Security Awareness Training",
    "Compliance Management",
    "Identity and Access Management",
    "Zero Trust Security",
    "Managed Security Services",
    "Incident Response",
    "GRC",
    "POPIA",
    "IBM Training",
    "CompTIA",
    "Red Hat",
    "SUSE Linux",
]

if _page == "🔥 Intent Leads":
    _colored_header(label="Intent Leads", description="Apollo companies actively researching cybersecurity topics — filtered by Bombora signal strength and CRS portfolio relevance.", color_name="red-70")

    _has_apo_il = bool(st.secrets.get("APOLLO_API_KEY","") or os.getenv("APOLLO_API_KEY",""))
    if not _has_apo_il:
        st.warning("APOLLO_API_KEY not configured.")
        st.stop()

    # ── Filters ───────────────────────────────────────────────────────────────
    with st.expander("🔧 Search Filters", expanded=True):
        _ilc1, _ilc2 = st.columns(2)
        with _ilc1:
            _il_scores = st.multiselect(
                "Intent Score",
                ["HIGH", "MEDIUM", "LOW"],
                default=["HIGH", "MEDIUM"],
                key="il_scores",
                help="Minimum Bombora intent signal strength for the selected topics",
            )
            _il_topics = st.multiselect(
                "Intent Topics",
                _CRS_INTENT_TOPICS,
                default=_CRS_INTENT_TOPICS[:6],
                key="il_topics",
                help="Companies actively researching these topics will surface",
            )
        with _ilc2:
            _il_locations = st.text_input(
                "Location (comma-separated)",
                value="africa",
                key="il_locations",
                help="e.g. 'South Africa, Kenya, Nigeria' or just 'africa'",
            )
            _il_emp = st.multiselect(
                "Employee Size",
                ["1,10", "11,50", "51,200", "201,500", "501,1000", "1001,5000", "5001,10000"],
                default=[],
                key="il_emp",
                help="Leave blank for all sizes",
            )
            _il_keywords = st.text_input(
                "Additional keywords",
                value="",
                key="il_keywords",
                placeholder="e.g. cybersecurity, SOC, cloud",
            )
            _il_num = st.slider("Results per search", 10, 100, 25, 5, key="il_num")

        _il_run = st.button("🔍 Search", type="primary", key="il_run")

    # ── Search ────────────────────────────────────────────────────────────────
    if _il_run or st.session_state.get("il_results"):
        if _il_run:
            _loc_list = [x.strip() for x in _il_locations.split(",") if x.strip()]
            try:
                with st.spinner("Searching Apollo for intent-qualified companies…"):
                    _il_raw, _il_total = _apollo_search_companies(
                        keywords=_il_keywords.strip() or "",
                        locations=_loc_list or None,
                        employee_ranges=_il_emp or None,
                        intent_topics=_il_topics or None,
                        intent_scores=_il_scores or None,
                        num=_il_num,
                    )
                _il_normed = [_norm_org(o) for o in _il_raw]
                st.session_state["il_results"]  = _il_normed
                st.session_state["il_total"]    = _il_total
            except Exception as _ile:
                st.error(f"Apollo error: {_ile}")
                st.stop()

        _il_results = st.session_state.get("il_results", [])
        _il_total   = st.session_state.get("il_total", 0)

        if not _il_results:
            st.info("No results — try broadening the intent topics or score range.")
        else:
            st.caption(f"Showing **{len(_il_results)}** companies · {_il_total:,} total matching")
            st.divider()

            # Regulatory context per country (used in outreach notes)
            _REG_CTX = {
                "south africa": "POPIA enforcement active",
                "nigeria":      "NDPA 2023 in force",
                "kenya":        "Data Protection Act 2019 enforced",
                "ghana":        "Data Protection Act 2012",
                "egypt":        "Personal Data Protection Law No. 151/2020",
                "mauritius":    "Data Protection Act 2017",
                "zimbabwe":     "Data Protection Act 2021",
                "tanzania":     "Personal Data Protection Act 2022",
                "botswana":     "Data Protection Act 2018",
                "rwanda":       "Data Protection and Privacy Law 2021",
            }

            for _ili, _ilorg in enumerate(_il_results):
                _il_name     = _ilorg.get("name", "Unknown")
                _il_domain   = _ilorg.get("domain", "")
                _il_industry = _ilorg.get("industry", "")
                _il_emp_cnt  = _ilorg.get("employees")
                _il_city     = _ilorg.get("city", "")
                _il_country  = _ilorg.get("country", "")
                _il_loc_str  = ", ".join(x for x in [_il_city, _il_country] if x)
                _il_kws      = _ilorg.get("keywords", [])[:8]
                _il_tech     = _ilorg.get("tech", [])
                _il_desc     = _ilorg.get("description", "")
                _il_org_id   = _ilorg.get("id", "")

                _il_score, _il_matched, _il_angles, _il_rationale = _score_org_for_crs(
                    _il_industry, _il_country, _il_emp_cnt, _il_tech,
                    keywords=_il_kws, description=_il_desc,
                )

                # ── AI fallback scoring when rule-based score is 0 ───────────
                _il_ai_scored = False
                if _il_score == 0:
                    _ai_score_key = f"il_ai_score_{_il_org_id or _ili}"
                    if _ai_score_key not in st.session_state:
                        _ai_prompt = (
                            "You are a B2B sales analyst for CRS (Cyber Retaliator Solutions), a South African "
                            "cybersecurity distributor and IBM/Red Hat/SUSE/CompTIA training partner. "
                            "Score this prospect company 0-100 for fit as a CRS customer or reseller.\n\n"
                            f"Company: {_il_name}\n"
                            f"Industry: {_il_industry or 'Unknown'}\n"
                            f"Country: {_il_country or 'Unknown'}\n"
                            f"Employees: {_il_emp_cnt or 'Unknown'}\n"
                            f"Keywords: {', '.join(_il_kws) if _il_kws else 'None'}\n"
                            f"Description: {(_il_desc or '')[:300]}\n"
                            f"Tech stack: {', '.join(_il_tech[:10]) if _il_tech else 'None'}\n\n"
                            "Scoring guide: African HQ = +18, strong cyber/gov/finance sector = +28, "
                            "50-500 employees = +14, relevant tech stack = up to +30. "
                            "Reply ONLY with valid JSON: {\"score\": <int 0-100>, \"rationale\": \"<one sentence>\"}"
                        )
                        try:
                            _raw = _call_ai(_ai_prompt)
                            import re as _re2
                            _jm = _re2.search(r'\{[^}]+\}', _raw or "")
                            if _jm:
                                _jd = json.loads(_jm.group())
                                st.session_state[_ai_score_key] = (
                                    max(0, min(100, int(_jd.get("score", 0)))),
                                    str(_jd.get("rationale", "AI-assessed"))
                                )
                            else:
                                st.session_state[_ai_score_key] = (0, "AI response unparseable")
                        except Exception as _aie:
                            st.session_state[_ai_score_key] = (0, f"AI scoring unavailable: {str(_aie)[:60]}")
                    _ai_s, _ai_rat = st.session_state[_ai_score_key]
                    if _ai_s > 0:
                        _il_score = _ai_s
                        _il_rationale = f"🤖 AI: {_ai_rat}"
                        _il_ai_scored = True

                _il_badge = (
                    "🟢 Excellent" if _il_score >= 60 else
                    "🟡 Good"      if _il_score >= 40 else
                    "🔵 Fair"      if _il_score >= 20 else "⚪ Low"
                )

                # ── Build outreach note ───────────────────────────────────
                _il_reg    = _REG_CTX.get((_il_country or "").lower(), "")
                _il_topics = st.session_state.get("il_topics", _CRS_INTENT_TOPICS[:6])
                # Map topics → recommended products
                _TOPIC_PROD: dict[str, str] = {
                    "Certified Information Systems Security Professional (CISSP)": "CompTIA / IBM training",
                    "Active Cyber Defense": "VECTRA AI + Todyl MXDR",
                    "Cyber & Intelligence": "Flare + VECTRA AI",
                    "Career Training Program": "CompTIA / IBM / Red Hat training",
                    "Chief Information Security Officer (CISO)": "VECTRA AI + Panorays + Flare",
                    "Cyber Essentials (CE)": "SMBsecure + GoldPhish",
                    "Cybersecurity": "VECTRA AI + Todyl + vRx",
                    "Network Security": "VECTRA AI NDR + Todyl SASE",
                    "Information Security": "Flare + Panorays + BeachheadSecure",
                    "Endpoint Security": "BeachheadSecure + VECTRA AI",
                    "Cloud Security": "Aikido + Strobes ASM",
                    "Vulnerability Management": "vRx + Strobes CTEM",
                    "Penetration Testing": "Strobes PTaaS + CRS VAPT",
                    "Security Operations": "VECTRA AI + Todyl MXDR",
                    "Threat Intelligence": "Flare dark web monitoring",
                    "Data Loss Prevention": "BeachheadSecure + Standss SendGuard",
                    "Security Awareness Training": "GoldPhish phishing simulation",
                    "Compliance Management": "Panorays + Telivy + SMBsecure",
                    "Identity and Access Management": "VECTRA ITDR",
                    "Zero Trust Security": "Todyl SASE + VECTRA ITDR",
                    "Managed Security Services": "Todyl MXDR + VECTRA AI",
                    "Incident Response": "VECTRA AI + Todyl MXDR",
                    "GRC": "Panorays + Telivy",
                    "POPIA": "SMBsecure + Telivy + Panorays",
                    "IBM Training": "IBM / Red Hat training",
                    "CompTIA": "CompTIA A+ / Security+ / CySA+ training",
                    "Red Hat": "Red Hat training",
                    "SUSE Linux": "SUSE Linux training",
                }
                _top_prods = list(dict.fromkeys(
                    _TOPIC_PROD.get(t, "") for t in _il_topics
                    if _TOPIC_PROD.get(t, "")
                ))[:3]
                # Best angle from tech stack if available, else from topics
                _lead_prod = _il_angles[0].split(":")[0] if _il_angles else (
                    _top_prods[0] if _top_prods else "VECTRA AI"
                )
                # Construct outreach note
                _out_lines = [
                    f"**{_il_name}** is actively researching "
                    f"{'|'.join(_il_topics[:3]) if _il_topics else 'cybersecurity'} "
                    f"— indicating a buying-cycle trigger.",
                ]
                if _il_industry:
                    _out_lines.append(f"As a **{_il_industry}** organisation"
                                      + (f" in {_il_country}" if _il_country else "")
                                      + (f" ({_il_reg})" if _il_reg else "") + ".")
                if _top_prods:
                    _out_lines.append(f"**Lead with:** {' · '.join(_top_prods[:2])}")
                if _il_angles:
                    _out_lines.append(f"**Tech angle:** {_il_angles[0]}")
                if _il_reg:
                    _out_lines.append(f"**Reg hook:** Use {_il_reg} to open the compliance conversation.")
                _il_outreach = "\n\n".join(_out_lines)

                with st.container(border=True):
                    _ilh1, _ilh2, _ilh3 = st.columns([4, 2, 1])
                    with _ilh1:
                        _domain_link = (f"[{_il_domain}](https://{_il_domain})"
                                        if _il_domain else "")
                        st.markdown(f"**{_il_name}**" +
                                    (f"  ·  {_domain_link}" if _domain_link else ""))
                        st.caption(
                            ("🏭 " + _il_industry if _il_industry else "") +
                            ("  ·  📍 " + _il_loc_str if _il_loc_str else "") +
                            ("  ·  👥 " + f"{_il_emp_cnt:,}" if _il_emp_cnt else "")
                        )
                        if _il_kws:
                            st.caption("🏷️ " + "  ·  ".join(_il_kws[:5]))
                    with _ilh2:
                        if _il_matched:
                            st.caption("🔧 **Tech signals:**")
                            for _ilm in _il_matched[:3]:
                                _opp_key = _ilm.lower()
                                _opp = _TECH_OPP.get(_opp_key, {})
                                st.caption(f"• {_ilm} → {_opp.get('sol', '')}")
                        else:
                            st.caption("📋 " + (_il_industry or "No tech data"))
                    with _ilh3:
                        st.metric("CRS Fit", f"{_il_score}/100")
                        st.caption(_il_badge)

                    # Score rationale
                    st.caption(f"📊 **Score rationale:** {_il_rationale}")

                    if _il_angles:
                        for _ang in _il_angles[:2]:
                            st.caption(f"💡 {_ang}")

                    # Outreach note — inline, below company header
                    st.markdown(_il_outreach)
                    _copy_block(_il_outreach, label="📋 Copy outreach note",
                                key=f"il_copy_{_ili}", flat=True)

                    # ── Find decision makers → routes to DM tab ──────────────
                    with st.expander("👥 Find decision makers", expanded=False):
                        _il_sol_pick = st.selectbox(
                            "CRS solution focus",
                            list(_CRS_DM_TITLES.keys()),
                            key=f"il_sol_{_ili}",
                        )
                        if st.button("👥 Find decision makers →", key=f"il_find_{_ili}",
                                     type="primary", use_container_width=True):
                            _queue_dm_and_go(
                                company=_il_name, solution=_il_sol_pick,
                                org_id=_il_org_id, domain=_il_domain,
                                industry=_il_industry, country=_il_country,
                                num=8, source="🔥 Intent Leads",
                            )

# ══════════════════════════════════════════════════════════════════════════════
# TAB 5 — LINKEDIN DORK
# ══════════════════════════════════════════════════════════════════════════════
def _as_list(v) -> list:
    if isinstance(v, list): return v
    if not v: return []
    try: return json.loads(v)
    except Exception: return []

if _page == "🔍 LinkedIn Dork":
    _colored_header(label="LinkedIn Lead Discovery", description="Dork LinkedIn profiles, cache enrichment in Supabase, auto-check Monday CRM, find contact info via Apollo / Hunter, edit fields, then push to Monday.", color_name="blue-30")

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
    st.caption(" · ".join([
        "🟢 Google CSE" if _has_google else "⚪ Google CSE (need GOOGLE_API_KEY+GOOGLE_CSE_ID)",
        "🟢 SerpAPI"    if _has_serper else "⚪ SerpAPI",
        "🟢 Apollo"     if _has_apollo else "⚪ Apollo",
        "🟢 Hunter"     if _has_hunter else "⚪ Hunter",
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
@st.cache_data(ttl=1800)
def _flare_token() -> str:
    """Obtain a short-lived Flare JWT. Raises RuntimeError on any failure so the
    caller can surface a real error message instead of silently returning []."""
    api_key   = st.secrets.get("FLARE_API_KEY",   "") or os.getenv("FLARE_API_KEY",   "")
    tenant_id = st.secrets.get("FLARE_TENANT_ID", "") or os.getenv("FLARE_TENANT_ID", "")
    if not api_key:
        raise RuntimeError("FLARE_API_KEY not configured")
    payload: dict = {}
    if tenant_id:
        try:
            payload["tenant_id"] = int(tenant_id)
        except ValueError:
            payload["tenant_id"] = tenant_id
    req = _urlreq.Request(
        "https://api.flare.io/tokens/generate",
        data=json.dumps(payload).encode(),
        headers={"Authorization": api_key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _urlreq.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
    except _urlerr.HTTPError as e:
        body = ""
        try: body = e.read().decode("utf-8", errors="ignore")[:300]
        except Exception: pass
        raise RuntimeError(f"Flare token HTTP {e.code}: {body or e.reason}") from e
    token = data.get("token") or data.get("jwt") or data.get("access_token")
    if not token:
        raise RuntimeError(f"Flare token response had no token field: {str(data)[:200]}")
    return token


def _flare_search(query: str, event_types: list, days_back: int = 30,
                  size: int = 20) -> list:
    token   = _flare_token()          # raises on failure — caller handles it
    from_ts = (_dt.datetime.now(_dt.timezone.utc)
               - _dt.timedelta(days=days_back)).isoformat()
    # Omit "from" entirely rather than sending null, which some API versions reject
    body = json.dumps({
        "query": {"type": "query_string", "query_string": query},
        "filters": {
            "type": event_types,
            "estimated_created_at": {"gte": from_ts},
        },
        "size": size,
        "order": "desc",
    }).encode()
    req = _urlreq.Request(
        "https://api.flare.io/firework/v4/events/global/_search",
        data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _urlreq.urlopen(req, timeout=25) as r:
            return json.loads(r.read()).get("items", [])
    except _urlerr.HTTPError as e:
        body_txt = ""
        try: body_txt = e.read().decode("utf-8", errors="ignore")[:300]
        except Exception: pass
        raise RuntimeError(f"Flare search HTTP {e.code}: {body_txt or e.reason}") from e


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


def _intel_pre_score(event_type: str, source_count: int, description: str) -> tuple:
    """Quick deterministic CRS Applicability score before AI rating.
    Returns (score 0-100, urgency 'high'|'medium'|'low', breakdown dict)."""
    score = 0
    bd: dict = {}

    # Event severity (0-30)
    _sev = {
        "ransomleak": 30, "ransomware": 30,
        "leaked-credential": 25, "stealer-log": 22,
        "paste": 18, "chat-message": 14, "news": 8,
    }
    sev = _sev.get(event_type.lower().replace(" ","_"), 8)
    score += sev
    bd["event_severity"] = sev

    # Source confidence (0-24)
    src_pts = min(source_count * 8, 24)
    score  += src_pts
    bd["source_confidence"] = src_pts

    # Sector / keyword fit (0-30)
    desc_lc = description.lower()
    strong  = ["bank","financial","government","health","telco","insurance",
                "mining","energy","defence","defense","university","pension",
                "municipality","municipality","water","electricity","port"]
    weak    = ["construction","catering","cleaning","stationery","vehicle",
                "furniture","linen","laundry","food","fleet","grass"]
    sect_pts = sum(5 for kw in strong if kw in desc_lc)
    sect_pts -= sum(15 for kw in weak if kw in desc_lc)
    sect_pts = max(-20, min(30, sect_pts))
    score   += sect_pts
    bd["sector_fit"] = max(0, sect_pts)

    # Urgency signals (0-20)
    urg_kw  = ["ransomware","encrypted","ransom","extortion","exfiltrat",
               "breach","stolen","leaked","exposed","compromised"]
    urg_pts = min(sum(5 for kw in urg_kw if kw in desc_lc), 20)
    score  += urg_pts
    bd["urgency_signals"] = urg_pts

    score   = max(0, min(100, score))
    urgency = "high" if score >= 65 else "medium" if score >= 40 else "low"
    return score, urgency, bd


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

def _get_region_config() -> dict:
    """Return Africa-focused feed/country/search config."""
    return {
        "label":            "Africa",
        "countries":        _INTEL_COUNTRIES,
        "default_countries":["South Africa", "Kenya", "Nigeria", "Ghana"],
        "feeds":            _AFRICAN_FEEDS,
        "sites_google":     _AFRICAN_SITES_GOOGLE,
        "geo_qualifier":    "Africa",
    }


_INTEL_COUNTRIES = [
    "South Africa", "Kenya", "Nigeria", "Ghana", "Tanzania", "Uganda",
    "Zambia", "Rwanda", "Botswana", "Namibia", "Zimbabwe", "Malawi",
    "Ethiopia", "Egypt", "Mozambique", "Mauritius", "Lesotho", "Eswatini",
    "Sierra Leone", "The Gambia", "Liberia", "Cameroon", "Senegal",
]

# Flare v4 enum values — ONLY these three are confirmed valid by the API.
# Any other value causes HTTP 422 REQUEST_VALIDATION_ERROR.
_INTEL_EVENT_TYPES = {
    "Ransomware / Leak":  "ransomleak",
    "Market Listing":     "listing",
    "Forum Attachment":   "attachment",
}

_INTEL_GOOGLE_TERMS = (
    '"data breach" OR "ransomware" OR "cyber attack" OR "hacked" OR '
    '"credential leak" OR "data leak" OR "security incident"'
)

if _page == "🛡️ Lead Intelligence":
    _rc = _get_region_config()
    _region_label = _rc["label"]
    _colored_header(label=f"Cyber Event Lead Intelligence — {_region_label}", description=f"Surface {_region_label} companies hit by ransomware, breaches, or dark-web exposure. AI-rates each as a CRS lead, then lets you find the right contacts.", color_name="violet-70")

    _ii1, _ii2, _ii3, _ii4 = st.columns([3, 2, 1, 1])
    with _ii1:
        _avail_countries = _rc["countries"]
        if st.checkbox("Select all", key="intel_ctry_all"):
            st.session_state["intel_countries"] = _avail_countries[:]
        elif not st.session_state.get("intel_ctry_all"):
            st.session_state.setdefault("intel_countries", _rc["default_countries"])
        # Reset if saved countries no longer match region
        _saved_ctry = st.session_state.get("intel_countries", [])
        if _saved_ctry and all(c not in _avail_countries for c in _saved_ctry):
            st.session_state["intel_countries"] = _rc["default_countries"]
        _i_countries = st.multiselect("Countries", _avail_countries, key="intel_countries")

    with _ii2:
        if st.checkbox("Select all", key="intel_evt_all"):
            st.session_state["intel_evt_types"] = list(_INTEL_EVENT_TYPES.keys())
        elif not st.session_state.get("intel_evt_all"):
            st.session_state.setdefault("intel_evt_types",
                                        ["Ransomware / Leak", "Market Listing", "Forum Attachment"])
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
    _i_src_apollo = bool(st.secrets.get("APOLLO_API_KEY","") or os.getenv("APOLLO_API_KEY",""))
    _src_col1, _src_col2 = st.columns([4, 1])
    with _src_col1:
        st.caption("Sources: " + "  ·  ".join([
            "🟢 Flare.io"    if _i_src_flare  else "⚪ Flare.io (add FLARE_API_KEY)",
            "🟢 Google News" if _i_src_google else "⚪ Google News (add SERPAPI_API_KEY)",
            f"🟢 RSS ({_region_label})",
            "🟢 Apollo contacts" if _i_src_apollo else "⚪ Apollo (add APOLLO_API_KEY)",
        ]))
    with _src_col2:
        if _i_src_flare and st.button("🔧 Test Flare", key="flare_test",
                                       use_container_width=True):
            with st.spinner("Testing Flare connection…"):
                _flare_token.clear()   # bust cache so we get a live result
                try:
                    _ft = _flare_token()
                    st.success(f"✅ Flare token OK ({len(_ft)} chars)")
                except Exception as _fte:
                    st.error(f"Flare error: {_fte}")

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
                        for _fe in _fevts:  # noqa: E501
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
                        _ferr_msg = str(_fe2)
                        st.warning(f"⚠️ Flare error ({_ic}): {_ferr_msg[:200]}")
                        _i_src_flare = False  # stop retrying for subsequent countries

                # ── Google News (broad regional context) ────────────────────
                if _i_src_google:
                    try:
                        _geo_q = _rc["geo_qualifier"]
                        _gq = (f'"{_ic}" {_geo_q} {_INTEL_GOOGLE_TERMS}'
                               if _geo_q else f'"{_ic}" {_INTEL_GOOGLE_TERMS}')
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

                # ── Google — region-specific publications only ──────────────
                if _i_src_google:
                    try:
                        _sites = _rc["sites_google"]
                        _feeds = _rc["feeds"]
                        _gq2 = f'({_sites}) "{_ic}" {_INTEL_GOOGLE_TERMS}'
                        for _gn2 in _news_search(_gq2, num=int(_i_per_ctry)):
                            _co3      = _extract_company_from_news(
                                _gn2["title"], _gn2["snippet"], _ic)
                            _fd2      = f"{_gn2['title']} — {_gn2['snippet']}"
                            _src_name = (next(
                                (s for s in _feeds
                                 if s.split()[0].lower() in _gn2["url"].lower()),
                                f"{_region_label} Press",
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

                # ── RSS feeds (region-aware) ─────────────────────────────────
                try:
                    _cyber_kw2 = (
                        "breach","ransomware","hack","cyber","attack","leak",
                        "credential","malware","phishing","data",
                    )
                    for _fn2, _fu2 in _rc["feeds"].items():
                        for _rss_item in _fetch_rss_feed(
                            _fn2, _fu2,
                            keywords=_cyber_kw2 + (_ic.lower(),),
                            days_back=int(_i_days),
                        )[:int(_i_per_ctry)]:
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
                                "source":        _rss_item.get("source", _fn2),
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

            # Flatten groups → merged result list with pre-scores
            _intel_dedup: list = []
            for _ck2, g2 in _groups.items():
                _merged = dict(g2["best"])
                _merged["source_count"]          = len(g2["sources"])
                _merged["all_sources"]           = sorted(g2["sources"])
                _merged["combined_description"]  = "\n".join(g2["descriptions"])[:1500]
                _merged["persons_found"]         = _dedupe_persons(g2["persons"])
                # Pre-score for CRS Applicability ranking (before AI rating)
                _ps, _pu, _pbd = _intel_pre_score(
                    _merged.get("event_type", "news"),
                    _merged["source_count"],
                    _merged.get("combined_description", _merged.get("description", "")),
                )
                _merged["pre_score"]    = _ps
                _merged["pre_urgency"]  = _pu
                _merged["pre_breakdown"] = _pbd
                _intel_dedup.append(_merged)

            # Sort by composite: pre_score DESC, then source_count DESC
            _intel_dedup.sort(key=lambda x: (-x["pre_score"], -x["source_count"]))

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

# ══════════════════════════════════════════════════════════════════════════════
# PAGE 6 — WEEKLY LEADS
# ══════════════════════════════════════════════════════════════════════════════
if _page == "💡 Weekly Leads":
    _colored_header(label="Weekly Lead Recommendations", description="Apollo-powered proactive pipeline: search by CRS solution and African sector, scored for CRS-portfolio fit and auto-checked against Monday CRM.", color_name="green-30")

    _has_apo_wl = bool(st.secrets.get("APOLLO_API_KEY","") or os.getenv("APOLLO_API_KEY",""))
    if not _has_apo_wl:
        st.warning("Apollo API key required. Add APOLLO_API_KEY to your secrets.")
        st.stop()

    # ── Controls ──────────────────────────────────────────────────────────────
    _wl_c1, _wl_c2, _wl_c3 = st.columns([3, 3, 2])
    with _wl_c1:
        _wl_solutions = st.multiselect(
            "Solution focus",
            list(_CRS_DM_TITLES.keys()),
            default=["All CRS products"],
            key="wl_solutions",
            help="Drives which decision-maker titles Apollo searches for",
        )
    with _wl_c2:
        _WL_SECTORS = [
            "financial services",
            "banking",
            "insurance",
            "government",
            "public sector",
            "healthcare",
            "hospital",
            "telecommunications",
            "mining",
            "energy",
            "education",
            "retail",
            "manufacturing",
            "logistics",
            "technology",
        ]
        _wl_sectors = st.multiselect(
            "Industry / sector",
            _WL_SECTORS,
            default=["financial services", "government", "healthcare", "telecommunications"],
            key="wl_sectors",
        )
    with _wl_c3:
        _wl_countries = st.multiselect(
            "Countries",
            ["South Africa", "Nigeria", "Kenya", "Ghana", "Tanzania",
             "Uganda", "Zimbabwe", "Botswana", "Namibia", "Rwanda"],
            default=["South Africa", "Nigeria", "Kenya"],
            key="wl_countries",
        )

    _wl_num = st.slider("Max results per search", 5, 20, 10, step=5, key="wl_num")

    _wl_run = st.button(
        "🔄 Refresh leads", type="primary", key="wl_run",
        use_container_width=False,
    )

    # ── Run Apollo ────────────────────────────────────────────────────────────
    if _wl_run or "wl_results" not in st.session_state:
        if not _wl_solutions:
            st.warning("Select at least one solution focus.")
        else:
            # Deduplicate titles across selected solutions
            _wl_titles_set: list[str] = []
            for _sol_k in _wl_solutions:
                for _t in _CRS_DM_TITLES.get(_sol_k, []):
                    if _t not in _wl_titles_set:
                        _wl_titles_set.append(_t)

            _wl_raw_results: list[dict] = []
            _seen_apo_ids: set[str] = set()
            _total_searches = len(_wl_sectors) * len(_wl_countries)
            _prog_bar = st.progress(0.0, text="Searching Apollo…")
            _prog_step = 0

            for _wl_sector in (_wl_sectors or ["cybersecurity"]):
                for _wl_ctry in (_wl_countries or ["South Africa"]):
                    try:
                        _wl_payload: dict = {
                            "per_page": int(_wl_num),
                            "page": 1,
                            "person_titles": _wl_titles_set[:10],
                            "q_keywords": _wl_sector,
                            "person_locations": [_wl_ctry],
                        }
                        _wl_raw = _apollo_post(
                            "mixed_people/api_search", _wl_payload
                        ).get("people") or []
                        for _p in _wl_raw:
                            _pid = _p.get("id", "")
                            if _pid and _pid in _seen_apo_ids:
                                continue
                            if _pid:
                                _seen_apo_ids.add(_pid)
                            _normed = _norm_apollo(_p)
                            _normed["_sector_searched"] = _wl_sector
                            _normed["_country_searched"] = _wl_ctry
                            # Score for CRS fit
                            _org_industry = (
                                (_p.get("organization") or {}).get("industry", "")
                                or _wl_sector
                            )
                            _normed["crs_fit"] = _crs_fit_score(
                                _normed.get("title", ""),
                                _org_industry,
                                _wl_ctry,
                                _normed.get("has_email", False),
                                bool(_normed.get("has_phone")),
                            )
                            _wl_raw_results.append(_normed)
                    except Exception as _wl_err:
                        st.warning(f"Apollo ({_wl_sector} / {_wl_ctry}): {str(_wl_err)[:100]}")
                    _prog_step += 1
                    _prog_bar.progress(
                        min(_prog_step / max(_total_searches, 1), 1.0),
                        text=f"Searched: {_wl_sector} / {_wl_ctry}",
                    )

            _prog_bar.empty()
            # Sort by CRS fit descending
            _wl_raw_results.sort(key=lambda r: -r.get("crs_fit", 0))
            st.session_state["wl_results"]      = _wl_raw_results
            st.session_state["wl_refreshed_at"] = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    # ── Display ───────────────────────────────────────────────────────────────
    _wl_results: list[dict] = st.session_state.get("wl_results", [])
    _wl_ts = st.session_state.get("wl_refreshed_at", "")
    if _wl_ts:
        st.caption(f"Last refreshed: {_wl_ts} · {len(_wl_results)} contacts")

    if not _wl_results:
        st.info("Click **Refresh leads** to pull this week's recommended contacts from Apollo.")
    else:
        # ── Fit-score filter ──────────────────────────────────────────────────
        _wl_min_fit = st.slider(
            "Minimum CRS-fit score", 0, 100, 30, step=5, key="wl_min_fit",
        )
        _wl_filtered = [r for r in _wl_results if r.get("crs_fit", 0) >= _wl_min_fit]
        st.markdown(f"**{len(_wl_filtered)} leads** (fit ≥ {_wl_min_fit}%)")

        for _wi, _wc in enumerate(_wl_filtered):
            _wcrm_sk = f"wl_crm_{_wi}"
            _wph_sk  = f"wl_ph_{_wi}"
            _wem_sk  = f"wl_em_{_wi}"
            _wname   = (st.session_state.get(f"wl_nm_{_wi}")
                        or _wc.get("name") or f"Contact {_wi+1}")
            _wfit    = _wc.get("crs_fit", 0)

            # Auto CRM check
            _wcrm = _auto_crm_check(
                _wc.get("name", ""), _wc.get("email", ""),
                _wc.get("linkedin", ""), _wcrm_sk,
            )
            _wmon_email = (_wcrm.get("crm_email", "") if _wcrm and _wcrm.get("on_crm") else "")
            _wmon_phone = (_wcrm.get("crm_phone", "") if _wcrm and _wcrm.get("on_crm") else "")

            # Fit colour band
            _fit_colour = (
                "🟢" if _wfit >= 70
                else "🟡" if _wfit >= 45
                else "🔴"
            )

            with st.container(border=True):
                _wA, _wB = st.columns([4, 2])
                with _wA:
                    _w_hdr = f"### {_fit_colour} {_wname}"
                    if _wcrm and _wcrm.get("on_crm"):
                        _w_hdr += "  `✓ CRM`"
                    st.markdown(_w_hdr)
                    _wrow = [x for x in [_wc.get("title"), _wc.get("company")] if x]
                    if _wrow:
                        st.caption(" · ".join(_wrow))
                    _wtags = []
                    if _wc.get("_sector_searched"):
                        _wtags.append(f"🏭 {_wc['_sector_searched'].title()}")
                    if _wc.get("_country_searched"):
                        _wtags.append(f"📍 {_wc['_country_searched']}")
                    if _wtags:
                        st.caption("  ".join(_wtags))
                    if _wc.get("linkedin"):
                        st.markdown(f"[LinkedIn]({_wc['linkedin']})")
                with _wB:
                    st.metric("CRS Fit", f"{_wfit}%")
                    _we_disp = _wmon_email or _wc.get("email", "")
                    _wp_disp = _wmon_phone or _wc.get("phone", "")
                    if _we_disp:
                        _w_esrc = "✅ Monday" if _wmon_email else "Apollo"
                        st.markdown(f"📧 `{_we_disp}` _{_w_esrc}_")
                    elif _wc.get("has_email"):
                        st.caption("📧 Email available (enrich to reveal)")
                    if _wp_disp:
                        st.markdown(f"📞 `{_wp_disp}`")
                    elif _wc.get("has_phone"):
                        st.caption("📞 Phone available (enrich to reveal)")

                # ── Enrich / push row ─────────────────────────────────────────
                _wact1, _wact2, _wact3 = st.columns(3)
                with _wact1:
                    if not _we_disp and _wc.get("id") and not st.session_state.get(_wem_sk):
                        if st.button("💳 Enrich (email + phone)", key=f"wl_enrich_{_wi}",
                                     use_container_width=True):
                            with st.spinner("Apollo enrichment…"):
                                try:
                                    _wenr = _enrich_contact(
                                        apollo_id=_wc.get("id",""),
                                        name=_wname,
                                        linkedin=_wc.get("linkedin",""),
                                        company=_wc.get("company",""),
                                    )
                                    if _wenr.get("name"):
                                        st.session_state[f"wl_nm_{_wi}"] = _wenr["name"]
                                        _wl_results[_wi]["name"] = _wenr["name"]
                                    st.session_state[_wem_sk] = _wenr.get("email", "")
                                    st.session_state[_wph_sk] = _wenr.get("phone", "")
                                    st.rerun()
                                except Exception as _wee:
                                    st.error(f"Enrichment failed: {_wee}")
                    elif st.session_state.get(_wem_sk):
                        st.success(f"📧 {st.session_state[_wem_sk]}")
                with _wact2:
                    if monday_active:
                        _wpush_pl = {
                            "name":           _wname,
                            "title":          _wc.get("title", ""),
                            "company":        _wc.get("company", ""),
                            "email":          st.session_state.get(_wem_sk) or _we_disp,
                            "phone":          st.session_state.get(_wph_sk) or _wp_disp,
                            "linkedin":       _wc.get("linkedin", ""),
                            "accuracy_score": str(_wfit),
                            "provider_chain": f"Weekly Leads · Apollo",
                        }
                        _w_push_lbl = (
                            "♻️ Update Monday" if (_wcrm and _wcrm.get("on_crm"))
                            else "📋 Push to Monday"
                        )
                        if st.button(_w_push_lbl, key=f"wl_push_{_wi}",
                                     use_container_width=True,
                                     type="primary" if not (_wcrm and _wcrm.get("on_crm")) else "secondary"):
                            with st.spinner("Syncing…"):
                                try:
                                    _wmr = sync_lead_to_monday(_wpush_pl)
                                    st.success(f"{_wmr.get('action','done').title()} · "
                                               f"ID: {_wmr.get('item_id')}")
                                    del st.session_state[_wcrm_sk]
                                except Exception as _wpe:
                                    st.error(f"Push failed: {_wpe}")
                with _wact3:
                    _copy_block(
                        "\n".join(l for l in [
                            f"NAME: {_wname}",
                            f"Title: {_wc.get('title','')}",
                            f"Company: {_wc.get('company','')}",
                            f"Email: {st.session_state.get(_wem_sk) or _we_disp}",
                            f"Phone: {st.session_state.get(_wph_sk) or _wp_disp}",
                            f"LinkedIn: {_wc.get('linkedin','')}",
                            f"CRS Fit: {_wfit}%",
                            f"Sector: {_wc.get('_sector_searched','')}",
                        ] if l),
                        key=f"wl_copy_{_wi}",
                    )

# ══════════════════════════════════════════════════════════════════════════════
# PAGE 7 — END-USER TARGETS
# ══════════════════════════════════════════════════════════════════════════════
if _page == "🎯 End-User Targets":
    _colored_header(label="End-User Targets", description="Find African companies by sector and size, score them on CRS-portfolio fit using their tech stack, then drill into decision-maker contacts.", color_name="orange-30")

    _eu_has_apo = bool(st.secrets.get("APOLLO_API_KEY","") or os.getenv("APOLLO_API_KEY",""))
    if not _eu_has_apo:
        st.warning("Apollo API key required. Add APOLLO_API_KEY to secrets.")
        st.stop()

    # ── Search controls ───────────────────────────────────────────────────────
    _eu_c1, _eu_c2, _eu_c3 = st.columns(3)
    with _eu_c1:
        _EU_INDUSTRIES = [
            "financial services", "banking", "insurance",
            "government administration", "public sector",
            "hospital & health care", "healthcare",
            "telecommunications", "information technology",
            "mining & metals", "oil & energy",
            "education management", "higher education",
            "retail", "manufacturing",
            "logistics & supply chain", "law practice",
            "media & broadcasting", "real estate",
        ]
        _eu_industries = st.multiselect(
            "Industry / sector",
            _EU_INDUSTRIES,
            default=["financial services", "government administration",
                     "hospital & health care", "telecommunications"],
            key="eu_industries",
        )
    with _eu_c2:
        _eu_countries = st.multiselect(
            "Countries",
            ["South Africa", "Nigeria", "Kenya", "Ghana",
             "Tanzania", "Uganda", "Zimbabwe", "Botswana",
             "Namibia", "Rwanda", "Zambia", "Mozambique"],
            default=["South Africa", "Nigeria", "Kenya"],
            key="eu_countries",
        )
    with _eu_c3:
        _EU_EMP_RANGES = {
            "SME  (50 – 200)":     ["50,200"],
            "Mid  (200 – 1 000)":  ["201,1000"],
            "Large (1 000 – 5 000)": ["1001,5000"],
            "Enterprise (5 000+)": ["5001,20000"],
            "All sizes":           [],
        }
        _eu_size_key = st.selectbox(
            "Company size", list(_EU_EMP_RANGES.keys()),
            index=1, key="eu_size",
        )
        _eu_emp_ranges = _EU_EMP_RANGES[_eu_size_key]

    _eu_kw_col, _eu_num_col = st.columns([4, 1])
    with _eu_kw_col:
        _eu_keyword = st.text_input(
            "Additional keyword (optional)",
            key="eu_keyword",
            placeholder="e.g. cybersecurity, POPIA, digital transformation",
        )
    with _eu_num_col:
        _eu_num = st.number_input("Per search", 5, 25, 10, step=5, key="eu_num")

    _eu_run = st.button("🔍 Find target companies", type="primary", key="eu_run")

    # ── Run company search ────────────────────────────────────────────────────
    if _eu_run:
        if not _eu_industries and not _eu_keyword:
            st.warning("Select at least one industry or enter a keyword.")
        else:
            _eu_raw: list[dict] = []
            _eu_seen: set[str] = set()
            _eu_searches = len(_eu_industries or [""]) * len(_eu_countries or ["South Africa"])
            _eu_pb = st.progress(0.0, text="Searching Apollo…")
            _eu_step = 0
            for _eu_ind in (_eu_industries or [""]):
                for _eu_ctr in (_eu_countries or ["South Africa"]):
                    try:
                        kw_parts = [p for p in [_eu_ind, _eu_keyword] if p]
                        _eu_orgs, _ = _apollo_search_companies(
                            keywords=" ".join(kw_parts),
                            locations=[_eu_ctr],
                            employee_ranges=_eu_emp_ranges or None,
                            num=int(_eu_num),
                        )
                        for _eo in _eu_orgs:
                            _eid = _eo.get("id","") or _eo.get("name","")
                            if _eid in _eu_seen:
                                continue
                            _eu_seen.add(_eid)
                            _enorm = _norm_org(_eo)
                            _enorm["_searched_ind"] = _eu_ind
                            _enorm["_searched_ctr"] = _eu_ctr
                            _escore, _etech_matched, _eangles, _erationale = _score_org_for_crs(
                                _enorm["industry"] or _eu_ind,
                                _enorm["country"]  or _eu_ctr,
                                _enorm["employees"],
                                _enorm["tech"],
                                keywords=_enorm.get("keywords", []),
                                description=_enorm.get("description", ""),
                            )
                            _enorm["crs_score"]    = _escore
                            _enorm["tech_matched"] = _etech_matched
                            _enorm["opp_angles"]   = _eangles
                            _enorm["rationale"]    = _erationale
                            _eu_raw.append(_enorm)
                    except Exception as _eue:
                        st.warning(f"Apollo ({_eu_ind}/{_eu_ctr}): {str(_eue)[:100]}")
                    _eu_step += 1
                    _eu_pb.progress(
                        min(_eu_step / max(_eu_searches, 1), 1.0),
                        text=f"{_eu_ind} / {_eu_ctr}",
                    )
            _eu_pb.empty()
            _eu_raw.sort(key=lambda o: -o.get("crs_score", 0))
            st.session_state["eu_results"]     = _eu_raw
            st.session_state["eu_refreshed"]   = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    # ── Display ───────────────────────────────────────────────────────────────
    _eu_results: list[dict] = st.session_state.get("eu_results", [])
    _eu_ts = st.session_state.get("eu_refreshed", "")
    if _eu_ts:
        st.caption(f"Last search: {_eu_ts} · {len(_eu_results)} companies")

    if not _eu_results:
        st.info("Click **Find target companies** to search.")
    else:
        _eu_min = st.slider("Minimum CRS interest score", 0, 100, 20, step=5, key="eu_min")
        _eu_filt = [r for r in _eu_results if r.get("crs_score", 0) >= _eu_min]
        st.markdown(f"**{len(_eu_filt)} companies** (score ≥ {_eu_min})")

        for _ei, _ec in enumerate(_eu_filt):
            _ename  = _ec.get("name", "Unknown")
            _escore = _ec.get("crs_score", 0)
            _eind   = _ec.get("industry") or _ec.get("_searched_ind", "")
            _ectr   = _ec.get("country") or _ec.get("_searched_ctr", "")
            _eemp   = _ec.get("employees")
            _etech  = _ec.get("tech_matched", [])
            _eangles = _ec.get("opp_angles", [])
            _efit   = "🟢" if _escore >= 65 else "🟡" if _escore >= 40 else "🔴"

            with st.container(border=True):
                _ea, _eb = st.columns([4, 2])
                with _ea:
                    st.markdown(f"### {_efit} {_ename}")
                    _emeta = [x for x in [_eind.title(), _ectr,
                                          f"{_eemp:,} employees" if _eemp else ""] if x]
                    if _emeta:
                        st.caption("  ·  ".join(_emeta))
                    if _ec.get("description"):
                        st.caption(_ec["description"][:160])
                    _elinks = []
                    if _ec.get("linkedin"):
                        _elinks.append(f"[LinkedIn]({_ec['linkedin']})")
                    if _ec.get("domain"):
                        _elinks.append(f"[Website](https://{_ec['domain']})")
                    if _elinks:
                        st.markdown("  ·  ".join(_elinks))
                with _eb:
                    st.metric("CRS Interest", f"{_escore}%")
                    if _ec.get("phone"):
                        st.markdown(f"📞 {_ec['phone']}")

                # Score rationale
                _erat = _ec.get("rationale", "")
                if _erat:
                    st.caption(f"📊 {_erat}")

                # Tech stack badges
                if _etech:
                    st.markdown(
                        "**Tech signals:** " + "  ".join(f"`{t}`" for t in _etech)
                    )

                # Opportunity angles
                if _eangles:
                    with st.expander("💡 CRS opportunity angles", expanded=(_escore >= 60)):
                        for _ang in _eangles:
                            st.markdown(f"- {_ang}")

                # ── Contact finder → routes to DM tab ────────────────────────
                with st.expander(f"👥 Find contacts at {_ename}", expanded=False):
                    _ecs1, _ecs2 = st.columns([3, 3])
                    with _ecs1:
                        _eu_sol = st.selectbox(
                            "Solution focus",
                            list(_CRS_DM_TITLES.keys()),
                            key=f"eu_sol_{_ei}", index=0,
                        )
                    with _ecs2:
                        _eu_loc_override = st.text_input(
                            "Country (optional override)",
                            value=_ectr,
                            key=f"eu_loc_{_ei}",
                        )
                    if st.button("👥 Find decision makers →", key=f"eu_find_{_ei}",
                                 type="primary", use_container_width=True):
                        _queue_dm_and_go(
                            company=_ename, solution=_eu_sol,
                            org_id=_ec.get("id", ""), domain=_ec.get("domain", ""),
                            location=_eu_loc_override,
                            industry=_eind, country=_ectr,
                            num=8, source="🎯 End-User Targets",
                        )

# ══════════════════════════════════════════════════════════════════════════════
# TAB — DECISION MAKERS
# ══════════════════════════════════════════════════════════════════════════════
if _page == "👥 Decision Makers":
    _colored_header(
        label="Decision Makers",
        description="Apollo contact searches queued from Intent Leads, End-User Targets, and Lead Verification — all in one place.",
        color_name="violet-70",
    )

    _dm_has_apo = bool(st.secrets.get("APOLLO_API_KEY","") or os.getenv("APOLLO_API_KEY",""))
    _dm_queue: list = st.session_state.get("dm_queue", [])

    if not _dm_queue:
        st.info("No searches queued yet. Click **👥 Find decision makers →** from any company card in Intent Leads, End-User Targets, or Lead Verification to search here.")
    else:
        _dma, _dmb = st.columns([6, 2])
        with _dma:
            st.markdown(f"**{len(_dm_queue)} compan{'y' if len(_dm_queue)==1 else 'ies'} queued**")
        with _dmb:
            if st.button("🗑️ Clear all", key="dm_clear_all"):
                st.session_state["dm_queue"] = []
                for _k in list(st.session_state.keys()):
                    if _k.startswith("dm_res_") or _k.startswith("dm_nm_") or _k.startswith("dm_em_") or _k.startswith("dm_ph_"):
                        del st.session_state[_k]
                st.rerun()

        for _dqi, _dq in enumerate(_dm_queue):
            _dq_company  = _dq["company"]
            _dq_solution = _dq["solution"]
            _dq_source   = _dq.get("source", "")
            _dq_key      = _dq["key"]
            _dq_res_key  = f"dm_res_{_dq_key}"
            _dq_industry = _dq.get("industry", "")
            _dq_country  = _dq.get("country", "")

            st.divider()
            _dqh1, _dqh2, _dqh3 = st.columns([4, 2, 1])
            with _dqh1:
                st.markdown(f"### 🏢 {_dq_company}")
                _dq_meta = [x for x in [_dq_solution, _dq_country or _dq.get("location","")] if x]
                if _dq_meta: st.caption("  ·  ".join(_dq_meta))
                if _dq_source: st.caption(f"from {_dq_source}")
            with _dqh2:
                _dq_contacts = st.session_state.get(_dq_res_key)
                if _dq_contacts is not None:
                    _dq_refresh = st.button("🔄 Re-search", key=f"dm_refresh_{_dqi}", use_container_width=True)
                else:
                    _dq_refresh = False
            with _dqh3:
                if st.button("✕", key=f"dm_remove_{_dqi}", help="Remove this company"):
                    st.session_state["dm_queue"] = [q for q in _dm_queue if q["key"] != _dq_key]
                    st.session_state.pop(_dq_res_key, None)
                    st.rerun()

            # ── Run search (auto on first visit, or on refresh) ──────────────
            _dq_contacts = st.session_state.get(_dq_res_key)
            if _dq_refresh:
                st.session_state.pop(_dq_res_key, None)
                _dq_contacts = None
            if (_dq_contacts is None) and _dm_has_apo:
                with st.spinner(f"Apollo: {_dq_solution} contacts at {_dq_company}…"):
                    try:
                        _dq_raw = _apollo_search_people(
                            company=_dq_company,
                            num=_dq.get("num", 8),
                            titles=_dq["titles"],
                            locations=[_dq["location"]] if _dq.get("location") else None,
                            org_id=_dq.get("org_id",""),
                            domain=_dq.get("domain",""),
                        )
                        _dq_normed = []
                        for _dqp in _dq_raw:
                            _dqn = _norm_apollo(_dqp)
                            _dqn["crs_fit"] = _crs_fit_score(
                                _dqn.get("title",""), _dq_industry, _dq_country,
                                _dqn.get("has_email", False), bool(_dqn.get("has_phone")),
                            )
                            _dq_normed.append(_dqn)
                        _dq_normed.sort(key=lambda x: -x.get("crs_fit", 0))
                        st.session_state[_dq_res_key] = _dq_normed
                        _dq_contacts = _dq_normed
                    except Exception as _dqe:
                        st.error(f"Apollo error: {_dqe}")
                        st.session_state[_dq_res_key] = []
                        _dq_contacts = []

            if not _dm_has_apo:
                st.warning("Apollo API key not configured.")
            elif _dq_contacts is None:
                st.caption("Searching…")
            elif not _dq_contacts:
                st.caption("No contacts found — try a different solution focus or re-search.")
            else:
                st.caption(f"**{len(_dq_contacts)} contacts found**")
                for _dci, _dcc in enumerate(_dq_contacts):
                    _dc_apo_id = _dcc.get("id","")
                    _dc_nm_sk  = f"dm_nm_{_dq_key}_{_dci}"
                    _dc_em_sk  = f"dm_em_{_dq_key}_{_dci}"
                    _dc_ph_sk  = f"dm_ph_{_dq_key}_{_dci}"
                    _dc_crm_sk = f"dm_crm_{_dq_key}_{_dci}"
                    _dc_enr_sk = f"dm_enr_{_dq_key}_{_dci}"
                    _dc_rev_sk = f"dm_rev_saved_{_dq_key}_{_dci}"

                    _dc_name     = st.session_state.get(_dc_nm_sk) or _dcc.get("name") or f"Contact {_dci+1}"
                    _dc_enr_data = st.session_state.get(_dc_enr_sk, {})
                    _dc_fit      = _dcc.get("crs_fit", 0)
                    _dc_badge    = "🟢" if _dc_fit >= 70 else "🟡" if _dc_fit >= 40 else "🔵"

                    _dc_crm    = _auto_crm_check(_dcc.get("name",""), _dcc.get("email",""),
                                                 _dcc.get("linkedin",""), _dc_crm_sk)
                    _dc_mon_em = (_dc_crm.get("crm_email","") if _dc_crm and _dc_crm.get("on_crm") else "")
                    _dc_mon_ph = (_dc_crm.get("crm_phone","") if _dc_crm and _dc_crm.get("on_crm") else "")

                    # Best email/phone — same priority chain as Lead Verification
                    _dc_em_val = (_dcc.get("work_email") or _dcc.get("email") or _dc_mon_em
                                  or _dc_enr_data.get("work_email") or _dc_enr_data.get("email")
                                  or (st.session_state.get(_dc_em_sk) or {}).get("email",""))
                    _dc_em_src = ("Apollo" if (_dcc.get("work_email") or _dcc.get("email"))
                                  else "Monday" if _dc_mon_em else "Apollo")
                    _dc_em_personal = (_dcc.get("personal_email") or _dc_enr_data.get("personal_email",""))

                    _dc_ph_val = (_dcc.get("phone") or _dc_mon_ph
                                  or _dc_enr_data.get("phone")
                                  or (st.session_state.get(_dc_ph_sk) or {}).get("phone",""))
                    _dc_ph_src = ("Apollo" if (_dcc.get("phone") or _dc_enr_data.get("phone"))
                                  else "Monday" if _dc_mon_ph else "")

                    with st.container(border=True):
                        _dca, _dcb = st.columns([4, 2])
                        with _dca:
                            st.markdown(f"### 👤 {_dc_badge} {_dc_name}")
                            _dc_rp = [x for x in [_dcc.get("title"), _dcc.get("company")] if x]
                            if _dc_rp: st.caption("💼 " + "  ·  ".join(_dc_rp))
                            if _dcc.get("domain"):   st.caption(f"🌐 {_dcc['domain']}")
                            if _dcc.get("linkedin"): st.markdown(f"[LinkedIn →]({_dcc['linkedin']})")
                            if _dcc.get("twitter"):  st.caption(f"Twitter: {_dcc['twitter']}")
                        with _dcb:
                            st.caption(f"🔵 {_dcc.get('source','Apollo')}  ·  CRS fit: {_dc_fit}/100")
                            if _dc_crm:
                                if _dc_crm.get("on_crm"):
                                    st.success(f"📋 {_dc_crm['crm_board']}")
                                    if _dc_crm.get("crm_url"):
                                        st.markdown(f"[Open →]({_dc_crm['crm_url']})")
                                else:
                                    st.caption("📋 Not in CRM")

                        # ── Email + Phone ──────────────────────────────────────
                        _dce1, _dce2 = st.columns(2)
                        with _dce1:
                            if _dc_em_val:
                                st.markdown(f"📧 **{_dc_em_val}**")
                                st.caption(f"Business · via {_dc_em_src}")
                                if _dc_em_personal and _dc_em_personal != _dc_em_val:
                                    st.markdown(f"📧 `{_dc_em_personal}`")
                                    st.caption("Personal · via Apollo")
                            else:
                                st.caption("📧 Available · ⚡ 1 credit" if _dcc.get("has_email") else "📧 Not flagged")
                        with _dce2:
                            if _dc_ph_val:
                                st.markdown(f"📞 **{_dc_ph_val}**")
                                st.caption(f"Mobile · via {_dc_ph_src}" if _dc_ph_src else "Mobile · via Apollo")
                            elif _dc_apo_id:
                                _hp = _dcc.get("has_phone","")
                                st.caption("📞 Direct dial available" if _hp == "yes"
                                           else "📞 May be available" if _hp == "maybe"
                                           else "📞 Use Reveal All below")
                            else:
                                st.caption("📞 No Apollo ID")
                            _dc_cph = _dcc.get("company_phone") or _dc_enr_data.get("company_phone","")
                            if _dc_cph:
                                st.markdown(f"🏢 **{_dc_cph}** (company)")

                        # ── Reveal All & Save to Apollo List ───────────────────
                        _dc_enrich_done = bool(_dc_em_val and _dc_ph_val)
                        if _dm_has_apo and _dc_apo_id and not _dc_enrich_done:
                            _dc_rv_lbl = (
                                "🔓 Reveal All & Save to Apollo List"
                                if not st.session_state.get(_dc_rev_sk)
                                else "🔄 Re-reveal & Update List"
                            )
                            if st.button(_dc_rv_lbl, key=f"dm_reveal_{_dq_key}_{_dci}",
                                         use_container_width=True, type="primary"):
                                with st.spinner(f"Revealing via Apollo — saving to '{_APOLLO_REVEALED_LIST}'…"):
                                    _dc_rv = _apollo_reveal_and_save(_dc_apo_id)
                                if _dc_rv["error"] and not _dc_rv["person"]:
                                    st.error(f"Apollo: {_dc_rv['error'][:140]}")
                                else:
                                    _dc_rn = _dc_rv["person"]
                                    if _dc_rn.get("name") and "***" not in _dc_rn["name"]:
                                        st.session_state[_dc_nm_sk] = _dc_rn["name"]
                                        st.session_state[_dq_res_key][_dci]["name"] = _dc_rn["name"]
                                    if _dc_rn.get("work_email") or _dc_rn.get("email"):
                                        _dc_best = _dc_rn.get("work_email") or _dc_rn["email"]
                                        st.session_state[_dc_em_sk] = {"email": _dc_best, "source": "Apollo"}
                                        st.session_state[_dq_res_key][_dci]["work_email"] = _dc_best
                                        st.session_state[_dq_res_key][_dci]["email"] = _dc_best
                                        if _dc_rn.get("personal_email"):
                                            st.session_state[_dq_res_key][_dci]["personal_email"] = _dc_rn["personal_email"]
                                    _dc_rc = _dc_rv.get("contact") or {}
                                    _dc_revealed_phone = (
                                        _dc_rn.get("phone") or
                                        _dc_rc.get("direct_phone") or
                                        _dc_rc.get("mobile_phone") or
                                        ((_dc_rc.get("phone_numbers") or [{}])[0]).get("sanitized_number","")
                                    )
                                    if _dc_revealed_phone:
                                        st.session_state[_dc_ph_sk] = {"phone": _dc_revealed_phone, "source": "Apollo"}
                                        st.session_state[_dq_res_key][_dci]["phone"] = _dc_revealed_phone
                                    if _dc_rn.get("linkedin"):
                                        st.session_state[_dq_res_key][_dci]["linkedin"] = _dc_rn["linkedin"]
                                    st.session_state[_dc_enr_sk] = _dc_rn
                                    st.session_state[_dc_rev_sk] = True
                                    if _dc_rv["error"]:
                                        st.warning(f"Revealed — list save failed: {_dc_rv['error'][:80]}")
                                    elif _dc_rc.get("id"):
                                        st.success(f"Saved to '{_APOLLO_REVEALED_LIST}' · Apollo ID: {_dc_rc['id']}")
                                    else:
                                        st.success(f"Revealed · added to '{_APOLLO_REVEALED_LIST}' list")
                                    if not _dc_rn.get("email") and not _dc_rn.get("work_email") and not _dc_revealed_phone:
                                        st.toast("Nothing revealed — contact may lack Apollo data")
                                    st.rerun()

                        # ── Company insights ───────────────────────────────────
                        _dc_co_src  = _dc_enr_data if _dc_enr_data.get("description") else _dcc
                        _dc_co_desc = _dc_co_src.get("description","")
                        _dc_co_rev  = _dc_co_src.get("revenue","")
                        _dc_co_emp  = _dc_co_src.get("employees")
                        _dc_co_ind  = _dc_co_src.get("industry","")
                        _dc_co_kw   = _dc_co_src.get("keywords") or []
                        _dc_co_tech = _dc_co_src.get("tech_count", 0)
                        _dc_co_yr   = _dc_co_src.get("founded_year")
                        _dc_co_city = _dc_co_src.get("city","")
                        _dc_co_ctry = _dc_co_src.get("country","")
                        if any([_dc_co_desc, _dc_co_rev, _dc_co_emp, _dc_co_ind, _dc_co_kw, _dc_co_tech]):
                            with st.expander("🏢 Company insights"):
                                if _dc_co_desc:
                                    st.caption(_dc_co_desc[:300] + ("…" if len(_dc_co_desc) > 300 else ""))
                                _dci1, _dci2, _dci3 = st.columns(3)
                                if _dc_co_rev:  _dci1.metric("Revenue", _dc_co_rev)
                                if _dc_co_emp:  _dci2.metric("Employees", f"{_dc_co_emp:,}" if isinstance(_dc_co_emp, int) else _dc_co_emp)
                                if _dc_co_yr:   _dci3.metric("Founded", _dc_co_yr)
                                if _dc_co_ind:  st.caption(f"Industry: {_dc_co_ind}")
                                if _dc_co_city or _dc_co_ctry:
                                    st.caption(f"📍 {', '.join(x for x in [_dc_co_city, _dc_co_ctry] if x)}")
                                if _dc_co_kw:   st.caption("Keywords: " + ", ".join(_dc_co_kw[:8]))
                                if _dc_co_tech: st.caption(f"Tech stack: {_dc_co_tech} technologies detected")

                        # ── Push buttons ───────────────────────────────────────
                        if monday_active:
                            _dc_src_ctx = f"Decision Makers · {_dq_solution}"
                            if _dq_source: _dc_src_ctx += f" | from {_dq_source}"
                            _dc_push_pl = {
                                "name":           _dc_name,
                                "title":          _dcc.get("title",""),
                                "company":        _dq_company,
                                "email":          _dc_em_val,
                                "phone":          _dc_ph_val,
                                "linkedin":       _dcc.get("linkedin",""),
                                "company_phone":  _dcc.get("company_phone",""),
                                "twitter":        _dcc.get("twitter",""),
                                "accuracy_score": str(_dc_fit),
                                "provider_chain": f"Decision Makers · {_dq_solution}",
                                "source_context": _dc_src_ctx,
                            }
                            _dcp1, _dcp2 = st.columns(2)
                            with _dcp1:
                                _dc_leads_lbl = "♻️ Update Leads" if (_dc_crm and _dc_crm.get("on_crm")) else "📋 Push to Leads"
                                if st.button(_dc_leads_lbl, key=f"dm_push_lead_{_dq_key}_{_dci}",
                                             use_container_width=True,
                                             type="secondary" if (_dc_crm and _dc_crm.get("on_crm")) else "primary"):
                                    with st.spinner("Pushing…"):
                                        try:
                                            _pmr = sync_lead_to_monday(_dc_push_pl)
                                            st.success(f"{_pmr.get('action','done').title()} · {_pmr.get('item_id')}")
                                            del st.session_state[_dc_crm_sk]
                                        except Exception as _dpe: st.error(str(_dpe))
                            with _dcp2:
                                if st.button("🏢 Push to Contacts", key=f"dm_push_contact_{_dq_key}_{_dci}",
                                             use_container_width=True, type="primary"):
                                    with st.spinner("Pushing…"):
                                        try:
                                            _rc2 = push_to_contacts_board(_dc_push_pl)
                                            st.success(f"{_rc2.get('action','done').title()} · {_rc2.get('item_id')}")
                                        except Exception as _pce: st.error(str(_pce))

                        _copy_block(
                            "\n".join(l for l in [
                                f"CONTACT: {_dc_name}",
                                f"Title: {_dcc.get('title','')}",
                                f"Company: {_dq_company}",
                                f"Email: {_dc_em_val}"            if _dc_em_val                                    else "",
                                f"Personal: {_dc_em_personal}"    if _dc_em_personal and _dc_em_personal != _dc_em_val else "",
                                f"Phone: {_dc_ph_val}"            if _dc_ph_val                                    else "",
                                f"Co Phone: {_dcc.get('company_phone','')}" if _dcc.get("company_phone")           else "",
                                f"LinkedIn: {_dcc.get('linkedin','')}"      if _dcc.get("linkedin")                else "",
                                f"Twitter: {_dcc.get('twitter','')}"        if _dcc.get("twitter")                 else "",
                                f"CRS Fit: {_dc_fit}%",
                                f"Source: {_dq_source}",
                            ] if l),
                            key=f"dm_copy_{_dq_key}_{_dci}",
                            flat=True,
                        )


# ══════════════════════════════════════════════════════════════════════════════
# PAGE — INTELLIGENCE AGENT
# ══════════════════════════════════════════════════════════════════════════════
if _page == "🤖 Intelligence Agent":
    _colored_header(
        label="CRS Chief Intelligence Agent",
        description="Source, analyse, and route leads from tenders, partner recs, awarded companies, and dork contacts — daily or on-demand.",
        color_name="violet-70",
    )

    # ── Run Analysis Panel ────────────────────────────────────────────────────
    _ia_pending_df  = _load_agent_leads(statuses=("pending",))
    _ia_all_df      = _load_agent_leads(statuses=("pending","pushed_companies","pushed_leads","pushed_contacts"))
    _ia_dismissed   = _load_agent_leads(statuses=("dismissed",))
    _ia_pending_n   = len(_ia_pending_df)

    with st.expander(f"⚙️ Run Analysis  {'— ' + str(_ia_pending_n) + ' leads pending' if _ia_pending_n else ''}", expanded=_ia_pending_n == 0):
        st.markdown("Select data sources and the agent will pull unprocessed records, score them 1–10, generate a sales outreach note, and queue them below.")
        _ia_sc1, _ia_sc2, _ia_sc3, _ia_sc4 = st.columns(4)
        _ia_src_t  = _ia_sc1.checkbox("📢 Open Tenders", value=True, key="ia_src_tenders",
                                       help="sa_tenders where ai_score ≥ 6")
        _ia_src_p  = _ia_sc2.checkbox("🤝 Partner Recs",  value=True, key="ia_src_partner",
                                       help="partner_recommendation_history (most recent run)")
        _ia_src_a  = _ia_sc3.checkbox("🏆 Awarded Cos",   value=True, key="ia_src_awarded",
                                       help="winning_bidder companies from awarded_tenders")
        _ia_src_d  = _ia_sc4.checkbox("🔍 Dork Contacts", value=True, key="ia_src_dork",
                                       help="dork_leads not yet pushed to Monday")
        _ia_lim    = st.slider("Max new records per source", 5, 50, 15, 5, key="ia_limit")
        _ia_run    = st.button("🧠 Run Agent Analysis Now", type="primary",
                               use_container_width=True, key="ia_run_btn")
        if _ia_run:
            _ia_sources = []
            if _ia_src_t: _ia_sources.append("tenders")
            if _ia_src_p: _ia_sources.append("partner_recs")
            if _ia_src_a: _ia_sources.append("awarded_companies")
            if _ia_src_d: _ia_sources.append("dork_leads")
            if not _ia_sources:
                st.warning("Select at least one source.")
            else:
                _ins, _sk, _err = _run_agent_batch(_ia_sources, limit=_ia_lim)
                st.success(f"✅ Done — {_ins} new leads queued · {_sk} already processed · {_err} errors")
                st.rerun()

    st.divider()

    # ── Helper: render a single agent_lead card ───────────────────────────────
    def _render_agent_card(row: dict, card_key: str):
        _ac_company  = str(row.get("company") or "Unknown")
        _ac_country  = str(row.get("country") or "")
        _ac_score    = int(row.get("score") or 0)
        _ac_ltype    = str(row.get("lead_type") or "Company Lead")
        _ac_src      = str(row.get("source_type") or "")
        _ac_rationale = str(row.get("rationale") or "")
        _ac_note     = str(row.get("outreach_note") or "")
        _ac_status   = str(row.get("status") or "pending")
        _ac_id       = str(row.get("id") or "")
        _ac_cname    = str(row.get("contact_name") or "")
        _ac_ctitle   = str(row.get("contact_title") or "")
        _ac_cemail   = str(row.get("contact_email") or "")
        _ac_cphone   = str(row.get("contact_phone") or "")
        _ac_cli      = str(row.get("contact_linkedin") or "")
        try:
            _ac_sols  = json.loads(row.get("proposed_solutions") or "[]") if isinstance(row.get("proposed_solutions"), str) else (row.get("proposed_solutions") or [])
            _ac_pains = json.loads(row.get("pain_points") or "[]") if isinstance(row.get("pain_points"), str) else (row.get("pain_points") or [])
        except Exception:
            _ac_sols = _ac_pains = []

        _ac_sc_emoji = "🟢" if _ac_score >= 7 else "🟡" if _ac_score >= 5 else "🔴"
        _src_labels  = {"tender": "📢 Tender", "partner_rec": "🤝 Partner Rec",
                        "awarded_company": "🏆 Awarded Co", "dork_lead": "🔍 Dork Lead",
                        "manual": "✍️ Manual"}
        _ltype_colors = {"Company Lead": "🏢", "Opportunity": "📢",
                         "Contact Lead": "👤", "Irrelevant": "❌"}

        with st.container(border=True):
            _h1, _h2 = st.columns([4, 1])
            with _h1:
                st.markdown(f"### {_ltype_colors.get(_ac_ltype,'🏢')} {_ac_company}")
                _meta = [x for x in [
                    f"📍 {_ac_country}" if _ac_country else "",
                    _src_labels.get(_ac_src, _ac_src),
                    _ac_ltype,
                    f"**Pushed** to {row.get('monday_board','Monday')}" if _ac_status.startswith("pushed") else "",
                ] if x]
                st.caption("  ·  ".join(_meta))
            with _h2:
                st.metric("Agent Score", f"{_ac_sc_emoji} {_ac_score}/10")

            if _ac_rationale:
                st.markdown(f"**Why this lead:** {_ac_rationale}")

            if _ac_note:
                st.info(f"💬 **Sales outreach note:** {_ac_note}")

            if _ac_sols or _ac_pains:
                _sol_col, _pain_col = st.columns(2)
                with _sol_col:
                    if _ac_sols:
                        st.markdown("**Proposed CRS solutions:**")
                        for s in _ac_sols[:4]:
                            st.markdown(f"  • {s}")
                with _pain_col:
                    if _ac_pains:
                        st.markdown("**Pain points:**")
                        for p in _ac_pains[:4]:
                            st.markdown(f"  • {p}")

            if _ac_ltype == "Contact Lead" and (_ac_cname or _ac_cemail):
                with st.expander("👤 Contact details"):
                    if _ac_cname:  st.caption(f"**Name:** {_ac_cname}")
                    if _ac_ctitle: st.caption(f"**Title:** {_ac_ctitle}")
                    if _ac_cemail: st.caption(f"**Email:** {_ac_cemail}")
                    if _ac_cphone: st.caption(f"**Phone:** {_ac_cphone}")
                    if _ac_cli:    st.markdown(f"[LinkedIn →]({_ac_cli})")

            # ── Action buttons ────────────────────────────────────────────
            if _ac_status == "pending":
                _b1, _b2, _b3, _b4 = st.columns(4)

                if monday_active and _ac_ltype in ("Company Lead", "Opportunity"):
                    with _b1:
                        if st.button("🏢 Companies", key=f"{card_key}_push_co",
                                     use_container_width=True):
                            try:
                                _pr = push_partner_to_companies({
                                    "company": _ac_company,
                                    "country": _ac_country,
                                    "crs_score": _ac_score * 10,
                                    "why": _ac_rationale,
                                    "outreach_angle": _ac_note,
                                    "proposed_solutions": _ac_sols,
                                    "urgency": "High" if _ac_score >= 8 else "Medium",
                                })
                                _item_id = str(_pr.get("item_id", ""))
                                _sb_execute(supabase.table("agent_leads").update({
                                    "status": "pushed_companies",
                                    "monday_item_id": _item_id,
                                    "monday_board": "Companies",
                                }).eq("id", _ac_id))
                                _load_agent_leads.clear()
                                st.success(f"Pushed · {_item_id}")
                                st.rerun()
                            except Exception as _pe:
                                st.error(str(_pe))

                if monday_active:
                    with _b2:
                        if st.button("📋 Leads Board", key=f"{card_key}_push_lead",
                                     use_container_width=True):
                            try:
                                _pr2 = sync_lead_to_monday({
                                    "name": _ac_cname or _ac_company,
                                    "title": _ac_ctitle or _ac_ltype,
                                    "company": _ac_company,
                                    "email": _ac_cemail,
                                    "phone": _ac_cphone,
                                    "linkedin": _ac_cli,
                                    "provider_chain": f"Intelligence Agent · {_ac_src}",
                                    "source_context": _ac_note[:200] if _ac_note else _ac_rationale[:200],
                                })
                                _item_id2 = str(_pr2.get("item_id", ""))
                                _sb_execute(supabase.table("agent_leads").update({
                                    "status": "pushed_leads",
                                    "monday_item_id": _item_id2,
                                    "monday_board": "Leads 2.0",
                                }).eq("id", _ac_id))
                                _load_agent_leads.clear()
                                st.success(f"Pushed · {_item_id2}")
                                st.rerun()
                            except Exception as _pe2:
                                st.error(str(_pe2))

                if monday_active and _ac_ltype == "Contact Lead" and (_ac_cemail or _ac_cname):
                    with _b3:
                        if st.button("🏢 Contacts Board", key=f"{card_key}_push_ct",
                                     use_container_width=True):
                            try:
                                _pr3 = push_to_contacts_board({
                                    "name": _ac_cname,
                                    "title": _ac_ctitle,
                                    "company": _ac_company,
                                    "email": _ac_cemail,
                                    "phone": _ac_cphone,
                                    "linkedin": _ac_cli,
                                    "provider_chain": f"Intelligence Agent · {_ac_src}",
                                    "source_context": _ac_note[:200] if _ac_note else _ac_rationale[:200],
                                })
                                _item_id3 = str(_pr3.get("item_id", ""))
                                _sb_execute(supabase.table("agent_leads").update({
                                    "status": "pushed_contacts",
                                    "monday_item_id": _item_id3,
                                    "monday_board": "Contacts",
                                }).eq("id", _ac_id))
                                _load_agent_leads.clear()
                                st.success(f"Pushed · {_item_id3}")
                                st.rerun()
                            except Exception as _pe3:
                                st.error(str(_pe3))

                with _b4:
                    if st.button("🗑️ Dismiss", key=f"{card_key}_dismiss",
                                 use_container_width=True):
                        try:
                            _sb_execute(supabase.table("agent_leads")
                                        .update({"status": "dismissed"}).eq("id", _ac_id))
                        except Exception as _de:
                            st.error(f"Dismiss failed: {_de}")
                            return
                        _load_agent_leads.clear()
                        st.rerun()
            else:
                # Already actioned
                _ac_board = row.get("monday_board", "")
                _ac_mid   = row.get("monday_item_id", "")
                st.caption(f"✅ {_ac_status.replace('_',' ').title()}"
                           + (f" · {_ac_board}" if _ac_board else "")
                           + (f" · ID {_ac_mid}" if _ac_mid else ""))

    # ── Lead Queue Tabs ────────────────────────────────────────────────────────
    _ia_qtab_pend, _ia_qtab_co, _ia_qtab_opp, _ia_qtab_ct, _ia_qtab_all, _ia_qtab_dis = st.tabs([
        f"⏳ Pending ({len(_ia_pending_df)})",
        "🏢 Company Leads",
        "📢 Opportunities",
        "👤 Contact Leads",
        "📋 All Actioned",
        "🗑️ Dismissed",
    ])

    def _tab_cards(df: pd.DataFrame, tab_key: str, empty_msg: str):
        if df.empty:
            st.caption(empty_msg)
            return
        for _qi, _qrow in df.iterrows():
            _render_agent_card(_qrow.to_dict(), f"{tab_key}_{_qi}")

    with _ia_qtab_pend:
        if _ia_pending_df.empty:
            st.info("No pending leads. Run an analysis above to populate the queue.")
        else:
            _fc1, _fc2, _fc3 = st.columns(3)
            _fc1.metric("Pending leads", len(_ia_pending_df))
            _high = len(_ia_pending_df[_ia_pending_df["score"] >= 7]) if not _ia_pending_df.empty and "score" in _ia_pending_df.columns else 0
            _fc2.metric("High-score (≥7)", _high)
            _fc3.metric("Sources", _ia_pending_df["source_type"].nunique() if "source_type" in _ia_pending_df.columns else 0)
            st.divider()
            for _qi, _qrow in _ia_pending_df.iterrows():
                _render_agent_card(_qrow.to_dict(), f"pend_{_qi}")

    with _ia_qtab_co:
        _co_df = _ia_pending_df[_ia_pending_df["lead_type"] == "Company Lead"] if not _ia_pending_df.empty and "lead_type" in _ia_pending_df.columns else pd.DataFrame()
        _tab_cards(_co_df, "co", "No pending Company Leads.")

    with _ia_qtab_opp:
        _opp_df = _ia_pending_df[_ia_pending_df["lead_type"] == "Opportunity"] if not _ia_pending_df.empty and "lead_type" in _ia_pending_df.columns else pd.DataFrame()
        _tab_cards(_opp_df, "opp", "No pending Opportunities.")

    with _ia_qtab_ct:
        _ct_df = _ia_pending_df[_ia_pending_df["lead_type"] == "Contact Lead"] if not _ia_pending_df.empty and "lead_type" in _ia_pending_df.columns else pd.DataFrame()
        _tab_cards(_ct_df, "ct", "No pending Contact Leads.")

    with _ia_qtab_all:
        _tab_cards(_ia_all_df, "all", "No actioned leads yet.")

    with _ia_qtab_dis:
        _tab_cards(_ia_dismissed, "dis", "No dismissed leads.")

    # ── Secondary tools: Knowledge Base + Vendor Surveillance ─────────────────
    st.divider()
    st.markdown("#### Intelligence Tools")
    _ia_vs_tab, _ia_ke_tab = st.tabs(["📰 Vendor Surveillance", "⚙️ Knowledge Enrichment"])

    with _ia_vs_tab:
        st.markdown("Fetch a vendor or partner site, compare it against the CRS portfolio, save findings to the knowledge base.")
        _vs_url = st.text_input("Vendor URL", value="https://retaliator.io", key="vs_url2")
        if st.button("🔭 Scan", type="primary", key="vs_scan2", use_container_width=True):
            with st.spinner(f"Fetching {_vs_url}…"):
                _vs_c = _fetch_url_content(_vs_url.strip())
            with st.spinner("Comparing against CRS portfolio…"):
                _vs_p = (f"{_CRS_AGENT_SYSTEM}\n\nVENDOR URL: {_vs_url}\nCONTENT:\n{_vs_c}\n\n"
                         "Compare against CRS portfolio. Return ONLY JSON:\n"
                         '{"vendor_name":"","summary":"","existing_overlap":[],'
                         '"new_services":[],"partnership_angle":"","recommended_action":""}')
                _vs_r = _call_ai(_vs_p)
                try:
                    _vs_j = json.loads(_vs_r)
                except Exception:
                    _m2 = re.search(r'\{[\s\S]*\}', _vs_r)
                    _vs_j = json.loads(_m2.group(0)) if _m2 else {"summary": _vs_r[:300]}
            st.session_state["vs_result2"] = _vs_j

        _vs_j = st.session_state.get("vs_result2")
        if _vs_j:
            with st.container(border=True):
                st.markdown(f"### {_vs_j.get('vendor_name','Vendor')}")
                st.caption(_vs_j.get("summary",""))
                _vc1, _vc2 = st.columns(2)
                with _vc1:
                    if _vs_j.get("existing_overlap"):
                        st.markdown("**Overlaps with CRS:**")
                        for _ov in _vs_j["existing_overlap"]:
                            st.markdown(f"  • {_ov}")
                with _vc2:
                    if _vs_j.get("new_services"):
                        st.markdown("**New / uncovered:**")
                        for _ns in _vs_j["new_services"]:
                            st.markdown(f"  • {_ns}")
                if _vs_j.get("partnership_angle"): st.info(f"🤝 {_vs_j['partnership_angle']}")
                st.caption(f"Action: **{_vs_j.get('recommended_action','')}**")
            if st.button("💾 Save to Knowledge Base", key="vs_save2", use_container_width=True):
                try:
                    supabase.table("knowledge_base").insert({
                        "source": _vs_url, "summary": json.dumps(_vs_j)}).execute()
                    _load_knowledge_base.clear()
                    st.success("Saved.")
                except Exception as _ke3:
                    st.error(str(_ke3))

    with _ia_ke_tab:
        st.markdown("Feed a URL or text to the knowledge base. The agent injects these summaries into every future lead analysis.")
        _ke_url2  = st.text_input("URL (optional)", key="ke_url2")
        _ke_text2 = st.text_area("Or paste text", height=120, key="ke_text2")
        if st.button("🚀 Feed to Knowledge Base", type="primary",
                     key="ke_feed2", use_container_width=True):
            if not _ke_url2.strip() and not _ke_text2.strip():
                st.warning("Provide a URL or paste content.")
            else:
                _kc = _fetch_url_content(_ke_url2.strip()) if _ke_url2.strip() else _ke_text2.strip()
                _kp = (f"{_CRS_AGENT_SYSTEM}\n\nExtract CRS-relevant insights:\n"
                       f"SOURCE: {_ke_url2 or 'Manual'}\nCONTENT:\n{_kc[:4000]}\n\n"
                       "3-5 sentence summary of CRS-relevant features only.")
                _ks = _call_ai(_kp)
                try:
                    supabase.table("knowledge_base").insert({
                        "source": _ke_url2.strip() or "Manual", "summary": _ks}).execute()
                    _load_knowledge_base.clear()
                    st.success("✅ Knowledge base updated.")
                    st.info(_ks[:400])
                except Exception as _kbe3:
                    st.error(str(_kbe3))

        st.divider()
        st.markdown("**Current Knowledge Base**")
        _kb_df2 = _load_knowledge_base()
        if _kb_df2.empty:
            st.caption("Empty. Feed a URL or document above.")
        else:
            for _, _kb_r in _kb_df2.iterrows():
                with st.expander(f"📄 {str(_kb_r.get('source',''))[:80]}  —  {str(_kb_r.get('created_at',''))[:10]}"):
                    st.write(_kb_r.get("summary",""))

