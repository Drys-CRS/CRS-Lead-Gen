"""
CRS Competitive Intelligence Dashboard — v2
Lean 4-tab dashboard. The nightly GitHub Action owns scraping + AI scoring;
this app adds on-demand AI scoring and partner analysis atop that data.
"""
import os
import sys
import json
import re
import time as _time
import streamlit as st
import pandas as pd
from supabase import create_client, Client

# ── AI: prefer new google.genai SDK ──────────────────────────────────────────
try:
    import google.genai as genai
    _GENAI_NEW = True
except ImportError:
    import google.generativeai as genai
    _GENAI_NEW = False

# ── Monday.com (optional) ─────────────────────────────────────────────────────
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

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="CRS Intelligence",
    page_icon="🛡️",
    layout="wide",
)

# ─────────────────────────────────────────────────────────────────────────────
# CRS COMPANY PROFILE  (used in all AI prompts)
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
# AI PROVIDER INITIALIZATION
# Cascade order: Groq → Cerebras → OpenRouter → GitHub → NVIDIA → DeepSeek → Gemini
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
        return OpenAI(
            api_key=key,
            base_url="https://openrouter.ai/api/v1",
            default_headers={
                "HTTP-Referer": "https://github.com/Drys-CRS/CRS-Lead-Gen",
                "X-Title": "CRS Intelligence",
            },
        )
    except Exception:
        return None

@st.cache_resource
def _init_github():
    for k in ("GITHUB_TOKEN", "GH_PAT"):
        key = st.secrets.get(k, "")
        if key:
            try:
                from openai import OpenAI
                return OpenAI(api_key=key,
                              base_url="https://models.inference.ai.azure.com")
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

_GITHUB_MODELS = [
    "Llama-3.3-70B-Instruct", "gpt-4o-mini", "Mistral-Large-2411", "Phi-4",
]
_OPENROUTER_MODELS = [
    "openrouter/free",
    "deepseek/deepseek-r1:free",
    "deepseek/deepseek-v3:free",
    "meta-llama/llama-4-maverick:free",
]

# ── Usage tracking (session-scoped, respects free-tier daily limits) ──────────
def _get_usage() -> dict:
    if "ai_usage" not in st.session_state:
        st.session_state["ai_usage"] = {k: 0 for k in _AI_DAILY_LIMITS}
    return st.session_state["ai_usage"]

def _increment_usage(name: str):
    _get_usage()[name] = _get_usage().get(name, 0) + 1

def _budget_ok(name: str) -> bool:
    return _get_usage().get(name, 0) < _AI_DAILY_LIMITS.get(name, 9999)

# ── Low-level provider callers ────────────────────────────────────────────────
def _clean(raw: str) -> str:
    return re.sub(r"^```json[\s]*|^```[\s]*|```$", "", raw.strip(), flags=re.MULTILINE).strip()

def _is_rl(err: str) -> bool:
    return any(x in err.lower() for x in ["429", "quota", "rate limit", "too many", "throttl"])

def _call_groq(prompt: str) -> str:
    resp = groq_ai.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2, max_tokens=1500,
    )
    return _clean(resp.choices[0].message.content)

def _call_cerebras(prompt: str) -> str:
    for model in ["gpt-oss-120b", "zai-glm-4.7"]:
        try:
            resp = cerebras_ai.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2, max_tokens=1500,
            )
            msg = resp.choices[0].message
            text = (getattr(msg, "content", None) or
                    getattr(msg, "reasoning_content", None) or "").strip()
            if text:
                return _clean(text)
        except Exception as e:
            if any(x in str(e) for x in ["404", "deprecated", "unavailable", "not found"]):
                continue
            raise
    raise ValueError("All Cerebras models unavailable")

def _call_openrouter(prompt: str) -> str:
    last_err = None
    for model in _OPENROUTER_MODELS:
        try:
            resp = openrouter_ai.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2, max_tokens=1500, timeout=30,
            )
            text = (resp.choices[0].message.content or "").strip()
            if text:
                return _clean(text)
        except Exception as e:
            last_err = e
            if _is_rl(str(e)):
                _time.sleep(3)
                continue
            if any(x in str(e).lower() for x in ["404", "unavailable", "not found"]):
                continue
            raise
    raise RuntimeError(f"All OpenRouter models failed: {last_err}")

