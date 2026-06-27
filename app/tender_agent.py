"""
tender_agent.py — CRS Autonomous Tender Intelligence Agent

Replaces manual OCDS scraping with an AI-driven web-search pipeline:
  Phase 1 — Tender discovery: targeted queries across African gov portals
  Phase 2 — Attack signal monitoring: breach/ransomware news → CRS leads
  Phase 3 — Partner fit analysis: ICT companies winning African tenders
  Phase 4 — Apollo enrichment: decision-makers for high-score (≥7) leads

Designed to run headlessly in GitHub Actions. No Streamlit dependency.
Reads secrets from environment variables; writes to the same Supabase tables
the dashboard reads (sa_tenders, partner_recommendation_history, agent_leads,
attack_signal_history).

Entry point:  run_agent(log=print)
"""

import os
import re
import json
import time
import hashlib
import datetime as _dt
import urllib.request as _urlreq

import requests

# ═══════════════════════════════════════════════════════════════════════════
# MODULE GLOBALS
# ═══════════════════════════════════════════════════════════════════════════
supabase   = None
groq_ai    = None
cerebras_ai= None
openrouter_ai = None
github_ai  = None
nvidia_ai  = None
deepseek_ai= None
gemini_client = None
_GENAI_NEW = False

_TODAY = _dt.date.today().isoformat()
_YEAR  = _dt.date.today().year

# CRS Capability Matrix — injected into every AI prompt
_CRS_SYSTEM = (
    "You are the Autonomous Tender Intelligence Agent for Cyber Retaliator Solutions (CRS), "
    "a South African cybersecurity VAD and IBM/Red Hat/SUSE/CompTIA training partner.\n\n"
    "CRS PORTFOLIO:\n"
    "  Security vendors: Vectra AI (NDR/XDR/ITDR), vRx (vuln/patch), Strobes (CTEM/PTaaS), "
    "Aikido (DevSecOps/AppSec), Flare (dark web/DRPS), BeachheadSecure (encryption/MFA), "
    "SMBsecure (SMB/POPIA), Telivy (MSSP audit), BlueFlag (SDLC), Todyl (SASE/SIEM/MXDR), "
    "Panorays (TPRM/DORA), GoldPhish/CRE (phishing awareness), Standss SendGuard (email GRC).\n"
    "  Training: IBM, Red Hat, SUSE, CompTIA. Own VAPT services.\n\n"
    "TARGET MARKETS: Government (all African countries), financial services, healthcare, "
    "education, telcos, mining, enterprises with dev teams.\n"
    "STRONG FIT: cybersecurity, ICT, SOC/MDR, POPIA compliance, vulnerability management.\n"
    "WEAK FIT: civil construction, catering, cleaning, pure hardware/roads/buildings.\n\n"
    "SCORING RULES:\n"
    "  9-10 = Perfect CRS fit (direct security/training requirement, large org).\n"
    "  7-8  = High fit (ICT infrastructure with clear security angle).\n"
    "  5-6  = Medium fit (general ICT, could be a training or tooling opportunity).\n"
    "  3-4  = Low fit (hardware-heavy, small org, minimal security angle).\n"
    "  1-2  = Irrelevant (catering, civil works, stationery, non-ICT goods).\n"
    "Always return structured JSON. Never hallucinate dates or contact details."
)

# African government tender portal domains and targeted search suffixes
_TENDER_PORTALS = [
    "etenders.gov.za",
    "tenders.go.ke",
    "procurement.gov.ng",
    "gpp.gov.gh",
    "ppda.go.ug",
    "ppaa.go.tz",
    "zppa.org.zm",
    "minecofin.gov.rw",
    "sitatunga.botswana.gov.bw",
    "publicprocurement.gov.mw",
]

