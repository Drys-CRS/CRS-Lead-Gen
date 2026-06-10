"""
Ghana – Ghana Electronic Procurement System (GHANEPS)
Portal : https://www.ghaneps.gov.gh
Method : Form-based search with HTML parsing (no public JSON API confirmed)
         Falls back to BeautifulSoup scraping of the public tenders list page.
Covers : Open tenders + awarded contracts
"""
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from utils import is_relevant, get_supabase, upsert_tenders

COUNTRY = "Ghana"
BASE_URL = "https://www.ghaneps.gov.gh"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.ghaneps.gov.gh/",
}

OPEN_URL = f"{BASE_URL}/epps/app/viewTender.do?searchType=basic&selectedItem=viewTender.do"
AWARDED_URL = f"{BASE_URL}/epps/contract/viewAwardedContracts.do?selectedItem=viewAwardedContracts.do"


def _parse_tenders_table(soup: BeautifulSoup, row_selector: str, col_map: dict) -> list[dict]:
    """Generic table parser. col_map: {field_name: col_index}"""
    rows = soup.select(row_selector)
    results = []
    for row in rows:
        cols = row.find_all("td")
        if not cols:
            continue
        record = {}
        for field, idx in col_map.items():
            try:
                record[field] = cols[idx].get_text(strip=True)
            except IndexError:
                record[field] = ""
        results.append(record)
    return results


def scrape_open():
    print(f"\n🇬🇭  [{COUNTRY}] Pulling open tenders…")
    supabase = get_supabase()
    supabase.table("sa_tenders").delete().eq("status", "Open").eq("country", COUNTRY).execute()

    try:
        r = requests.get(OPEN_URL, headers=HEADERS, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        # GHANEPS table: Ref No | Title | Procuring Entity | Category | Closing Date
        rows = _parse_tenders_table(soup, "table.dataTable tbody tr", {
            "tender_number": 0,
            "title": 1,
            "department_name": 2,
            "category": 3,
            "closing_date": 4,
        })
    except Exception as e:
        print(f"  [{COUNTRY}] Fetch/parse error: {e}")
        return

    print(f"  [{COUNTRY}] Parsed {len(rows)} open tenders. Filtering…")
    relevant = []
    for t in rows:
        text = f"{t.get('title', '')} {t.get('category', '')}"
        if not is_relevant(text):
            continue
        relevant.append({
            "tender_number": t.get("tender_number", ""),
            "department_name": t.get("department_name", ""),
            "title": t.get("title", "")[:200],
            "description": t.get("title", ""),
            "category": t.get("category", ""),
            "compliance_requirements": "Not specified",
            "portal_link": OPEN_URL,
            "closing_date": t.get("closing_date"),
            "status": "Open",
            "award_status": "Published",
            "country": COUNTRY,
        })

    upsert_tenders(supabase, relevant, COUNTRY, "Open")


def scrape_awarded():
    print(f"\n🇬🇭  [{COUNTRY}] Pulling awarded contracts…")
    supabase = get_supabase()
    supabase.table("sa_tenders").delete().eq("status", "Awarded").eq("country", COUNTRY).execute()

    try:
        r = requests.get(AWARDED_URL, headers=HEADERS, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        # GHANEPS awarded table: Ref No | Title | Supplier | Amount | PE | Date
        rows = _parse_tenders_table(soup, "table.dataTable tbody tr", {
            "tender_number": 0,
            "title": 1,
            "winning_bidder": 2,
            "award_value": 3,
            "department_name": 4,
        })
    except Exception as e:
        print(f"  [{COUNTRY}] Fetch/parse error: {e}")
        return

    print(f"  [{COUNTRY}] Parsed {len(rows)} awarded contracts. Filtering…")
    relevant = []
    for t in rows:
        text = f"{t.get('title', '')}"
        if not is_relevant(text):
            continue
        relevant.append({
            "tender_number": t.get("tender_number", ""),
            "department_name": t.get("department_name", ""),
            "title": t.get("title", "")[:200],
            "description": t.get("title", ""),
            "status": "Awarded",
            "winning_bidder": t.get("winning_bidder", "Unknown"),
            "award_value": t.get("award_value", "Not Disclosed"),
            "country": COUNTRY,
        })

    upsert_tenders(supabase, relevant, COUNTRY, "Awarded")


if __name__ == "__main__":
    scrape_open()
    scrape_awarded()