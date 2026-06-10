import scrapy
import json
import os
from supabase import create_client
from dotenv import load_dotenv
import re

# Load environment variables
load_dotenv(override=True)

def normalize_ref(ref_string):
    if not ref_string:
        return "UNKNOWN"
    return re.sub(r'[\s/]+', '-', str(ref_string).strip().upper())

class ETenderAPISpider(scrapy.Spider):
    name = "etender_api"
    
    # Targeting the live OCDS API endpoint used by the transparency portal
    start_urls = ["https://ocds.etenders.gov.za/api/tenders"]

    # Spoofing headers to look like a standard Chrome browser request
    custom_settings = {
        'DEFAULT_REQUEST_HEADERS': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'Referer': 'https://www.etenders.gov.za/'
        },
        'ROBOTSTXT_OBEY': False # Necessary for API access
    }

    def __init__(self, *args, **kwargs):
        super(ETenderAPISpider, self).__init__(*args, **kwargs)
        self.supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

    def parse(self, response):
        try:
            # Parse the JSON response directly
            data = response.json()
            tenders = data.get("data", []) # Adjust if the key is 'items' or 'results'
            
            self.logger.info(f"Successfully connected to live API. Found {len(tenders)} tenders.")

            for tender in tenders:
                tender_no = normalize_ref(tender.get("tenderNumber"))
                title = tender.get("title", "No Title")
                
                # Database structure
                tender_data = {
                    "tender_number": tender_no,
                    "department_name": tender.get("department", "Unknown"),
                    "title": title[:200],
                    "description": tender.get("description", "")[:500],
                    "issue_date": tender.get("datePublished"),
                    "closing_date": tender.get("closingDate"),
                    "status": "Open",
                    "award_status": "In Evaluation",
                    "country": "South Africa"
                }

                # Upsert to Supabase
                self.supabase.table("sa_tenders").upsert(
                    tender_data, 
                    on_conflict="tender_number,department_name" 
                ).execute()
                
                self.logger.info(f"Live Ingest: {tender_no}")

        except Exception as e:
            self.logger.error(f"Failed to process live API feed: {e}")