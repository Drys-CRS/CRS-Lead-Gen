"""
monday_client.py — CRS Monday.com Integration
All board IDs and column IDs are loaded from Streamlit secrets so they
can be configured without touching code.

Required secrets:
  MONDAY_API_KEY        = "your_token_here"

  # Board IDs — get from each board's URL: monday.com/boards/XXXXXXXXX
  MONDAY_LEADS_BOARD_ID        = "1234567890"
  MONDAY_CONTACTS_BOARD_ID     = "1234567890"
  MONDAY_COMPANIES_BOARD_ID    = "1234567890"
  MONDAY_TICKETS_BOARD_ID      = "1234567890"   # Outstanding Tickets

  # Group IDs within Leads board (get from board URL after selecting group)
  MONDAY_LEADS_INTAKE_GROUP    = "new_group"    # default intake group name
  MONDAY_COMPANIES_RESELLERS   = "resellers"    # Resellers group in Companies
"""
import json
import requests
import streamlit as st

MONDAY_URL = "https://api.monday.com/v2"

# ── Column value formats ────────────────────────────────────────────────────
# These are the column IDs as they appear in your board (lowercase, underscored).
# CRS board column IDs derived from the SOP — adjust if Monday assigned different IDs.
# Run _discover_columns(board_id) to print actual IDs from a live board.

# Leads Board column IDs (SOP-derived)
LEADS_COLS = {
    "company":           "company",
    "title":             "title",
    "linkedin":          "linkedin",
    "phone":             "phone",
    "email":             "email",
    "lead_interest":     "lead_interest",
    "lead_origin":       "lead_origin",
    "region":            "region",
    "country":           "country",
    "status":            "status",
    "am":                "am",
    "accuracy_score":    "accuracy_score",
    "industry":          "industry",
    "contact_notes":     "contact_notes",
    "next_contact_date": "date",
}

# Companies Board column IDs
COMPANIES_COLS = {
    "account_type":      "account_type",
    "region":            "region",
    "industry":          "industry",
    "website_url":       "website_url",
    "linkedin_url":      "linkedin_url",
    "crs_partner_status":"crs_partner_status",
    "notes":             "company_notes",
    "email_address":     "email_address",
}


def _gql(query: str, variables: dict = None) -> dict:
    """Execute a Monday GraphQL request. Returns the full response dict."""
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


# ── Column discovery ──────────────────────────────────────────────────────────
def discover_columns(board_id: str) -> dict:
    """Return {column_title: column_id} for a board. Use to find real column IDs."""
    q = """
    query ($bid: ID!) {
      boards(ids: [$bid]) {
        columns { id title type }
      }
    }"""
    data = _gql(q, {"bid": board_id})
    cols = data["data"]["boards"][0]["columns"]
    return {c["title"]: c["id"] for c in cols}


# ── Deduplication ─────────────────────────────────────────────────────────────
def find_item_by_name(board_id: str, name: str) -> str | None:
    """Return item_id if an item with this name already exists, else None."""
    q = """
    query ($bid: ID!, $name: String!) {
      items_page_by_column_values(
        board_id: $bid, limit: 5,
        columns: [{column_id: "name", column_values: [$name]}]
      ) {
        items { id name }
      }
    }"""
    try:
        data = _gql(q, {"bid": board_id, "name": name})
        items = data["data"]["items_page_by_column_values"]["items"]
        return items[0]["id"] if items else None
    except Exception:
        # Fallback: search all items (slower but always works)
        return _find_item_by_name_scan(board_id, name)


def _find_item_by_name_scan(board_id: str, name: str) -> str | None:
    """Scan board items for a name match (fallback)."""
    q = """
    query ($bid: ID!) {
      boards(ids: [$bid]) {
        items_page(limit: 500) { items { id name } }
      }
    }"""
    try:
        data = _gql(q, {"bid": board_id})
        items = data["data"]["boards"][0]["items_page"]["items"]
        name_lower = name.lower()
        for item in items:
            if item["name"].lower() == name_lower:
                return item["id"]
    except Exception:
        pass
    return None


# ── Create / update items ─────────────────────────────────────────────────────
def _cv(col_id: str, value) -> str:
    """Format a column value for Monday API. Returns JSON string fragment."""
    return {col_id: value}


