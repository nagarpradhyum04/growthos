"""DEMO DATASET — `python -m app.demo_seed`

Creates a fictional business ("Nimbus Air", commercial air purifiers) with a prospect list, products,
product documentation, and one customer with portal access, so the full GrowthOS story can be demoed.
It only inserts ordinary records (as an owner would through the UI). It does NOT fabricate agent output,
research, scores, metrics or traces — those are produced by actually running the agents.

Logins created:
  owner:    demo@growthos.example     / demo-password
  customer: customer@growthos.example / demo-password
"""
from datetime import date, timedelta

from sqlalchemy import select

from app.db import session_scope
from app.models import BusinessProfile, Campaign, Organization, Product, User
from app.security import hash_password
from app.services import customer_service, knowledge_service, lead_service

OWNER_EMAIL = "demo@growthos.example"
CUSTOMER_EMAIL = "customer@growthos.example"
PASSWORD = "demo-password"

PROSPECTS = [
    ("Northgate Physio", "Morgan Blake", "Operations Director", "morgan@northgate-physio.example",
     "Northgate Physio is a healthcare provider running 6 physiotherapy clinics with 140 employees. "
     "They opened two new clinics this year and are hiring 12 physiotherapists."),
    ("BrightPath Dental Group", "Sam Ortiz", "Practice Manager", "sam@brightpath-dental.example",
     "BrightPath Dental Group is a healthcare group of dental clinics with 60 employees. "
     "They launched a new pediatric clinic in September."),
    ("Riverside Medical Center", "Alex Chen", "Facilities Lead", "alex@riverside-medical.example",
     "Riverside Medical Center is an outpatient healthcare clinic with 300 staff. "
     "They announced an expansion of their day-surgery unit."),
    ("Lumen Software Studio", "Jo Patel", "CEO", "jo@lumen-studio.example",
     "Lumen Software Studio is a software agency with 45 employees building mobile apps. They are hiring 3 engineers."),
    ("Quietly Holdings", "Rene Diaz", "Partner", "rene@quietly.example", ""),
]

AP500_MANUAL = """# Setup
Place the AP-500 on a flat surface at least 30 cm from walls. Remove the plastic wrap from the HEPA filter before first use. Plug in and press the power button for 2 seconds.

# Filter replacement
Replace the HEPA filter every 6 months. The filter indicator turns red when replacement is due. Clean the washable pre-filter monthly with a vacuum. Use only original Nimbus filters.

# Error codes
E1 means the filter is not seated correctly; reopen the back panel and press the filter in until it clicks. E2 means the fan is blocked; switch off, unplug and remove obstructions. E3 means the air-quality sensor needs cleaning with a dry cotton swab.

# Noise and coverage
The AP-500 covers rooms up to 50 square meters. Night mode runs at 24 dB.
"""
AP900_MANUAL = """# Setup
The AP-900 is a medical-grade purifier for treatment rooms. Mount the wall bracket or use the floor stand. Connect to Wi-Fi with the Nimbus Care app to receive filter alerts.

# Filters
The AP-900 uses a H13 HEPA filter plus a carbon filter. Replace both every 12 months, or sooner if the app shows 'Filter low'.

# Cleaning
Wipe the exterior with a damp cloth. Never use alcohol-based cleaners on the sensor window.
"""
FAQ = """# Ordering
Orders of 10 units or more qualify for project pricing — contact our sales team for a quote.

# Delivery
Standard delivery takes 5 business days within the country.

# Brochure
A product brochure for the AP-500 and AP-900 is available on request from our sales team.
"""
WARRANTY = """# Coverage
Nimbus purifiers are covered against manufacturing defects from the purchase date: AP-500 for 24 months, AP-900 for 36 months. Filters are consumables and are not covered.

# Exclusions
Physical damage, water damage, use of non-original filters and unauthorized repairs are not covered.

# How to claim
Submit a claim in the customer portal with the serial number and a description of the issue. Our team reviews every claim.
"""
SERVICE = """# Service visits
A technician can visit on weekdays between 8:00 and 17:00. Annual maintenance includes filter replacement, sensor calibration and a fan inspection.

# Repairs
Out-of-warranty repairs are quoted before any work starts.
"""