def _call_github(prompt: str) -> str:
    last_err = None
    for model in _GITHUB_MODELS:
        try:
            resp = github_ai.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2, max_tokens=1500,
            )
            text = (resp.choices[0].message.content or "").strip()
            if text:
                return _clean(text)
        except Exception as e:
            last_err = e
            if any(x in str(e).lower() for x in ["404", "not found"]):
                continue
            raise
    raise RuntimeError(f"All GitHub Models failed: {last_err}")

def _call_nvidia(prompt: str) -> str:
    resp = nvidia_ai.chat.completions.create(
        model="meta/llama-3.3-70b-instruct",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2, max_tokens=1500,
    )
    return _clean(resp.choices[0].message.content)

def _call_deepseek(prompt: str) -> str:
    resp = deepseek_ai.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2, max_tokens=1500,
    )
    return _clean(resp.choices[0].message.content)

def _call_gemini(prompt: str, retries: int = 3) -> str:
    if gemini_ai is None:
        raise RuntimeError("Gemini not initialised — check GEMINI_API_KEY")
    for attempt in range(retries):
        try:
            if _GENAI_NEW:
                response = gemini_ai.models.generate_content(
                    model="gemini-2.5-flash", contents=prompt)
            else:
                response = gemini_ai.generate_content(prompt)
            return _clean(response.text)
        except Exception as e:
            if _is_rl(str(e)) and attempt < retries - 1:
                _time.sleep(20 * (attempt + 1))
            else:
                raise
    raise RuntimeError("Gemini quota exceeded after retries.")

def _call_ai(prompt: str) -> str:
    """Cascade: Groq → Cerebras → OpenRouter → GitHub → NVIDIA → DeepSeek → Gemini."""
    providers: list[tuple[str, callable]] = []
    if groq_ai       and _budget_ok("Groq"):       providers.append(("Groq",       _call_groq))
    if cerebras_ai   and _budget_ok("Cerebras"):   providers.append(("Cerebras",   _call_cerebras))
    if openrouter_ai:                               providers.append(("OpenRouter", _call_openrouter))
    if github_ai     and _budget_ok("GitHub"):     providers.append(("GitHub",     _call_github))
    if nvidia_ai     and _budget_ok("NVIDIA"):     providers.append(("NVIDIA",     _call_nvidia))
    if deepseek_ai   and _budget_ok("DeepSeek"):   providers.append(("DeepSeek",   _call_deepseek))
    if gemini_ai     and _budget_ok("Gemini"):     providers.append(("Gemini",     _call_gemini))

    if not providers:
        raise RuntimeError("All AI providers are at their daily limits.")

    last_err = None
    for name, fn in providers:
        try:
            result = fn(prompt)
            _increment_usage(name)
            return result
        except Exception as e:
            last_err = e
            if _is_rl(str(e)):
                st.toast(f"⏳ {name} rate limit — trying next…")
                _increment_usage(name)
            else:
                st.toast(f"⚠️ {name}: {str(e)[:60]} — trying next…")
            continue
    raise RuntimeError(f"All AI providers failed. Last: {last_err}")

def _provider_status() -> str:
    parts = [
        "🟢 Groq"       if groq_ai       else "⚪ Groq",
        "🟢 Cerebras"   if cerebras_ai   else "⚪ Cerebras",
        "🟢 OpenRouter" if openrouter_ai  else "⚪ OpenRouter",
        "🟢 GitHub"     if github_ai      else "⚪ GitHub",
        "🟢 NVIDIA"     if nvidia_ai      else "⚪ NVIDIA",
        "🟢 DeepSeek"   if deepseek_ai   else "⚪ DeepSeek",
        "🟢 Gemini"     if gemini_ai      else "⚪ Gemini",
    ]
    return " · ".join(parts)

