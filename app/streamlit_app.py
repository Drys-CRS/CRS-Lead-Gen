import streamlit as st
import pandas as pd
from supabase import create_client

st.set_page_config(page_title="CRS Competitive Intelligence", layout="wide")

@st.cache_resource
def init_connection():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_connection()

@st.cache_data(ttl=600)
def fetch_data_from_supabase():
    try:
        response = supabase.table("sa_tenders").select("*").execute()
        return pd.DataFrame(response.data)
    except Exception as e:
        st.error(f"Error fetching data: {e}")
        return pd.DataFrame()

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
    if dept_search:
        df_filtered = df_filtered[df_filtered['department_name'].str.contains(dept_search, case=False, na=False)]
        
    tab1, tab2 = st.tabs(["📢 Open Opportunities", "🏆 Competitive Intelligence (Awarded)"])

    with tab1:
        st.subheader("Currently Open Opportunities")
        open_df = df_filtered[df_filtered['status'] == 'Open']
        st.dataframe(open_df[['tender_number', 'department_name', 'title', 'issue_date', 'closing_date']], use_container_width=True)

    with tab2:
        st.subheader("Historical Awarded Tenders")
        awarded_df = df_filtered[df_filtered['status'] == 'Awarded'].copy()
        
        # Apply Competitor Filter
        if competitor_search:
            awarded_df = awarded_df[awarded_df['winning_bidder'].str.contains(competitor_search, case=False, na=False)]
        
        if not awarded_df.empty:
            # ROBUST CURRENCY CLEANING
            # This regex replaces everything that isn't a digit or a decimal point with nothing
            # We handle commas/dots by replacing the last comma with a decimal if it's a typical SA currency format
            awarded_df['clean_val'] = awarded_df['award_value'].astype(str).str.replace(r'[R\s]', '', regex=True)
            awarded_df['clean_val'] = awarded_df['clean_val'].str.replace(',', '.')
            awarded_df['numeric_value'] = pd.to_numeric(awarded_df['clean_val'], errors='coerce').fillna(0)
            
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
        else:
            st.info("No awarded tenders match your current filters.")