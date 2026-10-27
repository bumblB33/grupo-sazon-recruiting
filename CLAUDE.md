# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Take-home case study for Orbio: an AI candidate-screening agent for Grupo Sazón (restaurant chain hiring delivery drivers in Spain and Mexico). The brief is `docs/Orbio-Assignment.md`. The process design is `docs/process-design.md` (Phase 1 deliverable). Read both before adding code.

## Current state

Scaffold stage. Decisions taken 23 Oct that override the outline where they differ:
- LangGraph owns the node graph. Channels (CLI, WhatsApp via Twilio, voice) are adapters. Pipecat is a voice adapter only, added on the voice day.
- Voice is optional and comes last, after the demo video.
- Layout is `screening_agent/` per the outline. The old `src/` tree is deleted.
- The design outline is private prep material and lives outside the repo. The shippable Phase 1 deliverable is `docs/process-design.md`.

Working: domain, flow, CLI, storage, API with magic-link sessions, per-client API keys and webhook signature check, recruiter pages (`screening_agent/recruiter/`), summary, guardrail classifier, WhatsApp opener and outbound via Twilio REST, silence sweep (`screening-nudge`) that nudges and sets `abandoned`, evals and bake-off runner (`evals/`), tests for all of it with fakes. Not started: voice channel, Logfire.

Remaining work and open findings are tracked in `docs/STATUS.md`.

## Commands

Interpreter is the local venv at `.venv` (Python 3.12). Dependencies are declared in `pyproject.toml`.

```bash
source .venv/bin/activate
pip install -e ".[dev]"
pytest                              # all tests, no LLM calls
pytest tests/test_flow.py::test_no_licence_is_hard_stop
ruff check . && ruff format .
screening-cli                       # chat loop against the graph, needs PROJECT_ANTHROPIC_API_KEY or the provider's key
uvicorn screening_agent.api.app:app --reload    # needs a Mongo at SCREENING_DATABASE_URL
screening-nudge                     # silence sweep, run from cron every few minutes
screening-admin invite <email>           # also recruiters, deactivate, reactivate, create-api-key <label>, api-keys, revoke-api-key
docker compose up --build           # api + sweep + mongo
python -m evals.run_evals           # persona evals; --models a,b --judge --guardrail-models c,d --out docs for the bake-off (json, html); eval databases go to SCREENING_EVAL_DATABASE_URL, never SCREENING_DATABASE_URL
python -m evals.render_report docs/bakeoff.json   # re-render html from saved results, no LLM calls
firefox --headless --profile /tmp/ffprof --no-remote --window-size=1400,3600 --screenshot /tmp/bakeoff.png "file://$PWD/docs/bakeoff.html"   # add user_pref("ui.prefersReducedMotion", 1) (and ui.systemUsesDarkTheme) to /tmp/ffprof/user.js; no node, so no palette validator
```

Tests drive the graph with a scripted fake model (`tests/conftest.py`) that records bound tool names and model inputs. One scripted AI message is consumed per candidate message. Build a fresh `ai(...)` per turn: `add_messages` assigns an id to a message on first use, so replaying the same object replaces the earlier message instead of appending. `make_engine` injects a no-op `summarizer` and a permit-all `guardrail`; pass `guardrail=` to script blocks. API tests set `settings.dev_mode` via `monkeypatch`. Tests need Docker: `tests/conftest.py` starts one `mongo:7` test container per session and gives each test its own database. `SCREENING_TEST_DATABASE_URL` points the session at an existing MongoDB instead. Without either, every repository-backed test skips with a reason. An autouse fixture in conftest sets every secret and outbound Twilio setting to `None`, because settings also read `.env`. The `client` fixture is the API test client in dev mode. Each test gets its own database, and mongod aborts at Docker's default 1024 open files. The `repository` fixture drops its database on teardown and the test container starts with `nofile=65536`. A run of `pymongo.errors.ServerSelectionTimeoutError` errors partway through the suite means mongod died; read `docker logs` for `Too many open files`.

Verify login changes in Docker with a throwaway `docker compose -f compose.yaml -f <override outside the repo>` that sets `SCREENING_DEV_MODE`, `SCREENING_SESSION_SECRET`, `SCREENING_PUBLIC_URL`, `SCREENING_RECRUITER_EMAIL_DOMAINS`. Dev mode logs the login link instead of mailing it. Do not edit `.env`.

## Architecture

Governing decision: code owns the node graph and the tools, the LLM owns the turn.

