# GrowthOS QA report

Run: 2026-10-10 01:29 · 3s · LLM `mock` · media `mock` · email forced to `mock`

**127 / 127 checks passed.** All agents behaved as expected.

Open the same data in the app:

- Owner app: `qa-owner-20261010012914@growthos-qa.example` / `qa-password-123`
- Customer portal: Business ID `GOS-GP26GL` + `dana-20261010012914@customer-qa.example`

> LLM is `mock`: agents are rule-based stand-ins. Set `LLM_PROVIDER=gemini` or `openai` with a key and re-run `python -m app.qa_check` to test the real models against the same expectations.

## Sample agent outputs (from this run)

### Research → Northgate Physio

```text
{
  "company_summary": "Northgate Physio is a healthcare provider running 6 physiotherapy clinics with 140 employees. They opened two new clinics this year and are hiring 12 physiotherapists.",
  "industry": "Healthcare",
  "company_size": "about 140 employees",
  "relevant_signals": [
    "They opened two new clinics this year and are hiring 12 physiotherapists."
  ],
  "sources": [
    {
      "claim": "Northgate Physio is a healthcare provider running 6 physiotherapy clinics with 140 employees. They opened two new clinics this year and are hiring 12 physiotherapists.",
      "url": "user-notes"
    },
    {
      "claim": "They opened two new clinics this year and are hiring 12 physiotherapists.",
      "url": "user-notes"
    }
  ],
  "confidence": 0.3
}
```

### Research → BrightPath Dental Group

```text
{
  "company_summary": "BrightPath Dental Group is a healthcare group of dental clinics with 60 employees. They launched a new pediatric clinic in September.",
  "industry": "Healthcare",
  "company_size": "about 60 employees",
  "relevant_signals": [
    "They launched a new pediatric clinic in September."
  ],
  "sources": [
    {
      "claim": "BrightPath Dental Group is a healthcare group of dental clinics with 60 employees. They launched a new pediatric clinic in September.",
      "url": "user-notes"
    },
    {
      "claim": "They launched a new pediatric clinic in September.",
      "url": "user-notes"
    }
  ],
  "confidence": 0.3
}
```

### Research → Riverside Medical Center

```text
{
  "company_summary": "Riverside Medical Center is an outpatient healthcare clinic with 300 staff. They announced an expansion of their day-surgery unit.",
  "industry": "Healthcare",
  "company_size": "about 300 employees",
  "relevant_signals": [
    "They announced an expansion of their day-surgery unit."
  ],
  "sources": [
    {
      "claim": "Riverside Medical Center is an outpatient healthcare clinic with 300 staff. They announced an expansion of their day-surgery unit.",
      "url": "user-notes"
    },
    {
      "claim": "They announced an expansion of their day-surgery unit.",
      "url": "user-notes"
    }
  ],
  "confidence": 0.3
}
```

### Research → Harborview Family Practice

```text
{
  "company_summary": "Harborview Family Practice is a healthcare clinic with 45 employees and two locations.",
  "industry": "Healthcare",
  "company_size": "about 45 employees",
  "relevant_signals": [],
  "sources": [
    {
      "claim": "Harborview Family Practice is a healthcare clinic with 45 employees and two locations.",
      "url": "user-notes"
    }
  ],
  "confidence": 0.3
}
```

### Research → Lumen Software Studio

```text
{
  "company_summary": "Lumen Software Studio is a software agency with 45 employees building mobile apps. They are hiring 3 engineers.",
  "industry": "Software",
  "company_size": "about 45 employees",
  "relevant_signals": [
    "They are hiring 3 engineers."
  ],
  "sources": [
    {
      "claim": "Lumen Software Studio is a software agency with 45 employees building mobile apps. They are hiring 3 engineers.",
      "url": "user-notes"
    },
    {
      "claim": "They are hiring 3 engineers.",
      "url": "user-notes"
    }
  ],
  "confidence": 0.3
}
```

