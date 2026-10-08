# GrowthOS

GrowthOS is a small multi-agent growth operating system. It acts as an AI growth team that:

1. **Researches** a lead from public evidence and cites its sources.
2. **Qualifies** the lead with an explainable, rule-computed score.
3. **Drafts** a personalized email that uses only facts the research verified.
4. Lets a **human review**, edit, approve and **send** it.
5. **Tracks** replies and delivery.
6. **Follows up** automatically when nobody replies, up to a configurable limit.
7. **Stops immediately** on a reply, an unsubscribe, a paused campaign or a **Forget Me** request.
8. Shows basic **campaign analytics** and AI insights.

There is one LLM behind six specialized agents and an orchestrator. The LLM writes and
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
npm run dev                              # http://localhost:5173 (proxies /api → :8000)
```

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

## Using real providers

| Purpose | Settings |
| --- | --- |
| LLM (OpenAI) | `LLM_PROVIDER=openai`, `OPENAI_API_KEY=…`, optionally `LLM_MODEL=…` (default `gpt-4o-mini`) |
| Email (Resend) | `EMAIL_PROVIDER=resend`, `EMAIL_API_KEY=…`, `EMAIL_FROM_ADDRESS="You <you@yourdomain.com>"` |
| Web search (Tavily) | `SEARCH_PROVIDER=tavily`, `SEARCH_API_KEY=…` (the lead's own website is always fetched) |
| Webhooks | `WEBHOOK_SECRET=…`, sent by your provider as the `X-Webhook-Secret` header |

To add another LLM provider, implement `LLMProvider.complete_json` in
`backend/app/services/llm/` and register it in `build_provider()`. Agents don't change.

**Inbound replies:** point your inbound-email provider at `POST /webhooks/inbound-email` with
`{organization_id, from_address, subject, body, message_id}`. Delivery events go to
`POST /webhooks/email-status`. Both endpoints are idempotent.

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
TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/growthos_test pytest
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
GET /emails            GET|PUT /emails/{id}      POST /emails/{id}/approve | send
GET|POST /replies      POST /replies/{id}/analyze
POST /contacts/{id}/forget | unsubscribe
GET /analytics         POST /analytics/insights
GET /agent-runs        GET /jobs/{id}            POST /followups/process
GET|POST /public/unsubscribe?token=…   (link included in every email)
POST /webhooks/inbound-email | email-status
```

Errors always come back as `{"error": {"code", "message", "details"}}`. Stack traces are logged,
never returned.

## Deliberately out of scope

The MVP leaves out fine-tuning, voice, social and WhatsApp automation, CRM integrations, browser
agents, vector infrastructure, billing, mobile apps and complex permissions. Open tracking is
not implemented either, and analytics reports opens as "not tracked" rather than guessing.
