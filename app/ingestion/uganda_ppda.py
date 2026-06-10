"""
Uganda – Public Procurement & Disposal of Public Assets Authority (PPDA)
Portal : https://gpp.ppda.go.ug  (Government Procurement Portal)
Method : HTML scraping of the public tenders listing
Covers : Open tenders + awarded contracts
"""
import requests
from bs4 import BeautifulSoup
from utils import is_relevant, get_supabase, upsert_tenders

COUNTRY = "Uganda"
BASE_URL = "https://gpp.ppda.go.ug"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _scrape_table(url: str, col_map: dict, pages: int = 5) -> list[dict]:
    """Scrape paginated HTML table. col_map: {field: col_index}"""
    results = []
    for page in range(1, pages + 1):
        try:
            r = requests.get(f"{url}?page={page}", headers=HEADERS, timeout=30)
            if not r.ok:
                break
            soup = BeautifulSoup(r.text, "html.parser")
            rows = soup.select("table tbody tr")
            if not rows:
                break
            for row in rows:
                cols = row.find_all("td")
                record = {}
                for field, idx in col_map.items():
                    try:
                        record[field] = cols[idx].get_text(strip=True)
                    except IndexError:
                        record[field] = ""
                results.append(record)
        except Exception as e:
            print(f"  [{COUNTRY}] Page {page} error: {e}")
            break
    return results


def scrape_open():
    print(f"\n🇺🇬  [{COUNTRY}] Pulling open tenders…")
    supabase = get_supabase()
    supabase.table("sa_tenders").delete().eq("status", "Open").eq("country", COUNTRY).execute()

    url = f"{BASE_URL}/tenders"
    rows = _scrape_table(url, {
        "tender_number": 0,
        "title": 1,
        "department_name": 2,
        "category": 3,
        "closing_date": 4,
    })

    print(f"  [{COUNTRY}] Parsed {len(rows)} open tenders. Filtering…")
    relevant = []
    for t in rows:
        if not is_relevant(f"{t.get('title', '')} {t.get('category', '')}"):
            continue
        relevant.append({
            "tender_number": t.get("tender_number", ""),
            "department_name": t.get("department_name", ""),
            "title": t.get("title", "")[:200],
            "description": t.get("title", ""),
            "category": t.get("category", ""),
            "compliance_requirements": "Not specified",
            "portal_link": url,
            "closing_date": t.get("closing_date"),
            "status": "Open",
            "award_status": "Published",
            "country": COUNTRY,
        })

    upsert_tenders(supabase, relevant, COUNTRY, "Open")


def scrape_awarded():
    print(f"\n🇺🇬  [{COUNTRY}] Pulling awarded contracts…")
    supabase = get_supabase()
    supabase.table("sa_tenders").delete().eq("status", "Awarded").eq("country", COUNTRY).execute()

    url = f"{BASE_URL}/contract-awards"
    rows = _scrape_table(url, {
        "tender_number": 0,
        "title": 1,
        "department_name": 2,
        "winning_bidder": 3,
        "award_value": 4,
    })

    print(f"  [{COUNTRY}] Parsed {len(rows)} awarded contracts. Filtering…")
    relevant = []
    for t in rows:
        if not is_relevant(t.get("title", "")):
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