def run() -> None:
    with session_scope() as db:
        if db.scalar(select(User.id).where(User.email == OWNER_EMAIL)):
            print("Demo data already exists — nothing to do.")
            return
        org = Organization(name="Nimbus Air")
        db.add(org)
        db.flush()
        db.add(User(organization_id=org.id, email=OWNER_EMAIL, name="Demo Owner", password_hash=hash_password(PASSWORD)))
        db.add(BusinessProfile(
            organization_id=org.id, company_name="Nimbus Air",
            company_description="Nimbus Air supplies commercial air purifiers to clinics, practices and offices.",
            products_services="AP-500 and AP-900 commercial air purifiers, filters, installation and annual maintenance",
            target_customers="Healthcare clinics and practices with 20-500 staff",
            value_proposition="Clean, quiet air that improves patient comfort and reduces administrative workload for facility teams",
            industries=["Healthcare"], target_company_sizes=["20-500"], tone="warm, concise, professional",
            website="https://nimbus-air.example", key_differentiators="Medical-grade filtration and on-site maintenance",
            campaign_goals="Book discovery calls with clinic operations leaders", sender_name="Riley from Nimbus Air"))
        campaign = Campaign(organization_id=org.id, name="Clinics Q4", objective="Book discovery calls",
                            target_audience="Operations leaders at multi-site clinics")
        db.add(campaign)
        db.flush()
        for company, name, role, email, notes in PROSPECTS:
            lead_service.create_lead(db, org.id, campaign_id=campaign.id, company_name=company, website="",
                                     notes=notes, contact_name=name, contact_role=role, contact_email=email)

        ap500 = Product(organization_id=org.id, name="AP-500 Air Purifier", sku="AP500", category="Air purifier",
                        description="Commercial HEPA air purifier for rooms up to 50 m².", warranty_months=24, price=899)
        ap900 = Product(organization_id=org.id, name="AP-900 Medical-Grade Purifier", sku="AP900",
                        category="Air purifier", description="Medical-grade H13 purifier for treatment rooms.",
                        warranty_months=36, price=1999)
        db.add_all([ap500, ap900])
        db.flush()
        for title, doc_type, content, product in [
            ("AP-500 User Manual", "manual", AP500_MANUAL, ap500.id), ("AP-900 User Manual", "manual", AP900_MANUAL, ap900.id),
            ("Ordering & Delivery FAQ", "faq", FAQ, None), ("Warranty Policy", "warranty_policy", WARRANTY, None),
            ("Service & Repair", "service", SERVICE, None)]:
            knowledge_service.save_document(db, org.id, title=title, doc_type=doc_type, content=content, product_id=product)

        customer = customer_service.create_customer(db, org.id, name="Dana Reyes", email=CUSTOMER_EMAIL,
                                                    company="Harbor Family Clinic", phone="+1 555 0100")
        customer_service.add_purchase(db, customer, product_id=ap500.id, purchased_at=date.today() - timedelta(days=9),
                                      quantity=4, order_value=3596, serial_number="AP500-77812")
        # An older unit whose warranty is about to expire (exercises the warranty-expiry follow-up).
        customer_service.add_purchase(db, customer, product_id=ap900.id,
                                      purchased_at=customer_service.add_months(date.today(), -36) + timedelta(days=20),
                                      quantity=1, order_value=1999, serial_number="AP900-10544")
        customer_service.grant_portal_access(db, customer, PASSWORD)
    print(f"Demo data created.\n  Owner:    {OWNER_EMAIL} / {PASSWORD}\n  Customer: {CUSTOMER_EMAIL} / {PASSWORD}")


if __name__ == "__main__":
    run()
