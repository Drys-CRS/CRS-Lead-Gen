"""
Nigeria – Bureau of Public Procurement (BPP)
Portal : https://nocopo.bpp.gov.ng  (National Open Contracting Portal)
Method : OCDS-compatible JSON API
Covers : Open tenders + awarded contracts
"""
import requests
from utils import is_relevant, get_supabase, upsert_tenders

COUNTRY = "Nigeria"
BASE_URL = "https://nocopo.bpp.gov.ng/api"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}


def _fetch_ocds(endpoint: str, page_size: int = 100) -> list:
    """Pull all pages from the NoCoPo OCDS API."""
    records = []
    page = 1
    while True:
        try:
            r = requests.get(
                f"{BASE_URL}/{endpoint}",
                params={"page": page, "per_page": page_size},
                headers=HEADERS,
                timeout=30
            )
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"  [{COUNTRY}] API error page {page}: {e}")
            break

        # NoCoPo returns {'data': [...], 'meta': {'last_page': N}}
        batch = data.get("data", [])
        records.extend(batch)
        meta = data.get("meta", {})
        if page >= meta.get("last_page", 1) or not batch:
            break
        page += 1

    return records


def scrape_open():
    print(f"\n🇳🇬  [{COUNTRY}] Pulling open tenders…")
    supabase = get_supabase()
    supabase.table("sa_tenders").delete().eq("status", "Open").eq("country", COUNTRY).execute()

    records = _fetch_ocds("tenders")
    print(f"  [{COUNTRY}] Received {len(records)} open tenders. Filtering…")

    relevant = []
    for t in records:
        title = t.get("title") or t.get("description", "")
        category = t.get("procurementCategory") or t.get("category", "")
        if not is_relevant(f"{title} {category}"):
            continue

        tender_value = t.get("value", {})
        amount_str = (
            f"{tender_value.get('currency', '')} {tender_value.get('amount', '')}"
            if isinstance(tender_value, dict) else str(tender_value)
        )

        relevant.append({
            "tender_number": t.get("ocid") or t.get("id", ""),
            "department_name": (t.get("buyer") or {}).get("name", "") if isinstance(t.get("buyer"), dict) else t.get("buyer", ""),
            "title": str(title)[:200],
            "description": title,
            "category": category,
            "compliance_requirements": t.get("submissionMethod") or "Not specified",
            "portal_link": "https://nocopo.bpp.gov.ng",
            "issue_date": t.get("date") or t.get("tenderPeriod", {}).get("startDate"),
            "closing_date": (t.get("tenderPeriod") or {}).get("endDate"),
            "award_value": amount_str.strip() or None,
            "status": "Open",
            "award_status": "Published",
            "country": COUNTRY,
        })

    upsert_tenders(supabase, relevant, COUNTRY, "Open")


def scrape_awarded():
    print(f"\n🇳🇬  [{COUNTRY}] Pulling awarded contracts…")
    supabase = get_supabase()
    supabase.table("sa_tenders").delete().eq("status", "Awarded").eq("country", COUNTRY).execute()

    records = _fetch_ocds("awards")
    print(f"  [{COUNTRY}] Received {len(records)} awards. Filtering…")

    relevant = []
    for t in records:
        title = t.get("title") or t.get("description", "")
        if not is_relevant(title):
            continue

        suppliers = t.get("suppliers", [])
        winner = suppliers[0].get("name", "Unknown") if suppliers else t.get("supplier", {}).get("name", "Unknown")
        val = t.get("value", {})
        amount = f"{val.get('currency', '')} {val.get('amount', '')}".strip() if isinstance(val, dict) else str(val)

        relevant.append({
            "tender_number": t.get("relatedLot") or t.get("ocid") or t.get("id", ""),
            "department_name": (t.get("buyer") or {}).get("name", "") if isinstance(t.get("buyer"), dict) else "",
            "title": str(title)[:200],
            "description": title,
            "status": "Awarded",
            "winning_bidder": winner,
            "award_value": amount or "Not Disclosed",
            "country": COUNTRY,
        })

    upsert_tenders(supabase, relevant, COUNTRY, "Awarded")


if __name__ == "__main__":
    scrape_open()
    scrape_awarded()