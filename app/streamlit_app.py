import streamlit as st
import pandas as pd
from supabase import create_client

# 1. Initialize Supabase Connection
@st.cache_resource
def init_connection():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_connection()

# 2. Define the missing function
def fetch_data_from_supabase():
    try:
        # Fetching all data from 'sa_tenders'
        response = supabase.table("sa_tenders").select("*").execute()
        # Convert the JSON response into a Pandas DataFrame
        df = pd.DataFrame(response.data)
        return df
    except Exception as e:
        st.error(f"Error fetching data from Supabase: {e}")
        return pd.DataFrame() # Return an empty DataFrame on error

# Now your call at line 14 will work:
tenders_df = fetch_data_from_supabase()