def create_lead(
    name: str,
    company: str = "",
    title: str = "",
    email: str = "",
    phone: str = "",
    linkedin: str = "",
    lead_origin: str = "",
    lead_interest: str = "",
    region: str = "",
    country: str = "",
    notes: str = "",
    crs_score: int = None,
    outreach_angle: str = "",
) -> str | None:
    """
    Create a lead on the Leads Board.
    Deduplicates by name — if it already exists, updates it instead.
    Returns the Monday item_id.
    """
    board_id   = st.secrets.get("MONDAY_LEADS_BOARD_ID", "")
    group_id   = st.secrets.get("MONDAY_LEADS_INTAKE_GROUP", "topics")
    if not board_id:
        raise ValueError("MONDAY_LEADS_BOARD_ID not set in secrets.")

    # Check for duplicate
    existing_id = find_item_by_name(board_id, name)
    if existing_id:
        # Update instead of creating
        _update_lead_score(board_id, existing_id, crs_score, outreach_angle, notes)
        return existing_id

    # Build column values
    col_vals = {}
    if company:       col_vals["company"]       = company
    if title:         col_vals["title"]          = title
    if email:         col_vals["email"]          = {"email": email, "text": email}
    if phone:         col_vals["phone"]          = {"phone": phone, "countryShortName": "ZA"}
    if linkedin:      col_vals["linkedin"]       = {"url": linkedin, "text": linkedin}
    if lead_origin:   col_vals["lead_origin"]    = {"label": lead_origin}
    if lead_interest: col_vals["lead_interest"]  = {"label": lead_interest}
    if region:        col_vals["region"]         = {"label": region}
    if country:       col_vals["country"]        = country
    if notes or outreach_angle:
        col_vals["contact_notes"] = f"{notes}\n\nOutreach: {outreach_angle}".strip()
    if crs_score is not None:
        col_vals["accuracy_score"] = crs_score

    q = """
    mutation ($bid: ID!, $gid: String!, $name: String!, $cv: JSON!) {
      create_item(board_id: $bid, group_id: $gid, item_name: $name, column_values: $cv) {
        id
      }
    }"""
    data = _gql(q, {
        "bid":  board_id,
        "gid":  group_id,
        "name": name,
        "cv":   json.dumps(col_vals),
    })
    return data["data"]["create_item"]["id"]


def _update_lead_score(board_id: str, item_id: str, score: int, outreach: str, notes: str):
    """Update CRS score and outreach angle on an existing lead."""
    col_vals = {}
    if score is not None:
        col_vals["accuracy_score"] = score
    if outreach or notes:
        col_vals["contact_notes"] = f"{notes}\n\nOutreach: {outreach}".strip()
    if not col_vals:
        return
    q = """
    mutation ($bid: ID!, $iid: ID!, $cv: JSON!) {
      change_multiple_column_values(board_id: $bid, item_id: $iid, column_values: $cv) { id }
    }"""
    _gql(q, {"bid": board_id, "iid": item_id, "cv": json.dumps(col_vals)})


def update_lead_columns(board_id: str, item_id: str, col_vals: dict):
    """Generic column update — pass {column_id: value} dict."""
    q = """
    mutation ($bid: ID!, $iid: ID!, $cv: JSON!) {
      change_multiple_column_values(board_id: $bid, item_id: $iid, column_values: $cv) { id }
    }"""
    _gql(q, {"bid": board_id, "iid": item_id, "cv": json.dumps(col_vals)})


def create_subitem(parent_item_id: str, subitem_name: str, col_vals: dict = None) -> str | None:
    """Attach a subitem to an existing item (company/lead)."""
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


def create_company(
    name: str,
    account_type: str = "End-user",
    region: str = "",
    industry: str = "",
    website: str = "",
    linkedin: str = "",
    email: str = "",
    notes: str = "",
    partner_status: str = "",
    group_id: str = None,
) -> str | None:
    """
    Create a company on the Companies Board.
    Deduplicates by name. Returns item_id.
    """
    board_id = st.secrets.get("MONDAY_COMPANIES_BOARD_ID", "")
    if not board_id:
        raise ValueError("MONDAY_COMPANIES_BOARD_ID not set in secrets.")

    existing_id = find_item_by_name(board_id, name)
    if existing_id:
        return existing_id

    grp = group_id or st.secrets.get("MONDAY_COMPANIES_RESELLERS", "resellers")
    col_vals = {}
    if account_type: col_vals["account_type"]      = {"label": account_type}
    if region:       col_vals["region"]             = {"label": region}
    if industry:     col_vals["industry"]           = industry
    if website:      col_vals["website_url"]        = {"url": website, "text": website}
    if linkedin:     col_vals["linkedin_url"]       = {"url": linkedin, "text": linkedin}
    if email:        col_vals["email_address"]      = {"email": email, "text": email}
    if notes:        col_vals["company_notes"]      = notes
    if partner_status: col_vals["crs_partner_status"] = {"label": partner_status}

    q = """
    mutation ($bid: ID!, $gid: String!, $name: String!, $cv: JSON!) {
      create_item(board_id: $bid, group_id: $gid, item_name: $name, column_values: $cv) { id }
    }"""
    data = _gql(q, {
        "bid":  board_id,
        "gid":  grp,
        "name": name,
        "cv":   json.dumps(col_vals),
    })
    return data["data"]["create_item"]["id"]


