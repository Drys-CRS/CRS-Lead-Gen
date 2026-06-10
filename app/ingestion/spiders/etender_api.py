import requests
import json
import os
from supabase import create_client
from dotenv import load_dotenv

# Load environment variables
load_dotenv(override=True)

# Define your exact target areas. Python will check for these in the description.
TARGET_KEYWORDS = [
    "cyber", "security", "firewall", "network", "threat", "vulnerability",
    "training", "comptia", "ibm", "red hat", "ict ", "information technology",
    "cloud", "server", "endpoint", "infrastructure", "data center",
    "flare", "vectra", "aikido", "vicarius", "software", "hardware"
]

def scrape_etenders():
    print("🔥 STARTING ETENDERS API PULL 🔥")
    
    url = "https://www.etenders.gov.za/Home/PaginatedTenderOpportunities"
    
    params = {
        "draw": "1",
        "start": "0",
        "length": "1000",
        "status": "1", 
        "search[value]": "",
        "search[regex]": "false",
        "order[0][column]": "2",
        "order[0][dir]": "desc"
    }

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'X-Requested-With': 'XMLHttpRequest',
        'Accept': 'application/json, text/javascript, */*; q=0.01'
    }

    try:
        print("📡 Pulling the master list from eTenders...")
        response = requests.get(url, params=params, headers=headers)
        
        if response.status_code != 200:
            print(f"❌ Server Error: {response.text[:500]}")
            return

        data = response.json()
        all_tenders = data.get("data", [])
        
        print(f"📥 Received {len(all_tenders)} total tenders. Applying cyber & training filters...")
        
        # Connect to Supabase
       # 2. Connect to Supabase
        url_env = os.getenv("SUPABASE_URL")
        key_env = os.getenv("SUPABASE_KEY")
        
        if not url_env or not key_env:
            print("🚨 SUPABASE URL OR KEY IS MISSING! Check your .env file.")
            return
            
        supabase = create_client(url_env, key_env)
        
        # --- NEW WIPE LOGIC ---
        print("🧹 Clearing old 'Open' tenders from the database...")
        try:
            supabase.table("sa_tenders").delete().eq("status", "Open").execute()
            print("✅ Old tenders cleared. Ready for fresh data.")
        except Exception as e:
            print(f"⚠️ Warning: Failed to clear old tenders: {e}")
        # ----------------------
        
        # 3. Process and Upload
        success_count = 0
        skipped_count = 0
        
        for tender in all_tenders:
            # Grab the description and category, convert to lowercase for easy matching
            description = tender.get("description", "").lower()
            category_text = tender.get("category", "").lower()
            
            # Combine them into one string to search against
            searchable_text = f"{description} {category_text}"
            
            # Check if ANY of our target keywords exist in the text
            is_relevant = any(keyword in searchable_text for keyword in TARGET_KEYWORDS)
            
            if not is_relevant:
                skipped_count += 1
                continue # Skip this loop and move to the next tender
                
            # If it passes the filter, prepare it for the database
            tender_data = {
                "tender_number": tender.get("tender_No"),
                "department_name": tender.get("department"),
                "title": tender.get("description", "")[:200],
                # "category": tender.get("category"), <-- Commented out to prevent the PGRST204 error
                "issue_date": tender.get("date_Published"),
                "closing_date": tender.get("closing_Date"),
                "status": "Open",
                "award_status": "Published",
                "country": "South Africa"
            }

            try:
                supabase.table("sa_tenders").upsert(
                    tender_data, 
                    on_conflict="tender_number,department_name"
                ).execute()
                success_count += 1
                print(f"✅ Upserted Match: {tender.get('tender_No')} - {tender.get('category')}")
            except Exception as db_error:
                print(f"⚠️ DB Upsert Failed for {tender.get('tender_No')}: {db_error}")

        print("\n=================================")
        print(f"🚀 Pipeline Complete!")
        print(f"🗑️ Ignored {skipped_count} irrelevant tenders.")
        print(f"💾 Pushed {success_count} targeted tenders to Supabase.")
        print("=================================")

    except Exception as e:
        print(f"❌ Critical Pipeline Failure: {e}")

if __name__ == "__main__":
    scrape_etenders()