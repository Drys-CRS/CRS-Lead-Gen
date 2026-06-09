import streamlit as st
import pandas as pd
import os
from datetime import date
from supabase import create_client
from dotenv import load_dotenv

# Page configuration
st.set_page_config(page_title="Regional Cyber & IT Tender Tracker", page_icon="🌍", layout="wide")

# Load environment variables from the app folder
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"), override=True)

# Initialize Supabase connection
@st.cache_resource
def init_connection():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        st.error("Missing Supabase credentials. Please check your local database or deployment configuration secrets.")
        st.stop()
    return create_client(url, key)

try:
    supabase = init_connection()
except Exception as e:
    st.error(f"Failed to connect to database: {e}")
    st.stop()

# Fetch fresh data from the pipeline
def load_data():
    try:
        response = supabase.table("sa_tenders").select("*").order("closing_date", descending=False).execute()
        return pd.DataFrame(response.data)
    except Exception as e:
        st.error(f"Error reading from table 'sa_tenders': {e}")
        return pd.DataFrame()

df = load_data()

# App Interface
st.title("🌍 Cybersecurity & IT Procurement Intelligence Tracker")
st.caption("Live monitoring of multi-tier public sector, corporate, and SOE technology tenders.")

# Metric Block Calculations
if not df.empty:
    # Ensure standard date parsing
    df['closing_date'] = pd.to_datetime(df['closing_date']).dt.date
    today = date.today()
    
    open_tenders = df[df['award_status'] == 'In Evaluation']
    active_count = len(open_tenders[open_tenders['closing_date'] >= today])
    critical_closing = len(open_tenders[(open_tenders['closing_date'] >= today) & 
                                        (open_tenders['closing_date'] <= today + pd.Timedelta(days=7))])
    awarded_count = len(df[df['award_status'] == 'Awarded'])
    
    m1, m2, m3 = st.columns(3)
    m1.metric("Active Open Tenders", active_count)
    m2.metric("Closing Within 7 Days ⚠️", critical_closing)
    m3.metric("Tenders Successfully Awarded", awarded_count)

st.markdown("---")

# Navigation Sidebar Controls
st.sidebar.header("Filter Portfolio")
if not df.empty:
    # Country Filter
    countries = ["All"] + list(df['country'].unique()) if 'country' in df.columns else ["All", "South Africa"]
    selected_country = st.sidebar.selectbox("Target Territory", countries)
    
    # Organization Filter
    org_list = ["All"] + list(df['department_name'].unique())
    selected_org = st.sidebar.selectbox("Issuing Organization", org_list)
    
    # Status Filter
    status_list = ["All"] + list(df['award_status'].unique())
    selected_status = st.sidebar.selectbox("Award Status", status_list)
    
    # Filter Execution Logic
    filtered_df = df.copy()
    if selected_country != "All" and 'country' in filtered_df.columns:
        filtered_df = filtered_df[filtered_df['country'] == selected_country]
    if selected_org != "All":
        filtered_df = filtered_df[filtered_df['department_name'] == selected_org]
    if selected_status != "All":
        filtered_df = filtered_df[filtered_df['award_status'] == selected_status]
else:
    filtered_df = df

# Quick Actions
if st.button("🔄 Refresh Data Cache"):
    st.cache_data.clear()
    st.rerun()

# Interactive Data Grid Rendering
if filtered_df.empty:
    st.info("No procurement opportunities match your current filter matrix.")
else:
    # Shape grid columns dynamically
    grid_cols = ["tender_number", "department_name", "title", "closing_date", "award_status"]
    if 'country' in filtered_df.columns:
        grid_cols.insert(1, "country")
    
    display_df = filtered_df[grid_cols].copy()
    
    # User-friendly renaming
    rename_dict = {
        "tender_number": "Tender Reference",
        "country": "Country",
        "department_name": "Issuer / Entity",
        "title": "Scope of Work",
        "closing_date": "Closing Date",
        "award_status": "Status"
    }
    display_df.rename(columns=rename_dict, inplace=True)
    
    st.dataframe(
        display_df, 
        use_container_width=True, 
        hide_index=True
    )

    # Granular Inspection View
    st.subheader("📋 Detailed Scope & Requirements Inspection")
    for _, row in filtered_df.iterrows():
        status_tag = f"[{row['award_status']}]"
        with st.expander(f"{row['tender_number']} - {row['department_name']} {status_tag}"):
            st.markdown(f"### **{row['title']}**")
            st.write(f"**Description:** {row['description']}")
            st.write(f"**Compliance Mandates:** {row['compliance_requirements']}")
            st.caption(f"Source URL: {row['source_url']}")
            
            if row['award_status'] == 'Awarded':
                st.success(f"🏆 Awarded to: {row.get('winning_bidder', 'Unspecified Winner')} | Value: ZAR {row.get('award_value', 0):,}")