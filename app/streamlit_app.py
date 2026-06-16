"""
CRS Competitive Intelligence Dashboard — v2
Lean 4-tab dashboard. The nightly GitHub Action owns scraping + AI scoring;
this app is display + Monday.com push only.
"""
import os
import sys
import streamlit as st
import pandas as pd
from supabase import create_client, Client

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

# ── Supabase connection ───────────────────────────────────────────────────────
@st.cache_resource
def _get_supabase() -> Client:
    url = st.secrets.get("SUPABASE_URL") or os.getenv("SUPABASE_URL", "")
    key = st.secrets.get("SUPABASE_KEY") or os.getenv("SUPABASE_KEY", "")
    if not url or not key:
        st.error("Set SUPABASE_URL and SUPABASE_KEY in secrets.")
        st.stop()
    return create_client(url, key)

supabase = _get_supabase()

# ── Sidebar ───────────────────────────────────────────────────────────────────
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

    if st.button("Clear cache", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# ── Data loaders ──────────────────────────────────────────────────────────────
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
         .order("created_at", desc=True)
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

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_overview, tab_opps, tab_partners, tab_leads = st.tabs([
    "🏠 Overview",
    "📢 Opportunities",
    "🤝 Partners",
    "✅ Lead Verification",
])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — OVERVIEW
# Counts + recent high-score tenders; read-only from Supabase.
# Tables: sa_tenders, awarded_tenders, pipeline_runs
# ══════════════════════════════════════════════════════════════════════════════
with tab_overview:
    st.subheader("CRS Tender Intelligence — Overview")
    st.caption(
        "Africa-wide government tender intelligence for Cyber Retaliator Solutions — "
        "active tenders, historical awards, and AI-powered partner intelligence."
    )

    df_t   = _load_tenders()
    df_aw  = _load_awarded()
    df_run = _load_pipeline_runs()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Open tenders",     len(df_t))
    c2.metric("Awarded tenders",  len(df_aw))
    c3.metric("Countries (open)", df_t["country"].nunique() if "country" in df_t.columns else 0)
    last = df_run.iloc[0].to_dict() if not df_run.empty else {}
    c4.metric("Last pipeline run", last.get("status", "—"))

    st.divider()
    st.markdown("#### Top-scored open tenders")
    if df_t.empty:
        st.info("No open tenders found. Run the nightly pipeline to populate.")
    else:
        score_col = "ai_score" if "ai_score" in df_t.columns else "crs_alignment_score"
        top = (df_t
               .assign(_s=pd.to_numeric(df_t[score_col], errors="coerce"))
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
        show_r = [c for c in ["run_at", "status", "trigger",
                               "tenders_scraped", "tenders_scored", "duration_secs"]
                  if c in df_run.columns]
        st.dataframe(
            df_run[show_r] if show_r else df_run,
            use_container_width=True, hide_index=True,
        )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — OPPORTUNITIES
# Open tenders: filter, detail view, push to Monday.
# Table: sa_tenders
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

    # Detail panel + Monday push
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


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — PARTNERS
# Awarded → partner recommendations; read history / push to Monday.
# Tables: partner_recommendation_history, awarded_tenders
# ══════════════════════════════════════════════════════════════════════════════
with tab_partners:
    st.subheader("Partner Recommendations")
    st.caption("AI-generated partner analysis written by the nightly pipeline.")

    df_p = _apply_country(_load_partner_history(), col="country")

    if df_p.empty:
        st.info("No partner recommendations yet. The nightly pipeline populates this table.")
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
            sel_co = st.selectbox("Select company to push",
                                  ["—"] + co_list, key="partner_sel")
            if sel_co != "—":
                row_p = df_p[df_p["company"] == sel_co].iloc[0]
                with st.expander("Company detail", expanded=False):
                    for field in ["country", "partner_classification", "urgency",
                                  "estimated_deal_size", "proposed_solutions",
                                  "why_aligned", "outreach_angle", "key_tenders"]:
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
# Contacts verified / quarantined by the pipeline; push to Monday.
# Table: lead_verification_log
# ══════════════════════════════════════════════════════════════════════════════
with tab_leads:
    st.subheader("Lead Verification")
    st.caption("Contacts verified or quarantined by the pipeline cascade.")

    df_lv = _load_lead_verifications()

    lv_status_opts = ["All"]
    if not df_lv.empty and "status" in df_lv.columns:
        lv_status_opts += sorted(df_lv["status"].dropna().unique().tolist())
    lv_status = st.selectbox("Status", lv_status_opts, key="lv_status")
    if lv_status != "All" and "status" in df_lv.columns:
        df_lv = df_lv[df_lv["status"] == lv_status]

    if df_lv.empty:
        st.info("No verified leads yet.")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Total", len(df_lv))
        if "status" in df_lv.columns:
            verified_n = (df_lv["status"].str.lower() == "verified").sum()
            c2.metric("Verified", int(verified_n))
        if "accuracy_score" in df_lv.columns:
            avg_acc = pd.to_numeric(df_lv["accuracy_score"], errors="coerce").mean()
            c3.metric("Avg accuracy", f"{avg_acc:.0f}" if pd.notna(avg_acc) else "—")

        show_lv = [c for c in ["contact_name", "contact_title", "company",
                                "email", "phone", "authority", "accuracy_score",
                                "status", "provider_chain", "country", "created_at"]
                   if c in df_lv.columns]
        st.dataframe(df_lv[show_lv] if show_lv else df_lv,
                     use_container_width=True, hide_index=True)

        # Push to Monday Leads board
        name_col = "contact_name" if "contact_name" in df_lv.columns else None
        if monday_active and name_col:
            st.divider()
            names = df_lv[name_col].dropna().tolist()
            sel_lead = st.selectbox("Push contact to Monday Leads board",
                                    ["—"] + names, key="lv_sel")
            if sel_lead != "—":
                row_l = df_lv[df_lv[name_col] == sel_lead].iloc[0].to_dict()
                # Map log columns to what sync_lead_to_monday expects
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

                col_push, col_crm = st.columns(2)
                with col_push:
                    if st.button("Push to Monday", key="lv_push"):
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
        elif not monday_active:
            st.info("Add MONDAY_API_KEY to enable push.")
