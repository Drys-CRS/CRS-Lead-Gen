"""
monday_client.py — CRS Monday.com Integration
Column IDs and group IDs verified via MCP on 2026-06-11.

Required secret:
  MONDAY_API_KEY = "your_token_here"
"""
import json
import requests
import streamlit as st

MONDAY_URL = "https://api.monday.com/v2"

# ── Board & Group IDs (verified) ──────────────────────────────────────────────
TICKETS_BOARD_ID    = 5657844182   # "0 - Outstanding Tickets"
TICKETS_NEW_REQ_GRP = "topics"     # "New Requests" group

LEADS_BOARD_ID      = 7677528134   # "1.0 - Leads - 2.0"
LEADS_NEW_GRP       = "group_mm471gfq"  # "NEW Leads" group

# Tag IDs on Leads board
TAG_TENDER          = 27382437     # "Tender"
TAG_CYBERSECURITY   = 29105714     # "cybersec"
TAG_IBM_TRAINING    = 29105702     # "IBMTraining"

# ── Solution → CRS Division + vendor column mapping ──────────────────────────
# (Outstanding Tickets columns: single_select411 = CRS Division,
#  single_select0 = CyberSec Vendor, single_select19 = Training Vendor)
SOLUTION_MAP = {
    "vectra":       ("CyberSec",  "VECTRA",                   None),
    "ndr":          ("CyberSec",  "VECTRA",                   None),
    "xdr":          ("CyberSec",  "VECTRA",                   None),
    "soc":          ("CyberSec",  "VECTRA",                   None),
    "siem":         ("CyberSec",  "VECTRA",                   None),
    "vrx":          ("CyberSec",  "vRx",                      None),
    "vulnerability":("CyberSec",  "vRx",                      None),
    "patch":        ("CyberSec",  "vRx",                      None),
    "vapt":         ("CyberSec",  None,                       None),
    "penetration":  ("CyberSec",  None,                       None),
    "pentest":      ("CyberSec",  None,                       None),
    "smb":          ("CyberSec",  "SMBsecure",                None),
    "encryption":   ("CyberSec",  "Beachheadsecure",          None),
    "popia":        ("CyberSec",  "SMBsecure",                None),
    "beachhead":    ("CyberSec",  "Beachheadsecure",          None),
    "aikido":       ("CyberSec",  None,                       None),
    "sast":         ("CyberSec",  None,                       None),
    "devsec":       ("CyberSec",  None,                       None),
    "awareness":    ("CyberSec",  "Cyber Awareness Training", None),
    "phishing":     ("CyberSec",  "Cyber Awareness Training", None),
    "flare":        ("CyberSec",  None,                       None),
    "dark web":     ("CyberSec",  None,                       None),
    "ransomware":   ("CyberSec",  None,                       None),
    "ibm":          ("Training",  None,                       "IBM Training"),
    "redhat":       ("Training",  None,                       "Redhat"),
    "red hat":      ("Training",  None,                       "Redhat"),
    "suse":         ("Training",  None,                       "SUSE"),
    "comptia":      ("Training",  None,                       "CompTIA"),
    "agile":        ("Training",  None,                       "Agile SAFe Training"),
    "training":     ("Training",  None,                       "IBM Training"),
    "certification":("Training",  None,                       "IBM Training"),
}

