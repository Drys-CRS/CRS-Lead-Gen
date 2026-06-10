import requests
from bs4 import BeautifulSoup
import os
import json
from supabase import create_client
from dotenv import load_dotenv

# Load environment variables
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

def scrape_gov_za_awards():
    print("🏆 STARTING GOV.ZA AWARDS HTML SCRAPER 🏆")
    
    base_url = "https://www.gov.za"
    target_url = f"{base_url}/documents/awarded-tenders"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }

    try:
        print(f"📡 Fetching main page: {target_url}")
        response = requests.get(target_url, headers=headers)
        
        if response.status_code != 200:
            print(f"❌ Failed to load gov.za (HTTP {response.status_code})")
            return

        # Parse the HTML
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # gov.za usually stores these lists inside a table with the class 'views-table'
        table = soup.find('table', class_='views-table')
        
        if not table:
            print("❌ Could not find the expected HTML table on gov.za. The website layout may have changed.")
            return

        rows = table.find('tbody').find_all('tr')
        print(f"📥 Found {len(rows)} awarded tender postings on the front page. Scanning sub-pages...")
        
        # Connect to Supabase
        url_env = os.getenv("SUPABASE_URL")
        key_env = os.getenv("SUPABASE_KEY")
        
        if not url_env or not key_env:
            print("🚨 SUPABASE URL OR KEY IS MISSING! Check your .env file.")
            return
            
        supabase = create_client(url_env, key_env)
        
        success_count = 0
        skipped_count = 0
        
        for row in rows:
            # Extract Title and Link
            a_tag = row.find('a')
            if not a_tag:
                continue
                
            title = a_tag.text.strip()
            link = a_tag.get('href')
            
            # Format relative links into absolute URLs
            if not link.startswith('http'):
                full_link = base_url + link
            else:
                full_link = link
                
            # Extract Date
            date_td = row.find('td', class_='views-field-field-date-value')
            issue_date = date_td.text.strip() if date_td else "Unknown Date"
            
            # -----------------------------------------------------
            # DEEP SCAN: Visit the sub-page to read the actual text
            # -----------------------------------------------------
            sub_resp = requests.get(full_link, headers=headers)
            sub_soup = BeautifulSoup(sub_resp.text, 'html.parser')
            
            # Grab all visible text from the page and convert to lowercase for easy searching
            page_text = sub_soup.get_text(separator=" ", strip=True).lower()
            
            # Filter check against our keywords
            is_relevant = any(keyword.lower() in page_text for keyword in TARGET_KEYWORDS)
            
            if not is_relevant:
                skipped_count += 1
                continue
                
            # Generate a unique ID based on the end of the gov.za URL slug
            tender_id = full_link.rstrip('/').split('/')[-1].upper()
            
            # Clean up the department name from the title if possible (e.g., "Awarded tenders: Department of Health")
            department = title.replace("Awarded tenders:", "").strip()

            tender_data = {
                "tender_number": tender_id,
                "department_name": department,
                "title": title[:200], 
                "description": f"🏆 GOV.ZA AWARDED TENDER POSTING\n\nMatches found for your cybersecurity/training keywords in the attached documents. Please visit the portal link to download the winner PDFs.\n\nSource: {title}", 
                "category": "Government Documents",
                "portal_link": full_link,
                "issue_date": issue_date,
                "status": "Awarded", 
                "award_status": "Published on gov.za", 
                "country": "South Africa"
            }

            try:
                supabase.table("sa_tenders").upsert(
                    tender_data, 
                    on_conflict="tender_number,department_name"
                ).execute()
                success_count += 1
                print(f"✅ Target Identified & Logged: {department}")
            except Exception as db_error:
                print(f"⚠️ DB Upsert Failed for {tender_id}: {db_error}")

        print("\n=================================")
        print(f"🚀 Gov.za Awards Pipeline Complete!")
        print(f"🗑️ Ignored {skipped_count} irrelevant documents.")
        print(f"💾 Pushed {success_count} targeted wins to Supabase.")
        print("=================================")

    except Exception as e:
        print(f"❌ Critical Pipeline Failure: {e}")

if __name__ == "__main__":
    scrape_gov_za_awards()