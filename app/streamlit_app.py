import streamlit as st
import pandas as pd
import subprocess
import os
from supabase import create_client

# 1. Page Configuration
st.set_page_config(page_title="CRS Competitive Intelligence", layout="wide")

# 2. Database Connection
@st.cache_resource
def init_connection():
    # Ensure these secrets are set in your Streamlit Cloud or local .streamlit/secrets.toml
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
        st.error(f"Error fetching data from Supabase: {e}")
        return pd.DataFrame()

# 4. Trigger Scrapers (Updates the DB)
def run_scrapers():
    # Define paths to your scripts
    base_path = r"C:\src\CRS-Lead-Gen\app\ingestion\spiders"
    api_script = os.path.join(base_path, "etender_api.py")
    awards_script = os.path.join(base_path, "etender_awards.py")

    with st.spinner("Running scrapers... this may take a moment."):
        try:
            st.write("Running API Scraper...")
            subprocess.run(["python", api_script], check=True)
            st.write("Running Awards Scraper...")
            subprocess.run(["python", awards_script], check=True)
            st.success("Scripts completed successfully!")
        except subprocess.CalledProcessError as e:
            st.error(f"Error running scraper: {e}")

# 5. Main Dashboard Logic
st.title("🛡️ CRS Competitive Intelligence Dashboard")

# Sidebar Actions
if st.sidebar.button("🔄 Refresh Data (Run Scrapers)"):
    run_scrapers()      # Run the scripts
    st.cache_data.clear() # Clear cache so app pulls new data
    st.rerun()            # Force reload

# Load Data
tenders_df = fetch_data_from_supabase()

if tenders_df.empty:
    st.warning("No data found in Supabase. Please ensure your scrapers have run successfully.")
else:
    # Sidebar Filters
    st.sidebar.header("Intelligence Filters")
    competitor_search = st.sidebar.text_input("Filter by Winning Bidder")
    dept_search = st.sidebar.text_input("Filter by Department Name")
    
    # --- DATA FILTERING ---
    df_filtered = tenders_df.copy()
    
    # Filter by Department
    if dept_search:
        df_filtered = df_filtered[df_filtered['department_name'].str.contains(dept_search, case=False, na=False)]
    
    # --- TABS ---
    tab1, tab2 = tab1, tab2 = st.tabs(["📢 Open Opportunities", "🏆 Competitive Intelligence (Awarded)"])

    # TAB 1: OPEN
    with tab1:
        st.subheader("Currently Open Opportunities")
        open_df = df_filtered[df_filtered['status'] == 'Open'].copy()
        
        # 1. Interactive Table (Selection Enabled)
        event = st.dataframe(
            open_df[['tender_number', 'department_name', 'title', 'issue_date', 'closing_date']],
            use_container_width=True,
            selection_mode="single-row",
            on_select="rerun"
        )
        
        # 2. Context Frame (Shows only when a row is clicked)
        if event.selection.rows:
            selected_idx = event.selection.rows[0]
            selected_tender = open_df.iloc[selected_idx]
            
            st.divider()
            st.subheader(f"Context: {selected_tender['tender_number']}")
            st.write(f"**Description:** {selected_tender['description']}")
            st.write(f"**Compliance Requirements:** {selected_tender['compliance_requirements']}")
            
            # Action Buttons
            col1, col2 = st.columns(2)
            with col1:
                # Button to open eTenders site directly
                st.link_button("🌐 Open on eTenders", "https://www.etenders.gov.za/Home/opportunities")
            with col2:
                # Button to remove item
                if st.button("🗑️ Mark as Irrelevant"):
                    # Logic: Delete from Supabase
                    supabase.table("sa_tenders").delete().eq("tender_number", selected_tender['tender_number']).execute()
                    st.rerun()

    # TAB 2: COMPETITIVE INTELLIGENCE
    with tab2:
        st.subheader("Historical Awarded Tenders")
        awarded_df = df_filtered[df_filtered['status'] == 'Awarded'].copy()
        
        # Apply Competitor Filter
        if competitor_search:
            awarded_df = awarded_df[awarded_df['winning_bidder'].str.contains(competitor_search, case=False, na=False)]
        
        if not awarded_df.empty:
            # ROBUST CURRENCY CLEANING
            # Replace non-numeric chars (R, spaces, commas) to allow math operations
            awarded_df['clean_val'] = awarded_df['award_value'].astype(str).str.replace(r'[R\s,]', '', regex=True)
            awarded_df['numeric_value'] = pd.to_numeric(awarded_df['clean_val'], errors='coerce').fillna(0)
            
            # Create Pivot Table
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
            st.dataframe(
                awarded_df[['tender_number', 'department_name', 'winning_bidder', 'award_value', 'title']],
                use_container_width=True
            )
        else:
            st.info("No awarded tenders match your current filters.")