_TENDER_QUERIES = [
    f'"cybersecurity" OR "information security" tender Africa {_YEAR}',
    f'"ICT" OR "software" OR "cloud" tender "government" Africa {_YEAR}',
    f'"vulnerability" OR "SOC" OR "SIEM" OR "network security" tender {_YEAR}',
    f'"training" "cybersecurity" OR "IBM" OR "CompTIA" tender Africa {_YEAR}',
    f'site:etenders.gov.za "cybersecurity" OR "security software" {_YEAR}',
    f'site:tenders.go.ke "ICT" OR "cybersecurity" OR "software" {_YEAR}',
    f'"penetration testing" OR "VAPT" OR "security assessment" tender Africa {_YEAR}',
    f'"POPIA" OR "data protection" OR "compliance" tender "South Africa" {_YEAR}',
    f'"managed security" OR "MSSP" OR "SOC services" tender Africa {_YEAR}',
    f'"Red Hat" OR "SUSE" OR "Linux" training tender Africa {_YEAR}',
]

_ATTACK_QUERIES = [
    f'"ransomware" "South Africa" {_YEAR}',
    f'"data breach" "Kenya" OR "Nigeria" OR "Ghana" {_YEAR}',
    f'"cyberattack" OR "cyber attack" Africa {_YEAR}',
    f'"hacked" OR "compromised" "government" Africa {_YEAR}',
    f'"malware" "Africa" company {_YEAR}',
]

_PARTNER_QUERIES = [
    f'"ICT company" "won" OR "awarded" tender Africa {_YEAR}',
    f'"system integrator" "cybersecurity" Africa {_YEAR}',
    f'"IT company" "government contract" Africa {_YEAR}',
    f'"technology partner" "security" Africa {_YEAR}',
]


# ═══════════════════════════════════════════════════════════════════════════
# INIT
# ═══════════════════════════════════════════════════════════════════════════
def _env(*names: str, default: str = "") -> str:
    for n in names:
        v = os.environ.get(n)
        if v:
            return str(v).strip()
    return default


def init_supabase():
    global supabase
    from supabase import create_client
    url = _env("SUPABASE_URL")
    key = _env("SUPABASE_KEY", "SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set.")
    supabase = create_client(url, key)
    return supabase


def init_ai(log=print):
    global groq_ai, cerebras_ai, openrouter_ai, github_ai
    global nvidia_ai, deepseek_ai, gemini_client, _GENAI_NEW
    providers = []
    for name, setup in [
        ("Groq", lambda: _init_groq()),
        ("Cerebras", lambda: _init_cerebras()),
        ("OpenRouter", lambda: _init_openrouter()),
        ("GitHub", lambda: _init_github()),
        ("NVIDIA", lambda: _init_nvidia()),
        ("DeepSeek", lambda: _init_deepseek()),
        ("Gemini", lambda: _init_gemini()),
    ]:
        try:
            if setup():
                providers.append(name)
        except Exception as e:
            log(f"  ⚠️ {name} init failed: {e}")
    log(f"  AI providers: {providers or ['none — check keys']}")
    return providers


def _init_groq():
    global groq_ai
    k = _env("GROQ_API_KEY")
    if not k: return False
    from groq import Groq
    groq_ai = Groq(api_key=k)
    return True

def _init_cerebras():
    global cerebras_ai
    k = _env("CEREBRAS_API_KEY")
    if not k: return False
    from cerebras.cloud.sdk import Cerebras
    cerebras_ai = Cerebras(api_key=k)
    return True

def _init_openrouter():
    global openrouter_ai
    k = _env("OPENROUTER_API_KEY")
    if not k: return False
    from openai import OpenAI
    openrouter_ai = OpenAI(api_key=k, base_url="https://openrouter.ai/api/v1",
                           default_headers={"HTTP-Referer": "https://github.com/Drys-CRS/CRS-Lead-Gen"})
    return True

def _init_github():
    global github_ai
    k = _env("GH_PAT", "GITHUB_MODELS_TOKEN", "GH_MODELS_TOKEN")
    if not k: return False
    from openai import OpenAI
    github_ai = OpenAI(api_key=k, base_url="https://models.inference.ai.azure.com")
    return True

