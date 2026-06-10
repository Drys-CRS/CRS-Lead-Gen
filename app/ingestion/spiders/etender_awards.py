import requests
import json
import os
from supabase import create_client
from dotenv import load_dotenv

# Load environment variables
load_dotenv(override=True)

# Your highly targeted cybersecurity and training filter list
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
    print("🏆 STARTING ETENDERS AWARDS PULL (API STATUS=2) 🏆")
    
    url = "https://www.etenders.gov.za/Home/PaginatedTenderOpportunities"
    
    params = {
        "draw": "1",
        "start": "0",
        "length": "1000",       
        "status": "2",          # 2 = Awarded Tenders
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
        
        success_count = 0
        skipped_count = 0
        
        for tender in awarded_tenders:
            full_description = tender.get("description", "")
            category_text = tender.get("category", "")
            
            searchable_text = f"{full_description} {category_text}".lower()
            
            # Filter against your target keywords
            is_relevant = any(keyword.lower() in searchable_text for keyword in TARGET_KEYWORDS)
            
            if not is_relevant:
                skipped_count += 1
                continue 
                
            # --- EXTRACT SUCCESSFUL BIDDERS AND AMOUNTS ---
            awards_data = tender.get("awards", [])
            winner_names = "Not Disclosed"
            award_values = "Not Disclosed"
            
            if awards_data and isinstance(awards_data, list) and len(awards_data) > 0:
                names_list = []
                values_list = []
                
                for award in awards_data:
                    # Get Name
                    names_list.append(award.get("awardee", "Unknown Bidder"))
                    
                    # Get and format Amount safely
                    raw_amount = award.get("amount")
                    if isinstance(raw_amount, (int, float)):
                        values_list.append(f"R{raw_amount:,.2f}")
                    elif raw_amount:
                        values_list.append(str(raw_amount))
                    else:
                        values_list.append("Unknown Amount")
                
                # Join them together in case there are multiple winners
                winner_names = " | ".join(names_list)
                award_values = " | ".join(values_list)

            tender_data = {
                "tender_number": tender.get("tender_No"),
                "department_name": tender.get("department"),
                "title": full_description[:200], 
                "description": full_description, 
                "category": category_text,
                "compliance_requirements": tender.get("conditions", "Not specified"),
                "portal_link": "https://www.etenders.gov.za/Home/opportunities?id=2", 
                "issue_date": tender.get("date_Published"),
                "closing_date": tender.get("closing_Date"),
                "status": "Awarded",
                "award_status": "Published", 
                "winning_bidder": winner_names, # Mapped to new column
                "award_value": award_values,    # Mapped to new column
                "country": "South Africa"
            }

            try:
                supabase.table("sa_tenders").upsert(
                    tender_data, 
                    on_conflict="tender_number,department_name"
                ).execute()
                success_count += 1
                print(f"✅ Logged Win: {tender.get('tender_No')} -> {winner_names} ({award_values})")
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