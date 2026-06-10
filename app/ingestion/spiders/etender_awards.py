import requests
import os
from supabase import create_client
from dotenv import load_dotenv

load_dotenv(override=True)

def clean_currency(amount_str):
    """Converts 'R347 760,00' -> 347760.00"""
    if not amount_str or amount_str == "0": return 0.0
    # Remove 'R', spaces, and convert comma to dot
    clean = amount_str.replace('R', '').replace(' ', '').replace(',', '.')
    try:
        return float(clean)
    except:
        return 0.0

def scrape_awarded_tenders():
    print("🏆 STARTING ETENDERS AWARDS PULL (CLEANING DATA) 🏆")
    
    url = "https://www.etenders.gov.za/Home/PaginatedTenderOpportunities"
    
    # status 2 = Awarded
    params = {"draw": "1", "start": "0", "length": "1000", "status": "2"}
    headers = {'User-Agent': 'Mozilla/5.0', 'X-Requested-With': 'XMLHttpRequest'}

    try:
        supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
        
        # Wipe old awarded records
        supabase.table("sa_tenders").delete().eq("status", "Awarded").execute()
        
        response = requests.get(url, params=params, headers=headers)
        data = response.json()
        awarded_tenders = data.get("data", [])
        
        success_count = 0
        for tender in awarded_tenders:
            # 1. Extract from the 'company' array provided in your JSON
            companies = tender.get("company", [])
            winner_names = []
            award_values = []
            
            for comp in companies:
                winner_names.append(comp.get("company", "Unknown"))
                # Use our new cleaner
                award_values.append(clean_currency(comp.get("tenderAmount", "0")))

            # Join arrays
            bidder_str = " | ".join(winner_names)
            # Sum the values if there are multiple, or just take the first
            total_val = sum(award_values)

            # 2. Map to Supabase
            tender_data = {
                "tender_number": tender.get("tender_No"),
                "department_name": tender.get("department"),
                "title": tender.get("description", "")[:200],
                "description": tender.get("description", ""),
                "status": "Awarded",
                "winning_bidder": bidder_str,
                "award_value": str(total_val) # Saved as text or numeric
            }

            supabase.table("sa_tenders").upsert(tender_data, on_conflict="tender_number,department_name").execute()
            success_count += 1
            print(f"✅ Logged: {tender.get('tender_No')} | {bidder_str} | R{total_val:,.2f}")

        print(f"\n🚀 Pipeline Complete! {success_count} wins stored.")

    except Exception as e:
        print(f"❌ Critical Error: {e}")

if __name__ == "__main__":
    scrape_awarded_tenders()