def _init_nvidia():
    global nvidia_ai
    k = _env("NVIDIA_API_KEY")
    if not k: return False
    from openai import OpenAI
    nvidia_ai = OpenAI(api_key=k, base_url="https://integrate.api.nvidia.com/v1")
    return True

def _init_deepseek():
    global deepseek_ai
    k = _env("DEEPSEEK_API_KEY")
    if not k: return False
    from openai import OpenAI
    deepseek_ai = OpenAI(api_key=k, base_url="https://api.deepseek.com")
    return True

def _init_gemini():
    global gemini_client, _GENAI_NEW
    k = _env("GEMINI_API_KEY")
    if not k: return False
    import google.genai as genai
    gemini_client = genai.Client(api_key=k)
    _GENAI_NEW = True
    return True


# ═══════════════════════════════════════════════════════════════════════════
# AI CASCADE
# ═══════════════════════════════════════════════════════════════════════════
def _call_ai(prompt: str, log=print, retries: int = 2) -> str:
    """Call AI providers in cascade order. Returns response text."""
    cascade = [
        ("Groq",       groq_ai,       "llama-3.3-70b-versatile",           "chat.completions"),
        ("Cerebras",   cerebras_ai,   "llama3.3-70b",                       "chat.completions"),
        ("OpenRouter", openrouter_ai, "meta-llama/llama-3.3-70b-instruct:free", "chat.completions"),
        ("GitHub",     github_ai,     "Llama-3.3-70B-Instruct",            "chat.completions"),
        ("NVIDIA",     nvidia_ai,     "meta/llama-3.3-70b-instruct",       "chat.completions"),
        ("DeepSeek",   deepseek_ai,   "deepseek-chat",                     "chat.completions"),
    ]
    for name, client, model, _ in cascade:
        if client is None:
            continue
        for attempt in range(retries):
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3, max_tokens=1200,
                )
                return resp.choices[0].message.content.strip()
            except Exception as e:
                if attempt == retries - 1:
                    log(f"  ⚠️ {name} failed: {str(e)[:80]}")
                time.sleep(1)

    # Gemini fallback
    if gemini_client and _GENAI_NEW:
        try:
            from google.genai import types as _gt
            r = gemini_client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
                config=_gt.GenerateContentConfig(temperature=0.3, max_output_tokens=1200),
            )
            return r.text.strip()
        except Exception as e:
            log(f"  ⚠️ Gemini failed: {str(e)[:80]}")
    raise RuntimeError("All AI providers exhausted.")


# ═══════════════════════════════════════════════════════════════════════════
# WEB SEARCH
# ═══════════════════════════════════════════════════════════════════════════
def _web_search(query: str, num: int = 10, log=print) -> list:
    """Search using SERPER → SERPAPI → Google CSE. Returns list of {title, url, snippet, date}."""
    serper_key  = _env("SERPER_API_KEY")
    serpapi_key = _env("SERPAPI_API_KEY")
    google_key  = _env("GOOGLE_API_KEY")
    google_cse  = _env("GOOGLE_CSE_ID")

    if serper_key:
        try:
            r = requests.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": serper_key, "Content-Type": "application/json"},
                json={"q": query, "num": num},
                timeout=15,
            )
            r.raise_for_status()
            items = r.json().get("organic", [])
            return [{"title": i.get("title",""), "url": i.get("link",""),
                     "snippet": i.get("snippet",""), "date": i.get("date","")}
                    for i in items]
        except Exception as e:
            log(f"  ⚠️ Serper: {e}")

    if serpapi_key:
        try:
            r = requests.get(
                "https://serpapi.com/search",
                params={"api_key": serpapi_key, "q": query, "num": num, "engine": "google"},
                timeout=20,
            )
            r.raise_for_status()
            items = r.json().get("organic_results", [])
            return [{"title": i.get("title",""), "url": i.get("link",""),
                     "snippet": i.get("snippet",""), "date": i.get("date","")}
                    for i in items]
        except Exception as e:
            log(f"  ⚠️ SerpAPI: {e}")

    if google_key and google_cse:
        try:
            r = requests.get(
                "https://www.googleapis.com/customsearch/v1",
                params={"key": google_key, "cx": google_cse, "q": query, "num": min(num, 10)},
                timeout=15,
            )
            r.raise_for_status()
            items = r.json().get("items", [])
            return [{"title": i.get("title",""), "url": i.get("link",""),
                     "snippet": i.get("snippet",""), "date": ""}
                    for i in items]
        except Exception as e:
            log(f"  ⚠️ Google CSE: {e}")

    log("  ⚠️ No search API configured (SERPER_API_KEY / SERPAPI_API_KEY / GOOGLE_API_KEY)")
    return []