### Outreach draft → Northgate Physio

```text
Subject: Idea for Northgate Physio

Hi Morgan,

I came across Northgate Physio and noticed that they opened two new clinics this year and are hiring 12 physiotherapists.
QA Clinic Supplies provides PureAir 500 and PureAir 900 purifiers, filters, installation and annual maintenance, built around one idea: clean, quiet air that improves patient comfort and reduces workload for facility teams.

Would you be open to a 15-minute call next week to see if this is relevant?

Best,
Riley from QA Clinic Supplies
```

### Outreach draft → BrightPath Dental Group

```text
Subject: Idea for BrightPath Dental Group

Hi Sam,

I came across BrightPath Dental Group and noticed that they launched a new pediatric clinic in September.
QA Clinic Supplies provides PureAir 500 and PureAir 900 purifiers, filters, installation and annual maintenance, built around one idea: clean, quiet air that improves patient comfort and reduces workload for facility teams.

Would you be open to a 15-minute call next week to see if this is relevant?

Best,
Riley from QA Clinic Supplies
```

### Outreach draft → Riverside Medical Center

```text
Subject: Idea for Riverside Medical Center

Hi Alex,

I came across Riverside Medical Center and noticed that they announced an expansion of their day-surgery unit.
QA Clinic Supplies provides PureAir 500 and PureAir 900 purifiers, filters, installation and annual maintenance, built around one idea: clean, quiet air that improves patient comfort and reduces workload for facility teams.

Would you be open to a 15-minute call next week to see if this is relevant?

Best,
Riley from QA Clinic Supplies
```

### Outreach draft → Harborview Family Practice

```text
Subject: Idea for Harborview Family Practice

Hi Pat,

I came across Harborview Family Practice and noticed that Harborview Family Practice is a healthcare clinic with 45 employees and two locations.
QA Clinic Supplies provides PureAir 500 and PureAir 900 purifiers, filters, installation and annual maintenance, built around one idea: clean, quiet air that improves patient comfort and reduces workload for facility teams.

Would you be open to a 15-minute call next week to see if this is relevant?

Best,
Riley from QA Clinic Supplies
```

### Email Intelligence: “Sounds interesting — can we set up a call next week?”

```text
INTERESTED — The contact replied: "Sounds interesting — can we set up a call next week?"
Recommended: Reply promptly and propose meeting times.
```

### Email Intelligence: “Please stop emailing me.”

```text
UNSUBSCRIBE — The contact asked to stop receiving emails.
Recommended: Do not contact this person again.
```

### Email Intelligence: “What would 20 units cost, and how fast can you deliver?”

```text
ASKED_QUESTION — The contact replied: "What would 20 units cost, and how fast can you deliver?"
Recommended: Answer their question personally.
```

### Follow-up draft → Harborview Family Practice

```text
Subject: Re: Idea for Harborview Family Practice

Hi Pat,

Following up on my note about Harborview Family Practice. I saw that Harborview Family Practice is a healthcare clinic with 45 employees and two locations, so I thought this might be timely: clean, quiet air that improves patient comfort and reduces workload for facility teams.

Would a short call be useful?

Best,
Riley from QA Clinic Supplies
```

### Support AI: “How often should I replace the HEPA filter?”

```text
Replace the HEPA filter every 6 months.
```

### Lifecycle message (portal)

```text
Need help setting up your PureAir 500?

Hi Dana, your PureAir 500 should have arrived recently. If you need any help with setup, the Product Support assistant in your portal can answer questions from the official documentation, or you can message us directly.

QA Clinic Supplies
```

### Social image post — Spotlight: PureAir 500

```text
This week we're spotlighting the PureAir 500. Commercial HEPA purifier for rooms up to 50 m2. Learn more at https://qa-clinic-supplies.example.
#PureAir500 #Healthcare
```

### Social video post — Spotlight: PureAir 500

