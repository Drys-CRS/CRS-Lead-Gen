import scrapy
import json
import os
from supabase import create_client
from dotenv import load_dotenv

load_dotenv(override=True)

class ETenderSpider(scrapy.Spider):
    name = "etender_api"
    start_urls = ["http://example.com"]

    def __init__(self, *args, **kwargs):
        super(ETenderSpider, self).__init__(*args, **kwargs)
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")
        self.supabase = create_client(url, key)

    def parse(self, response):
        # Comprehensive dataset across the major South African procurement tiers
        mock_json_data = """
        {
            "tenders": [
                {
                    "tenderNumber": "E/KM3241-CS",
                    "department": "Eskom Holdings SOC Ltd",
                    "country": "South Africa",
                    "title": "Substation Firewall Infrastructure Refresh and Network Segmentation",
                    "description": "Procurement of industrial-grade enterprise firewalls, deployment services, and zero-trust architecture implementation across critical generation sub-stations.",
                    "datePublished": "2026-06-09",
                    "closingDate": "2026-07-28",
                    "url": "https://tenderbulletin.eskom.co.za",
                    "requirements": "Mandatory CSD Registration, B-BBEE Level 1-4, Certified OEM Deployment Partner Status"
                },
                {
                    "tenderNumber": "TN/2026/05/0012/GCTC",
                    "department": "Transnet SOC Ltd",
                    "country": "South Africa",
                    "title": "Endpoint Detection and Response (EDR) Licensing and 3-Year Support",
                    "description": "Supply, delivery, and configuration of enterprise-wide EDR agent licensing to secure port and rail logistics operations infrastructure.",
                    "datePublished": "2026-06-08",
                    "closingDate": "2026-07-14",
                    "url": "https://transnetetenders.azurewebsites.net",
                    "requirements": "B-BBEE Level 1-3, Valid Tax Compliance Status, National Treasury CSD Verified"
                },
                {
                    "tenderNumber": "241S/2025/26",
                    "department": "City of Cape Town Municipality",
                    "title": "Provision of Red Hat Enterprise Linux (RHEL) and SUSE Subscription Portfolios",
                    "country": "South Africa",
                    "description": "Tender for an authorized value-added partner to supply enterprise open-source software subscriptions, technical support, and platform architecture training.",
                    "datePublished": "2026-06-10",
                    "closingDate": "2026-07-22",
                    "url": "https://web1.capetown.gov.za/web1/TenderPortal",
                    "requirements": "Local Supplier Preference, B-BBEE Compliant, OEM Authorized Distributor Letter"
                },
                {
                    "tenderNumber": "RFP 45/2026",
                    "department": "South African Revenue Service (SARS)",
                    "country": "South Africa",
                    "title": "Advanced Threat Exposure Management and Vulnerability Assessment Platform",
                    "description": "Implementation of a centralized vulnerability management platform incorporating VAPT automation, risk-based prioritization, and security posture dashboards.",
                    "datePublished": "2026-06-07",
                    "closingDate": "2026-07-09",
                    "url": "https://www.sars.gov.za/about/procurement",
                    "requirements": "Strict B-BBEE Level 1-2 Requirement, Comprehensive CSD Profile, ISO 27001 Compliance Certification"
                },
                {
                    "tenderNumber": "DPW-HQ-20419",
                    "department": "Department of Public Works and Infrastructure",
                    "country": "South Africa",
                    "title": "Cybersecurity Awareness and Information Security Risk Training",
                    "description": "Provision of formal cybersecurity capability training, risk management courses, and basic awareness qualifications for public sector administrative personnel.",
                    "datePublished": "2026-06-05",
                    "closingDate": "2026-07-18",
                    "url": "https://www.publicworks.gov.za",
                    "requirements": "SAQA Aligned Training Credentials, MICT SETA or QCTO Accreditation, CSD Registered"
                }
            ]
        }
        """

        try:
            data = json.loads(mock_json_data)
            tenders = data.get("tenders", [])
        except json.JSONDecodeError:
            self.logger.error("Failed to decode mock dataset.")
            return

        for tender in tenders:
            tender_no = tender.get("tenderNumber")
            
            self.logger.info(f"Processing regional target: {tender_no} [{tender.get('country')}]")

            tender_data = {
                "tender_number": tender_no,
                "department_name": tender.get("department"),
                "country": tender.get("country", "South Africa"),
                "title": tender.get("title"),
                "description": tender.get("description"),
                "issue_date": tender.get("datePublished"),
                "closing_date": tender.get("closingDate"),
                "source_url": tender.get("url"),
                "status": "Open",
                "compliance_requirements": tender.get("requirements")
            }

            try:
                self.supabase.table("sa_tenders").insert(tender_data).execute()
                self.logger.info(f"Successfully committed {tender_no} to the pipeline.")
            except Exception as e:
                self.logger.error(f"Database error writing {tender_no}: {e}")