"""
monday_client.py — CRS Monday.com Integration
Uses the real column IDs from the Outstanding Tickets board (5657844182)
discovered via MCP on 2026-06-11.

Required secret:
  MONDAY_API_KEY = "your_token_here"
"""
import json
import requests
import streamlit as st

MONDAY_URL        = "https://api.monday.com/v2"
TICKETS_BOARD_ID  = 5657844182
TENDERS_GROUP_ID  = "group_mkz9h01q"   # "Tenders" group within Outstanding Tickets


# ── Solution → CRS Division + Vendor mapping ─────────────────────────────────
SOLUTION_MAP = {
    # CyberSec keywords → (CRS Division, CyberSec Vendor label)
    "vectra":          ("CyberSec", "VECTRA"),
    "ndr":             ("CyberSec", "VECTRA"),
    "xdr":             ("CyberSec", "VECTRA"),
    "soc":             ("CyberSec", "VECTRA"),
    "threat":          ("CyberSec", "VECTRA"),
    "vrx":             ("CyberSec", "vRx"),
    "vulnerability":   ("CyberSec", "vRx"),
    "patch":           ("CyberSec", "vRx"),
    "vapt":            ("CyberSec", None),        # VAPT has no vendor dropdown
    "penetration":     ("CyberSec", None),
    "pentest":         ("CyberSec", None),
    "smb":             ("CyberSec", "SMBsecure"),
    "endpoint":        ("CyberSec", "SMBsecure"),
    "encryption":      ("CyberSec", "Beachheadsecure"),
    "popia":           ("CyberSec", "SMBsecure"),
    "beachhead":       ("CyberSec", "Beachheadsecure"),
    "flare":           ("CyberSec", None),
    "dark web":        ("CyberSec", None),
    "ransomware":      ("CyberSec", None),
    "aikido":          ("CyberSec", None),
    "sast":            ("CyberSec", None),
    "application":     ("CyberSec", None),
    "awareness":       ("CyberSec", "Cyber Awareness Training"),
    "phishing":        ("CyberSec", "Cyber Awareness Training"),
    # Training keywords → (CRS Division, Training Vendor label)
    "ibm":             ("Training", "IBM Training"),
    "redhat":          ("Training", "Redhat"),
    "red hat":         ("Training", "Redhat"),
    "suse":            ("Training", "SUSE"),
    "comptia":         ("Training", "CompTIA"),
    "agile":           ("Training", "Agile SAFe Training"),
    "training":        ("Training", "IBM Training"),   # default training vendor
    "certification":   ("Training", "IBM Training"),
}

def _infer_division(title: str, description: str) -> tuple:
    """Return (crs_division_label, cybersec_vendor, training_vendor) from text."""
    text = f"{title} {description}".lower()
    for kw, (div, vendor) in SOLUTION_MAP.items():
        if kw in text:
            if div == "CyberSec":
                return div, vendor, None
            else:
                return div, None, vendor
    return "CyberSec", None, None   # default


# ── Region mapping ─────────────────────────────────────────────────────────────
REGION_MAP = {
    "South Africa":  "South Africa",
    "Kenya":         "Africa and other",
    "Nigeria":       "Africa and other",
    "Ghana":         "Africa and other",
    "Tanzania":      "Africa and other",
    "Uganda":        "Africa and other",
    "Zambia":        "Africa and other",
    "Rwanda":        "Africa and other",
}
LOCATION_MAP = {
    "South Africa": "South Africa",
    "Kenya":        "Africa",
    "Nigeria":      "Africa",
    "Ghana":        "Africa",
    "Tanzania":     "Africa",
    "Uganda":       "Africa",
    "Zambia":       "Africa",
    "Rwanda":       "Africa",
}


# ── GraphQL helper ─────────────────────────────────────────────────────────────
def _gql(query: str, variables: dict = None) -> dict:
    key = st.secrets.get("MONDAY_API_KEY", "")
    if not key:
        raise ValueError("MONDAY_API_KEY not set in Streamlit secrets.")
    headers = {
        "Authorization": key,
        "Content-Type":  "application/json",
        "API-Version":   "2024-01",
    }
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    r = requests.post(MONDAY_URL, json=payload, headers=headers, timeout=20)
    r.raise_for_status()
    data = r.json()
    if "errors" in data:
        raise RuntimeError(f"Monday API error: {data['errors']}")
    return data


