"""
Southern Africa scrapers:
  - Botswana  : PPADB  (https://www.ppadb.co.bw)
  - Namibia   : NamBid / NIPAM portal (https://www.procurement.gov.na)
  - Zimbabwe  : ZPPA   (https://www.praz.org.zw)
  - Zambia    : ZPPA   (https://www.zppa.org.zm / e-GP portal)

All use HTML scraping as none expose a public JSON API.
"""
import requests
from bs4 import BeautifulSoup
from utils import is_relevant, get_supabase, upsert_tenders

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _html_table(url: str, country: str, col_map: dict, table_sel: str = "table tbody tr") -> list[dict]:
    """Generic HTML table scraper. Returns list of dicts per col_map."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        results = []
        for row in soup.select(table_sel):
            cols = row.find_all("td")
            record = {}
            for field, idx in col_map.items():
                try:
                    record[field] = cols[idx].get_text(strip=True)
                except IndexError:
                    record[field] = ""
            if any(record.values()):
                results.append(record)
        return results
    except Exception as e:
        print(f"  [{country}] Fetch/parse error for {url}: {e}")
        return []


# ──────────────────────────────────────────────
# BOTSWANA
# ──────────────────────────────────────────────
def scrape_botswana():
    country = "Botswana"
    print(f"\n🇧🇼  [{country}] Pulling tenders…")
    supabase = get_supabase()
    supabase.table("sa_tenders").delete().eq("country", country).execute()

    # PPADB public notices
    open_url = "https://www.ppadb.co.bw/index.php/bid-opportunities"
    rows = _html_table(open_url, country, {
        "tender_number": 0, "title": 1, "department_name": 2, "closing_date": 3
    })

    relevant = []
    for t in rows:
        if not is_relevant(t.get("title", "")):
            continue
        relevant.append({
            "tender_number": t.get("tender_number", ""),
            "department_name": t.get("department_name", ""),
            "title": t.get("title", "")[:200],
            "description": t.get("title", ""),
            "compliance_requirements": "Not specified",
            "portal_link": open_url,
            "closing_date": t.get("closing_date"),
            "status": "Open",
            "country": country,
        })

    upsert_tenders(supabase, relevant, country, "Open")


# ──────────────────────────────────────────────
# NAMIBIA
# ──────────────────────────────────────────────
def scrape_namibia():
    country = "Namibia"
    print(f"\n🇳🇦  [{country}] Pulling tenders…")
    supabase = get_supabase()
    supabase.table("sa_tenders").delete().eq("country", country).execute()

    # Namibia Central Procurement Board
    open_url = "https://www.cpb.org.na/tenders"
    rows = _html_table(open_url, country, {
        "tender_number": 0, "title": 1, "department_name": 2, "closing_date": 3
    })

    relevant = []
    for t in rows:
        if not is_relevant(t.get("title", "")):
            continue
        relevant.append({
            "tender_number": t.get("tender_number", ""),
            "department_name": t.get("department_name", ""),
            "title": t.get("title", "")[:200],
            "description": t.get("title", ""),
            "compliance_requirements": "Not specified",
            "portal_link": open_url,
            "closing_date": t.get("closing_date"),
            "status": "Open",
            "country": country,
        })

    upsert_tenders(supabase, relevant, country, "Open")


# ──────────────────────────────────────────────
# ZIMBABWE
# ──────────────────────────────────────────────
def scrape_zimbabwe():
    country = "Zimbabwe"
    print(f"\n🇿🇼  [{country}] Pulling tenders…")
    supabase = get_supabase()
    supabase.table("sa_tenders").delete().eq("country", country).execute()

    # PRAZ (Procurement Regulatory Authority of Zimbabwe)
    open_url = "https://www.praz.org.zw/tenders"
    rows = _html_table(open_url, country, {
        "tender_number": 0, "title": 1, "department_name": 2, "closing_date": 3
    })

    relevant = []
    for t in rows:
        if not is_relevant(t.get("title", "")):
            continue
        relevant.append({
            "tender_number": t.get("tender_number", ""),
            "department_name": t.get("department_name", ""),
            "title": t.get("title", "")[:200],
            "description": t.get("title", ""),
            "compliance_requirements": "Not specified",
            "portal_link": open_url,
            "closing_date": t.get("closing_date"),
            "status": "Open",
            "country": country,
        })

    upsert_tenders(supabase, relevant, country, "Open")


# ──────────────────────────────────────────────
# ZAMBIA
# ──────────────────────────────────────────────
def scrape_zambia():
    country = "Zambia"
    print(f"\n🇿🇲  [{country}] Pulling tenders from ZPPA e-GP…")
    supabase = get_supabase()
    supabase.table("sa_tenders").delete().eq("country", country).execute()

    # ZPPA e-GP portal public tender list
    open_url = "https://www.zppa.org.zm/tenders"
    rows = _html_table(open_url, country, {
        "tender_number": 0, "title": 1, "department_name": 2, "closing_date": 3
    })

    relevant = []
    for t in rows:
        if not is_relevant(t.get("title", "")):
            continue
        relevant.append({
            "tender_number": t.get("tender_number", ""),
            "department_name": t.get("department_name", ""),
            "title": t.get("title", "")[:200],
            "description": t.get("title", ""),
            "compliance_requirements": "Not specified",
            "portal_link": open_url,
            "closing_date": t.get("closing_date"),
            "status": "Open",
            "country": country,
        })

    upsert_tenders(supabase, relevant, country, "Open")


if __name__ == "__main__":
    scrape_botswana()
    scrape_namibia()
    scrape_zimbabwe()
    scrape_zambia()