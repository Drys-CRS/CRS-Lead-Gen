import scrapy
import json
import os
from supabase import create_client
from dotenv import load_dotenv

load_dotenv(override=True)

class ETenderAPISpider(scrapy.Spider):
    name = "etender_api"

    def start_requests(self):
        url = "https://www.etenders.gov.za/Home/PaginatedTenderOpportunities"
        
        # We must simulate the exact JSON structure DataTables sends to prevent server crashes
        payload = {
            "draw": 1,
            "start": 0,
            "length": 1000,
            "status": 1, # 1 = Currently Advertised
            "search": {"value": "", "regex": False},
            "order": [{"column": 2, "dir": "desc"}] # Matches their JS sorting rule
        }

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'X-Requested-With': 'XMLHttpRequest',
            'Content-Type': 'application/json; charset=UTF-8',
            'Accept': 'application/json, text/javascript, */*; q=0.01'
        }

        # Send as a POST request with the JSON body
        yield scrapy.Request(
            url=url,
            method="POST",
            body=json.dumps(payload),
            headers=headers,
            callback=self.parse
        )

    def __init__(self, *args, **kwargs):
        super(ETenderAPISpider, self).__init__(*args, **kwargs)
        self.supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

    def parse(self, response):
        try:
            data = json.loads(response.text)
            tenders = data.get("data", [])
            
            self.logger.info(f"Successfully pulled {len(tenders)} active tenders from the live API.")
            
            for tender in tenders:
                tender_data = {
                    "tender_number": tender.get("tender_No"),
                    "department_name": tender.get("department"),
                    "title": tender.get("description", "")[:200],
                    "category": tender.get("category"),
                    "issue_date": tender.get("date_Published"),
                    "closing_date": tender.get("closing_Date"),
                    "status": "Open",
                    "award_status": "Published",
                    "country": "South Africa"
                }

                # Upsert to Supabase
                self.supabase.table("sa_tenders").upsert(
                    tender_data, 
                    on_conflict="tender_number,department_name"
                ).execute()

        except Exception as e:
            self.logger.error(f"Failed to parse API data: {e}")