- Screening is an explicit node graph in Python: stages, transitions, validators. Stage order is cheapest disqualifier first: consent, name, licence (hard stop), zone (hard stop), availability, schedule, experience, start date, outcome.
- Each node exposes only the tools for fields still missing. One LLM call per turn: it records data by calling a tool and its text goes to the candidate. Code validates tool args with Pydantic, advances the node, swaps the tool set. The LLM cannot skip a stage because the tool does not exist until code exposes it.
- `CandidateProfile` is the single Pydantic model. Current stage is "first required field still missing." Validation rules live in code, not prompts. `CandidateProfile.model_dump()` is the structured JSON output.
- Every channel calls `ScreeningEngine.handle(candidate_id, text, channel, external_id)` in `flow/engine.py`. It returns a `HandleResult` with outcome `replied`, `duplicate` or `closed` and a `terminal` flag. Inbound message, state and reply are saved in one transaction. A process-local lock serialises one candidate. When `terminal` is true the channel calls `engine.summarize_outcome(candidate_id)` after replying (FastAPI uses `BackgroundTasks`, CLI and evals call it inline), so the summary LLM call never delays the reply or holds the lock.
- Tool gating is enforced in `apply_tools`. Allowed tools are recomputed after each accepted call in the turn, so consent plus name in one message both land. A call to a tool still not exposed is rejected, re-asks the current stage, and is not counted as a candidate strike (model fault, not candidate fault). Only validator rejections count toward `reask_limit`.
- `qualify_if_complete` in `flow/transitions.py` is the only place that sets `qualified`. It runs after every accepted patch, so tool order within a turn does not matter.
- Replies for re-ask, zone confirmation and every terminal status are fixed templates in `flow/replies.py`, not model output. Priority: terminal, then re-ask, then zone confirm, then model text, then the next stage's question. The reply actually sent is appended to history as an AI message when it differs from the model's text.
- Graph per message: `turn` (one LLM call with the stage's tools bound) then `apply_tools` (validate, transition, pick reply). No LangGraph checkpointer; `storage/repository.py` persists the full state inside the candidate document.
- Never an automated no on a judgement call. Anything ambiguous goes to `needs_recruiter_review`.
- Guardrail (`llm/guardrail.py`) is one structured-output call before the turn, injected into `ScreeningEngine` as a callable. Categories: on_topic, off_topic, abusive, prompt_injection. It fails open: a classifier error allows the message and records a `guardrail_failed` event. A blocked message redirects once, then closes to `needs_recruiter_review` (`OFF_TOPIC_STRIKE_LIMIT`).
- Outbound without an inbound goes through `OutboundChannel` (`send_text`, `send_opener`). `channels/whatsapp.py: TwilioWhatsAppSender` posts to the Twilio Messages REST API with API key basic auth (`SCREENING_TWILIO_API_KEY_SID`/`_SECRET`, Account SID only in the URL); the opener uses `SCREENING_TWILIO_OPENER_CONTENT_SID` when set (templates are the only deliverable message outside the 24h window). `POST /candidates` opens a conversation and sends the opener; candidate id is the E.164 phone.
- Silence is a cron sweep, not a timer. `flow/silence.py: silence_action` is a pure decision over `Conversation.opened_at`, `last_inbound_at`, `nudge_count` and the `SCREENING_*_HOURS` settings. Before the first reply: opener retry at 24h, abandon at 48h. After a reply: nudges at 2h and 23h, abandon at 24h. `ScreeningEngine.sweep_silence(now, channels)` decides on a snapshot, re-checks under the candidate lock, and isolates a failed send per candidate (`nudge_failed` event). `version` on the candidate document is optimistic locking across processes: a write from an older version raises `StaleStateError`; `handle` re-runs the turn once, the sweep skips.
- Storage is one MongoDB document per candidate in `candidates`: recruiter fields, engine `state`, `version`, silence timing and the embedded `transcript` (direction, channel, body, external id). A turn is one conditional `update_one` on that document, so no multi-document transaction and no replica set is needed. `events` is a separate append-only collection. Dedupe is a `$ne` on the transcript external id in that conditional update, so a lost race across processes raises `DuplicateMessageError` from the write itself. `SCREENING_DATABASE_URL` must name the database.
- Deployment is `compose.yaml`: `api` (uvicorn), `sweep` (loops `screening-nudge` every `SWEEP_INTERVAL_SECONDS`), `mongo` with a named volume and healthcheck. Secrets come from `.env` (see `.env.example`). Nudge text is the stage's re-ask wrapped in `replies.NUDGE`. A channel with no outbound sender (CLI, evals) is only abandoned. Abandoned candidates get no summary call; the outcome event records the drop-off stage.
- Dates are judged in the candidate's calendar day, not the server's. `domain/clock.py: candidate_today(zone)` uses the service area's IANA timezone, falling back to `SCREENING_DEFAULT_TIMEZONE`. The start-date validator and the prompt's "today" both use it.
- Recruiter UI is `screening_agent/recruiter/router.py`: Jinja2 pages mounted on the API app at `/recruiter`, no JavaScript. Access is invite-only: `screening-admin invite <email>` creates the `recruiters` row (`Repository.invite_recruiter`, `$setOnInsert`, so it never lifts a deactivation), and the address must also be at a domain in `SCREENING_RECRUITER_EMAIL_DOMAINS`. Login is a one-time emailed link: `POST /recruiter/login` takes an email, accepts it when it is well formed, at an allowed domain and belongs to an active invited recruiter, takes an atomic per-address cooldown and per-IP window slot (`Repository.try_acquire_login_slot`, `login_throttles`), stores the SHA-256 of a random token in `login_tokens` (TTL index, single use via conditional update) and sends the link through Twilio SendGrid (`channels/email.py`). The link base is `SCREENING_PUBLIC_URL`; the request Host is used only in dev mode (`deps.login_base_url`). A send failure is logged and the page is unchanged. `GET /recruiter/login/{token}` only renders a confirm button (mail scanners prefetch GET); `POST /recruiter/login/{token}` consumes the token, re-checks the recruiter is active and sets an HttpOnly cookie holding an HS256 JWT (`api/auth.py`, signed with `SCREENING_SESSION_SECRET`, `SCREENING_SESSION_HOURS`, `iat` as a float timestamp, `Secure` when the public URL is https). `api/deps.py: require_recruiter` returns a `Principal` from a per-client `X-API-Key` (`<key id>.<secret>`, hash in `api_keys`, minted by `screening-admin`) or from that cookie. `auth.recruiter_from_session` (called by `deps.recruiter_from_cookie`) re-checks on every request that the recruiter is active, the domain is still allowed, and the cookie `iat` postdates `sessions_valid_after`, which `deactivate_recruiter` sets (upsert, so an address can be blocked before its first login). Page routes answer 303 to login instead of 401. The login form always answers "check your inbox" and echoes the address only when it is well formed. The override form and cookie-authenticated JSON writes carry a CSRF token (`auth.csrf_token`: HMAC of the session cookie, checked by `deps.verify_csrf` as bytes with `compare_digest`). The check is keyed on the principal: a cookie recruiter must present it and is refused when it cannot be derived; an API key or the dev-mode principal needs none, so API-key writes work without a session secret. JSON writes use `deps.require_recruiter_write`, which reads it from `X-CSRF-Token` (served by `GET /csrf-token`). `GET /candidates` pages with `limit`/`offset`. `Repository.override(..., actor)` writes the `recruiter_override` event with the actor, so the form and the PATCH route share one path. `GET /candidates/{id}` returns `CandidateDetail` with transcript and events.
- API auth fails closed. Recruiter routes need `SCREENING_SESSION_SECRET` and the login form needs SendGrid settings and `SCREENING_PUBLIC_URL`; the Twilio webhook needs `SCREENING_TWILIO_AUTH_TOKEN` (`X-Twilio-Signature`, HMAC-SHA1 over the webhook URL plus sorted form params, base64). Set `SCREENING_TWILIO_WEBHOOK_URL` when a proxy rewrites the URL Twilio signed. The webhook answers with TwiML, which is how the reply reaches the candidate. Without them the routes return 503 unless `SCREENING_DEV_MODE=true`.
- Bake-off report: `evals/results.py: BakeoffResults` is the JSON contract, `evals/html_report.py` is the view model, `evals/templates/bakeoff.html` the Jinja page. Provider errors fold into one counted line after stripping `request_id`; a model with no turns and one error renders "did not run" instead of zeros. `render_report` also rewrites `bakeoff.json`.
- Stack: Pydantic, LangGraph, FastAPI, MongoDB via pymongo, Pydantic Logfire. Voice day adds Pipecat, Deepgram STT, ElevenLabs TTS. Primary LLM chosen by a scripted bake-off, not assumed.
- Terminal statuses: `qualified`, `disqualified` (objective criteria only, with reason code, recruiter can override), `needs_recruiter_review`, `abandoned`.

Layout: `screening_agent/{domain,flow,llm,channels,storage,api,recruiter}`, plus top-level `evals/` and `tests/`.

## Conventions

- Candidate-facing text: Spanish or English per message, informal tú, one question per message, 1-2 sentences, at most one emoji. Agent discloses it is an AI.
- Graders in `evals/` score the final JSON, outcome and deterministic reply style. Wording is scored by the LLM judge in `evals/judge.py`, never by string matching.
- Model construction goes through `llm/models.py: chat_model(model_id)`. The `PROVIDERS` table sets the key and sampling parameters per provider: Anthropic and OpenAI none (current Claude and GPT-6 models reject them), Mistral temperature 0, hosted providers (Bedrock, Vertex) neither. Provider keys come from settings (`PROVIDERS`: `PROJECT_ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `MISTRAL_API_KEY`; an org-level Anthropic key also needs `PROJECT_ANTHROPIC_WORKSPACE_ID`, sent as `anthropic-workspace-id`), because pydantic-settings does not export `.env`; a missing key raises `ProviderKeyMissingError`. Settings ignore empty env assignments, so `KEY=` in `.env` counts as unset. Twilio auth token and API key secret, the SendGrid key and the session secret are `SecretStr`. Never read `ANTHROPIC_API_KEY`, Claude Code in the same terminal uses that name.
- Never build an emailed or redirect URL from the request `Host` header; take it from settings and fail closed (503) when unset outside dev mode (`deps.login_base_url`).
- Rate limits and claims use a single atomic Mongo write (`find_one_and_update` with upsert, or an upsert that collides on `_id`), never count-then-insert.