def _fetch_page(url: str, max_chars: int = 4000) -> str:
    """Fetch a URL and return stripped visible text."""
    try:
        req = _urlreq.Request(url, headers={"User-Agent": "Mozilla/5.0 CRS-Agent/1.0"})
        with _urlreq.urlopen(req, timeout=12) as r:
            raw = r.read().decode("utf-8", errors="ignore")
        raw = re.sub(r"<script[^>]*>[\s\S]*?</script>", "", raw, flags=re.I)
        raw = re.sub(r"<style[^>]*>[\s\S]*?</style>",  "", raw, flags=re.I)
        raw = re.sub(r"<[^>]+>", " ", raw)
        return re.sub(r"\s+", " ", raw).strip()[:max_chars]
    except Exception:
        return ""


# ═══════════════════════════════════════════════════════════════════════════
# DEDUPLICATION
# ═══════════════════════════════════════════════════════════════════════════
def _title_hash(title: str) -> str:
    return hashlib.md5(re.sub(r"[^a-z0-9]", "", (title or "").lower()).encode()).hexdigest()[:12]


def _load_known_hashes(log=print) -> set:
    """Load title hashes from existing sa_tenders rows to avoid re-inserting."""
    try:
        rows = supabase.table("sa_tenders").select("title").execute().data or []
        return {_title_hash(r.get("title","")) for r in rows}
    except Exception as e:
        log(f"  ⚠️ Could not load known hashes: {e}")
        return set()


def _load_irrelevant_patterns(log=print) -> list:
    """Load titles marked is_irrelevant=True for the feedback loop."""
    try:
        rows = (supabase.table("sa_tenders")
                .select("title,department_name")
                .eq("is_irrelevant", True)
                .execute().data or [])
        # Extract first 3 significant words from each irrelevant title as a negative pattern
        patterns = []
        for r in rows:
            words = re.findall(r"\b[a-z]{4,}\b", (r.get("title","") or "").lower())
            if len(words) >= 2:
                patterns.append(words[0])
        return list(set(patterns))
    except Exception:
        return []


# ═══════════════════════════════════════════════════════════════════════════
# PHASE 1 — TENDER DISCOVERY
# ═══════════════════════════════════════════════════════════════════════════
def _ai_extract_tender(title: str, snippet: str, url: str, content: str, log=print) -> dict | None:
    """Use AI to extract structured tender data from a search result."""
    prompt = (
        f"{_CRS_SYSTEM}\n\n"
        "Extract structured tender data from the search result below.\n"
        "If this is NOT a government/private sector procurement tender for ICT/security/training, "
        "return {\"is_tender\": false}.\n"
        "Return ONLY valid JSON:\n"
        '{"is_tender":true,"title":"full title","department_name":"dept or org",'
        '"country":"country name","description":"1-3 sentence description",'
        '"closing_date":"YYYY-MM-DD or null","tender_number":"ref or null",'
        '"source_url":"url","category":"ICT|Security|Training|Cloud|Other"}\n\n'
        f"SEARCH TITLE: {title}\n"
        f"SNIPPET: {snippet}\n"
        f"URL: {url}\n"
        f"PAGE CONTENT (truncated):\n{content[:2000]}"
    )
    try:
        raw = _call_ai(prompt, log=log)
        m = re.search(r'\{[\s\S]*\}', raw)
        if m:
            data = json.loads(m.group(0))
            if not data.get("is_tender"):
                return None
            data.pop("is_tender", None)
            return data
    except Exception as e:
        log(f"  ⚠️ Extraction failed for {url[:60]}: {e}")
    return None


