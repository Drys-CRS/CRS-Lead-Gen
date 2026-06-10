import streamlit as st
import pandas as pd
from supabase import create_client

# 1. Page Configuration
st.set_page_config(page_title="CRS Competitive Intelligence", layout="wide")

# 2. Database Connection
@st.cache_resource
def init_connection():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_connection()

# 3. Data Fetching
@st.cache_data(ttl=600)
def fetch_data_from_supabase():
    try:
        response = supabase.table("sa_tenders").select("*").execute()
        return pd.DataFrame(response.data)
    except Exception as e:
        st.error(f"Error fetching data: {e}")
        return pd.DataFrame()

# 4. Main Dashboard
st.title("🛡️ CRS Competitive Intelligence Dashboard")

if st.sidebar.button("🔄 Refresh Data"):
    st.cache_data.clear()
    st.rerun()

tenders_df = fetch_data_from_supabase()

if tenders_df.empty:
    st.warning("No data found in Supabase.")
else:
    # --- INTELLIGENCE FILTERS ---
    st.sidebar.header("Intelligence Filters")
    competitor_search = st.sidebar.text_input("Filter by Winning Bidder")
    dept_search = st.sidebar.text_input("Filter by Department Name")
    
    # --- DATA FILTERING ---
    df_filtered = tenders_df.copy()
    
    # Apply Department Filter
    if dept_search:
        df_filtered = df_filtered[df_filtered['department_name'].str.contains(dept_search, case=False, na=False)]
        
    # --- TABS ---
    tab1, tab2 = st.tabs(["📢 Open Opportunities", "🏆 Competitive Intelligence (Awarded)"])

    # TAB 1: OPEN
    with tab1:
        st.subheader("Currently Open Opportunities")
        open_df = df_filtered[df_filtered['status'] == 'Open']
        st.dataframe(open_df[['tender_number', 'department_name', 'title', 'issue_date', 'closing_date']], use_container_width=True)

    # TAB 2: AWARDED
    with tab2:
        st.subheader("Historical Awarded Tenders")
        awarded_df = df_filtered[df_filtered['status'] == 'Awarded'].copy()
        
        # Apply Competitor Filter
        if competitor_search:
            awarded_df = awarded_df[awarded_df['winning_bidder'].str.contains(competitor_search, case=False, na=False)]
        
        # Clean data for Pivot
        awarded_df['numeric_value'] = awarded_df['award_value'].replace(r'[R, ]', '', regex=True)
        awarded_df['numeric_value'] = pd.to_numeric(awarded_df['numeric_value'], errors='coerce').fillna(0)
        
        # Pivot Table
        pivot_table = awarded_df.pivot_table(
            values='numeric_value', 
            index='winning_bidder', 
            aggfunc={'numeric_value': ['sum', 'count']}
        ).rename(columns={'sum': 'Total Won Value (ZAR)', 'count': 'Tender Count'})
        
        pivot_table = pivot_table.sort_values(by='Total Won Value (ZAR)', ascending=False)
        
        st.subheader("Competitor Market Share Roll-up")
        st.dataframe(pivot_table.style.format({'Total Won Value (ZAR)': 'R{:,.2f}'}), use_container_width=True)
        
        st.divider()
        st.subheader("Detailed Award List")
        st.dataframe(awarded_df[['tender_number', 'department_name', 'winning_bidder', 'award_value', 'title']], use_container_width=True)