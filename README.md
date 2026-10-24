# Grupo Sazón screening agent

AI candidate-screening agent for delivery-driver hiring, plus a recruiter API. Take-home for Orbio.

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
export ANTHROPIC_API_KEY=...        # or the key for the provider in SCREENING_LIVE_MODEL
export SCREENING_DEV_MODE=true      # local only: lets the API run without the two secrets below
export SCREENING_RECRUITER_API_KEY=...
export SCREENING_TWILIO_AUTH_TOKEN=...     # verifies X-Twilio-Signature on the webhook
export SCREENING_TWILIO_WEBHOOK_URL=...    # only if a proxy rewrites the URL Twilio signed
```

Configuration is read from `SCREENING_*` environment variables or `.env`. See `screening_agent/config.py`.

## Run

```bash
screening-cli                        # text chat against the screening flow
uvicorn screening_agent.api.app:app  # webhook, candidates, analytics
pytest                               # unit and flow tests, no LLM calls
python -m evals.run_evals            # persona evals against the live model
ruff check . && ruff format .
```

## Architecture

Code owns the node graph and the tools. The LLM owns the turn.

```
channels/   CLI, WhatsApp via Twilio (voice: planned)
    |
flow/engine.py   per-candidate lock -> dedupe -> load state -> guardrail -> graph.invoke -> save turn -> reply
    |
flow/graph.py    LangGraph: turn (one tool-calling LLM call) -> apply_tools
    |            tools exposed = fields still missing from the current stage onward
flow/transitions.py   Pydantic validation, hard stops, zone matching, single qualify rule
domain/          CandidateProfile, enums, service areas, language detection
storage/         SQLModel: candidates, conversations, messages, events (append-only)
api/             FastAPI: /webhook/whatsapp (Twilio form POST, TwiML reply), /candidates, /candidates/{id}, PATCH override, /analytics
evals/           personas, code-based graders on final JSON and outcome
```

## Key design decisions

- **One LLM call per candidate message.** The model calls a recording tool and writes its reply in the same turn. Code validates the tool arguments, advances the stage, and swaps the tool set.
- **Structural guardrails.** The model cannot ask about experience before the licence check because that tool is not exposed yet.
- **Code-owned closing messages.** Re-asks, confirmations, disqualifications and the qualified message are fixed text per language, so compliance wording never depends on the model.
- **Two automated stops only.** No licence and out of service area. Everything ambiguous goes to `needs_recruiter_review`.
- **Idempotent inbound.** Inbound message, new state and reply are written in one transaction, keyed on the provider message id. A redelivered webhook returns `duplicate`; a failed turn leaves no dedupe row, so the retry is processed.
- **Tool gating is enforced twice.** Only the current stage's tools are bound to the model, and a call to any other tool is rejected when applied. Allowed tools are recomputed after each accepted call, so one message can answer several questions. Model misuse of a tool re-asks the current question and is never counted against the candidate.
- **Candidate-local dates.** "Today" for start dates and the prompt is the calendar day in the candidate's service-area timezone, not the server's.
- **Fail-closed API.** Recruiter routes and the webhook return 503 until their secrets are configured, unless `SCREENING_DEV_MODE` is on. The summary LLM call runs as a background task after the reply.
- **Provider is configuration.** `SCREENING_LIVE_MODEL` takes any `provider:model` id supported by LangChain. The default is a placeholder until the bake-off runs.

Process design: `docs/process-design.md`.

## Status

Scaffold. Working: domain validators, LangGraph flow, CLI, SQLite storage, FastAPI routes with key auth and webhook signature check, post-outcome summary, flow and API tests with a scripted model. Not yet built: WhatsApp outbound outside the TwiML reply (templates, nudges), voice channel, guardrail classifier, silence timers (`abandoned`), recruiter UI, Logfire tracing, model bake-off, full persona set. Service areas are fixture data. Per-candidate locking is process-local.

## Sample conversations

To be added from real runs after the model bake-off.