# ── Deduplication ──────────────────────────────────────────────────────────────
def find_tender_by_number(tender_number: str) -> str | None:
    """Return item_id if this tender number already exists on the board."""
    q = """
    query ($bid: ID!, $val: String!) {
      items_page_by_column_values(
        board_id: $bid, limit: 5,
        columns: [{column_id: "text_mkz9683j", column_values: [$val]}]
      ) { items { id name } }
    }"""
    try:
        data = _gql(q, {"bid": str(TICKETS_BOARD_ID), "val": tender_number})
        items = data["data"]["items_page_by_column_values"]["items"]
        return items[0]["id"] if items else None
    except Exception:
        return None


# ── Main push function ─────────────────────────────────────────────────────────
def push_tender_to_tickets(tender: dict) -> tuple[str | None, str]:
    """
    Push a tender to the Outstanding Tickets board → Tenders group.
    Deduplicates by tender number.
    Returns (item_id, action) where action is 'created' or 'exists'.
    """
    tender_number = str(tender.get("tender_number") or "").strip()
    title         = str(tender.get("title") or tender.get("description") or "")[:200]
    description   = str(tender.get("description") or "")
    department    = str(tender.get("department_name") or "")
    country       = str(tender.get("country") or "South Africa")
    closing_date  = str(tender.get("closing_date") or "")[:10]
    issue_date    = str(tender.get("issue_date") or "")[:10]
    portal_link   = str(tender.get("portal_link") or "")
    ai_rationale  = str(tender.get("ai_rationale") or "")[:500]

    # Deduplicate
    if tender_number:
        existing = find_tender_by_number(tender_number)
        if existing:
            return existing, "exists"

    # Infer CRS division and vendor
    div, cybersec_vendor, training_vendor = _infer_division(title, description)

    region   = REGION_MAP.get(country, "Africa and other")
    location = LOCATION_MAP.get(country, "Africa")

    # Build column values using real IDs
    col_vals = {
        # Tender-specific fields
        "text_mkz9683j":    tender_number,
        "long_text_mkz9tze4": f"{description}\n\nDepartment: {department}",
        "color_mkz91j57":   {"label": "Open Tender"},
        # Dates — Monday expects YYYY-MM-DD
        **({"date_mkz9ag0h": {"date": issue_date}}   if issue_date   else {}),
        **({"date_mkz9kfdr": {"date": closing_date}} if closing_date else {}),
        # Company
        "short_text":       department,
        "short_text541":    department,   # End User = same as department for tenders
        # Region & location
        "single_select76":  {"label": region},
        "single_select05":  {"label": location},
        # CRS Division
        "single_select411": {"label": div},
        # Vendor selection
        **({"single_select0": {"label": cybersec_vendor}}   if cybersec_vendor   else {}),
        **({"single_select19": {"label": training_vendor}}  if training_vendor   else {}),
        # Status → Working on it (initial)
        "status":           {"label": "Working on it"},
        # Portal link
        **({"link_mkz9vz25": {"url": portal_link, "text": "eTenders / Portal"}} if portal_link else {}),
        # AI notes in Additional Info
        "long_text_1":      f"AI Fit Score: {tender.get('ai_score','N/A')}/10\n\n{ai_rationale}",
        # New customer
        "single_select":    {"label": "New Customer"},
    }

    # Item name = Tender Number or title
    item_name = tender_number if tender_number else title[:80]

    q = """
    mutation ($bid: ID!, $gid: String!, $name: String!, $cv: JSON!) {
      create_item(board_id: $bid, group_id: $gid, item_name: $name, column_values: $cv) {
        id
      }
    }"""
    data = _gql(q, {
        "bid":  str(TICKETS_BOARD_ID),
        "gid":  TENDERS_GROUP_ID,
        "name": item_name,
        "cv":   json.dumps(col_vals),
    })
    item_id = data["data"]["create_item"]["id"]
    return item_id, "created"


def get_board_id() -> int:
    return TICKETS_BOARD_ID

def get_tenders_group_id() -> str:
    return TENDERS_GROUP_ID