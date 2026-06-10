import scrapy
import json
import os
from supabase import create_client
from dotenv import load_dotenv

load_dotenv(override=True)

class ETenderAPISpider(scrapy.Spider):
    name = "etender_api"

    # 1. Force Scrapy to ignore robots.txt just for this specific spider
    custom_settings = {
        'ROBOTSTXT_OBEY': False,
        'LOG_LEVEL': 'DEBUG'
    }

    def start_requests(self):
        self.logger.info("🔥 START_REQUESTS IS FIRING 🔥")
        url = "https://www.etenders.gov.za/Home/PaginatedTenderOpportunities"
        
        payload = {
            "draw": 1,
            "start": 0,
            "length": 1000,
            "status": 1,
            "search": {"value": "", "regex": False},
            "order": [{"column": 2, "dir": "desc"}]
        }

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'X-Requested-With': 'XMLHttpRequest',
            'Content-Type': 'application/json; charset=UTF-8',
            'Accept': 'application/json, text/javascript, */*; q=0.01'
        }

        # 2. dont_filter=True forces Scrapy to run this even if it thinks it already has
        yield scrapy.Request(
            url=url,
            method="POST",
            body=json.dumps(payload),
            headers=headers,
            callback=self.parse,
            dont_filter=True 
        )

    def __init__(self, *args, **kwargs):
        super(ETenderAPISpider, self).__init__(*args, **kwargs)
        self.supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

    def parse(self, response):
        self.logger.info(f"✅ RESPONSE RECEIVED: HTTP Status {response.status}")
        try:
            data = json.loads(response.text)
            tenders = data.get("data", [])
            
            self.logger.info(f"🎯 Successfully pulled {len(tenders)} active tenders from the live API.")
            
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
            self.logger.error(f"❌ Failed to parse API data: {e}")