def _ai_score_tender(tender: dict, log=print) -> dict:
    """Score a tender against the CRS Capability Matrix."""
    prompt = (
        f"{_CRS_SYSTEM}\n\n"
        "Score this tender opportunity for CRS. Return ONLY valid JSON:\n"
        '{"score":<1-10>,"rationale":"2-3 sentences",'
        '"proposed_solutions":["sol1","sol2"],'
        '"partner_type":"System Integrator|MSP|VAR|Training Provider|Consulting/Advisory",'
        '"outreach_angle":"one sentence — specific CRS product + confirmed pain point",'
        '"is_irrelevant":<true if clearly non-ICT>}\n\n'
        f"TITLE: {tender.get('title','')}\n"
        f"DEPARTMENT: {tender.get('department_name','')}\n"
        f"COUNTRY: {tender.get('country','')}\n"
        f"CATEGORY: {tender.get('category','')}\n"
        f"DESCRIPTION: {tender.get('description','')}\n"
    )
    try:
        raw = _call_ai(prompt, log=log)
        m = re.search(r'\{[\s\S]*\}', raw)
        if m:
            return json.loads(m.group(0))
    except Exception as e:
        log(f"  ⚠️ Scoring failed: {e}")
    return {"score": 0, "rationale": "Scoring failed", "proposed_solutions": [],
            "outreach_angle": "", "is_irrelevant": False}


def _search_tenders(log=print, known_hashes: set = None, neg_patterns: list = None) -> int:
    """Phase 1: search for African ICT/security tenders and insert into sa_tenders."""
    if known_hashes is None:
        known_hashes = set()
    if neg_patterns is None:
        neg_patterns = []

    found = scored = saved = 0
    for query in _TENDER_QUERIES:
        log(f"  🔍 Tender query: {query[:80]}")
        results = _web_search(query, num=8, log=log)
        for result in results:
            title   = result.get("title", "")
            url     = result.get("url", "")
            snippet = result.get("snippet", "")
            if not title or not url:
                continue
            h = _title_hash(title)
            if h in known_hashes:
                continue
            # Feedback loop: skip titles matching irrelevant patterns
            title_lower = title.lower()
            if any(p in title_lower for p in neg_patterns[:20]):
                continue
            found += 1
            page = _fetch_page(url)
            tender = _ai_extract_tender(title, snippet, url, page, log=log)
            if tender is None:
                continue
            scored_data = _ai_score_tender(tender, log=log)
            score = int(scored_data.get("score", 0) or 0)
            if score == 0:
                continue
            scored += 1
            row = {
                "title":           tender.get("title", title)[:500],
                "department_name": tender.get("department_name", "")[:300],
                "country":         tender.get("country", "Unknown"),
                "description":     tender.get("description", snippet)[:2000],
                "closing_date":    tender.get("closing_date"),
                "tender_number":   tender.get("tender_number", f"AGENT-{h}"),
                "source_url":      url,
                "category":        tender.get("category", "ICT"),
                "ai_score":        score,
                "ai_rationale":    scored_data.get("rationale", ""),
                "ai_solutions":    json.dumps(scored_data.get("proposed_solutions", [])),
                "ai_outreach_angle": scored_data.get("outreach_angle", ""),
                "is_irrelevant":   bool(scored_data.get("is_irrelevant", False)),
                "status":          "open",
                "source":          "agent_web_search",
            }
            try:
                supabase.table("sa_tenders").upsert(
                    row, on_conflict="tender_number,department_name"
                ).execute()
                known_hashes.add(h)
                saved += 1
                log(f"    ✅ Saved [{score}/10] {row['title'][:60]} ({row['country']})")
            except Exception as e:
                log(f"    ❌ DB error: {str(e)[:80]}")
        time.sleep(1)  # rate-limit between queries

    log(f"  📊 Tenders: {found} found · {scored} scored · {saved} saved")
    return saved


