"""
Tanzania – National e-Procurement System (NeST)
Portal : https://nest.ppra.go.tz
Method : Public tenders list — JSON DataTables endpoint
Covers : Open tenders. Awards are published on the older TANePS portal (HTML).
"""
import requests
from bs4 import BeautifulSoup
from utils import is_relevant, get_supabase, upsert_tenders

COUNTRY = "Tanzania"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}


def scrape_open():
    print(f"\n🇹🇿  [{COUNTRY}] Pulling open tenders from NeST…")
    supabase = get_supabase()
    supabase.table("sa_tenders").delete().eq("status", "Open").eq("country", COUNTRY).execute()

    # NeST published tenders — publicly accessible without auth
    url = "https://nest.ppra.go.tz/tenders/published-tenders"
    all_records = []

    # Try paginated DataTables endpoint first
    dt_url = "https://nest.ppra.go.tz/tenders/published-tenders-data"
    params = {"draw": 1, "start": 0, "length": 500}
    try:
        r = requests.get(dt_url, params=params, headers=HEADERS, timeout=30)
        if r.ok and "data" in r.json():
            all_records = r.json()["data"]
    except Exception:
        pass  # Fall back to HTML scraping below

    # HTML fallback
    if not all_records:
        try:
            categories = ["G", "W", "C", "N"]  # Goods, Works, Consultancy, Non-Consultancy
            for cat in categories:
                r = requests.get(
                    f"https://nest.ppra.go.tz/tenders/published-tenders?category={cat}",
                    headers={"User-Agent": HEADERS["User-Agent"]},
                    timeout=30
                )
                if not r.ok:
                    continue
                soup = BeautifulSoup(r.text, "html.parser")
                for row in soup.select("table tbody tr"):
                    cols = row.find_all("td")
                    if len(cols) >= 4:
                        all_records.append({
                            "tender_No": cols[0].get_text(strip=True),
                            "department": cols[1].get_text(strip=True),
                            "description": cols[2].get_text(strip=True),
                            "closing_Date": cols[3].get_text(strip=True),
                            "category": cat,
                        })
        except Exception as e:
            print(f"  [{COUNTRY}] HTML fallback error: {e}")
            return

    print(f"  [{COUNTRY}] Received {len(all_records)} open tenders. Filtering…")
    relevant = []
    for t in all_records:
        desc = t.get("description") or t.get("tenderDescription", "")
        cat = t.get("category", "")
        if not is_relevant(f"{desc} {cat}"):
            continue
        relevant.append({
            "tender_number": t.get("tender_No") or t.get("tenderNumber", ""),
            "department_name": t.get("department") or t.get("procuringEntity", ""),
            "title": str(desc)[:200],
            "description": desc,
            "category": cat,
            "compliance_requirements": "Not specified",
            "portal_link": url,
            "closing_date": t.get("closing_Date") or t.get("closingDate"),
            "issue_date": t.get("date_Published") or t.get("publishingDate"),
            "status": "Open",
            "award_status": "Published",
            "country": COUNTRY,
        })

    upsert_tenders(supabase, relevant, COUNTRY, "Open")


def scrape_awarded():
    """
    Tanzania awarded tenders — scraped from the legacy TANePS/PPRA tender portal.
    The portal lists contract awards in an HTML table.
    """
    print(f"\n🇹🇿  [{COUNTRY}] Pulling awarded tenders…")
    supabase = get_supabase()
    supabase.table("sa_tenders").delete().eq("status", "Awarded").eq("country", COUNTRY).execute()

    url = "http://tender.ppra.go.tz/contract-awards"
    try:
        r = requests.get(url, headers={"User-Agent": HEADERS["User-Agent"]}, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        relevant = []
        for row in soup.select("table tbody tr"):
            cols = row.find_all("td")
            if len(cols) < 4:
                continue
            desc = cols[1].get_text(strip=True) if len(cols) > 1 else ""
            if not is_relevant(desc):
                continue
            relevant.append({
                "tender_number": cols[0].get_text(strip=True),
                "department_name": cols[2].get_text(strip=True) if len(cols) > 2 else "",
                "title": desc[:200],
                "description": desc,
                "status": "Awarded",
                "winning_bidder": cols[3].get_text(strip=True) if len(cols) > 3 else "Unknown",
                "award_value": cols[4].get_text(strip=True) if len(cols) > 4 else "Not Disclosed",
                "country": COUNTRY,
            })

        upsert_tenders(supabase, relevant, COUNTRY, "Awarded")

    except Exception as e:
        print(f"  [{COUNTRY}] Awards fetch/parse error: {e}")


if __name__ == "__main__":
    scrape_open()
    scrape_awarded()