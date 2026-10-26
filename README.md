# Grupo Sazón screening agent

AI candidate-screening agent for delivery-driver hiring, plus a recruiter API. Take-home for Orbio.

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"            # add ,evals for the OpenAI and Mistral bake-off candidates
export PROJECT_ANTHROPIC_API_KEY=... # Anthropic models; not ANTHROPIC_API_KEY, which Claude Code reads
export SCREENING_DEV_MODE=true      # local only: lets the API run without the two secrets below
export SCREENING_RECRUITER_API_KEY=...    # any secret you choose, see below
export SCREENING_TWILIO_AUTH_TOKEN=...     # verifies X-Twilio-Signature on the webhook
export SCREENING_TWILIO_WEBHOOK_URL=...    # the exact URL set in the Twilio console, see below
export SCREENING_TWILIO_ACCOUNT_SID=...    # outbound: opener and nudges, used in the Messages URL
export SCREENING_TWILIO_API_KEY_SID=SK...  # outbound REST auth (API key, not the auth token)
export SCREENING_TWILIO_API_KEY_SECRET=...
export SCREENING_TWILIO_WHATSAPP_FROM=+14155238886
export SCREENING_TWILIO_OPENER_CONTENT_SID=HX...   # approved opener template; plain text fallback in sandbox
export SCREENING_DATABASE_URL=mongodb://localhost:27017/screening
```

Docker: copy `.env.example` to `.env`, fill the secrets, then `docker compose up --build`. The stack runs the API on port 8000, a sweep loop and MongoDB with a named volume. Tests also need Docker: pytest starts a throwaway `mongo:7` container and skips the repository-backed tests when no Docker socket is present.

Configuration is read from `SCREENING_*` environment variables or `.env`. See `screening_agent/config.py`.

`SCREENING_RECRUITER_API_KEY` is not a Twilio or provider value. It is a shared secret this app owns. Generate one and give it to the recruiters. They paste it in the login page at `/recruiter/login`, and API clients send it in the `X-API-Key` header.

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

`SCREENING_TWILIO_WEBHOOK_URL` is the public URL you type into the Twilio console as the WhatsApp sender's "when a message comes in" webhook, for example `https://<your-tunnel-host>/webhook/whatsapp`. Twilio signs that exact string. Set it when the app sees a different URL than Twilio called, which is the case behind a tunnel or reverse proxy, including the Docker stack behind ngrok. Leave it empty when Twilio reaches the app directly at the URL it signed.

## Run

```bash
screening-cli                        # text chat against the screening flow
uvicorn screening_agent.api.app:app  # webhook, candidates, analytics, recruiter pages at /recruiter/
screening-nudge                      # silence sweep for cron: nudges, then abandons
pytest                               # unit and flow tests, no LLM calls
python -m evals.run_evals            # persona evals against the configured models, PASS/FAIL per persona
python -m evals.run_evals --models anthropic:claude-sonnet-5-5,openai:gpt-6.1-sol,mistralai:mistral-medium-latest \
    --guardrail-models anthropic:claude-haiku-5-5,openai:gpt-6-luna --judge --report docs/bakeoff.md
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
api/             FastAPI: /webhook/whatsapp (Twilio form POST, TwiML reply), POST /candidates (opener), /candidates, /candidates/{id} (profile, summary, transcript, events), PATCH override, /analytics
recruiter/       server-rendered pages on the same app: login, candidate table with filters and funnel, detail with transcript and override form
evals/           scripted personas, code graders (final JSON, outcome, reply style), LLM judge (tone, summary), guardrail accuracy set, bake-off report
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
- **One recruiter key, two carriers.** The recruiter pages are plain HTML forms on the API app. Login stores the recruiter key in an HttpOnly cookie, and JSON routes accept either the header or the cookie.
- **Guardrail fails open.** One structured-output classification before each turn. A classifier outage allows the message and logs an event; it never blocks a candidate.
- **Silence is a cron sweep.** No long-lived timers. `screening-nudge` reads opener time, last candidate message and nudges sent, decides nudge or abandon, and runs under the same per-candidate lock as the webhook.
- **Provider is configuration.** `SCREENING_LIVE_MODEL`, `SCREENING_SUMMARY_MODEL` and `SCREENING_GUARDRAIL_MODEL` take any `provider:model` id supported by LangChain; `llm/models.py` is the single constructor. Defaults are placeholders until the bake-off writes `docs/bakeoff.md`. Provider keys come from settings, so `.env` works outside Docker too: `PROJECT_ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `MISTRAL_API_KEY`. A missing key fails closed, so a shell `ANTHROPIC_API_KEY` is never billed by accident. Anthropic ids get no sampling parameters, OpenAI and Mistral run at temperature 0, Bedrock and Vertex use their cloud credentials.
- **Evals grade outputs, the judge grades words.** Personas are scripted turns because the stage order is fixed. Code graders check the final JSON, outcome, turn count and reply style (one question, one emoji, length, language). A fixed Haiku judge scores tone and summary usefulness so the bake-off compares models on the same yardstick.

Process design: `docs/process-design.md`.

## Status

Working: domain validators, LangGraph flow, CLI, MongoDB storage, FastAPI routes with key auth and webhook signature check, recruiter pages with override, post-outcome summary, guardrail classifier, WhatsApp opener and nudges via Twilio REST, silence sweep with `abandoned`, evals and bake-off runner, tests with fakes for all of it. Not yet built: voice channel, Logfire tracing. Per-candidate locking is process-local; cross-process writes (api vs sweep containers) are guarded by a version check on the candidate document, and the loser re-reads.

Remaining work, in order:

- Run the live bake-off. It needs the three provider keys and a Mongo (Docker, or `SCREENING_TEST_DATABASE_URL`). It writes `docs/bakeoff.md`.
- Set the `Settings` model defaults in `screening_agent/config.py` to the winners.
- Fill "Sample conversations" below from the bake-off transcripts.
- Voice channel (Pipecat, Deepgram, ElevenLabs) on the same engine.
- Logfire tracing.

Unverified and known gaps:

- `mistralai:mistral-medium-latest` and `mistralai:mistral-small-latest` are aliases that Mistral can move to a new model and price. Pin `mistral-medium-3-5` and `mistral-small-2603` for a repeatable bake-off.
- The bake-off cost column counts the turn model only. Guardrail, summary and judge tokens are not included.
- `detect_language` has no vote for "hi" or "hey", so a candidate who opens with "hi" gets a Spanish reply. One-line fix in `domain/language.py`, not applied.
- `llm_timeout_seconds` is a float; `langchain-mistralai` types its timeout as int. Keep it whole-numbered for Mistral runs.
- Service areas in `domain/service_areas.py` are fixture data keyed by bare city name, not the client's 45 locations.
- The live provider runs have not been executed. The full test suite, including the Mongo-backed tests, passes.

## Sample conversations

To be added from real runs after the model bake-off.