# ── High-level CRS-specific pushes ────────────────────────────────────────────
def push_tender_lead(tender: dict) -> str | None:
    """
    Push a high-scoring tender to the Leads Board.
    Maps tender fields → Monday Leads columns.
    """
    solution_map = {
        "cyber": "Vectra", "soc": "Vectra", "ndr": "Vectra", "xdr": "Vectra",
        "vulnerability": "vRx", "patch": "vRx", "vapt": "Pentest / VA",
        "penetration": "Pentest / VA", "pentest": "Pentest / VA",
        "training": "IBM", "ibm": "IBM", "redhat": "REDHAT", "suse": "REDHAT",
        "comptia": "IBM", "cloud": "Vectra", "siem": "Vectra",
        "phishing": "ECCA / CRE", "awareness": "ECCA / CRE",
        "threat": "Flare", "dark web": "Flare", "ransomware": "Flare",
        "endpoint": "SMBsecure", "encryption": "BH", "popia": "SMBsecure",
        "application": "Aikido", "devsec": "Aikido", "sast": "Aikido",
    }
    title_lower = (tender.get("title") or "").lower()
    desc_lower  = (tender.get("description") or "").lower()
    combined    = f"{title_lower} {desc_lower}"
    lead_interest = "Vectra"   # default
    for kw, solution in solution_map.items():
        if kw in combined:
            lead_interest = solution
            break

    country  = tender.get("country", "South Africa")
    region_map = {
        "South Africa": "South Africa", "Kenya": "East Africa",
        "Nigeria": "West Africa", "Ghana": "West Africa",
        "Tanzania": "East Africa", "Uganda": "East Africa",
        "Zambia": "Southern Africa", "Rwanda": "East Africa",
    }
    region = region_map.get(country, "International")

    return create_lead(
        name         = tender.get("department_name") or tender.get("title","Unknown")[:80],
        company      = tender.get("department_name",""),
        lead_origin  = "Tender Portal",
        lead_interest= lead_interest,
        region       = region,
        country      = country,
        notes        = f"Tender: {tender.get('tender_number','')} | Closing: {tender.get('closing_date','')}",
        crs_score    = tender.get("ai_score"),
        outreach_angle = tender.get("ai_rationale","")[:500],
    )


def push_attack_signal_lead(signal: dict) -> str | None:
    """
    Push a high-scoring attack signal (victim org) to Leads Board
    and attach the attack detail as a subitem.
    """
    victim  = signal.get("victim_org","")
    if not victim or victim.lower() in ("unknown",""):
        return None

    attack_map = {
        "ransomware":  "Flare",
        "data breach": "SMBsecure",
        "phishing":    "ECCA / CRE",
        "ddos":        "Vectra",
        "malware":     "vRx",
        "unknown":     "Vectra",
    }
    attack_type   = (signal.get("attack_type") or "unknown").lower()
    lead_interest = attack_map.get(attack_type, "Vectra")

    item_id = create_lead(
        name          = victim,
        company       = victim,
        title         = signal.get("contact_title","CISO"),
        lead_origin   = "Cyber Attack Signal",
        lead_interest = lead_interest,
        notes         = f"Attack type: {attack_type}\nSource: {signal.get('source','')}\nDate: {signal.get('published','')}",
        crs_score     = signal.get("crs_score"),
        outreach_angle= signal.get("outreach_angle",""),
    )

    # Attach attack detail as subitem
    if item_id:
        try:
            subitem_name = f"{attack_type.title()} — {signal.get('published','recent')}"
            create_subitem(item_id, subitem_name, {
                "text": signal.get("title","")[:200],
            })
        except Exception:
            pass  # subitems require board to have subitem column — non-fatal

    return item_id


def push_apollo_contact(person: dict) -> str | None:
    """Push an Apollo contact to the Leads Board."""
    name = (person.get("name") or "").strip()
    if not name:
        return None
    return create_lead(
        name          = name,
        company       = person.get("company",""),
        title         = person.get("title",""),
        email         = person.get("email",""),
        phone         = person.get("phone",""),
        linkedin      = person.get("linkedin",""),
        lead_origin   = "Apollo Contact Search",
        crs_score     = person.get("crs_score"),
    )


def push_partner_company(partner: dict) -> str | None:
    """Push an AI-recommended partner to the Companies Board (Resellers group)."""
    name = (partner.get("company") or partner.get("name","")).strip()
    if not name:
        return None
    return create_company(
        name         = name,
        account_type = partner.get("partnership_type","Reseller").split("/")[0].strip(),
        region       = partner.get("country",""),
        notes        = f"AI Partnership Recommendation:\n{partner.get('why',partner.get('why_aligned',''))}\n\nOutreach: {partner.get('outreach_angle','')}",
        partner_status = "Prospect",
        group_id     = st.secrets.get("MONDAY_COMPANIES_RESELLERS","resellers"),
    )