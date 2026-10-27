# Project status

Moving state for the screening agent. The README describes the system as built. This file tracks what is done, what is missing, what is unverified and what is undecided. Update it when a gap closes or a question is answered.

## Built and tested

- Domain validators and `CandidateProfile`.
- LangGraph flow: tool gating, transitions, fixed replies, single qualify rule.
- CLI chat channel.
- MongoDB storage: one document per candidate, append-only events, database-level dedupe, version check across processes.
- FastAPI routes with magic-link sessions, per-client API keys and Twilio webhook signature check.
- Recruiter pages with filters, funnel and override. Invite-only login, session revocation on deactivate, confirm-button login links, CSRF on the override form and on cookie-authenticated JSON writes.
- Post-outcome summary as a background task.
- Guardrail classifier that fails open.
- WhatsApp opener and nudges via Twilio REST.
- Silence sweep (`screening-nudge`) that nudges, then sets `abandoned`.
- Evals and bake-off runner.
- Tests with fakes for all of the above. The full suite, including the Mongo-backed tests, passes with no LLM calls.

## Not built

- Live demo console: web chat, turn inspector, how-it-works page, ops panel, Orbio-styled shell.
- Logfire tracing and the per-turn decision record.
- In-API silence scheduler with a sweep lease and per-nudge claims.
- Voice channel (Pipecat, Deepgram STT, ElevenLabs TTS) on the same engine.

## Requirements coverage

Against `docs/Orbio-Assignment.md`. Rubric weights: technical build 40%, process design 25%, presentation 25%, bonus 10%.

| Requirement | State | Closing step |
|---|---|---|
| Phase 1 process design | `docs/process-design.md` | none |
| Screening agent, validation, JSON output, history, storage, summary, error handling | built and tested with fakes, never run live | 6 |
| Recruiter tool | built: list, funnel, detail, override | 3 to 5 make it demo-ready |
| LLM choice justified | not done: the bake-off has no valid run | 7, 8, 9 |
| Live demo ("show, don't tell") | not possible: no live run, no web chat | 1 to 6 |
| README: setup, architecture, key decisions | present | 9 updates them |
| README: potential improvements, sample conversations | missing | 9 |
| Demo video, 5-10 minutes | missing | 11 |
| Bonus: multi-language with code-switching, guardrails, re-engagement, tests and evals | built | none |
| Bonus: analytics | partial: counts by status and stage only | 5 |
| Bonus: deployment design (deploy, monitor, scale) | partial: compose only | 1, 2, 9 |
| Bonus: voice agent | not built | 12 |
| Bonus: sentiment, scheduling, ATS design, RAG | not built, not planned | none |

Voice is last. Bonus features carry 10% of the rubric, and the brief rewards depth over breadth. A live WhatsApp screening with auditable decisions serves the 40% build and 25% presentation weights. A half-built voice channel adds failure risk to the live call.

## Demo design

Goal: a live demo on a call. Every feature is reachable in the browser. Every agent decision on screen has a reason. Every trace and architectural rule can be checked against the running code.

### Decisions

- The recruiter console is the only demo surface. `screening-cli` is deleted. `screening-admin` stays for invites and API keys. `screening-nudge` stays as a manual one-shot trigger.
- Visual identity: Orbio product chrome, Grupo Sazón shown as the tenant. Tokens come from the `--ui-*` set on orbioai.co/platform: background `#edefe8`, panel `#fcfdf9`, surface `#fff`, text `#1e2418` / `#555c4a` / `#858c78`, border `#dde0d4` / `#b8bda8`, agent accent `#b8e636` on `#f0f7d8`, brand `#2f3f22`, status success `#3d7254`, warning `#7a5f17`, error `#b83232`, info `#316692`. Fonts: Geist (display), Inter (body), IBM Plex Mono (data). The layout is original. Only the tokens are shared.
- Tokens live in one CSS block in `base.html`. No page sets a raw colour.
- Status mapping: qualified to success, disqualified to error, needs_recruiter_review to warning, abandoned to text-3, in_progress to info.
- Pages stay server-rendered with no JavaScript. Each action is a form post followed by a redirect.
- The demo runs on the presenter's laptop with `docker compose`, presented over screen share. No public hosting.
- WhatsApp is shown live with the presenter's own phone as the candidate, through the Twilio sandbox and a tunnel to the laptop. Web chat is the fallback if the tunnel or Twilio fails on the call.

