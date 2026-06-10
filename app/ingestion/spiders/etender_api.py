import requests
import json
import os
from supabase import create_client
from dotenv import load_dotenv

# Load environment variables
load_dotenv(override=True)

def scrape_etenders():
    print("🔥 STARTING ETENDERS API PULL 🔥")
    
    url = "https://www.etenders.gov.za/Home/PaginatedTenderOpportunities"
    
    # DataTables GET request parameters (flattened for URL encoding)
    params = {
        "draw": "1",
        "start": "0",
        "length": "1000",       # Pull up to 1000 records at once
        "status": "1",          # 1 = Currently Advertised
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
        # 1. Hit the API directly using GET and params
        print("📡 Sending GET request with DataTables parameters...")
        response = requests.get(url, params=params, headers=headers)
        
        print(f"✅ RESPONSE RECEIVED: HTTP Status {response.status_code}")
        
        if response.status_code != 200:
            print(f"❌ Server Error: {response.text[:500]}") # Print first 500 chars of error
            return

        data = response.json()
        tenders = data.get("data", [])
        
        print(f"🎯 Successfully pulled {len(tenders)} active tenders from the live API.")
        
        # 2. Connect to Supabase
        url_env = os.getenv("SUPABASE_URL")
        key_env = os.getenv("SUPABASE_KEY")
        
        if not url_env or not key_env:
            print("🚨 SUPABASE URL OR KEY IS MISSING! Check your .env file.")
            return
            
        supabase = create_client(url_env, key_env)
        
        # 3. Process and Upload
        success_count = 0
        for tender in tenders:
            tender_data = {
                "tender_number": tender.get("tender_No"),
                "department_name": tender.get("department"),
                "title": tender.get("description", "")[:200],
                "category": tender.get("category"), # <--- THE CULPRIT
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
            except Exception as db_error:
                print(f"⚠️ DB Upsert Failed for {tender.get('tender_No')}: {db_error}")

        print(f"🚀 Pipeline Complete: {success_count} tenders pushed to Supabase.")

    except Exception as e:
        print(f"❌ Critical Pipeline Failure: {e}")

if __name__ == "__main__":
    scrape_etenders()