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
Company: CRS (Competitive Risk Solutions)
Core capabilities:
  - Cybersecurity consulting and managed services
  - Risk assessment and compliance (POPIA, ISO 27001, NIST)
  - Penetration testing and vulnerability management
  - Security awareness training
  - Incident response and forensics
  - IT governance and audit support
  - Software development and systems integration

Target sectors: Government, financial services, healthcare, education
Preferred contract value: R500,000 – R50,000,000
Certifications: (add your actual certs here)
Location: South Africa — national coverage
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
# 8. MAIN DASHBOARD
# ─────────────────────────────────────────────
st.title("🛡️ CRS Competitive Intelligence Dashboard")

# Sidebar
st.sidebar.header("Controls")
if st.sidebar.button("🔄 Refresh Data"):
    st.cache_data.clear()
    st.rerun()

st.sidebar.header("Filters")
competitor_search = st.sidebar.text_input("Filter by Winning Bidder")
dept_search = st.sidebar.text_input("Filter by Department")

# Load data
tenders_df = fetch_tenders()

if tenders_df.empty:
    st.warning("No data found. Ensure your scrapers have run successfully.")
    st.stop()

# Ensure AI columns exist in DataFrame
for col in ["ai_score", "ai_rationale"]:
    if col not in tenders_df.columns:
        tenders_df[col] = None

# Apply department filter
df_filtered = tenders_df.copy()
if dept_search:
    df_filtered = df_filtered[
        df_filtered["department_name"].str.contains(dept_search, case=False, na=False)
    ]

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
    display_cols = ["tender_number", "department_name", "title", "closing_date"]
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

        st.write(f"**Department:** {t.get('department_name', 'N/A')}")
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

        # Pivot
        pivot = awarded_df.pivot_table(
            values="numeric_value",
            index="winning_bidder",
            aggfunc={"numeric_value": ["sum", "count"]}
        )
        pivot.columns = ["Tender Count", "Total Won (ZAR)"]
        pivot = pivot.sort_values("Total Won (ZAR)", ascending=False)

        st.subheader("Competitor Market Share")
        st.dataframe(
            pivot.style.format({"Total Won (ZAR)": "R{:,.0f}"}),
            use_container_width=True
        )

        st.divider()
        st.subheader("Award Detail")
        st.dataframe(
            awarded_df[["tender_number", "department_name", "winning_bidder", "award_value", "title"]],
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