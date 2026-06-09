import scrapy
import os
from supabase import create_client
from dotenv import load_dotenv

load_dotenv(override=True)

class ItSignalsSpider(scrapy.Spider):
    name = "it_signals"
    
    # Targeting the public jobs endpoint for cybersecurity roles in South Africa
    start_urls = [
        "https://www.linkedin.com/jobs/search/?keywords=Cybersecurity%20OR%20SOC%20OR%20VAPT&location=South%20Africa"
    ]

    # Mimicking a real browser to bypass basic bot-detection
    custom_settings = {
        'USER_AGENT': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'ACCEPT_LANGUAGE': 'en-US,en;q=0.9',
        'DOWNLOAD_DELAY': 3, # Crucial: Wait 3 seconds between requests so we don't trigger rate limits
        'CONCURRENT_REQUESTS': 1
    }

    def __init__(self, *args, **kwargs):
        super(ItSignalsSpider, self).__init__(*args, **kwargs)
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")
        self.supabase = create_client(url, key)

    def parse(self, response):
        # LinkedIn's public job cards usually live inside these specific elements
        jobs = response.css('div.base-search-card__info')
        
        if not jobs:
            self.logger.warning("No jobs found. LinkedIn may have served a CAPTCHA or altered their HTML structure.")
            return

        for job in jobs:
            # Extracting the core data using LinkedIn's public CSS classes
            title = job.css('h3.base-search-card__title::text').get()
            company = job.css('h4.base-search-card__subtitle a::text').get()
            location = job.css('span.job-search-card__location::text').get()

            if company and title:
                company_name = company.strip()
                job_title = title.strip()
                loc = location.strip() if location else "South Africa"

                # We use the job title as our raw signal text for now
                signal_text = f"Hiring: {job_title}"

                self.logger.info(f"Discovered buying signal from: {company_name} - {job_title}")

                lead_data = {
                    "company_name": company_name,
                    "raw_signal_text": signal_text,
                    "location": loc,
                    "source_url": response.url,
                    "status": "New"
                }

                try:
                    self.supabase.table("leads").insert(lead_data).execute()
                    self.logger.info(f"Saved {company_name} to database.")
                except Exception as e:
                    self.logger.error(f"Database error: {e}")