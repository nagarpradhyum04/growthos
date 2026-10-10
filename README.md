# GrowthOS

**An AI operating system for business growth and customer relationships.**
The lifecycle runs Lead → Outreach → Conversion → Purchase → Support → Warranty → Service → Retention →
Analytics → Learning.

> AI handles the routine. AI identifies the important. Humans control important business decisions.

- Specialist agents do the work, coordinated by an **Orchestrator** that owns workflow state and traces
  every step.
- **Shared memory** gives the agents context.
- A **Safety Agent / policy layer** that is independent of the LLM keeps them responsible.
- An **approvals inbox** escalates only what matters, and always says why.
- **Analytics insights** are stored in memory and reused by future workflows.
- **Social Studio** drafts one static image post and one short video post for your social page every
  week (Nano Banana images, Veo videos). Each one waits for your approval and is never auto-published.

The sales core (unchanged from the MVP) acts as an AI growth team that:

1. **Researches** a lead from public evidence and cites its sources.
2. **Qualifies** the lead with an explainable, rule-computed score.
3. **Drafts** a personalized email that uses only facts the research verified.
4. Lets a **human review**, edit, approve and **send** it.
5. **Tracks** replies and delivery.
6. **Follows up** automatically when nobody replies, up to a configurable limit.
7. **Stops immediately** on a reply, an unsubscribe, a paused campaign or a **Forget Me** request.
8. Shows basic **campaign analytics** and AI insights.

There is one LLM behind all the specialized agents and the orchestrator. The LLM writes and
classifies; the backend enforces every business rule. See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

```text
backend/    FastAPI API, worker, agents, LLM service, Alembic migrations, tests, evals
frontend/   React + Vite dashboard
docs/       Architecture notes
```

## Quick start (local, no API keys needed)

The defaults use clearly separated **mock adapters**: `LLM_PROVIDER=mock` and `EMAIL_PROVIDER=mock`.
The whole product runs offline. Switch to real providers whenever you are ready.

### 1. Prerequisites

You need Python 3.11+, Node 20+, and PostgreSQL 14+ (or Docker).

```bash
docker compose up -d          # Postgres on :5432 with databases growthos and growthos_test
```

### 2. Configuration

```bash
cp .env.example .env          # edit as needed; .env is git-ignored
```

