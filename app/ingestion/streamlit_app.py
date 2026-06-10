import streamlit as st
import pandas as pd
import os
from datetime import date
from supabase import create_client
from dotenv import load_dotenv

# Page configuration
st.set_page_config(page_title="SA Cyber & IT Tender Tracker", page_icon="🇿🇦", layout="wide")
load_dotenv(override=True)

# Initialize Supabase
@st.cache_resource
def init_connection():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    return create_client(url, key)

supabase = init_connection()

# Fetch data function (Clears cache automatically to pull fresh data daily/on demand)
def load_data():
    response = supabase.table("sa_tenders").select("*").order("closing_date", descending=False).execute()
    return pd.DataFrame(response.data)

df = load_data()

# App Title & Header
st.title("🇿🇦 South African Cybersecurity & IT Procurement Tracker")
st.caption("Live tracking of public sector and SOE technology procurement portfolios.")

# Metric Breakdown Row
if not df.empty:
    # Convert dates for calculations
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

# Navigation Sidebar Filters
st.sidebar.header("Filter Portfolio")
if not df.empty:
    org_list = ["All"] + list(df['department_name'].unique())
    selected_org = st.sidebar.selectbox("Issuing Organization", org_list)
    
    status_list = ["All"] + list(df['award_status'].unique())
    selected_status = st.sidebar.selectbox("Award Status", status_list)
    
    # Filter logic
    filtered_df = df.copy()
    if selected_org != "All":
        filtered_df = filtered_df[filtered_df['department_name'] == selected_org]
    if selected_status != "All":
        filtered_df = filtered_df[filtered_df['award_status'] == selected_status]
else:
    filtered_df = df

# Action Button: Refresh Pipeline
if st.button("🔄 Refresh Pipeline Dashboard Data"):
    st.cache_data.clear()
    st.rerun()

# Data Grid Display
if filtered_df.empty:
    st.info("No tenders found matching your filter selection.")
else:
    # Clean up column visual labels for the display grid
    display_df = filtered_df[[
        "tender_number", "department_name", "title", "closing_date", 
        "award_status", "winning_bidder", "award_value", "source_url"
    ]].copy()
    
    display_df.columns = [
        "Tender Reference", "Department/SOE", "Scope of Work", "Closing Date", 
        "Current Status", "Winning Entity", "Award Value (ZAR)", "Source Link"
    ]
    
    # Render interactive data grid
    # In your Streamlit app, right below where you load the data:
import streamlit as st
import pandas as pd

# ... [Your existing Supabase connection and data loading code goes here] ...
# Assuming your loaded data is stored in a Pandas DataFrame called 'df'

st.title("CRS Target Pipeline: IT & Cybersecurity")

# --- 1. Split the Data ---
# We use the 'award_status' column to route the data into two separate dataframes
df_pending = df[df['award_status'] != 'Awarded'].copy()
df_won = df[df['award_status'] == 'Awarded'].copy()

# --- 2. Shared Column Configuration ---
# This keeps your clickable links and currency formatting consistent across both tables
shared_config = {
    "document_url": st.column_config.LinkColumn("Tender Document", display_text="Download PDF"),
    "source_url": st.column_config.LinkColumn("Portal Link", display_text="View Portal"),
    "award_value": st.column_config.NumberColumn("Award Value (ZAR)", format="R %d")
}

# --- 3. Build the Tabbed Interface ---
tab1, tab2 = st.tabs(["🟢 Active Pipeline", "🏆 Competitive Intelligence"])

with tab1:
    st.subheader(f"Open Opportunities ({len(df_pending)})")
    st.caption("Active IBM, Red Hat, CompTIA, and Cybersecurity tenders currently in evaluation.")
    
    # Hide the winner columns since these are still open
    display_pending = df_pending.drop(columns=['winning_bidder', 'award_value'], errors='ignore')
    
    st.dataframe(
        display_pending,
        column_config=shared_config,
        hide_index=True,
        use_container_width=True
    )

with tab2:
    st.subheader(f"Awarded Contracts ({len(df_won)})")
    st.caption("Track competitor wins and contract values for future renewal targeting.")
    
    # Rearrange columns to put the competitor and value front and center
    cols = df_won.columns.tolist()
    if 'winning_bidder' in cols and 'award_value' in cols:
        cols.insert(2, cols.pop(cols.index('winning_bidder')))
        cols.insert(3, cols.pop(cols.index('award_value')))
        display_won = df_won[cols]
    else:
        display_won = df_won

    st.dataframe(
        display_won,
        column_config=shared_config,
        hide_index=True,
        use_container_width=True
    )

    # Detailed Inspection Accordion View
    st.subheader("📋 In-Depth Tender Scope Inspection")
    for _, row in filtered_df.iterrows():
        with st.expander(f"{row['tender_number']} - {row['department_name']} ({row['award_status']})"):
            st.markdown(f"### **{row['title']}**")
            st.write(f"**Detailed Scope:** {row['description']}")
            st.write(f"**Compliance Mandates:** {row['compliance_requirements']}")
            
            # Sub-layout for winners
            if row['award_status'] == 'Awarded':
                st.success(f"🏆 **Winner Assigned:** {row['winning_bidder']} | **Contract Value:** ZAR {row['award_value']:,}")
            elif row['award_status'] == 'In Evaluation':
                st.info("⏳ Status: Submissions are currently undergoing regulatory technical evaluation.")