### Surfaces

- Web chat (`/recruiter/chat`, enabled by `SCREENING_DEMO_CHAT`). Start a new web candidate or resume one. Each form carries a CSRF token and a fresh `external_id`, so a resubmit dedupes through `handle`. A terminal turn queues `summarize_outcome`. Candidates whose channel is not `web` are refused, so a recruiter cannot type into a WhatsApp conversation. Web candidates appear in the candidate list with a `web` tag.
- Turn inspector, beside the chat and on the candidate page. Per turn: stage before and after, guardrail category, tools exposed, tools called with accept or reject and the validator message, reply source (terminal, re-ask, zone confirm, model text, next question), model, tokens, latency, Logfire trace link. Source: a new `turn` event written by the engine with the turn. In-app it may show message text, because the transcript already holds it.
- How-it-works page. Generated from code at request time, so it cannot drift: stage order from `Stage`, tools exposed per stage, validation rules, `reask_limit`, `OFF_TOPIC_STRIKE_LIMIT`, silence thresholds, configured models, guardrail fail-open rule. Links to the README for the prose. It does not copy it.
- Start a WhatsApp screening from the console: a form over the same path as `POST /candidates` (E.164 phone, language), so the opener goes out from the browser, not curl.
- Demo reset, enabled only by `SCREENING_DEMO_CHAT`: delete one candidate document and its events so the presenter's phone can be screened again. The candidate id is the phone, so without a reset `POST /candidates` answers 409 on the second run. Each reset writes a `demo_reset` log line with the actor.
- Ops panel. Scheduler state (lease holder, last run, nudged, abandoned, failed), "Run sweep now" through the same lease, read-only recruiters and API keys, which secrets and integrations are configured (names only, never values), Logfire on or off.

### Tracing

- `configure_observability(service_name)` runs only from the API lifespan and `screening-nudge`. Tests and evals never configure it. `send_to_logfire="if-token-present"`.
- Spans: `handle`, `guardrail`, `turn`, `summary`, `sweep`, `nudge`. Plus FastAPI, pymongo and httpx instrumentation with no bodies, headers or endpoint arguments.
- Metadata only leaves the service: hashed candidate id, stage, outcome, model, token counts, latency. No message text, prompts, replies, phone numbers or emails.
- `/recruiter/login/.*` is excluded from FastAPI tracing, because the path holds a live login token.
- Token counts come from LangChain `usage_metadata`, so every bake-off provider is covered by one code path.

### Silence scheduler

- An asyncio task in the API lifespan runs `sweep_silence` in a worker thread every `SCREENING_SWEEP_INTERVAL_SECONDS`, when `SCREENING_SWEEP_ENABLED` is set. The compose `sweep` service is removed. `api` gets `restart: unless-stopped`.
- One sweep per interval across workers: a `sweep` lease in a `leases` collection, taken with the same single-write upsert as the login cooldown.
- At most one send per nudge: a `nudge:{candidate}:{n}` claim is written before the send and released when the send raises. A crash mid-send keeps the claim, so that nudge is never resent.

## Remaining work, in order

Precondition: commit the open auth and CSRF work, then branch from it.

