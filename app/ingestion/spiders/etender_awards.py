import requests
import json
import os
from supabase import create_client
from dotenv import load_dotenv

load_dotenv(override=True)

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
    print("🏆 STARTING ETENDERS AWARDS PULL (STATUS=2) 🏆")
    
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
        # 1. Connect and Wipe
        supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
        
        print("🧹 Clearing old 'Awarded' tenders from the database...")
        try:
            supabase.table("sa_tenders").delete().eq("status", "Awarded").execute()
            print("✅ Database wiped. Ready for fresh awards.")
        except Exception as e:
            print(f"⚠️ Warning: Could not clear database: {e}")

        # 2. Fetch Data
        response = requests.get(url, params=params, headers=headers)
        data = response.json()
        awarded_tenders = data.get("data", [])
        
        print(f"📥 Received {len(awarded_tenders)} awards. Filtering...")
        
        success_count = 0
        for tender in awarded_tenders:
            # Filter
            searchable_text = f"{tender.get('description', '')} {tender.get('category', '')}".lower()
            if not any(k.lower() in searchable_text for k in TARGET_KEYWORDS):
                continue

            # --- EXTRACT SUCCESSFUL BIDDERS ---
            awards_data = tender.get("awards", [])
            winner_names = "Not Disclosed"
            award_values = "0"
            
            if awards_data and isinstance(awards_data, list):
                names = [a.get("awardee") or "Unknown" for a in awards_data]
                vals = [str(a.get("amount") or "0") for a in awards_data]
                winner_names = " | ".join(names)
                award_values = " | ".join(vals)

            # 3. Upsert New Record
            tender_data = {
                "tender_number": tender.get("tender_No"),
                "department_name": tender.get("department"),
                "title": tender.get("description", "")[:200],
                "description": tender.get("description", ""),
                "category": tender.get("category", ""),
                "compliance_requirements": tender.get("conditions", "N/A"),
                "portal_link": "https://www.etenders.gov.za/Home/opportunities?id=2",
                "status": "Awarded",
                "winning_bidder": winner_names,
                "award_value": award_values
            }

            supabase.table("sa_tenders").upsert(tender_data, on_conflict="tender_number,department_name").execute()
            success_count += 1
            print(f"✅ Logged: {tender.get('tender_No')} -> {winner_names}")

        print(f"\n🚀 Pipeline Complete! {success_count} wins stored.")

    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    scrape_awarded_tenders()