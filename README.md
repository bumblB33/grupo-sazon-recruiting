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
export SCREENING_TWILIO_ACCOUNT_SID=...    # outbound: opener and nudges
export SCREENING_TWILIO_WHATSAPP_FROM=+14155238886
export SCREENING_TWILIO_OPENER_CONTENT_SID=HX...   # approved opener template; plain text fallback in sandbox
export SCREENING_DATABASE_URL=mongodb://localhost:27017/screening
```

Docker: copy `.env.example` to `.env`, fill the secrets, then `docker compose up --build`. The stack runs the API on port 8000, a sweep loop and MongoDB with a named volume. Tests also need Docker: pytest starts a throwaway `mongo:7` container and skips the repository-backed tests when no Docker socket is present.

Configuration is read from `SCREENING_*` environment variables or `.env`. See `screening_agent/config.py`.

## Run

```bash
screening-cli                        # text chat against the screening flow
uvicorn screening_agent.api.app:app  # webhook, candidates, analytics
screening-nudge                      # silence sweep for cron: nudges, then abandons
pytest                               # unit and flow tests, no LLM calls
python -m evals.run_evals            # persona evals against the live model
ruff check . && ruff format .
```

## Architecture

Code owns the node graph and the tools. The LLM owns the turn.

```
channels/   CLI, WhatsApp via Twilio (inbound webhook, outbound REST), nudge CLI (voice: planned)
    |
flow/engine.py   per-candidate lock -> dedupe -> load state -> guardrail -> graph.invoke -> save turn -> reply
    |            start_conversation (opener), sweep_silence (nudge or abandon)
flow/silence.py  pure silence policy: opener retry 24h / abandon 48h; after a reply nudge 2h, 23h / abandon 24h
    |
flow/graph.py    LangGraph: turn (one tool-calling LLM call) -> apply_tools
    |            tools exposed = fields still missing from the current stage onward
flow/transitions.py   Pydantic validation, hard stops, zone matching, single qualify rule
domain/          CandidateProfile, enums, service areas, language detection
storage/         MongoDB: one candidate document (recruiter fields, engine state, version, transcript), events (append-only)
api/             FastAPI: /webhook/whatsapp (Twilio form POST, TwiML reply), POST /candidates (opener), /candidates, /candidates/{id}, PATCH override, /analytics
evals/           personas, code-based graders on final JSON and outcome
```

## Key design decisions

- **One LLM call per candidate message.** The model calls a recording tool and writes its reply in the same turn. Code validates the tool arguments, advances the stage, and swaps the tool set.
- **Structural guardrails.** The model cannot ask about experience before the licence check because that tool is not exposed yet.
- **Code-owned closing messages.** Re-asks, confirmations, disqualifications and the qualified message are fixed text per language, so compliance wording never depends on the model.
- **Two automated stops only.** No licence and out of service area. Everything ambiguous goes to `needs_recruiter_review`.
- **Idempotent inbound.** Inbound message, new state and reply are written in one conditional update on the candidate document, keyed on the provider message id. A redelivered webhook returns `duplicate`; a failed turn leaves no dedupe entry, so the retry is processed.
- **Tool gating is enforced twice.** Only the current stage's tools are bound to the model, and a call to any other tool is rejected when applied. Allowed tools are recomputed after each accepted call, so one message can answer several questions. Model misuse of a tool re-asks the current question and is never counted against the candidate.
- **Candidate-local dates.** "Today" for start dates and the prompt is the calendar day in the candidate's service-area timezone, not the server's.
- **One document per candidate.** MongoDB holds recruiter fields, engine state, silence timing and transcript together, so a turn is one atomic update without a replica set. Events are a separate append-only collection.
- **Fail-closed API.** Recruiter routes and the webhook return 503 until their secrets are configured, unless `SCREENING_DEV_MODE` is on. The summary LLM call runs as a background task after the reply.
- **Guardrail fails open.** One structured-output classification before each turn. A classifier outage allows the message and logs an event; it never blocks a candidate.
- **Silence is a cron sweep.** No long-lived timers. `screening-nudge` reads opener time, last candidate message and nudges sent, decides nudge or abandon, and runs under the same per-candidate lock as the webhook.
- **Provider is configuration.** `SCREENING_LIVE_MODEL` takes any `provider:model` id supported by LangChain. The default is a placeholder until the bake-off runs.

Process design: `docs/process-design.md`.

## Status

Working: domain validators, LangGraph flow, CLI, SQLite storage, FastAPI routes with key auth and webhook signature check, post-outcome summary, guardrail classifier, WhatsApp opener and nudges via Twilio REST, silence sweep with `abandoned`, tests with fakes for all of it. Not yet built: voice channel, recruiter UI, Logfire tracing, model bake-off, full persona set. Service areas are fixture data. Per-candidate locking is process-local; cross-process writes (api vs sweep containers) are guarded by a version check on the candidate document, and the loser re-reads.

## Sample conversations

To be added from real runs after the model bake-off.