# ═══════════════════════════════════════════════════════════════════════════
# PHASE 2 — ATTACK SIGNAL MONITORING
# ═══════════════════════════════════════════════════════════════════════════
def _search_attack_signals(log=print) -> int:
    """Phase 2: search for African cybersecurity incidents and write to attack_signal_history."""
    saved = 0
    # Load existing signal headlines to avoid duplicates
    try:
        existing = {r.get("headline","") for r in
                    (supabase.table("attack_signal_history")
                     .select("headline").order("created_at", desc=True)
                     .limit(200).execute().data or [])}
    except Exception:
        existing = set()

    for query in _ATTACK_QUERIES:
        log(f"  🔍 Attack signal query: {query[:80]}")
        results = _web_search(query, num=6, log=log)
        for result in results:
            title   = result.get("title", "")
            url     = result.get("url", "")
            snippet = result.get("snippet", "")
            if not title or title in existing:
                continue
            prompt = (
                f"{_CRS_SYSTEM}\n\n"
                "Analyse this cybersecurity incident news item as a CRS lead opportunity.\n"
                "Return ONLY valid JSON:\n"
                '{"is_attack_signal":true,"company":"affected company or Unknown",'
                '"country":"country","attack_type":"Ransomware|Breach|DDoS|Phishing|Other",'
                '"affected_sector":"Government|Finance|Healthcare|Education|Other",'
                '"outreach_angle":"how CRS should approach this company",'
                '"crs_solutions":["sol1"],'
                '"score":<1-10 as CRS lead>}\n\n'
                f"HEADLINE: {title}\nSNIPPET: {snippet}\nURL: {url}"
            )
            try:
                raw = _call_ai(prompt, log=log)
                m = re.search(r'\{[\s\S]*\}', raw)
                if not m:
                    continue
                data = json.loads(m.group(0))
                if not data.get("is_attack_signal") or int(data.get("score", 0) or 0) < 4:
                    continue
                row = {
                    "headline":          title[:500],
                    "url":               url,
                    "company":           data.get("company","Unknown"),
                    "country":           data.get("country","Unknown"),
                    "attack_type":       data.get("attack_type","Other"),
                    "affected_sector":   data.get("affected_sector","Other"),
                    "outreach_angle":    data.get("outreach_angle",""),
                    "crs_solutions":     json.dumps(data.get("crs_solutions",[])),
                    "lead_score":        int(data.get("score", 0) or 0),
                    "source":            "agent_web_search",
                    "signal_date":       result.get("date","") or _TODAY,
                }
                supabase.table("attack_signal_history").upsert(
                    row, on_conflict="headline"
                ).execute()
                existing.add(title)
                saved += 1
                log(f"    ✅ Attack signal [{row['lead_score']}/10]: {row['company']} ({row['attack_type']})")
            except Exception as e:
                log(f"    ❌ Signal error: {str(e)[:80]}")
        time.sleep(1)

    log(f"  📊 Attack signals: {saved} saved")
    return saved