# ─────────────────────────────────────────────────────────────────────────────
# AI TASK FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────
def ai_score_tender(row: dict) -> dict:
    """Score a single tender against the CRS portfolio. Returns {score, rationale}."""
    prompt = f"""You are a channel-partner analyst for Cyber Retaliator Solutions (CRS).

{CRS_PROFILE}

Score this government tender as a CRS business opportunity (1–10):
  1–3 = Poor fit (no ICT/security angle)
  4–6 = Possible fit (general ICT)
  7–8 = Good fit (clear security/ICT requirements matching CRS)
  9–10 = Excellent fit (directly requires CRS solutions/training)

TENDER:
Title:       {row.get('title', '')}
Department:  {row.get('department_name', '')}
Country:     {row.get('country', '')}
Description: {str(row.get('description', ''))[:600]}
Category:    {row.get('category', '')}

Return ONLY valid JSON, no markdown:
{{"score": <1-10>, "rationale": "<2-3 sentences explaining the score and which CRS products apply>"}}"""

    raw = _call_ai(prompt)
    try:
        parsed = json.loads(raw)
        return {"score": int(parsed.get("score", 5)), "rationale": str(parsed.get("rationale", ""))}
    except Exception:
        m = re.search(r'"score"\s*:\s*(\d+)', raw)
        return {"score": int(m.group(1)) if m else 5, "rationale": raw[:300]}


def ai_analyse_partners(awarded_df: pd.DataFrame) -> list:
    """Identify top partner candidates from awarded tender data."""
    df = awarded_df.dropna(subset=["winning_bidder"]).copy()
    if df.empty:
        return []

    # Aggregate per company
    agg = []
    for company, grp in df.groupby("winning_bidder", sort=False):
        company = str(company).strip()
        if not company or len(company) < 3:
            continue
        country = str(grp["country"].mode().iloc[0]) if "country" in grp else "Unknown"
        titles  = grp["title"].dropna().str[:60].tolist()[:3] if "title" in grp else []
        depts   = grp["department_name"].dropna().str[:50].unique().tolist()[:2] if "department_name" in grp else []
        agg.append({
            "company": company[:80], "country": country[:50],
            "wins": len(grp), "titles": " | ".join(titles), "depts": " | ".join(depts),
        })
    agg.sort(key=lambda x: x["wins"], reverse=True)

    lines = ["company|country|wins|sample_tenders|departments"]
    for r in agg[:40]:
        lines.append(f"{r['company']}|{r['country']}|{r['wins']}|{r['titles']}|{r['depts']}")

    prompt = (
        "You are a channel-partner analyst for Cyber Retaliator Solutions (CRS), "
        "a South African cybersecurity VAD and IBM/RedHat/SUSE/CompTIA training partner.\n\n"
        "CRS PORTFOLIO: VECTRA (NDR/XDR), vRx (vuln/patch), Strobes (CTEM/PTaaS), "
        "Aikido (AppSec), Flare (dark web), BeachheadSecure (encryption/MFA), "
        "SMBsecure (SMB/POPIA), Telivy (MSSP audit), BlueFlag (SDLC), "
        "CRE/GoldPhish (awareness), IBM/RedHat/SUSE/CompTIA training, own VAPT.\n\n"
        "AWARDED TENDER WIN DATA (pipe-delimited):\n"
        + "\n".join(lines) +
        "\n\nIdentify the TOP 12 ICT/security companies CRS should approach as channel partners. "
        "Exclude government departments, construction, catering, cleaning, vehicles, stationery.\n\n"
        "Return ONLY a JSON array (no markdown):\n"
        '[{"company":"...","country":"...","tenders_won":N,'
        '"partner_classification":"System Integrator|MSP|VAR|Training Provider|Consulting",'
        '"proposed_solutions":["VECTRA","vRx"],'
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
         "Uganda", "Zambia", "Rwanda", "Botswana", "Namibia", "Zimbabwe"],
        default=[],
        placeholder="All",
    )
    min_score = st.slider("Min AI score", 0, 10, 0)
    st.divider()

    monday_active = _MONDAY_OK and bool(
        st.secrets.get("MONDAY_API_KEY") if hasattr(st, "secrets") else ""
    )
    if monday_active:
        st.success("Monday.com ✓")
    else:
        st.caption("Monday.com: key not set")

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
    r = (supabase.table("sa_tenders")
         .select("*")
         .neq("status", "Awarded")
         .neq("is_irrelevant", True)
         .order("closing_date", desc=False)
         .limit(1000)
         .execute())
    return pd.DataFrame(r.data or [])

@st.cache_data(ttl=300)
def _load_awarded() -> pd.DataFrame:
    r = (supabase.table("awarded_tenders")
         .select("*")
         .order("closing_date", desc=True)
         .limit(1000)
         .execute())
    return pd.DataFrame(r.data or [])

