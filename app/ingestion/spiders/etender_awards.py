import requests
import os
from supabase import create_client
from dotenv import load_dotenv

# Load environment variables
load_dotenv(override=True)

# Highly targeted keyword list
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
    
    # status 2 = Awarded
    params = {"draw": "1", "start": "0", "length": "1000", "status": "2"}
    headers = {'User-Agent': 'Mozilla/5.0', 'X-Requested-With': 'XMLHttpRequest'}

    try:
        supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
        
        # Wipe old awarded records to refresh
        print("🧹 Clearing old 'Awarded' records...")
        supabase.table("sa_tenders").delete().eq("status", "Awarded").execute()
        
        print("📡 Fetching data...")
        response = requests.get(url, params=params, headers=headers)
        data = response.json()
        awarded_tenders = data.get("data", [])
        
        print(f"📥 Received {len(awarded_tenders)} tenders. Filtering...")
        
        success_count = 0
        for tender in awarded_tenders:
            # 1. Filter
            searchable_text = f"{tender.get('description', '')} {tender.get('category', '')}".lower()
            if not any(k.lower() in searchable_text for k in TARGET_KEYWORDS):
                continue

            # 2. Extract Data
            companies = tender.get("company", [])
            winner_names = "Not Disclosed"
            award_amount = "Not Disclosed"
            
            if companies and isinstance(companies, list):
                # Grab first record
                primary = companies[0]
                winner_names = primary.get("company", "Unknown")
                award_amount = primary.get("tenderAmount", "Not Disclosed")
            
            # Fallback to tender-level if company array is empty
            if winner_names == "Not Disclosed":
                winner_names = tender.get("bidders") or "Unknown"
                award_amount = tender.get("tenderAmount") or "Not Disclosed"

            # 3. Upsert to DB
            tender_data = {
                "tender_number": tender.get("tender_No"),
                "department_name": tender.get("department"),
                "title": tender.get("description", "")[:200],
                "description": tender.get("description", ""),
                "status": "Awarded",
                "winning_bidder": winner_names,
                "award_value": award_amount
            }

            supabase.table("sa_tenders").upsert(tender_data, on_conflict="tender_number,department_name").execute()
            success_count += 1
            print(f"✅ Logged: {tender.get('tender_No')} | {winner_names} | {award_amount}")

        print(f"\n🚀 Pipeline Complete! {success_count} targeted wins stored.")

    except Exception as e:
        print(f"❌ Critical Error: {e}")

if __name__ == "__main__":
    scrape_awarded_tenders()