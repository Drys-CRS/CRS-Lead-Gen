import streamlit as st
import pandas as pd
from supabase import create_client

# ... your database connection setup ...

st.title("🛡️ CRS Competitive Intelligence")

# Create Tabs for cleaner UI
tab1, tab2 = st.tabs(["📢 Open Opportunities", "🏆 Awarded Tenders"])

# Fetch Data (Assuming you have a function to fetch from Supabase)
# def fetch_tenders(status): ...
tenders_df = fetch_data_from_supabase() # Your existing function

with tab1:
    st.subheader("Currently Open Tenders")
    open_tenders = tenders_df[tenders_df['status'] == 'Open']
    st.dataframe(open_tenders)

with tab2:
    st.subheader("Historical Awarded Tenders")
    awarded_tenders = tenders_df[tenders_df['status'] == 'Awarded']
    
    # Display the new columns we just added
    st.dataframe(awarded_tenders[['tender_number', 'department_name', 'winning_bidder', 'award_value', 'title']])

# Optional: Add a specific competitor filter in the sidebar
st.sidebar.header("Intelligence Filters")
competitor_filter = st.sidebar.text_input("Search by Competitor Name")

if competitor_filter:
    filtered_wins = awarded_tenders[awarded_tenders['winning_bidder'].str.contains(competitor_filter, case=False, na=False)]
    st.write(f"Wins found for {competitor_filter}:")
    st.dataframe(filtered_wins)