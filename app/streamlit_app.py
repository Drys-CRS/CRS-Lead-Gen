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
# SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    _logo = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "crs_logo.png")
    if os.path.exists(_logo):
        st.image(_logo, width=160)
    st.title("CRS Intelligence")
    st.caption("v2 · pipeline owned by GitHub Actions")
    st.divider()

    country_filter = st.multiselect(
        "Countries",
        ["South Africa", "Kenya", "Nigeria", "Ghana", "Tanzania",
         "Uganda", "Zambia", "Rwanda", "Botswana", "Namibia", "Zimbabwe",
         "Mozambique", "Ethiopia", "Egypt", "Angola", "Cameroon"],
        default=[], placeholder="All",
    )
    min_score = st.slider("Min AI score", 0, 10, 0)
    st.divider()

    monday_active = _MONDAY_OK and bool(
        st.secrets.get("MONDAY_API_KEY") if hasattr(st, "secrets") else "")
    st.success("Monday.com ✓") if monday_active else st.caption("Monday.com: key not set")

    st.divider()
    st.markdown("**AI Providers**")
    for part in _provider_status().split(" · "):
        st.caption(part)
    st.divider()

    if st.button("Clear cache", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# ─────────────────────────────────────────────────────────────────────────────
# DATA LOADERS
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def _load_tenders() -> pd.DataFrame:
    r = (supabase.table("sa_tenders").select("*")
         .neq("status", "Awarded").neq("is_irrelevant", True)
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
    """ai_rationale may be a JSON blob or plain string; always return a dict."""
    if not raw or str(raw) in ("nan", "None", ""):
        return {}
    try:
        return json.loads(str(raw))
    except Exception:
        return {"rationale": str(raw)}

def _parse_list(raw) -> list:
    """Parse a JSON list stored as a string. Returns []  on failure."""
    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    try:
        v = json.loads(str(raw))
        return v if isinstance(v, list) else []
    except Exception:
        return [s.strip() for s in str(raw).split(",") if s.strip()]

# ─────────────────────────────────────────────────────────────────────────────
# URGENCY BADGE HELPER
# ─────────────────────────────────────────────────────────────────────────────
def _badge(urgency: str) -> str:
    u = str(urgency).lower()
    if u == "high":   return "🔴 High"
    if u == "medium": return "🟡 Medium"
    if u == "low":    return "🟢 Low"
    return urgency or "—"

# ─────────────────────────────────────────────────────────────────────────────
# TABS
# ─────────────────────────────────────────────────────────────────────────────
tab_overview, tab_opps, tab_partners, tab_leads = st.tabs([
    "🏠 Overview", "📢 Opportunities", "🤝 Partners", "✅ Lead Verification",
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

    df = _score_filter(_country(_load_tenders()))

    col_f1, col_f2 = st.columns([2, 3])
    with col_f1:
        status_opts = ["All"] + (sorted(df["status"].dropna().unique().tolist())
                                 if "status" in df.columns else [])
        sel_status = st.selectbox("Status", status_opts, key="opp_status")
        if sel_status != "All" and "status" in df.columns:
            df = df[df["status"] == sel_status]
    with col_f2:
        q = st.text_input("Search department / title", key="opp_search")
        if q:
            mask = pd.Series(False, index=df.index)
            for col in ("department_name", "title", "description"):
                if col in df.columns:
                    mask |= df[col].str.contains(q, case=False, na=False)
            df = df[mask]

    c1, c2, c3 = st.columns(3)
    c1.metric("Shown", len(df))
    if "country" in df.columns: c2.metric("Countries", df["country"].nunique())
    if "ai_score" in df.columns:
        avg = pd.to_numeric(df["ai_score"], errors="coerce").mean()
        c3.metric("Avg AI score", f"{avg:.1f}" if pd.notna(avg) else "—")

    show_cols = [c for c in ["tender_number","department_name","title",
                              "country","closing_date","ai_score","status"] if c in df.columns]
    st.dataframe(df[show_cols], use_container_width=True, hide_index=True)

    if not df.empty and "tender_number" in df.columns:
        tn_list = df["tender_number"].dropna().tolist()
        sel_tn = st.selectbox("Select tender to view / push", ["—"] + tn_list, key="opp_sel")
        if sel_tn != "—":
            row = df[df["tender_number"] == sel_tn].iloc[0]
            rat = _parse_rationale(row.get("ai_rationale"))

            with st.expander("Tender detail", expanded=True):
                dc1, dc2 = st.columns([2, 1])
                with dc1:
                    for field in ["title","department_name","country","description",
                                  "closing_date","issue_date","category",
                                  "compliance_requirements","portal_link","source_url"]:
                        val = row.get(field)
                        if val and str(val) not in ("", "nan", "None"):
                            st.markdown(f"**{field.replace('_',' ').title()}:** {val}")
                    for field in ["contact_person","contact_email","contact_phone"]:
                        val = row.get(field)
                        if val and str(val) not in ("", "nan", "None"):
                            st.markdown(f"**{field.replace('_',' ').title()}:** {val}")
                with dc2:
                    score = row.get("ai_score")
                    if score is not None:
                        st.metric("AI Score", f"{score}/10")
                    if rat.get("partner_type"):
                        st.info(f"**Partner type:** {rat['partner_type']}")
                    sols = rat.get("proposed_solutions", [])
                    if sols:
                        st.markdown("**Proposed solutions:**")
                        for s in (sols if isinstance(sols, list) else [sols]):
                            st.markdown(f"• {s}")
                    if rat.get("outreach_angle"):
                        st.markdown("**Outreach angle:**")
                        st.info(rat["outreach_angle"])
                    if rat.get("rationale"):
                        st.markdown("**Rationale:**")
                        st.caption(rat["rationale"])

            col_a, col_b = st.columns(2)
            with col_a:
                if monday_active:
                    if st.button("Push to Monday", key="opp_push"):
                        with st.spinner("Pushing…"):
                            res = push_tender_to_monday(row.to_dict())
                        st.success(f"Ticket: **{res.get('ticket_action')}** | Lead: **{res.get('lead_action')}**")
                else:
                    st.info("Add MONDAY_API_KEY to enable push.")
            with col_b:
                if st.button("Re-score with AI", key="opp_rescore"):
                    with st.spinner("Scoring…"):
                        try:
                            scored = ai_score_tender(row.to_dict())
                            blob = json.dumps({
                                "rationale": scored["rationale"],
                                "partner_type": scored["partner_type"],
                                "proposed_solutions": scored["proposed_solutions"],
                                "outreach_angle": scored["outreach_angle"],
                            })
                            supabase.table("sa_tenders").update(
                                {"ai_score": scored["score"], "ai_rationale": blob}
                            ).eq("tender_number", sel_tn).execute()
                            st.cache_data.clear()
                            st.success(f"Score: **{scored['score']}/10** — {scored['rationale']}")
                        except Exception as e:
                            st.error(f"Scoring failed: {e}")

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
