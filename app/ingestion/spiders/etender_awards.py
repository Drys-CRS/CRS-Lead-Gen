import requests
import json
import os
from supabase import create_client
from dotenv import load_dotenv

# Load environment variables
load_dotenv(override=True)

# The exact same targeted filter list
TARGET_KEYWORDS = [
    "cyber", "EDR", "firewall", "network", "threat", "vulnerability",
    "training", "comptia", "ibm", "red hat", "ict ", "information technology",
    "cloud", "server", "endpoint", "infrastructure", "data center",
    "flare", "vectra", "aikido", "vicarius", "software", "hardware", "NDR", "IDR", "SAST", "VAPT",
    "penetration testing", "cybersecurity", "cyber security", "cyber risk", "cyber risk management",
    "cyber defense", "cyber defence", "cyber incident response", "cyber threat intelligence", "cyber threat hunting",
    "cyber vulnerability management", "cyber risk assessment", "cyber risk mitigation", "cyber risk monitoring",
    "cyber risk reporting", "cyber risk compliance", "penetration testing", "data security",
    "z/os", "SOC", "Patch Management", "Technical Training", "Cybersecurity Training", "IT Training", "Information Security Training",
    "AI", "Security+", "IBM i", "Red Hat", "CompTIA", "Cloud Security", "Network Security", "Endpoint Security",
    "redhat", "SUSE", "Application Security", "Identity and Access Management", "IAM", "Zero Trust", "SIEM", "Security Orchestration"
]

def scrape_awarded_tenders():
    print("🏆 STARTING ETENDERS AWARDS PULL 🏆")
    
    url = "https://www.etenders.gov.za/Home/PaginatedTenderOpportunities"
    
    # Notice the status is now '4' for Awarded
    params = {
        "draw": "1",
        "start": "0",
        "length": "1000",       
        "status": "4",          # 4 = Awarded Tenders
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
        print("📡 Pulling the Awarded master list from eTenders...")
        response = requests.get(url, params=params, headers=headers)
        
        if response.status_code != 200:
            print(f"❌ Server Error: {response.text[:500]}")
            return

        data = response.json()
        awarded_tenders = data.get("data", [])
        
        print(f"📥 Received {len(awarded_tenders)} total Awarded tenders. Applying advanced filters...")
        
        # Connect to Supabase
        url_env = os.getenv("SUPABASE_URL")
        key_env = os.getenv("SUPABASE_KEY")
        
        if not url_env or not key_env:
            print("🚨 SUPABASE URL OR KEY IS MISSING! Check your .env file.")
            return
            
        supabase = create_client(url_env, key_env)
        
        # NOTE: We DO NOT clear the database here. We want to keep a permanent historical record of who won what.
        
        success_count = 0
        skipped_count = 0
        
        for tender in awarded_tenders:
            full_description = tender.get("description", "")
            category_text = tender.get("category", "")
            
            searchable_text = f"{full_description} {category_text}".lower()
            
            # Filter for cyber and training
            is_relevant = any(keyword.lower() in searchable_text for keyword in TARGET_KEYWORDS)
            
            if not is_relevant:
                skipped_count += 1
                continue 
                
            # Attempt to extract winner details if the government populated the 'awards' array
            winner_name = "Not Disclosed"
            award_amount = "Not Disclosed"
            
            awards_data = tender.get("awards")
            if awards_data and isinstance(awards_data, list) and len(awards_data) > 0:
                # Grab the first awardee
                winner_name = awards_data[0].get("awardee", "Not Disclosed")
                award_amount = str(awards_data[0].get("amount", "Not Disclosed"))
                
            # Add the award details to the description so you can see it on the dashboard without needing new columns
            enriched_description = f"🏆 AWARDED TO: {winner_name} | AMOUNT: {award_amount}\n\n{full_description}"
                
            tender_data = {
                "tender_number": tender.get("tender_No"),
                "department_name": tender.get("department"),
                "title": full_description[:200], 
                "description": enriched_description, 
                "category": category_text,
                "compliance_requirements": tender.get("conditions", "Not specified"),
                "portal_link": "https://www.etenders.gov.za/Home/opportunities?id=1",
                "issue_date": tender.get("date_Published"),
                "closing_date": tender.get("closing_Date"),
                "status": "Awarded", # Tagging as Awarded
                "award_status": winner_name, # Storing the winner name here
                "country": "South Africa"
            }

            try:
                supabase.table("sa_tenders").upsert(
                    tender_data, 
                    on_conflict="tender_number,department_name"
                ).execute()
                success_count += 1
                print(f"✅ Logged Win: {tender.get('tender_No')} -> {winner_name}")
            except Exception as db_error:
                print(f"⚠️ DB Upsert Failed for {tender.get('tender_No')}: {db_error}")

        print("\n=================================")
        print(f"🚀 Awards Pipeline Complete!")
        print(f"🗑️ Ignored {skipped_count} irrelevant awards.")
        print(f"💾 Pushed {success_count} targeted wins to Supabase.")
        print("=================================")

    except Exception as e:
        print(f"❌ Critical Pipeline Failure: {e}")

if __name__ == "__main__":
    scrape_awarded_tenders()