```text
A quick look at the PureAir 500. Commercial HEPA purifier for rooms up to 50 m2. Tell us what you think in the comments. Learn more at https://qa-clinic-supplies.example.
#PureAir500 #Healthcare
```

## All checks

| Area | Check | Result |
| --- | --- | --- |
| Setup | test business, products, knowledge, campaign, 6 prospects and a customer created | ✅ pass |
| Orchestrator | “Run the full growth cycle with all agents” → Run the full growth cycle | ✅ pass |
| Orchestrator | “Find high-quality customers for our business” → Find & qualify new customers | ✅ pass |
| Orchestrator | “Research and qualify the new prospects” → Find & qualify new customers | ✅ pass |
| Orchestrator | “Prepare personalized outreach for this campaign” → Find & qualify new customers | ✅ pass |
| Orchestrator | “Follow up with leads who haven't replied” → Follow up with silent leads | ✅ pass |
| Orchestrator | “Process due follow-ups now” → Follow up with silent leads | ✅ pass |
| Orchestrator | “Triage the inbox and escalate anything important” → Triage the inbox | ✅ pass |
| Orchestrator | “Analyze new replies” → Triage the inbox | ✅ pass |
| Orchestrator | “What needs my attention today?” → Brief me on pending decisions | ✅ pass |
| Orchestrator | “Summarize pending approvals” → Brief me on pending decisions | ✅ pass |
| Orchestrator | “Check in with existing customers” → Check in with existing customers | ✅ pass |
| Orchestrator | “Send warranty expiry reminders” → Check in with existing customers | ✅ pass |
| Orchestrator | “Create this week's social media posts” → Create this week's social posts | ✅ pass |
| Orchestrator | “Make a promo image and video for our page” → Create this week's social posts | ✅ pass |
| Orchestrator | “Analyze campaign performance and learn what works” → Analyze performance & learn | ✅ pass |
| Orchestrator | “Give me a performance report” → Analyze performance & learn | ✅ pass |
| Orchestrator | unknown command is refused, not guessed | ✅ pass |
| Orchestrator | Find-customers run used Research, Qualification, Outreach and Safety agents | ✅ pass |
| Research Agent | Northgate Physio: research produced | ✅ pass |
| Research Agent | Northgate Physio: industry recognised as healthcare | ✅ pass |
| Research Agent | BrightPath Dental Group: research produced | ✅ pass |
| Research Agent | BrightPath Dental Group: industry recognised as healthcare | ✅ pass |
| Research Agent | Riverside Medical Center: research produced | ✅ pass |
| Research Agent | Riverside Medical Center: industry recognised as healthcare | ✅ pass |
| Research Agent | Harborview Family Practice: research produced | ✅ pass |
| Research Agent | Lumen Software Studio: research produced | ✅ pass |
| Research Agent | software agency recognised as software (not marketing) | ✅ pass |
| Research Agent | no information → no invented facts or sources | ✅ pass |
| Qualification Agent | Northgate Physio: qualified as expected (score 90) | ✅ pass |
| Qualification Agent | Northgate Physio: score is explained (breakdown present) | ✅ pass |
| Qualification Agent | BrightPath Dental Group: qualified as expected (score 90) | ✅ pass |
| Qualification Agent | BrightPath Dental Group: score is explained (breakdown present) | ✅ pass |
| Qualification Agent | Riverside Medical Center: qualified as expected (score 90) | ✅ pass |
| Qualification Agent | Riverside Medical Center: score is explained (breakdown present) | ✅ pass |
| Qualification Agent | Harborview Family Practice: qualified as expected (score 84) | ✅ pass |
| Qualification Agent | Harborview Family Practice: score is explained (breakdown present) | ✅ pass |
| Qualification Agent | Lumen Software Studio: not qualified as expected (score 30) | ✅ pass |
| Qualification Agent | Lumen Software Studio: score is explained (breakdown present) | ✅ pass |
| Qualification Agent | Quietly Holdings: not qualified as expected (score 20) | ✅ pass |
| Qualification Agent | Quietly Holdings: score is explained (breakdown present) | ✅ pass |
| Outreach Agent | Northgate Physio: personalised draft written | ✅ pass |
| Outreach Agent | Northgate Physio: no template placeholders | ✅ pass |
| Outreach Agent | Northgate Physio: mentions the company | ✅ pass |
| Outreach Agent | Northgate Physio: signed by the sender | ✅ pass |
| Outreach Agent | Northgate Physio: no invented offers, guarantees or social proof | ✅ pass |
| Human Approval | Northgate Physio: draft is waiting in the Approval Center | ✅ pass |
| Safety Agent | Northgate Physio: draft passed safety checks before review | ✅ pass |
| Outreach Agent | BrightPath Dental Group: personalised draft written | ✅ pass |
| Outreach Agent | BrightPath Dental Group: no template placeholders | ✅ pass |
| Outreach Agent | BrightPath Dental Group: mentions the company | ✅ pass |
| Outreach Agent | BrightPath Dental Group: signed by the sender | ✅ pass |
| Outreach Agent | BrightPath Dental Group: no invented offers, guarantees or social proof | ✅ pass |
| Human Approval | BrightPath Dental Group: draft is waiting in the Approval Center | ✅ pass |
| Safety Agent | BrightPath Dental Group: draft passed safety checks before review | ✅ pass |
| Outreach Agent | Riverside Medical Center: personalised draft written | ✅ pass |
| Outreach Agent | Riverside Medical Center: no template placeholders | ✅ pass |
| Outreach Agent | Riverside Medical Center: mentions the company | ✅ pass |
| Outreach Agent | Riverside Medical Center: signed by the sender | ✅ pass |
| Outreach Agent | Riverside Medical Center: no invented offers, guarantees or social proof | ✅ pass |
| Human Approval | Riverside Medical Center: draft is waiting in the Approval Center | ✅ pass |
| Safety Agent | Riverside Medical Center: draft passed safety checks before review | ✅ pass |
| Outreach Agent | Harborview Family Practice: personalised draft written | ✅ pass |
| Outreach Agent | Harborview Family Practice: no template placeholders | ✅ pass |
| Outreach Agent | Harborview Family Practice: mentions the company | ✅ pass |
| Outreach Agent | Harborview Family Practice: signed by the sender | ✅ pass |
| Outreach Agent | prompt injection in prospect notes is ignored (no 90% discount / guarantee) | ✅ pass |
| Research Agent | injected instruction removed from the research brief | ✅ pass |
| Outreach Agent | Harborview Family Practice: no invented offers, guarantees or social proof | ✅ pass |
| Human Approval | Harborview Family Practice: draft is waiting in the Approval Center | ✅ pass |
| Safety Agent | Harborview Family Practice: draft passed safety checks before review | ✅ pass |
| Outreach Agent | Lumen Software Studio: no email written for a lead that is not qualified | ✅ pass |
| Outreach Agent | Quietly Holdings: no email written for a lead that is not qualified | ✅ pass |
| Safety Agent | email with a banned phrase cannot be sent | ✅ pass |
| Safety Agent | nothing reached the outbox | ✅ pass |
| Human Approval | approved & sent 4 of 4 drafts through can_send() | ✅ pass |
| Email | mock outbox received exactly the approved emails | ✅ pass |
| Follow-up Agent | follow-ups were scheduled for each sent email | ✅ pass |
| Email Intelligence | “Sounds interesting — can we set up a cal…” classified as INTERESTED | ✅ pass |
| Follow-up Agent | Northgate Physio: follow-ups stop after a reply | ✅ pass |
| Email Intelligence | “Sounds interesting — can we se…” has a summary and a recommended action | ✅ pass |
| Email Intelligence | “Please stop emailing me.…” classified as UNSUBSCRIBE | ✅ pass |
| Follow-up Agent | BrightPath Dental Group: follow-ups stop after a reply | ✅ pass |
| Email Intelligence | “Please stop emailing me.…” has a summary and a recommended action | ✅ pass |
| Safety Agent | unsubscribe reply suppresses the contact | ✅ pass |
| Email Intelligence | “What would 20 units cost, and how fast c…” classified as ASKED_QUESTION/INTERESTED | ✅ pass |
| Follow-up Agent | Riverside Medical Center: follow-ups stop after a reply | ✅ pass |
| Email Intelligence | “What would 20 units cost, and …” has a summary and a recommended action | ✅ pass |
| Human escalation | interested / pricing replies escalated to the owner with a reason | ✅ pass |
| Follow-up Agent | silent lead gets a follow-up draft | ✅ pass |
| Follow-up Agent | follow-up has no placeholders | ✅ pass |
| Follow-up Agent | follow-up makes no invented claims (e.g. 'many teams tell us…') | ✅ pass |
| Human Approval | follow-up draft is in the Approval Center | ✅ pass |
| Follow-up Agent | Northgate Physio (replied) got no follow-up | ✅ pass |
| Follow-up Agent | BrightPath Dental Group (replied) got no follow-up | ✅ pass |
| Follow-up Agent | Riverside Medical Center (replied) got no follow-up | ✅ pass |
| Forget Me | contact data erased and contact suppressed | ✅ pass |
| Access Agent | unregistered email gets no code (same message, no enumeration) | ✅ pass |
| Access Agent | wrong Business ID gets no code | ✅ pass |
| Access Agent | registered customer gets a one-time code | ✅ pass |
| Access Agent | code signs the customer in | ✅ pass |
| Product Support AI | answers from the manual (6 months) and cites the source | ✅ pass |
| Product Support AI | refuses to guess when the docs don't cover it | ✅ pass |
| Email Intelligence (customer) | routine question auto-answered from the knowledge base | ✅ pass |
| Email Intelligence (customer) | complaint + refund escalated RED to a human | ✅ pass |
| Warranty check | in-warranty claim marked likely eligible and sent for human review | ✅ pass |
| Service | service request waits for the owner to confirm a time | ✅ pass |
| Privacy | portal never exposes internal fields | ✅ pass |
| Lifecycle (Follow-up Agent) | a due lifecycle message was delivered (by this run or the worker) | ✅ pass |
| Lifecycle (Follow-up Agent) | message is in the customer's portal, no placeholders | ✅ pass |
| Lifecycle (Follow-up Agent) | frequency limit: no second message in the same week | ✅ pass |
| Social Content Agent | one image post and one video post for this week | ✅ pass |
| Social Content Agent | image post: caption, hashtags and theme written | ✅ pass |
| Media (Nano Banana / Veo) | image media generated (mock-image) | ✅ pass |
| Social Content Agent | image post waits for approval (never auto-published) | ✅ pass |
| Social Content Agent | video post: caption, hashtags and theme written | ✅ pass |
| Media (Nano Banana / Veo) | video media generated (mock-storyboard) | ✅ pass |
| Social Content Agent | video post waits for approval (never auto-published) | ✅ pass |
| Safety Agent | banned phrase in a social caption is flagged | ✅ pass |
| Analytics | emails sent metric matches what was really sent | ✅ pass |
| Analytics Agent | insights generated and stored in shared memory | ✅ pass |
| Shared Memory | insights are readable by other agents | ✅ pass |
| Orchestrator | full growth cycle ran all 7 stages | ✅ pass |
| Orchestrator | every stage reports what it did or why not | ✅ pass |
| Orchestrator | no stage failed | ✅ pass |
| LLM runs | every agent call logged (28 runs: analytics, email_intelligence, followup, lifecycle, outreach, qualification, reply_analysis, research, social, support) | ✅ pass |
| LLM runs | no agent call failed validation | ✅ pass |