# ═══════════════════════════════════════════════════════════════════════════
# PHASE 3 — PARTNER FIT ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════
def _search_partners(log=print) -> int:
    """Phase 3: identify ICT companies winning African tenders as potential CRS channel partners."""
    saved = 0
    # Load existing partner names to avoid duplicates
    try:
        existing = {r.get("company","") for r in
                    (supabase.table("partner_recommendation_history")
                     .select("company").execute().data or [])}
    except Exception:
        existing = set()

    for query in _PARTNER_QUERIES:
        log(f"  🔍 Partner query: {query[:80]}")
        results = _web_search(query, num=8, log=log)
        for result in results:
            title   = result.get("title", "")
            url     = result.get("url", "")
            snippet = result.get("snippet", "")
            if not title:
                continue
            prompt = (
                f"{_CRS_SYSTEM}\n\n"
                "Assess this company as a potential CRS channel partner.\n"
                "Return ONLY valid JSON:\n"
                '{"is_partner_candidate":true,"company":"exact company name",'
                '"country":"country","sector":"ICT|Security|Telco|Other",'
                '"partner_fit":"High|Medium|Low",'
                '"why":"2-3 sentences — why CRS should partner with this company",'
                '"proposed_solutions":["sol1"],'
                '"outreach_angle":"specific first-contact angle",'
                '"urgency":"High|Medium|Low",'
                '"estimated_deal_size":"< R500k|R500k-R2m|R2m-R10m|> R10m",'
                '"crs_score":<1-10>}\n\n'
                f"RESULT: {title}\nSNIPPET: {snippet}\nURL: {url}"
            )
            try:
                raw = _call_ai(prompt, log=log)
                m = re.search(r'\{[\s\S]*\}', raw)
                if not m:
                    continue
                data = json.loads(m.group(0))
                if not data.get("is_partner_candidate"):
                    continue
                company = data.get("company", "").strip()
                if not company or company in existing or company.lower() in ("unknown","none"):
                    continue
                if int(data.get("crs_score", 0) or 0) < 4:
                    continue
                row = {
                    "company":            company,
                    "country":            data.get("country","Unknown"),
                    "sector":             data.get("sector","ICT"),
                    "partner_fit":        data.get("partner_fit","Medium"),
                    "why":                data.get("why",""),
                    "proposed_solutions": json.dumps(data.get("proposed_solutions",[])),
                    "outreach_angle":     data.get("outreach_angle",""),
                    "urgency":            data.get("urgency","Medium"),
                    "estimated_deal_size": data.get("estimated_deal_size",""),
                    "crs_score":          int(data.get("crs_score", 0) or 0),
                    "source":             "agent_web_search",
                    "run_at":             _dt.datetime.utcnow().isoformat(),
                }
                supabase.table("partner_recommendation_history").insert(row).execute()
                existing.add(company)
                saved += 1
                log(f"    ✅ Partner [{data.get('partner_fit')}]: {company} ({data.get('country')})")
            except Exception as e:
                log(f"    ❌ Partner error: {str(e)[:80]}")
        time.sleep(1)

    log(f"  📊 Partners: {saved} saved")
    return saved


# ═══════════════════════════════════════════════════════════════════════════
# PHASE 4 — APOLLO ENRICHMENT FOR HIGH-SCORE LEADS
# ═══════════════════════════════════════════════════════════════════════════
def _enrich_with_apollo(log=print) -> int:
    """Phase 4: use Apollo to find decision-makers for high-score (≥7) sa_tenders
    that don't yet have a contact and write results to agent_leads."""
    apollo_key = _env("APOLLO_API_KEY")
    if not apollo_key:
        log("  ⚠️ APOLLO_API_KEY not set — skipping enrichment phase")
        return 0

    try:
        rows = (supabase.table("sa_tenders")
                .select("id,title,department_name,country,ai_outreach_angle")
                .gte("ai_score", 7)
                .is_("contact_email", "null")
                .neq("is_irrelevant", True)
                .order("ai_score", desc=True)
                .limit(10)
                .execute().data or [])
    except Exception as e:
        log(f"  ⚠️ Could not load high-score tenders: {e}")
        return 0

    # Already-enriched source_ids
    try:
        enriched = {r.get("source_id","") for r in
                    (supabase.table("agent_leads").select("source_id")
                     .eq("source_type","tender_enrichment").execute().data or [])}
    except Exception:
        enriched = set()

    saved = 0
    for row in rows:
        sid = str(row.get("id",""))
        if sid in enriched:
            continue
        dept = row.get("department_name","") or row.get("title","")[:40]
        country = row.get("country","")
        titles = ["CISO","Chief Information Security Officer","CTO","Head of ICT",
                  "IT Director","Head of Procurement","Head of IT","ICT Manager"]
        try:
            resp = requests.post(
                "https://api.apollo.io/v1/mixed_people/search",
                headers={"Content-Type": "application/json", "Cache-Control": "no-cache",
                         "X-Api-Key": apollo_key},
                json={
                    "organization_names": [dept],
                    "person_titles": titles,
                    "per_page": 5,
                    "page": 1,
                },
                timeout=20,
            )
            resp.raise_for_status()
            people = resp.json().get("people", [])
        except Exception as e:
            log(f"  ⚠️ Apollo search failed for {dept}: {e}")
            continue

        for person in people:
            name  = f"{person.get('first_name','')} {person.get('last_name','')}".strip()
            email = (person.get("email") or
                     (person.get("contact",{}) or {}).get("email","") or "")
            phone = ""
            if person.get("phone_numbers"):
                phone = person["phone_numbers"][0].get("sanitized_number","")
            li = person.get("linkedin_url","")
            lead_rec = {
                "source_type":   "tender_enrichment",
                "source_id":     sid,
                "company":       dept,
                "country":       country,
                "lead_type":     "Contact Lead",
                "score":         int(row.get("ai_score", 7) or 7),
                "rationale":     f"Decision-maker at {dept} — related to tender scoring ≥7",
                "outreach_note": row.get("ai_outreach_angle",""),
                "contact_name":  name,
                "contact_title": person.get("title",""),
                "contact_email": email,
                "contact_phone": phone,
                "contact_linkedin": li,
            }
            try:
                supabase.table("agent_leads").insert(lead_rec).execute()
                saved += 1
                log(f"    ✅ Apollo contact: {name} @ {dept}")
            except Exception as e:
                log(f"    ❌ agent_leads insert: {str(e)[:80]}")

        enriched.add(sid)
        time.sleep(0.5)

    log(f"  📊 Apollo enrichment: {saved} contacts added to agent_leads")
    return saved


