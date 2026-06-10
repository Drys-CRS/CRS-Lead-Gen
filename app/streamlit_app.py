import streamlit as st
import pandas as pd
from supabase import create_client

# 1. Page Config
st.set_page_config(page_title="CRS Competitive Intelligence", layout="wide")

# 2. Database Connection
@st.cache_resource
def init_connection():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_connection()

# 3. Data Fetching
@st.cache_data(ttl=600) # Cache for 10 minutes
def fetch_data_from_supabase():
    try:
        response = supabase.table("sa_tenders").select("*").execute()
        return pd.DataFrame(response.data)
    except Exception as e:
        st.error(f"Error fetching data: {e}")
        return pd.DataFrame()

# Main Layout
st.title("🛡️ CRS Competitive Intelligence Dashboard")
tenders_df = fetch_data_from_supabase()

if tenders_df.empty:
    st.warning("No data found in Supabase. Run your scrapers first!")
else:
    # Sidebar Filters
    st.sidebar.header("Intelligence Filters")
    competitor_search = st.sidebar.text_input("Search Competitors (Awarded)")
    
    # Tabs
    tab1, tab2 = st.tabs(["📢 Open Opportunities", "🏆 Awarded Tenders"])

    # OPEN TENDERS VIEW
    with tab1:
        st.subheader("Currently Open Opportunities")
        open_df = tenders_df[tenders_df['status'] == 'Open']
        
        # Display key info
        st.dataframe(
            open_df[['tender_number', 'department_name', 'title', 'issue_date', 'closing_date']],
            use_container_width=True
        )

    # AWARDED TENDERS VIEW
    with tab2:
        st.subheader("Historical Awarded Tenders")
        awarded_df = tenders_df[tenders_df['status'] == 'Awarded']
        
        # Apply Competitor Filter if used
        if competitor_search:
            awarded_df = awarded_df[awarded_df['winning_bidder'].str.contains(competitor_search, case=False, na=False)]
        
        # Display key columns
        st.dataframe(
            awarded_df[['tender_number', 'department_name', 'winning_bidder', 'award_value', 'title']],
            use_container_width=True
        )

        # Visual Intelligence - Market Spend
        if not awarded_df.empty:
            st.divider()
            st.subheader("Market Spend Analysis")
            # Cleaning values for charts (stripping R and spaces)
            try:
                awarded_df['plot_value'] = awarded_df['award_value'].replace(r'[R, ]', '', regex=True)
                awarded_df['plot_value'] = pd.to_numeric(awarded_df['plot_value'], errors='coerce')
                
                chart_data = awarded_df.groupby('department_name')['plot_value'].sum().sort_values(ascending=False)
                st.bar_chart(chart_data)
            except:
                st.info("Award values are being formatted; chart will update shortly.")

# Refresh Button
if st.sidebar.button("🔄 Refresh Data"):
    st.cache_data.clear()
    st.rerun()