@st.cache_data(ttl=300)
def _load_partner_history() -> pd.DataFrame:
    r = (supabase.table("partner_recommendation_history")
         .select("*")
         .order("created_at", desc=True)
         .limit(500)
         .execute())
    return pd.DataFrame(r.data or [])

@st.cache_data(ttl=300)
def _load_lead_verifications() -> pd.DataFrame:
    r = (supabase.table("lead_verification_log")
         .select("*")
         .order("created_at", desc=True)
         .limit(500)
         .execute())
    return pd.DataFrame(r.data or [])

@st.cache_data(ttl=120)
def _load_pipeline_runs() -> pd.DataFrame:
    r = (supabase.table("pipeline_runs")
         .select("*")
         .order("run_at", desc=True)
         .limit(10)
         .execute())
    return pd.DataFrame(r.data or [])

def _apply_country(df: pd.DataFrame, col: str = "country") -> pd.DataFrame:
    if country_filter and col in df.columns:
        return df[df[col].isin(country_filter)]
    return df

def _apply_score(df: pd.DataFrame) -> pd.DataFrame:
    for col in ("ai_score", "crs_alignment_score"):
        if col in df.columns and min_score > 0:
            return df[pd.to_numeric(df[col], errors="coerce").fillna(0) >= min_score]
    return df

# ─────────────────────────────────────────────────────────────────────────────
# TABS
# ─────────────────────────────────────────────────────────────────────────────
tab_overview, tab_opps, tab_partners, tab_leads = st.tabs([
    "🏠 Overview",
    "📢 Opportunities",
    "🤝 Partners",
    "✅ Lead Verification",
])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — OVERVIEW
# ══════════════════════════════════════════════════════════════════════════════
with tab_overview:
    st.subheader("CRS Tender Intelligence — Overview")
    st.caption(
        "Africa-wide government tender intelligence — active tenders, historical awards, "
        "and AI-powered partner intelligence."
    )

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
        st.info("No open tenders found. Run the nightly pipeline to populate.")
    else:
        score_col = "ai_score" if "ai_score" in df_t.columns else "crs_alignment_score"
        top = (df_t
               .assign(_s=pd.to_numeric(df_t.get(score_col, pd.Series()), errors="coerce"))
               .sort_values("_s", ascending=False)
               .drop(columns="_s")
               .head(10))
        show = [c for c in ["tender_number", "department_name", "title",
                             "country", "closing_date", score_col]
                if c in top.columns]
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
            st.text(last.get("error_log", "—") or "—")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — OPPORTUNITIES
