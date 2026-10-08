# GrowthOS architecture

GrowthOS is one backend, one worker, one PostgreSQL database and one React frontend.
There are no microservices, no vector database and no custom models.

```text
React (Vite) ──HTTP/JSON──► FastAPI (app.main) ──► PostgreSQL ◄── Worker (app.worker)
                                 │                                    │
                                 └──────── services / agents ─────────┘
                                                │
                                   LLMService ──► LLMProvider (openai | mock)
                                   ResearchTools ──► website fetcher (+ Tavily search)
                                   EmailProvider ──► resend | mock
```

## Who is responsible for what

| Concern | Owner |
| --- | --- |
| Reasoning, summarizing, classifying, writing | LLM (through `LLMService`) |
| Auth, org isolation, state, scheduling, sending | Backend |
| **Whether an email may be sent** | `services/safety.py::can_send` (pure database rules) |
| Opt-out / Forget Me enforcement | `services/suppression.py` + deterministic `services/opt_out.py` |
| Lead score | `services/scoring.py` (fixed weights over the agent's evidence-backed ratings) |

The LLM never decides whether anything is allowed. It only produces content, which is
schema-validated and checked by deterministic rules before it is used.

## Multi-agent design: one LLM, many roles

```text
                 Orchestrator (services/orchestrator.py)
                 │ decides next step, skips finished steps, never sends
      ┌──────────┼──────────────┐
  Research   Qualification   Outreach
      └──────────┼──────────────┘
             Follow-up  ◄── worker, when a follow-up is due and allowed
          Reply Analysis ◄── worker / API, when a reply arrives
             Analytics  ◄── on demand, over deterministic metrics
```

Each agent (`services/agents/*.py`) is a versioned prompt (`services/llm/prompts/<name>_v1.txt`)
plus an output schema (`services/agents/schemas.py`), optional tools, and deterministic checks.
All of them share the same `LLMService`:

1. Builds the request: the prompt file + the JSON input + the output's JSON Schema.
2. Retries transient errors (timeout, rate limit) with backoff.
3. Validates the output with Pydantic and the agent's own validator.
4. If the output is invalid, retries **once** with a correction message. If it is still invalid,
   the run fails. Corrupted data is never used.
5. Writes an `agent_runs` row: agent, prompt version, model, redacted input and output, status,
   attempts, latency and error.

Deterministic guards inside the agents:

- **Research:** cited source URLs must be among the fetched evidence URLs. With no evidence,
  industry and size must be `unknown`, signals stay empty, and confidence is capped at 0.3.
  Instruction-like sentences in fetched web text are dropped.
- **Qualification:** the agent cannot give a positive rating to a criterion the research marks
  as unknown. The backend computes the score.
- **Outreach / Follow-up:** the email must have no template placeholders, a bounded length, and
  no email addresses. Every `personalization_used` item must be backed by the research.
- **Analytics:** every number in the narrative must appear in the metrics.

## Email lifecycle

```text
DRAFT ─approve─► APPROVED ─send─► SENT ─webhook─► DELIVERED
  ▲  edit resets      │  └─send_at─► SCHEDULED ─worker─┘      │
  └───────────────────┘                                       ├─reply─► REPLIED
FAILED (provider error, retryable)                            └─sequence ends─► COMPLETED
SUPPRESSED (contact opted out / forgotten before sending)
```

`emails` has a unique `(campaign_id, contact_id, sequence_number)` constraint, so one sequence
step maps to one row. Sending locks the row (`SELECT … FOR UPDATE`), so duplicate requests
cannot double-send. The email id is also passed to the provider as an idempotency key.

## Follow-ups

Sending step *n* creates a `followups` row for step *n+1*, due after `followup_delay_days`.
The worker picks up due rows and does the following:

- **Cancels** the row if the contact is suppressed, has replied, the lead is disabled, or the
  campaign is completed.
- **Waits** while the campaign is paused (the row stays pending until resume).
- **Closes the sequence** (`LIMIT_REACHED`, emails → `COMPLETED`) when *n+1* > `max_followups`.
- **Otherwise** has the Follow-up Agent write a DRAFT. In automated mode the draft is approved
  and sent, still through `can_send`.

## Forget Me

Suppression is stored as a SHA-256 hash of the normalized email address in `suppression_records`.
Forget Me then:

1. Upserts the suppression record.
2. Marks the contact suppressed and unsubscribed.
3. Cancels pending follow-ups and sets unsent emails to `SUPPRESSED`.
4. Cancels queued jobs for the lead or contact.
5. Erases the contact's name, role and email, plus the email, draft and reply content.
6. When no other contact remains on the lead: deletes the research and clears the agent-run payloads.

Lead creation and `can_send` both check the hash. Erasing profile data can therefore never make
the person contactable again.

## Background jobs

The `jobs` table is the queue. The worker claims jobs with `FOR UPDATE SKIP LOCKED`, retries
retryable failures with exponential backoff, and requeues jobs that a crashed worker left
`RUNNING`. Job types:

- `process_lead` (orchestrator pipeline)
- `analyze_reply`
- `send_scheduled_email`
- `generate_insights`

The worker also processes due follow-ups on every tick.

## Data model

```text
organizations ─┬─ users
               ├─ business_profiles (1:1)
               ├─ suppression_records (hash only)
               └─ campaigns ─ leads ─┬─ contacts
                                     ├─ research_results
                                     ├─ email_drafts (immutable agent output)
                                     ├─ emails (editable, stateful)
                                     ├─ email_replies
                                     └─ followups
agent_runs, jobs (operational)
```

Every tenant table carries `organization_id`. API lookups go through
`services.common.get_owned()`, so another organization's id behaves exactly like a missing one (404).
