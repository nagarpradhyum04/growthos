"""TEST CAMPAIGN + LEADS — `python -m app.seed_test_leads [--owner-email you@example.com]`

Adds the QA test campaign ("QA Clinics") and its 6 test prospects to YOUR business (the owner account given,
or the only owner if there is just one). Nothing else is changed: no profile, no agent output, no emails.
Then run "Find high-quality customers for our business" in the Command Center to watch the agents work.

The prospects were written for a business that sells to healthcare clinics with 20-500 staff. Qualification
compares each lead with YOUR business profile, so with a different profile the expected results change.
"""
import argparse
import sys

from sqlalchemy import select

from app.db import session_scope
from app.errors import GrowthOSError
from app.models import BusinessProfile, Campaign, User
from app.qa_check import LEADS
from app.services import lead_service

CAMPAIGN = {"name": "QA Clinics", "objective": "Book discovery calls",
            "target_audience": "Operations leaders at clinics"}
EXPECTED = {"qualified": "should qualify → outreach draft → Approvals",
            "not_qualified": "should NOT qualify → no email written"}


def run(owner_email: str | None) -> int:
    with session_scope() as db:
        owners = db.scalars(select(User).where(User.role == "owner")).all()
        if owner_email:
            owner = next((u for u in owners if u.email == owner_email.lower()), None)
            if owner is None:
                print(f"No owner account with email {owner_email}.")
                return 1
        elif len(owners) == 1:
            owner = owners[0]
        else:
            print("Several owner accounts exist. Choose one with --owner-email:\n  " +
                  "\n  ".join(u.email for u in owners))
            return 1
        org_id = owner.organization_id
        campaign = db.scalar(select(Campaign).where(Campaign.organization_id == org_id, Campaign.name == CAMPAIGN["name"]))
        if campaign is None:
            campaign = Campaign(organization_id=org_id, **CAMPAIGN)
            db.add(campaign)
            db.flush()
        print(f"Business of {owner.email} → campaign “{campaign.name}”")
        for key, company, name, role, notes, expected in LEADS:
            try:
                with db.begin_nested():
                    lead_service.create_lead(db, org_id, campaign_id=campaign.id, company_name=company, website="",
                                             notes=notes, contact_name=name, contact_role=role,
                                             contact_email=f"{key}@prospect-qa.example")
                print(f"  + {company:28} {EXPECTED[expected]}")
            except GrowthOSError as exc:
                print(f"  = {company:28} skipped ({exc.message})")
        profile = db.scalar(select(BusinessProfile).where(BusinessProfile.organization_id == org_id))
        if profile and "healthcare" not in " ".join(profile.industries or []).lower():
            print("\nNote: your business profile does not target Healthcare, so these clinic leads will mostly be "
                  "scored as not qualified for YOUR business. That is correct behaviour, not a bug.")
    print("\nNext: Command Center → “Find high-quality customers for our business” (campaign: QA Clinics).")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--owner-email", help="owner account to add the test leads to")
    sys.exit(run(parser.parse_args().owner_email))