### 3. Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
alembic upgrade head                     # create the schema
uvicorn app.main:app --reload --port 8000
```

API docs are at http://localhost:8000/docs.

### 4. Worker

Start the worker in a second terminal (same virtualenv). It handles follow-ups, reply analysis,
scheduled sends and pipeline jobs.

```bash
cd backend && python -m app.worker
```

### 5. Frontend

```bash
cd frontend
npm install
npm run dev                              # business app:     http://localhost:5173 (proxies /api → :8000)
npm run dev:portal                       # customer portal:  http://localhost:5174 (same API + database)
```

The customer portal is a **separate app** on its own port. To sign in, a customer enters:

1. The **Business ID** the owner shares, shown on the owner's Customers and Settings pages (e.g. `GOS-AVYKQQ`).
2. Their email address.

An **Access Agent** checks the request. It confirms that the Business ID exists, that the email is on
that business's customer list, that the customer hasn't opted out, and that the request rate is
reasonable. It then emails a one-time 6-digit code. With `EMAIL_PROVIDER=mock`, the code is shown on
screen for local demos.

The check is rule-based on purpose, because granting access to customer data is a security decision.
Every attempt shows up in the owner's agent trace. The response never reveals whether an email is
registered.

### 6. Try the flow

1. Create an account. You land on **Business Profile**: describe what you sell, plus your
   target industries and company sizes.
2. Create a **Campaign**. For a quick demo, set *Days between follow-ups* to `0`.
3. Add a **Lead** with a website (or notes).
4. On the lead page, click **Run full pipeline**: Research → Qualify → Draft.
5. **Review & send**: edit the draft, approve it, then send it. The safety check panel shows
   why a send would be blocked.
6. Log a reply on the lead page, or wait for the worker to generate a follow-up draft.
7. Try **Forget Me**: outreach stops, personal data is erased, and the address can never be
   re-imported.

## Full product demo (business owner + customer)

Load the demo dataset, a fictional business called "Nimbus Air":

```bash
cd backend && python -m app.demo_seed
```

It inserts plain records only: prospects, products, documentation, and one customer. It does not
fabricate agent output, metrics or traces; those come from actually running the agents.

| Role | Login |
| --- | --- |
| Business owner (http://localhost:5173) | `demo@growthos.example` / `demo-password` |
| Customer portal (http://localhost:5174) | Business ID printed by the seed + `customer@growthos.example` (code shown on screen in mock mode) |

Keep the worker running for the goal workflow, follow-ups and lifecycle messages.

1. **Owner → Command Center:** type a command or click a suggestion. The Orchestrator understands
   these commands, and several can run at once, each with its own trace:
   - *Find high-quality customers*
   - *Follow up with leads who haven't replied*
   - *Triage the inbox*
   - *What needs my attention today?*
   - *Check in with existing customers*
   - *Analyze performance and learn*

   A live preview shows which workflow your text maps to. Anything it can't map safely is refused
   with suggestions. For *Find high-quality customers*, the Orchestrator fans out to one lead workflow
   per prospect. The workflow page shows
   the live orchestration flow and agent trace:
   - Research, Qualification and Outreach run on every prospect.
   - The Safety Agent checks each draft.
   - Drafts are routed to human review.

   In the demo data, 3 prospects qualify and 2 do not get contacted.
2. **Approvals:** every card explains *why* it needs you. *Approve & send* goes through `can_send()`.
3. **A reply arrives:** on a lead, log *"We'd like to order 20 units — could you do a 10% discount?"*.
   - Email Intelligence classifies it **YELLOW** and escalates it, quoting the detected
     discount/purchase intent.
   - A *"thanks!"* reply stays GREEN and is not escalated.
4. **Win the deal:** on the lead, click *Convert to customer* and grant portal access.
5. **Customer → portal (http://localhost:5174):** the customer signs in with the Business ID and their
   email, sees their products with warranty status, and does the following:
   - Asks the Support AI *"What does error E2 mean?"* and gets an answer that cites the manual.
   - Asks something that isn't documented. The AI answers *"I couldn't find that information…"*.
   - Submits a warranty claim, books a repair, and sends a complaint, which is escalated **RED**.
6. **Owner → Warranty & Service:** the page shows the deterministic eligibility check and the
   relevant policy text. Approve the claim, confirm the appointment, and run lifecycle follow-ups,
   which respect preferences and frequency limits.
7. **Analytics:** the funnel, email-intelligence mix and lifecycle metrics are shown. *Generate
   insights* stores learnings in **Shared Memory**.
8. **Run another goal:** its trace shows *"Read shared memory: N learned insight(s)…"*, so the next
   Outreach run uses what was learned.

## Hackathon demo script (sales flow)

The UI is built to make the multi-agent system visible. *Agents reason and recommend;
deterministic backend rules and human approval control what the system may do.*

**Demo 1: a good lead.** Keep the worker running.

1. Add a lead with a website or notes, e.g. *"Acme Logistics is a logistics software company with
   120 employees. They are hiring 5 account executives."*
2. Click **▶ Run full pipeline**. The **Orchestration workflow** and **Agent activity** panels
   update live from the real `agent_runs` rows: status, result, duration and time for each step.
3. **Research intelligence** shows the evidence, sources, and every unverifiable field as
   *Unknown*. Facts used in the email are marked **✓ used in email**.
4. **Explainable qualification** shows the per-criterion points (e.g. 30/30, 20/20, 0/30, 20/20)
   and the total versus the threshold. The score comes from fixed backend weights, not from the LLM.
5. **Email Review** shows the flow *AI drafted → Human review → Safety gate → Send*, the AI
   confidence, the evidence used, and the live `can_send()` checklist. The actions are
   **Edit draft**, **Approve & Send** and **Reject**.
6. Log a reply such as *"Sounds interesting — could we do a call Thursday?"*:
   - The Reply Analysis Agent classifies it as **INTERESTED**.
   - The follow-up is stopped by rule.
   - The Replies page explains what was detected, what is recommended, and what the backend did.
7. **Analytics** updates the funnel, the reply mix and the campaign comparison. *Generate
   insights* runs the Analytics Agent on those numbers only.

**Demo 2: GrowthOS knows when not to act.** Add a lead with no website and no notes. Research
returns *Unknown* everywhere, the score is low (20/100), Outreach shows **Blocked**, and no email
is written. Pause the campaign on a lead with a draft to see **SEND BLOCKED** with the exact
reason.

## Roles

- **Owners** sign in to the business app and use every business endpoint.
- **Customers** sign in only through the customer portal (Business ID + email code) and can only call
  `/portal/*`. The owner login rejects customer accounts.

This is enforced server-side: owner endpoints return 403 for customer tokens and vice versa. Every
portal query is scoped to the customer bound to the token. Portal responses never include lead
scores, tiers, agent reasoning, campaign data or other customers.

## Using real providers

| Purpose | Settings |
| --- | --- |
| LLM (OpenAI) | `LLM_PROVIDER=openai`, `OPENAI_API_KEY=…`, optionally `LLM_MODEL=…` (default `gpt-4o-mini`) |
| Email (Resend) | `EMAIL_PROVIDER=resend`, `EMAIL_API_KEY=…`, `EMAIL_FROM_ADDRESS="You <you@yourdomain.com>"` |
| Web search (Tavily) | `SEARCH_PROVIDER=tavily`, `SEARCH_API_KEY=…` (the lead's own website is always fetched) |
| Webhooks | `WEBHOOK_SECRET=…`, sent by your provider as the `X-Webhook-Secret` header |
| Social media (Gemini) | `MEDIA_PROVIDER=gemini`, `GEMINI_API_KEY=…`; optionally `GEMINI_IMAGE_MODEL` (default `gemini-2.5-flash-image`, "Nano Banana") and `GEMINI_VIDEO_MODEL` (default `veo-3.1-generate-preview`) |

To add another LLM provider, implement `LLMProvider.complete_json` in
`backend/app/services/llm/` and register it in `build_provider()`. Agents don't change.

**Inbound replies:** point your inbound-email provider at `POST /webhooks/inbound-email` with
`{organization_id, from_address, subject, body, message_id}`. Delivery events go to
`POST /webhooks/email-status`. Both endpoints are idempotent.

## Social Studio (weekly promotion posts)

Each week GrowthOS drafts **one static image post and one short video post** for the business page.

1. The **Social Content Agent** (prompt `social_v1`) picks a theme it hasn't used recently and writes
   captions, hashtags, an on-image headline and prompts for the image and video models. It may use
   only the business profile and product catalogue. Deterministic checks reject invented offers,
   prices, numbers and absolute claims ("guaranteed", "#1") that the business never stated.
2. The **Safety Agent** checks your banned phrases and each platform's caption limits. A flagged post
   is marked *Needs review* and can't be approved until you fix it.
3. The **media provider** renders the media. With `MEDIA_PROVIDER=gemini` it calls Nano Banana
   (`gemini-2.5-flash-image`) for the image and Veo (polled long-running operation) for an ~8-second
   9:16 video. In mock mode the previews are clearly labelled SVG placeholders built from the real
   captions. A media failure is reported as *Failed* with the provider's error; nothing is faked.
4. Both posts go to the **Human Approval Center** and **Social Studio**. There you can edit,
   regenerate the media, approve or reject. Approved posts can be downloaded together with their
   caption. GrowthOS never publishes to a social network.

The worker queues this automatically once per business per week (`SOCIAL_AUTO_WEEKLY=true`; toggle
per business in *Settings & Rules*). You can also run it on demand: type *"Create this week's social
media posts"* in the Command Center or click *Generate* in Social Studio. Approved and rejected posts
are never overwritten. Media files are stored in `MEDIA_DIR` (default `backend/media/`, gitignored)
and served only to the business owner.

## Checking your API keys

```bash
cd backend
python -m app.check_providers                 # one tiny real request per configured provider
python -m app.check_providers --media         # also generate one real test image (uses Gemini quota)
python -m app.check_providers --send-test-email you@example.com
```

The command reports OK, WARN or FAIL for the LLM, the Gemini key, social media generation, email, web research
and secrets, and says what to change for anything that fails. Gemini keys from Google AI Studio (`AIza…`) and
Vertex AI express-mode keys (`AQ.…`) both work. The right endpoint is chosen automatically, or you can set
`GEMINI_BACKEND`.

## Business rules (always enforced by the backend)

Every send passes `can_send()` in `backend/app/services/safety.py`. It blocks the send when:

- the contact is suppressed or unsubscribed, or a suppression record exists for their email hash
- the campaign is paused or completed, or the lead is disabled
- the email is not approved, was already sent, or the previous step was never sent
- the follow-up limit is reached (`MAX_FOLLOWUPS`, default 2, overridable per campaign)
- the same person already received this step in this campaign (duplicate prevention), or they
  replied

Replies are handled in two layers:

- **Deterministic first:** any reply cancels pending follow-ups immediately. Opt-out language
  (*unsubscribe*, *stop emailing me*, *forget me*, *delete my data*…) suppresses the contact
  before the LLM runs. The LLM can never downgrade that decision.
- **Agent second:** the Reply Analysis Agent classifies the reply. If it says `UNSUBSCRIBE`,
  the contact is suppressed too.

Initial emails always need human approval. Automatic follow-up sending is an organization setting
and still goes through `can_send()`.

## Testing

```bash
cd backend
TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/growthos_test pytest
```

Tests run against a real PostgreSQL database (`growthos_test`) with mock adapters. They cover:

- **Business rules:** suppressed, unsubscribed and hash-only suppression; paused campaign;
  follow-up limit; duplicates; approval; provider failure and retry.
- **LLMService:** schema validation, correction retry, transient retries, run logging, redaction.
- **Agents:** missing information, fabricated citations or personalization, invented analytics
  numbers, reply classification, deterministic scoring.
- **API:** auth, organization isolation, webhooks, unsubscribe links.
- **Integration:** Lead → Research → Qualify → Email → Approve → Send → Reply / Follow-ups →
  limit; Forget Me; the worker and scheduled sends.

## Evaluation (prompt / model regression)

The `backend/evals/datasets/` directory holds 60 cases:

- 10 research
- 10 qualification
- 20 outreach
- 10 follow-up
- 10 reply classification

They include insufficient information, misleading third-party data, prompt injection, private
details, strong and weak leads, competitors, closed companies, positive and negative replies,
questions, out-of-office, unsubscribe and Forget Me. Duplicate contacts and suppression are
business rules, so pytest covers them.

```bash
cd backend
python -m evals.run_evals --provider mock      # offline baseline (also run in pytest)
python -m evals.run_evals --provider openai    # real model; run after every prompt/model change
python -m evals.run_evals --suite outreach -v
```

Results go to `backend/evals/results/` (git-ignored). The command exits non-zero when the pass
rate is below `--min-pass-rate` (default 100%).

## API overview

```text
POST /auth/register   POST /auth/login   GET /auth/me
GET|PUT /business-profile                 PATCH /organization/settings
GET|POST /campaigns    GET|PUT /campaigns/{id}   POST /campaigns/{id}/pause|resume|complete
GET|POST /leads        GET /leads/{id}
POST /leads/{id}/research | qualify | generate-email | process (queued) | disable | enable
GET /emails            GET|PUT /emails/{id}      POST /emails/{id}/approve | send | reject
GET|POST /replies      POST /replies/{id}/analyze
POST /contacts/{id}/forget | unsubscribe
GET /analytics         POST /analytics/insights
GET /agent-runs        GET /jobs/{id}            POST /followups/process
GET|POST /public/unsubscribe?token=…   (link included in every email)
POST /webhooks/inbound-email | email-status
```

GrowthOS OS layer:

```text
POST /workflows/goal {goal, campaign_id?, command?}   GET /workflows/commands   GET /workflows/route?text=
GET /workflows   GET /workflows/{id} (trace + children)   GET /trace
GET /approvals   POST /approvals/{id}/approve | reject | take-over | mark-automated
GET|POST /memory   DELETE /memory/{id}          GET|PUT /policy
POST /leads/bulk   POST /leads/{id}/convert
GET|POST /customers   GET /customers/{id}   POST /customers/{id}/purchases | portal-access | messages
GET|POST|PUT /products   GET|POST|PUT|DELETE /knowledge   POST /knowledge/search   GET /inbox
GET /warranty-claims   PATCH /warranty-claims/{id}   GET /service-requests   PATCH /service-requests/{id}
POST /lifecycle/run    GET /notifications      GET /system/status
GET /social/overview | posts   POST /social/generate {week_start?, regenerate?}
PATCH /social/posts/{id}   POST /social/posts/{id}/approve | reject | regenerate-media   GET /social/posts/{id}/media
Portal sign-in (public): POST /portal-auth/request {business_id, email}   POST /portal-auth/verify {request_id, code}
Portal: GET /portal/me | products | products/{purchase_id} | warranty | service | appointments |
        conversations | notifications    POST /portal/support/ask | warranty | service |
        service/{id}/cancel | conversations    PATCH /portal/preferences
```

Errors always come back as `{"error": {"code", "message", "details"}}`. Stack traces are logged,
never returned.

## End-to-end QA run (all agents, real data flow)

```bash
cd backend
python -m app.qa_check
```

This creates a separate test business called **QA Clinic Supplies** with:
- 6 prospects: 4 that fit the profile (one has a prompt injection hidden in its notes), 1 off-target and 1 with no information
- products, manuals, a warranty policy and an FAQ
- a customer with two purchases

It then runs every agent and the main features through the same API the UI uses:
- the Orchestrator commands
- Research, Qualification, Outreach, the Safety gate, approve & send
- Email Intelligence on replies, follow-ups, Forget Me
- portal sign-in (Access Agent), Product Support, the warranty check, service requests and lifecycle messages
- social posts with media, analytics and memory, and the full growth cycle

Each result is checked against what the agent is supposed to do. The pass/fail report and real sample outputs go to
[`docs/QA_REPORT.md`](docs/QA_REPORT.md), and the logins are printed so you can open the same data in the app.

The QA run uses your configured LLM and media providers. Email is always forced to mock, so no real email is sent.
Run it again after switching to a real model (`LLM_PROVIDER=gemini` or `openai`) to check the real model against
the same expectations. Your other businesses are not touched.

### Just the test campaign and leads

To load only the test campaign and its 6 prospects into your own business (nothing else is changed):

```bash
cd backend
python -m app.seed_test_leads --owner-email you@yourbusiness.com
```

Or in the app, open **Leads → Import prospects**, pick a campaign and paste [`docs/test_leads.txt`](docs/test_leads.txt).
Then run *"Find high-quality customers for our business"*. With a profile that targets healthcare clinics with
20-500 staff, 4 leads should qualify and get drafts in Approvals; Lumen Software Studio and Quietly Holdings should not.

## Troubleshooting

- **App feels slow on Windows:** use `127.0.0.1`, not `localhost`, for `DATABASE_URL` and
  `VITE_BACKEND_URL`. On Windows, `localhost` resolves to IPv6 `::1` first while Postgres and
  uvicorn listen on IPv4, so every connection waits for a refused IPv6 attempt.
- **"Something went wrong (ref abc123)":** search the API log for `ref abc123` to see the full
  error. Also check that migrations are current with `alembic upgrade head`.
- **Customer portal sign-in:** a customer signs in with the Business ID plus the email the owner
  registered for them. The same email can be an owner account and a customer of several businesses.

## Known limitations

- **Prospect discovery:** the Research Agent researches prospects you import (single or bulk). It
  does not crawl the web to discover new companies.
- **Replies to prospects:** Email Intelligence drafts a suggested response for escalated *prospect*
  replies, but you send it from your own inbox. Only customer-portal conversations are answered
  in-app.
- **Retrieval:** knowledge retrieval uses lexical BM25 in Postgres. `knowledge_service.retrieve()`
  is the seam for swapping in embeddings (e.g. pgvector).
- **Confidence:** agent confidence is shown only where an agent actually produces it (research,
  outreach drafts). Email tiers come from rules, not model confidence.
- **Lifecycle delivery:** lifecycle messages are delivered to the customer portal (as message and
  notification), not by email.
- **Mock adapters:** with the mock LLM adapter the agents are rule-based stand-ins, so text quality is
  basic. Run the evals with a real provider before relying on prompts.

## Deliberately out of scope

The MVP leaves out fine-tuning, voice, social *publishing* (posts are drafted and approved, then you
post them yourself) and WhatsApp automation, CRM integrations, browser
agents, vector infrastructure, billing, mobile apps and complex permissions. Open tracking is
not implemented either, and analytics reports opens as "not tracked" rather than guessing.
