import streamlit as st
import pandas as pd
from supabase import create_client, Client
import os
import requests

# --- Page Configuration ---
st.set_page_config(page_title="CRS Target Pipeline", layout="wide")

# --- Supabase & Connection Setup ---
@st.cache_resource
def init_connection():
    # Attempt to retrieve secrets from Streamlit Cloud
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
        gh_pat = st.secrets["GH_PAT"]
    except Exception:
        # Fallback to environment variables if running locally
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        gh_pat = os.environ.get("GH_PAT")
    
    return {
        "supabase": create_client(url, key),
        "gh_token": gh_pat
    }

conn = init_connection()
supabase = conn["supabase"]

# --- GitHub Workflow Trigger ---
def trigger_github_workflow():
    owner = "Drys-CRS"
    repo = "CRS-Lead-Gen"
    # Ensure this matches your file name in .github/workflows/
    workflow_id = "daily_scrape.yml" 
    
    url = f"https://api.github.com/repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches"
    
    headers = {
        "Authorization": f"token {conn['gh_token']}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    # Ensure 'ref' matches your repository's default branch (usually 'main' or 'master')
    data = {"ref": "main"}
    
    response = requests.post(url, headers=headers, json=data)
    return response

# --- Sidebar Controls ---
st.sidebar.title("Pipeline Controls")

if st.sidebar.button("🔄 Refresh View"):
    st.cache_data.clear()
    st.rerun()

if st.sidebar.button("🚀 Force Run Scrapers"):
    with st.spinner("Dispatching trigger to GitHub..."):
        resp = trigger_github_workflow()
        if resp.status_code == 204:
            st.sidebar.success("Pipeline triggered! Check GitHub Actions.")
        else:
            st.sidebar.error(f"Trigger failed (Status {resp.status_code}): {resp.text}")

st.sidebar.caption(f"Last updated: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}")

# --- Data Loading ---
@st.cache_data(ttl=600)
def load_data():
    response = supabase.table("sa_tenders").select("*").execute()
    return pd.DataFrame(response.data)

# --- Main App Interface ---
st.title("CRS Target Pipeline: IT & Cybersecurity")

try:
    df = load_data()
    
    if df.empty:
        st.info("No data in database. Click 'Force Run Scrapers' to populate.")
    else:
        df_pending = df[df['award_status'] != 'Awarded'].copy()
        df_won = df[df['award_status'] == 'Awarded'].copy()

        shared_config = {
            "document_url": st.column_config.LinkColumn("Tender Document", display_text="Download PDF"),
            "source_url": st.column_config.LinkColumn("Portal Link", display_text="View Portal"),
            "award_value": st.column_config.NumberColumn("Award Value (ZAR)", format="R %d")
        }

        tab1, tab2 = st.tabs(["🟢 Active Pipeline", "🏆 Competitive Intelligence"])

        with tab1:
            st.subheader(f"Open Opportunities ({len(df_pending)})")
            display_pending = df_pending.drop(columns=['winning_bidder', 'award_value', 'id', 'created_at'], errors='ignore')
            st.dataframe(display_pending, column_config=shared_config, hide_index=True, use_container_width=True)

        with tab2:
            st.subheader(f"Awarded Contracts ({len(df_won)})")
            display_won = df_won.drop(columns=['id', 'created_at'], errors='ignore')
            st.dataframe(display_won, column_config=shared_config, hide_index=True, use_container_width=True)

except Exception as e:
    st.error(f"Error loading data: {e}")