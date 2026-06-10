import scrapy
import json
import os
from supabase import create_client
from dotenv import load_dotenv

load_dotenv(override=True)

class ETenderAPISpider(scrapy.Spider):
    name = "etender_api"
    # Target the newly discovered live API endpoint
    start_urls = ["https://www.etenders.gov.za/Home/PaginatedTenderOpportunities"]

    def start_requests(self):
        # Send a POST request with 'status=1' (Currently Advertised)
        yield scrapy.FormRequest(
            url="https://www.etenders.gov.za/Home/PaginatedTenderOpportunities",
            formdata={'status': '1'},
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