# Region mapping for Outstanding Tickets
REGION_MAP = {
    "South Africa": "South Africa",
    "Kenya": "Africa and other", "Nigeria": "Africa and other",
    "Ghana": "Africa and other", "Tanzania": "Africa and other",
    "Uganda": "Africa and other", "Zambia": "Africa and other",
    "Rwanda": "Africa and other", "Liberia": "Africa and other",
    "Angola": "Africa and other", "Botswana": "Africa and other",
    "Egypt": "Africa and other", "Ethiopia": "Africa and other",
    "Zimbabwe": "Africa and other", "Mozambique": "Africa and other",
    "Namibia": "Africa and other", "Malawi": "Africa and other",
    "Mauritius": "Africa and other",
}
LOCATION_MAP = {
    "South Africa": "South Africa",
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
def find_item_by_column(board_id: int, column_id: str, value: str) -> str | None:
    """Return item_id if a matching item exists, else None."""
    q = """
    query ($bid: ID!, $col: String!, $val: String!) {
      items_page_by_column_values(
        board_id: $bid, limit: 3,
        columns: [{column_id: $col, column_values: [$val]}]
      ) { items { id name } }
    }"""
    try:
        data = _gql(q, {"bid": str(board_id), "col": column_id, "val": value})
        items = data["data"]["items_page_by_column_values"]["items"]
        return items[0]["id"] if items else None
    except Exception:
        return None


def _create_item(board_id: int, group_id: str, name: str, col_vals: dict) -> str | None:
    """Create an item and return its ID."""
    q = """
    mutation ($bid: ID!, $gid: String!, $name: String!, $cv: JSON!) {
      create_item(board_id: $bid, group_id: $gid, item_name: $name, column_values: $cv) {
        id
      }
    }"""
    data = _gql(q, {
        "bid":  str(board_id),
        "gid":  group_id,
        "name": name,
        "cv":   json.dumps(col_vals),
    })
    return data["data"]["create_item"]["id"]


def _update_item(board_id: int, item_id: str, col_vals: dict):
    """Update columns on an existing item."""
    q = """
    mutation ($bid: ID!, $iid: ID!, $cv: JSON!) {
      change_multiple_column_values(board_id: $bid, item_id: $iid, column_values: $cv) { id }
    }"""
    _gql(q, {"bid": str(board_id), "iid": item_id, "cv": json.dumps(col_vals)})


def create_subitem(parent_item_id: str, subitem_name: str, col_vals: dict = None) -> str | None:
    """Attach a subitem to an existing item."""
    q = """
    mutation ($pid: ID!, $name: String!, $cv: JSON!) {
      create_subitem(parent_item_id: $pid, item_name: $name, column_values: $cv) { id }
    }"""
    data = _gql(q, {
        "pid":  parent_item_id,
        "name": subitem_name,
        "cv":   json.dumps(col_vals or {}),
    })
    return data["data"]["create_subitem"]["id"]


# ── Solution inference ─────────────────────────────────────────────────────────
def _infer_solution(title: str, description: str) -> tuple:
    """Return (crs_division, cybersec_vendor, training_vendor) from text."""
    text = f"{title} {description}".lower()
    for kw, (div, cs_v, tr_v) in SOLUTION_MAP.items():
        if kw in text:
            return div, cs_v, tr_v
    return "CyberSec", None, None


# ── MAIN PUSH FUNCTION ─────────────────────────────────────────────────────────
def push_tender_to_monday(tender: dict) -> dict:
    """
    Push a tender to TWO Monday boards simultaneously:

    1. Outstanding Tickets (board 5657844182)
       → Group: "New Requests" (topics)
       → Status: "Tender Request" (id=105)
       Populates: tender number, description, dates, vendor, region,
                  AI score in Additional Info

    2. Leads - 2.0 (board 7677528134)
       → Group: "NEW Leads" (group_mm471gfq)
       Populates: department name as contact, tagged "Tender",
                  outreach angle in Additional Contact Info,
                  AI score in Accuracy Score

    Deduplicates on Tender Number (Tickets) and item name (Leads).
    Returns {"ticket_id": ..., "lead_id": ..., "ticket_action": ..., "lead_action": ...}
    """
    tender_number = str(tender.get("tender_number") or "").strip()
    title         = str(tender.get("title") or "")[:200]
    description   = str(tender.get("description") or "")
    department    = str(tender.get("department_name") or "")[:200]
    country       = str(tender.get("country") or "South Africa")
    closing_date  = str(tender.get("closing_date") or "")[:10]
    issue_date    = str(tender.get("issue_date") or "")[:10]
    portal_link   = str(tender.get("portal_link") or "")
    ai_score      = tender.get("ai_score")
    ai_rationale  = str(tender.get("ai_rationale") or "")[:500]

    div, cs_vendor, tr_vendor = _infer_solution(title, description)
    region   = REGION_MAP.get(country, "Africa and other")
    location = LOCATION_MAP.get(country, "Africa")

    result = {}

    # ── 1. Outstanding Tickets — New Requests, Status = Tender Request ────────
    ticket_id     = None
    ticket_action = "skipped"

    if tender_number:
        ticket_id = find_item_by_column(
            TICKETS_BOARD_ID, "text_mkz9683j", tender_number
        )

    if ticket_id:
        ticket_action = "exists"
        # Update AI score & rationale on existing ticket
        try:
            _update_item(TICKETS_BOARD_ID, ticket_id, {
                "long_text_1": f"AI Fit Score: {ai_score}/10\n\n{ai_rationale}",
            })
        except Exception:
            pass
    else:
        # Build column values for new ticket
        ticket_cols = {
            "text_mkz9683j":     tender_number,
            "long_text_mkz9tze4":f"{description}\n\nDepartment: {department}",
            "status":            {"label": "Tender Request"},   # id=105
            "color_mkz91j57":    {"label": "Open Tender"},
            "short_text":        department,
            "short_text541":     department,
            "single_select76":   {"label": region},
            "single_select05":   {"label": location if location in ("South Africa", "Africa") else "Africa"},
            "single_select411":  {"label": div},
            "single_select":     {"label": "New Customer"},
            "long_text_1":       f"AI Fit Score: {ai_score}/10\n\n{ai_rationale}",
        }
        if cs_vendor:
            ticket_cols["single_select0"]  = {"label": cs_vendor}
        if tr_vendor:
            ticket_cols["single_select19"] = {"label": tr_vendor}
        if issue_date:
            ticket_cols["date_mkz9ag0h"]   = {"date": issue_date}
        if closing_date:
            ticket_cols["date_mkz9kfdr"]   = {"date": closing_date}
        if portal_link:
            ticket_cols["link_mkz9vz25"]   = {"url": portal_link, "text": "Portal"}

        item_name = tender_number if tender_number else title[:80]
        try:
            ticket_id = _create_item(
                TICKETS_BOARD_ID, TICKETS_NEW_REQ_GRP, item_name, ticket_cols
            )
            ticket_action = "created"
        except Exception as e:
            ticket_action = f"error: {str(e)[:120]}"

    result["ticket_id"]     = ticket_id
    result["ticket_action"] = ticket_action

    # ── 2. Leads - 2.0 — NEW Leads group, tagged "Tender" ─────────────────────
    lead_id     = None
    lead_action = "skipped"
    lead_name   = department or title[:80]

    if lead_name:
        lead_id = find_item_by_column(LEADS_BOARD_ID, "name", lead_name)

    if lead_id:
        lead_action = "exists"
        # Enrich existing lead with tender context
        try:
            existing_note = f"Tender: {tender_number} | Closing: {closing_date} | Score: {ai_score}/10\n{ai_rationale}"
            _update_item(LEADS_BOARD_ID, lead_id, {
                "long_text_mks8gmfw": existing_note[:2000],
                "text__1":            str(ai_score) if ai_score else "",
            })
        except Exception:
            pass
    else:
        # Determine lead interest tag — use existing tag IDs
        lead_interest_tag = TAG_IBM_TRAINING if div == "Training" else TAG_CYBERSECURITY

        lead_cols = {
            "tags":               [TAG_TENDER, lead_interest_tag],
            "dup__of_lead_origin":[TAG_TENDER],
            "text1__1":           f"{div} — {country}",
            "text__1":            str(ai_score) if ai_score else "",
            "long_text_mks8gmfw": (
                f"Source: Tender Portal | Country: {country}\n"
                f"Tender No: {tender_number} | Closing: {closing_date}\n"
                f"AI Fit Score: {ai_score}/10\n\n{ai_rationale}"
            )[:2000],
            "text0":              f"Tender {tender_number} — {country}",
        }

        try:
            lead_id = _create_item(
                LEADS_BOARD_ID, LEADS_NEW_GRP, lead_name, lead_cols
            )
            lead_action = "created"
        except Exception as e:
            lead_action = f"error: {str(e)[:120]}"

    result["lead_id"]     = lead_id
    result["lead_action"] = lead_action

    return result


def get_ticket_board_id() -> int:
    return TICKETS_BOARD_ID

def get_leads_board_id() -> int:
    return LEADS_BOARD_ID