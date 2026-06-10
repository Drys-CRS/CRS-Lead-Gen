"""
Shared utilities for all CRS tender spiders.
"""
import os
from supabase import create_client
from dotenv import load_dotenv

load_dotenv(override=True)

# ─────────────────────────────────────────────────────────────────
# KEYWORD FILTER  (shared across every country scraper)
# ─────────────────────────────────────────────────────────────────
TARGET_KEYWORDS = [
    "cyber", "EDR", "firewall", "network", "threat", "vulnerability",
    "training", "comptia", "ibm", "red hat", "ict ", "information technology",
    "cloud", "server", "endpoint", "infrastructure", "data center",
    "flare", "vectra", "aikido", "vicarius", "software", "hardware",
    "NDR", "IDR", "SAST", "VAPT", "penetration testing",
    "cybersecurity", "cyber security", "cyber risk", "cyber risk management",
    "cyber defense", "cyber defence", "cyber incident response",
    "cyber threat intelligence", "cyber threat hunting",
    "cyber vulnerability management", "cyber risk assessment",
    "cyber risk mitigation", "cyber risk monitoring",
    "cyber risk reporting", "cyber risk compliance", "data security",
    "z/os", "SOC", "patch management", "technical training",
    "cybersecurity training", "IT training", "information security training",
    "AI", "Security+", "IBM i", "Red Hat", "CompTIA",
    "cloud security", "network security", "endpoint security",
    "redhat", "SUSE", "application security",
    "identity and access management", "IAM", "zero trust",
    "SIEM", "security orchestration",
]


def is_relevant(text: str) -> bool:
    """Return True if any keyword matches the lowercased text."""
    lower = text.lower()
    return any(kw.lower() in lower for kw in TARGET_KEYWORDS)


def get_supabase():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise EnvironmentError("SUPABASE_URL or SUPABASE_KEY not set in environment.")
    return create_client(url, key)


def upsert_tenders(supabase, records: list[dict], country: str, label: str = ""):
    """Upsert a list of tender dicts into sa_tenders. Prints a summary."""
    if not records:
        print(f"  [{country}] No {label} records to upsert.")
        return
    success, failed = 0, 0
    for record in records:
        try:
            supabase.table("sa_tenders").upsert(
                record, on_conflict="tender_number,department_name"
            ).execute()
            success += 1
        except Exception as e:
            failed += 1
            print(f"  ⚠️  DB error for {record.get('tender_number')}: {e}")
    print(f"  [{country}] {label}: ✅ {success} upserted, ❌ {failed} failed")