# ═══════════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════
def run_agent(log=print) -> dict:
    """
    Execute the full CRS Tender Intelligence Agent pipeline.
    Call init_supabase() and init_ai() before this function.
    """
    start = _dt.datetime.utcnow()
    stats: dict = {"tenders": 0, "attack_signals": 0, "partners": 0, "contacts": 0, "errors": 0}

    log("=" * 60)
    log(f"CRS Tender Intelligence Agent  {start.isoformat()[:16]} UTC")
    log("=" * 60)

    log("\n📌 Loading deduplication state…")
    known_hashes = _load_known_hashes(log)
    neg_patterns  = _load_irrelevant_patterns(log)
    log(f"  {len(known_hashes)} known tenders · {len(neg_patterns)} negative patterns loaded")

    log("\n🔍 Phase 1 — Tender Discovery…")
    try:
        stats["tenders"] = _search_tenders(log, known_hashes, neg_patterns)
    except Exception as e:
        log(f"  ❌ Phase 1 error: {e}")
        stats["errors"] += 1

    log("\n🚨 Phase 2 — Attack Signal Monitoring…")
    try:
        stats["attack_signals"] = _search_attack_signals(log)
    except Exception as e:
        log(f"  ❌ Phase 2 error: {e}")
        stats["errors"] += 1

    log("\n🤝 Phase 3 — Partner Fit Analysis…")
    try:
        stats["partners"] = _search_partners(log)
    except Exception as e:
        log(f"  ❌ Phase 3 error: {e}")
        stats["errors"] += 1

    log("\n👤 Phase 4 — Apollo Enrichment…")
    try:
        stats["contacts"] = _enrich_with_apollo(log)
    except Exception as e:
        log(f"  ❌ Phase 4 error: {e}")
        stats["errors"] += 1

    elapsed = ((_dt.datetime.utcnow() - start).seconds) // 60
    log(f"\n✅ Agent complete in ~{elapsed}m")
    log(f"   Tenders: {stats['tenders']}  Attack signals: {stats['attack_signals']}"
        f"  Partners: {stats['partners']}  Contacts: {stats['contacts']}"
        f"  Errors: {stats['errors']}")
    return stats


if __name__ == "__main__":
    init_supabase()
    init_ai()
    run_agent()