# ══════════════════════════════════════════════════════════════════════════════
with tab_opps:
    st.subheader("Open Opportunities")

    df = _apply_score(_apply_country(_load_tenders()))

    col_f1, col_f2 = st.columns([2, 3])
    with col_f1:
        status_opts = ["All"]
        if "status" in df.columns:
            status_opts += sorted(df["status"].dropna().unique().tolist())
        sel_status = st.selectbox("Status", status_opts, key="opp_status")
        if sel_status != "All" and "status" in df.columns:
            df = df[df["status"] == sel_status]
    with col_f2:
        dept_q = st.text_input("Search department / title", key="opp_search")
        if dept_q:
            mask = pd.Series(False, index=df.index)
            for col in ("department_name", "title"):
                if col in df.columns:
                    mask |= df[col].str.contains(dept_q, case=False, na=False)
            df = df[mask]

    c1, c2, c3 = st.columns(3)
    c1.metric("Shown", len(df))
    if "country" in df.columns:
        c2.metric("Countries", df["country"].nunique())
    score_col = "ai_score" if "ai_score" in df.columns else "crs_alignment_score"
    if score_col in df.columns:
        avg = pd.to_numeric(df[score_col], errors="coerce").mean()
        c3.metric("Avg AI score", f"{avg:.1f}" if pd.notna(avg) else "—")

    show_cols = [c for c in ["tender_number", "department_name", "title",
                              "country", "closing_date", score_col, "status"]
                 if c in df.columns]
    st.dataframe(df[show_cols], use_container_width=True, hide_index=True)

    # Detail panel
    if not df.empty and "tender_number" in df.columns:
        tn_list = df["tender_number"].dropna().tolist()
        sel_tn = st.selectbox("Select tender to view / push", ["—"] + tn_list, key="opp_sel")
        if sel_tn != "—":
            row = df[df["tender_number"] == sel_tn].iloc[0]
            with st.expander("Tender detail", expanded=True):
                for field in ["title", "department_name", "country", "description",
                              "closing_date", "issue_date", score_col,
                              "ai_rationale", "contact_person", "contact_email",
                              "contact_phone", "portal_link", "source_url"]:
                    val = row.get(field)
                    if val is not None and str(val) not in ("", "nan", "None"):
                        st.markdown(f"**{field.replace('_', ' ').title()}:** {val}")

            col_a, col_b = st.columns(2)
            with col_a:
                if monday_active:
                    if st.button("Push to Monday", key="opp_push"):
                        with st.spinner("Pushing to Monday…"):
                            res = push_tender_to_monday(row.to_dict())
                        st.success(
                            f"Ticket: **{res.get('ticket_action')}** | "
                            f"Lead: **{res.get('lead_action')}**"
                        )
                else:
                    st.info("Add MONDAY_API_KEY to enable push.")
            with col_b:
                if st.button("Re-score with AI", key="opp_rescore"):
                    with st.spinner("Scoring…"):
                        try:
                            scored = ai_score_tender(row.to_dict())
                            supabase.table("sa_tenders").update({
                                "ai_score":     scored["score"],
                                "ai_rationale": scored["rationale"],
                            }).eq("tender_number", sel_tn).execute()
                            st.cache_data.clear()
                            st.success(
                                f"Score: **{scored['score']}/10** — {scored['rationale']}"
                            )
                        except Exception as e:
                            st.error(f"Scoring failed: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — PARTNERS
# ══════════════════════════════════════════════════════════════════════════════
with tab_partners:
    st.subheader("Partner Recommendations")
    st.caption("AI-generated partner analysis. History is written by the nightly pipeline; "
               "use the button below to run fresh analysis on demand.")

    df_p = _apply_country(_load_partner_history(), col="country")

    if df_p.empty:
        st.info("No partner recommendations yet. Run the analysis below.")
    else:
        c1, c2 = st.columns(2)
        c1.metric("Recommendations", len(df_p))
        if "country" in df_p.columns:
            c2.metric("Countries", df_p["country"].nunique())

        show_p = [c for c in ["created_at", "company", "country",
                               "partner_classification", "urgency",
                               "estimated_deal_size", "proposed_solutions"]
                  if c in df_p.columns]
        st.dataframe(df_p[show_p] if show_p else df_p,
                     use_container_width=True, hide_index=True)

        if "company" in df_p.columns:
            co_list = df_p["company"].dropna().tolist()
            sel_co = st.selectbox("Select company to view / push",
                                  ["—"] + co_list, key="partner_sel")
            if sel_co != "—":
                row_p = df_p[df_p["company"] == sel_co].iloc[0]
                with st.expander("Company detail", expanded=False):
                    for field in ["country", "partner_classification", "urgency",
                                  "estimated_deal_size", "proposed_solutions",
                                  "why_aligned", "outreach_angle", "key_tenders",
                                  "issuing_departments"]:
                        val = row_p.get(field)
                        if val is not None and str(val) not in ("", "nan", "None"):
                            st.markdown(f"**{field.replace('_', ' ').title()}:** {val}")
                if monday_active:
                    if st.button("Push to Companies board", key="partner_push"):
                        with st.spinner("Pushing…"):
                            res_p = push_partner_to_companies(row_p.to_dict())
                        st.success(
                            f"Action: **{res_p.get('action')}** | "
                            f"ID: {res_p.get('item_id')}"
                        )
                else:
                    st.info("Add MONDAY_API_KEY to enable push.")

    st.divider()

    # On-demand partner analysis
    st.markdown("#### Run partner analysis now")
    st.caption("Analyses the awarded tenders data and identifies top companies to approach.")
    if st.button("Analyse awarded tenders for partners", key="partner_run"):
        df_aw_for_analysis = _load_awarded()
        if df_aw_for_analysis.empty:
            st.warning("No awarded tender data to analyse.")
        else:
            with st.spinner(f"Analysing {len(df_aw_for_analysis)} awarded tenders…"):
                try:
                    results = ai_analyse_partners(df_aw_for_analysis)
                    if results:
                        # Persist to history table
                        rows_to_insert = []
                        for p in results:
                            rows_to_insert.append({
                                "company":              str(p.get("company", ""))[:200],
                                "country":              str(p.get("country", ""))[:100],
                                "crs_score":            p.get("tenders_won"),
                                "why":                  str(p.get("why_aligned", ""))[:500],
                                "outreach_angle":       str(p.get("outreach_angle", ""))[:500],
                                "urgency":              str(p.get("urgency", ""))[:20],
                                "partnership_type":     str(p.get("partner_classification", ""))[:100],
                                "estimated_deal_size":  str(p.get("estimated_deal_size", ""))[:50],
                                "proposed_solutions":   json.dumps(p.get("proposed_solutions", [])),
                            })
                        supabase.table("partner_recommendation_history").insert(rows_to_insert).execute()
                        st.cache_data.clear()
                        st.success(f"Found {len(results)} partner candidates — saved to history.")
                        st.dataframe(
                            pd.DataFrame(results)[
                                [c for c in ["company", "country", "tenders_won",
                                             "partner_classification", "urgency",
                                             "proposed_solutions", "outreach_angle"]
                                 if c in pd.DataFrame(results).columns]
                            ],
                            use_container_width=True, hide_index=True,
                        )
                    else:
                        st.warning("No suitable partner candidates identified.")
                except Exception as e:
                    st.error(f"Analysis failed: {e}")

    st.divider()
    st.markdown("#### Awarded tender context")
    df_aw_p = _apply_country(_load_awarded())
    if not df_aw_p.empty:
        show_aw = [c for c in ["tender_number", "department_name", "title",
                                "country", "winning_bidder", "award_value",
                                "closing_date"]
                   if c in df_aw_p.columns]
        st.dataframe(df_aw_p[show_aw] if show_aw else df_aw_p,
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
        lv_status_opts = ["All"]
        if not df_lv.empty and "status" in df_lv.columns:
            lv_status_opts += sorted(df_lv["status"].dropna().unique().tolist())
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
            verified_n = (df_lv["status"].str.lower() == "verified").sum()
            c2.metric("Verified", int(verified_n))
        if "accuracy_score" in df_lv.columns:
            avg_acc = pd.to_numeric(df_lv["accuracy_score"], errors="coerce").mean()
            c3.metric("Avg accuracy", f"{avg_acc:.0f}%" if pd.notna(avg_acc) else "—")

        show_lv = [c for c in ["contact_name", "contact_title", "company",
                                "email", "phone", "authority", "accuracy_score",
                                "status", "provider_chain", "country", "created_at"]
                   if c in df_lv.columns]
        st.dataframe(df_lv[show_lv] if show_lv else df_lv,
                     use_container_width=True, hide_index=True)

        # Push to Monday Leads board
        name_col = "contact_name" if "contact_name" in df_lv.columns else None
        if name_col:
            st.divider()
            sel_lead = st.selectbox(
                "Select contact to push / look up",
                ["—"] + df_lv[name_col].dropna().tolist(),
                key="lv_sel",
            )
            if sel_lead != "—":
                row_l = df_lv[df_lv[name_col] == sel_lead].iloc[0].to_dict()

                with st.expander("Contact detail", expanded=False):
                    for field in ["contact_name", "contact_title", "company", "email",
                                  "phone", "linkedin", "authority", "accuracy_score",
                                  "provider_chain", "status", "country"]:
                        val = row_l.get(field)
                        if val is not None and str(val) not in ("", "nan", "None"):
                            st.markdown(f"**{field.replace('_', ' ').title()}:** {val}")

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
                            st.success(
                                f"Action: **{res_l.get('action')}** | "
                                f"ID: {res_l.get('item_id')}"
                            )
                    with col_crm:
                        if st.button("Check Monday CRM", key="lv_crm"):
                            with st.spinner("Looking up CRM…"):
                                crm = lookup_monday_crm(contact_payload)
                            if crm.get("on_crm"):
                                st.info(
                                    f"Found on **{crm['crm_board']}** — "
                                    f"[{crm.get('crm_title', sel_lead)}]"
                                    f"({crm.get('crm_url', '')})"
                                )
                            else:
                                st.warning("Not found in Monday CRM.")
                else:
                    st.info("Add MONDAY_API_KEY to enable push.")
