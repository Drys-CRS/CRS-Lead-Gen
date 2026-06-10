import scrapy
import json
import re
import os
from supabase import create_client
from dotenv import load_dotenv

# --- 1. The Intelligence Filter ---
TARGET_KEYWORDS = [
    "ibm", 
    "comptia", 
    "red hat", 
    "redhat", 
    "rhel",
    "cybersecurity training",
    "information security training",
    "certification",
    "it training",
    "security awareness"
]

def normalize_ref(ref_string):
    if not ref_string:
        return "UNKNOWN"
    return re.sub(r'[\s/]+', '-', str(ref_string).strip().upper())

def is_target_lead(title, description):
    """Scans the tender text to see if it matches our core IT Training portfolio."""
    full_text = f"{title} {description}".lower()
    for keyword in TARGET_KEYWORDS:
        if keyword in full_text:
            return True
    return False

# --- 2. The Spider Logic ---
class ITTrainingSpider(scrapy.Spider):
    name = "it_training_tenders"
    # Pointing to the general eTender portal source
    start_urls = ["https://www.etenders.gov.za/home/AdvertisedTenders/"]

    def __init__(self, *args, **kwargs):
        super(ITTrainingSpider, self).__init__(*args, **kwargs)
        load_dotenv(override=True)
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")
        self.supabase = create_client(url, key)

    def parse(self, response):
        self.logger.info("Executing targeted sweep for IT & Cybersecurity Training tenders...")
        
        # Simulated payload representing a daily dump of hundreds of mixed government tenders
        mock_daily_dump = [
            {
                "tenderNumber": "DPW-HQ-20419",
                "department": "Department of Public Works and Infrastructure",
                "title": "Cybersecurity Awareness and Information Security Risk Training",
                "description": "Provision of formal cybersecurity capability training for public sector administrative personnel.",
                "datePublished": "2026-06-05",
                "closingDate": "2026-07-18"
            },
            {
                "tenderNumber": "WATER-2026-09",
                "department": "Department of Water and Sanitation",
                "title": "Maintenance of Centrifugal Pumps",
                "description": "Annual service contract for heavy duty water pumps at the Vaal reservoir.",
                "datePublished": "2026-06-09",
                "closingDate": "2026-08-01"
            },
            {
                "tenderNumber": "241S/2025/26",
                "department": "City of Cape Town Municipality",
                "title": "Provision of Red Hat Enterprise Linux (RHEL) Subscription Portfolios",
                "description": "Tender for an authorized partner to supply enterprise open-source software and platform architecture training.",
                "datePublished": "2026-06-10",
                "closingDate": "2026-07-22"
            },
            {
                "tenderNumber": "ROADS-992-GP",
                "department": "SANRAL",
                "title": "Pothole Repair and Asphalt Resurfacing",
                "description": "Contract for the repair of the N1 highway asphalt.",
                "datePublished": "2026-06-10",
                "closingDate": "2026-07-15"
            }
        ]

        leads_found = 0

        # ... inside the parse loop ...
        for tender in mock_daily_dump:  # (Or the live payload if you replaced the mock)
            title = tender.get("title", "")
            description = tender.get("description", "")
            raw_ref = tender.get("tenderNumber")

            if not is_target_lead(title, description):
                self.logger.debug(f"Dropped irrelevant contract: {raw_ref}")
                continue 

            leads_found += 1
            tender_no = normalize_ref(raw_ref)

            # --- NEW: Extract the Document Link ---
            # Treasury stores files in an array; we grab the first primary document
            documents = tender.get("documents", [])
            doc_link = None
            if documents and len(documents) > 0:
                blob_name = documents[0].get("blobName")
                file_name = documents[0].get("downloadedFileName")
                if blob_name and file_name:
                    doc_link = f"https://www.etenders.gov.za/home/Download/?blobName={blob_name}&downloadedFileName={file_name}"

            tender_data = {
                "tender_number": tender_no,
                "department_name": tender.get("department"),
                "country": "South Africa",
                "title": title[:200],
                "description": description,
                "issue_date": tender.get("datePublished"),
                "closing_date": tender.get("closingDate"),
                "status": "Open",
                "award_status": "In Evaluation",
                "document_url": doc_link # Our new field!
            }

            try:
                self.supabase.table("sa_tenders").upsert(
                    tender_data, 
                    on_conflict="tender_number,department_name" 
                ).execute()
                self.logger.info(f"HIGH VALUE LEAD SECURED: {tender_no} - {title[:40]}...")
            except Exception as e:
                self.logger.error(f"Database error writing {tender_no}: {e}")

        self.logger.info(f"Sweep complete. Filtered {len(mock_daily_dump)} raw contracts. Secured {leads_found} target leads.")