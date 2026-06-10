import streamlit as st
import pandas as pd
from supabase import create_client, Client
import os

# --- Page Configuration ---
st.set_page_config(page_title="CRS Target Pipeline", layout="wide")

# --- Supabase Connection ---
@st.cache_resource
def init_connection() -> Client:
    # Check for Streamlit Cloud secrets first, fallback to local environment variables
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
    except FileNotFoundError:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
    
    return create_client(url, key)

supabase = init_connection()

# --- Data Loading ---
@st.cache_data(ttl=600) # Cache data for 10 minutes to keep the dashboard fast
def load_data():
    response = supabase.table("sa_tenders").select("*").execute()
    return pd.DataFrame(response.data)

st.title("CRS Target Pipeline: IT & Cybersecurity")

try:
    df = load_data()
    
    if df.empty:
        st.info("No tender data found in the database. Run your spiders to populate the pipeline.")
    else:
        # --- 1. Split the Data ---
        df_pending = df[df['award_status'] != 'Awarded'].copy()
        df_won = df[df['award_status'] == 'Awarded'].copy()

        # --- 2. Shared Column Configuration ---
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
            
            if not df_pending.empty:
                # Hide the winner columns and database metadata
                display_pending = df_pending.drop(columns=['winning_bidder', 'award_value', 'id', 'created_at'], errors='ignore')
                
                st.dataframe(
                    display_pending,
                    column_config=shared_config,
                    hide_index=True,
                    use_container_width=True
                )
            else:
                st.write("No active opportunities matching your criteria.")

        with tab2:
            st.subheader(f"Awarded Contracts ({len(df_won)})")
            st.caption("Track competitor wins and contract values for future renewal targeting.")
            
            if not df_won.empty:
                cols = df_won.columns.tolist()
                
                # Clean up internal database columns
                for col in ['id', 'created_at']:
                    if col in cols:
                        cols.remove(col)
                        
                # Rearrange columns to put the competitor and value front and center
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
            else:
                st.write("No historical awarded contracts recorded yet.")

except Exception as e:
    st.error(f"Error connecting to database or loading data: {e}")