1. Tracing and the `turn` event, test first with `logfire.testing`. Assert span names, attributes and that no text, phone or email appears in any attribute.
2. Silence scheduler, lease and nudge claims, test first.
3. Console shell restyle with the Orbio tokens across every existing page.
4. Web chat and turn inspector. Delete `screening-cli`.
5. How-it-works page, ops panel, start-screening form and demo reset. Add completion rate, drop-off stage and average duration to the funnel, from `opened_at`, `updated_at` and the outcome event.
6. Live preflight on the laptop: provider keys and workspace id in `.env`, `docker compose up --build` before the call, one real conversation per outcome through the web chat so the list and funnel hold real data, Logfire token set and one trace opened from the inspector link. The `mongo-data` volume keeps these conversations between runs. WhatsApp leg: Twilio account and API key in `.env`, presenter's phone joined to the sandbox, tunnel up, Twilio console webhook and `SCREENING_TWILIO_WEBHOOK_URL` set to `<tunnel>/webhook/whatsapp`, one full screening from the phone, then a demo reset.
7. Run the live bake-off with `--out docs`. It needs the three provider keys and a Mongo on `localhost:27017` (the compose `mongo` service does not publish a host port). It writes `docs/bakeoff.json` and `bakeoff.html`. The current files are from a failed run: both Anthropic models hit the missing `anthropic-workspace-id` header, and every OpenAI call errored. Only Mistral produced results, so they do not support a model choice.
8. Set the `Settings` defaults for `live_model`, `summary_model` and `guardrail_model` in `screening_agent/config.py` to the winners. The current defaults are placeholders.
9. README deliverable sections that are missing: "Sample conversations" from the bake-off transcripts, "LLM choice" justified from `bakeoff.html`, "Potential improvements", and "Deployment and scaling" (monitoring through Logfire, the path to 10K candidates a week, the process-local lock as the first limit). Update README and CLAUDE.md for the console, tracing and scheduler.
10. Multi-lens adversarial review of the branch.
11. Record the 5-10 minute demo video from the console: one WhatsApp screening from the phone, the turn inspector, a trace, the how-it-works page, an override.
12. Voice channel, only if time remains after 11. See "Requirements coverage" for why it is last.

## Known gaps

- Login links appear in access and proxy logs until used or expired. The token is still single use and short lived.
- Every recruiter and API key has the same rights. There are no roles or scopes.

- The live provider runs have not been executed. No model output has been observed end to end.
- Service areas in `domain/service_areas.py` are fixture data keyed by bare city name, not the client's 45 locations.
- The bake-off cost column counts the turn model only. Guardrail, summary and judge tokens are not included.
- The guardrail latency gate default (p95 at most 2.5s) is a first guess set before any live run. Adjust from the first `bakeoff.json`.
- `llm_timeout_seconds` is a float. `langchain-mistralai` types its timeout as int. Keep it whole-numbered for Mistral runs.
- `mistralai:mistral-medium-latest` and `mistralai:mistral-small-latest` are aliases that Mistral can move to a new model and price. Pin `mistral-medium-3-5` and `mistral-small-2603` for a repeatable bake-off.

## Open questions

- Which model wins the bake-off for the live turn, the summary and the guardrail. Decided by `docs/bakeoff.html`, not yet produced.
- Where the client's real list of 45 service areas comes from, and in what format. Blocks replacing the fixture data.
- Logfire trace link format and project URL for the inspector. Needs the Logfire project to exist. Until then the inspector shows the trace id only.
- Fonts: self-host Geist, Inter and IBM Plex Mono, or load them from a CDN. A CDN fails on a call with poor network and sends visitor IPs to a third party. Self-hosting needs each font licence checked first.
- Which tunnel exposes the laptop to Twilio (cloudflared or ngrok), and whether its URL is stable across restarts. A changed URL means updating the Twilio console and `SCREENING_TWILIO_WEBHOOK_URL` before the call.
- How long a Twilio sandbox join lasts, and whether the sandbox delivers the plain-text opener to a joined number with no prior inbound. Unverified. The dry run answers both.
- Demo reset as a hard delete or as archive and re-key. A delete breaks the append-only event log that `docs/process-design.md` promises. Archive and re-key keeps the history under a new id and frees the phone for a new run.
