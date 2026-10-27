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
- Pyright in `standard` mode with no errors.
- Logfire tracing with a no-PII test, and the per-turn decision record on the inbound transcript entry.
- Live reply policy with a fixed-question fallback, and candidate tone from the guardrail call.
- Tests with fakes for all of the above. The full suite, including the Mongo-backed tests, passes with no LLM calls.

## Not built

- Live demo console: web chat, turn inspector, how-it-works page, ops panel, Orbio-styled shell.
- In-API silence scheduler with a sweep lease and per-nudge claims.
- Voice channel (Pipecat, Deepgram STT, ElevenLabs TTS) on the same engine.

## Requirements coverage

Against `docs/Orbio-Assignment.md`. Rubric weights: technical build 40%, process design 25%, presentation 25%, bonus 10%.

| Requirement | State | Closed by |
|---|---|---|
| Phase 1 process design | `docs/process-design.md` | none |
| Screening agent, validation, JSON output, history, storage, summary, error handling | built and tested with fakes, never run live | Live preflight |
| Recruiter tool | built: list, funnel, detail, override | Console restyle, web chat, console pages |
| LLM choice justified | not done: the bake-off has no valid run | Bake-off, model defaults, README |
| Live demo ("show, don't tell") | not possible: no live run, no web chat, mocked data | Everything up to the live preflight |
| README: setup, architecture, key decisions | present | README |
| README: potential improvements, sample conversations | missing | README |
| Demo video, 5-10 minutes | missing | Demo video |
| Bonus: multi-language with code-switching, re-engagement, tests and evals | built | none |
| Bonus: guardrails | input classifier and live reply policy built | none |
| Bonus: sentiment | candidate tone built, untested on a live model | Bake-off |
| Bonus: analytics | partial: counts by status and stage only | Console pages |
| Bonus: deployment design (deploy, monitor, scale) | partial: compose and tracing | Scheduler, README |
| Bonus: voice agent | not built, optional | Voice |
| Bonus: scheduling, ATS design, RAG | not built, not planned | none |

Voice is last in this plan. Bonus features carry 10% of the rubric, and the brief rewards depth over breadth. A live WhatsApp screening with auditable decisions serves the 40% build and 25% presentation weights. A half-built voice channel adds failure risk to the live call.

## Live reply quality

Built. `flow/reply_policy.py` owns the rules for live replies and evals.

- Live rules, all deterministic: at most one question, at most one emoji, at most `MAX_REPLY_CHARS`, no markdown or list lines, no links, the candidate's language. Only a confident language mismatch fails; a tie passes.
- Not live rules: "claims to be human" and "asks for data outside the screening". A regex gives false positives ("dirección" is both address and direction), and each false positive turns a reply into a template. They belong to the LLM judge in evals with the other semantic checks (warmth, promises about pay or hiring, invented job facts).
- AI disclosure needs no live rule. Every channel starts with the fixed opener (`replies.opener`), which discloses the AI and the recording.
- On a violation the candidate gets the fixed question for the stage after this turn's patch, with reply source `policy_fallback`. The turn record keeps the model text and the violated rules. No second LLM call.
- Evals and the bake-off grade the raw model text and report the policy fallback rate per model.
- Candidate tone: the guardrail call returns `neutral`, `confused` or `frustrated` in the same structured output. A confused or frustrated candidate gets a calmer instruction in that turn's prompt. A failed classifier means `neutral`. The guardrail set has tone cases and a `--tone-min-accuracy` gate (default 0.8). Category accuracy on the live models is unverified until the bake-off runs.
- Prompt review is open: rewrite `build_prompt` against `docs/process-design.md` tone rules, then confirm with the live persona run and the judge.

## Names and data

Grupo Sazón is fictional, so every name, location and persona is ours to define.

- Author the 45 service areas across Spain and Mexico, with local aliases and IANA timezones, in `domain/service_areas.py`. This replaces the 16-city fixture.
- The assistant name (`SCREENING_ASSISTANT_NAME`, now `Sazón`) can be changed for the demo.
- Rewrite the eval personas as realistic candidates: typos, slang from both countries, one-word answers, voice-note style run-ons, questions back to the agent, code-switching, a frustrated candidate and a confused one.
- Demo dataset: run the personas live through the engine into the demo database as `web` candidates with a `seed-` id prefix. The command takes the database URL as a required argument with no default. It does not reuse `SCREENING_EVAL_DATABASE_URL`, and evals still never write to the app database.
- Seeded conversations finish in seconds, so analytics exclude the `seed-` prefix from duration and drop-off, or show it as a separate series.
- Before the live seed, inventory what is in the demo database now and where it came from. Delete only after approval.

## Demo design

Goal: a live demo on a call. Every feature is reachable in the browser. Every agent decision on screen has a reason. Every trace and architectural rule can be checked against the running code.

### Decisions

- The recruiter console is the only demo surface. `screening-cli` is deleted. `screening-admin` stays for invites and API keys. `screening-nudge` stays as a manual one-shot trigger.
- Visual identity: Orbio product chrome, Grupo Sazón shown as the tenant. Tokens come from the `--ui-*` set on orbioai.co/platform: background `#edefe8`, panel `#fcfdf9`, surface `#fff`, text `#1e2418` / `#555c4a` / `#858c78`, border `#dde0d4` / `#b8bda8`, agent accent `#b8e636` on `#f0f7d8`, brand `#2f3f22`, status success `#3d7254`, warning `#7a5f17`, error `#b83232`, info `#316692`. Fonts: Geist (display), Inter (body), IBM Plex Mono (data). The layout is original. Only the tokens are shared.
- Tokens live in one CSS block in `base.html`. No page sets a raw colour.
- Status mapping: qualified to success, disqualified to error, needs_recruiter_review to warning, abandoned to text-3, in_progress to info.
- Pages stay server-rendered. Each action is a form post followed by a redirect. The candidate page refreshes itself with `<meta http-equiv="refresh">` while the conversation is in progress, so WhatsApp turns appear in the inspector without a manual reload. The web chat page never auto-refreshes, because a refresh would wipe the message being typed. A web chat turn blocks the form post for the LLM call, with no progress indicator.
- Self-hosted fonts and any other static files need a `StaticFiles` mount and a package-data glob in `pyproject.toml`. Today package data covers only `templates/*.html`, and the Docker image installs with `pip install .`.
- The demo runs on the presenter's laptop with `docker compose`, presented over screen share. No public hosting.
- WhatsApp is shown live with the presenter's own phone as the candidate, through the Twilio sandbox and a tunnel to the laptop. Web chat is the fallback if the tunnel or Twilio fails on the call.

### Surfaces

- Web chat (`/recruiter/chat`, enabled by `SCREENING_DEMO_CHAT`). Start a new web candidate through `start_conversation` with the fixed opener, or resume one. A web candidate id is `web-` plus a random id, because there is no phone. The web outbound sender sends nothing: the page reads the opener and replies from the transcript. The sweep gets no sender for `web`, so a silent web candidate is only abandoned. Each form carries a CSRF token and a fresh `external_id`, so a resubmit dedupes through `handle`. A terminal turn queues `summarize_outcome`. Candidates whose channel is not `web` are refused, so a recruiter cannot type into a WhatsApp conversation. Web candidates appear in the candidate list with a `web` tag.
- Turn inspector, beside the chat and on the candidate page. Per turn: stage before and after, guardrail category and candidate tone, tools exposed, tools called with accept or reject and the validator message, reply source (terminal, re-ask, zone confirm, model text, policy fallback, next question), raw model text when it was replaced, violated rules, model, tokens, latency, keyed candidate hash, Logfire trace id or link. In-app it may show message text, because the transcript already holds it.
- The turn record is a field on the inbound transcript entry, written by the same conditional update in `save_turn`. A turn that is not saved (the `StaleStateError` re-run, a `DuplicateMessageError`, a crash) leaves no record, and a saved turn always has one. The `events` collection and its timeline are unchanged.
- How-it-works page. It shows only facts the code can list at request time: stage order from `Stage`, tools exposed per stage, `reask_limit`, `OFF_TOPIC_STRIKE_LIMIT`, silence thresholds, configured models, the reply-policy rules and the guardrail fail-open rule. Validation rules appear only if the validators read them from a declared table the page also reads. No hand-written rule text in the template. Links to the README for the prose. It does not copy it.
- Start a WhatsApp screening from the console: a form over the same path as `POST /candidates` (E.164 phone, language), with the CSRF check of `require_recruiter_write`, so the opener goes out from the browser, not curl.
- Demo reset: only for phones in a `SCREENING_DEMO_PHONES` allowlist, separate from `SCREENING_DEMO_CHAT`, so no real candidate can be reset. The candidate id is the phone, so without a reset `POST /candidates` answers 409 on the second run. Hard delete or archive and re-key is open. Either way the actor is recorded, and the phone stays out of logs and traces.
- Ops panel. Scheduler state (enabled or not, lease holder, last run, nudged, abandoned, failed), "Run sweep now" through the same lease, which secrets and integrations are configured (names only, never values), Logfire on or off. Recruiters and API keys show as counts only, because every recruiter has the same rights and could otherwise read every email and key id.

### Tracing

Built. `screening_agent/observability.py` owns it.

- `configure_observability` runs from the API lifespan and `screening-nudge`, and only when `SCREENING_LOGFIRE_TOKEN` is set. Evals never configure it. `send_to_logfire="if-token-present"`, no console output, no metrics: old-semconv HTTP duration metrics carry the raw path.
- Engine spans use the plain OpenTelemetry API, so they cost nothing and warn nothing when Logfire is not configured. Spans: `handle`, `guardrail`, `turn`, `summary`, `sweep`, `nudge`. Model and tokens use the GenAI semantic convention names. FastAPI, pymongo and httpx are instrumented with no statements, headers, bodies or endpoint arguments (`request_attributes_mapper` returns `None`; the default records argument values).
- FastAPI instrumentation patches `build_middleware_stack`, and Starlette builds the stack before the lifespan runs. `configure_observability` resets `app.middleware_stack` so the next request rebuilds it with tracing.
- Candidate ids leave URL attributes twice: a span processor at `on_start`, which covers Logfire's pending span, and the FastAPI `server_request_hook`, because ASGI sets the URL attributes again after start. The processor order relative to Logfire's pending-span processor comes from installed source, not docs. The no-PII test pins it.
- Scrubbing adds E.164 and email patterns with a callback that returns a fixed `[redacted]`. Logfire's default redaction text quotes the matched value. Scrubbing is a backstop only: Logfire never scrubs `logfire.msg`, `exception.message`, `exception.stacktrace`, `http.url`, `http.target`, `url.*` or `db.statement`, and it keeps a value that matches a pattern in full. Exception messages therefore never name the candidate (`StaleStateError`), and URLs are rewritten before export.
- `/recruiter/login/.+` is excluded from FastAPI tracing. The throttle and send-failure log lines no longer carry the email or IP. `LoggingEmailSender` prints to stderr instead of logging.
- The candidate hash is a truncated HMAC-SHA256 keyed by `SCREENING_CANDIDATE_HASH_SECRET`. Without the secret the spans carry no candidate id and the lifespan warns.
- Turn, guardrail and summary token counts come from `usage_metadata`. The guardrail uses `include_raw=True` and the summarizer returns the `AIMessage`.
- The turn record (`flow/turn_record.py`) is the `turn` field of the inbound transcript entry, written by the same conditional update as the turn. It holds stage before and after, guardrail category, tools exposed, tool calls with the validator message, reply source, replaced model text, per-call usage, latency, candidate hash and trace id. Reply policy adds violated rules and tone.
- The no-PII test (`tests/test_observability.py`) drives the API, webhook, login and recruiter pages, and checks every exported span, pending span, log record and span event for the phone, email, login token and message text. It configures Logfire in-process with an in-memory exporter. Trade-off: Logfire stays configured and pymongo, httpx and the app stay instrumented for the rest of the pytest session. Nothing is sent, because no token is set, and the suite passes in that state. A subprocess would isolate it at the cost of speed and debuggability.
- The Logfire pytest plugin is disabled in `addopts`. It exports test spans whenever `CI` and `LOGFIRE_TOKEN` are both set.
- Monitoring alerts are not built. The README scaling section names what to alert on: guardrail failure rate, policy fallback rate, failed and unknown nudges, sweep lag.

### Silence scheduler

- An asyncio task in the API lifespan runs `sweep_silence` in a worker thread every `SCREENING_SWEEP_INTERVAL_SECONDS`, when `SCREENING_SWEEP_ENABLED` is set. The lifespan warns when it is off and the ops panel shows the state. The compose `sweep` service is removed. `api` and `mongo` get `restart: unless-stopped`.
- The task uses the cached `get_engine()` instance that serves the webhook. Per-candidate locks belong to an engine instance, so a second instance would not serialise the sweep against an inbound message in the same process.
- One sweep per interval across workers: a `sweep` lease in a `leases` collection, taken with the same single-write upsert as the login cooldown, with a TTL index on `expires_at`. `screening-nudge` and "Run sweep now" take the same lease, so a manual sweep never runs beside the scheduled one.
- At most one send per nudge: a claim is written before the send. The key is per silence episode, `nudge:{candidate}:{last_inbound_at or opened_at}:{n}`, because `nudge_count` resets to 0 on every inbound and a key on the count alone would block every nudge after the first episode. Claims carry a TTL index.
- A definite failure before Twilio accepts the message (a 4xx answer, a refused connection) releases the claim, and the next tick retries. A timeout or a lost response keeps the claim and records `nudge_unknown`, because Twilio may have sent it. A crash mid-send keeps the claim.
- Design refinements from the first implementation pass, not built yet:
  - The lease record holds two times. `held_until` stops two sweeps from overlapping. `expires_at`, the TTL field, is the later of `held_until` and the last start plus the interval, so a scheduled sweep runs at most once per interval. "Run sweep now" and `screening-nudge` check `held_until` only. Release filters on the owner and sets `held_until` to now.
  - Any 4xx (429 included) and a refused or timed-out connection release the claim. A 5xx, a read timeout, a lost response or any unclassified exception keeps it and records `nudge_unknown`. Twilio documents only 429 as not processed; the other 4xx cases are an inference. `TwilioWhatsAppSender` raises `DeliveryRefusedError` or `DeliveryUnknownError` for the engine to tell them apart.
  - A claim expires at the episode's abandon time plus a margin. The episode is closed by then.
  - The scheduler gets `get_engine()` on its first tick, not at startup, so the API still starts without a model key. A failed tick is logged without candidate data and the loop continues.
  - On shutdown the lifespan sets a stop flag, which the sweep checks between candidates, then awaits the task. A worker thread cannot be cancelled.
  - The existing failed-send test needs its fake sender to raise `DeliveryRefusedError`; a plain exception will count as unknown.
- Silence thresholds are wall-clock hours. A laptop that sleeps between the dry run and the call abandons in-progress candidates on the first tick after it wakes. The preflight sets short demo thresholds or runs the dry run inside the window.

## Remaining work, in order

Decided 27 Oct: the case study is due today with a 5 to 10 minute video. Scope is cut to what the video needs. The plan is `PLAN-demo-console-and-scheduler.md`.

1. Turn inspector on the recruiter candidate page, with a meta refresh while the conversation is in progress. See "Surfaces".
2. WhatsApp preflight on the laptop: provider keys and workspace id in `.env`, `docker compose up --build`, short silence thresholds in a compose override outside the repo, tunnel up, Twilio sandbox joined, console webhook and `SCREENING_TWILIO_WEBHOOK_URL` set to `<tunnel>/webhook/whatsapp`, one full screening from the phone. Read every reply in the inspector and log each prose or tone fault as a persona or policy case.
3. README deliverable sections: "LLM choice" justified from design with the failed bake-off named, "Sample conversations" from the preflight transcripts, "Potential improvements", "Deployment and scaling". Update README and CLAUDE.md for tracing, reply policy and the inspector.
4. Record the video: phone screening beside the candidate page, the inspector, the summary, one override.
5. Demo reset (archive and re-key, `SCREENING_DEMO_PHONES`), only if time remains after the video. Then reword "append-only" in `docs/process-design.md` and the README to allow the re-key.
6. Multi-lens adversarial review of the branch. Gates: pytest, ruff, pyright with no new errors.

Deferred past the deadline, designs kept in this file: service areas and persona rewrite, the live bake-off and model defaults, demo seed data, the in-API silence scheduler with lease and nudge claims, web chat, how-it-works page, ops panel, start form, rules table, analytics series, shell restyle, `screening-cli` deletion, voice. The compose `sweep` service stays and covers re-engagement.

## Known gaps

- Login links appear in access and proxy logs until used or expired. The token is still single use and short lived.
- No trace has been sent to a real Logfire project. The no-PII test uses an in-memory exporter.
- The Docker image has not been rebuilt since `logfire[fastapi,pymongo,httpx]` was added to the dependencies.
- The guardrail tone prompt and the tone cases are untested on a live model. Category accuracy after the tone change is unverified until the bake-off runs.
- Every recruiter and API key has the same rights. There are no roles or scopes.
- The bake-off cost column counts the turn model only. Guardrail, summary and judge tokens are not included.
- The guardrail latency gate default (p95 at most 2.5s) is a first guess set before any live run. Adjust from the first `bakeoff.json`.
- `llm_timeout_seconds` is a float. `langchain-mistralai` types its timeout as int. Keep it whole-numbered for Mistral runs.
- `mistralai:mistral-medium-latest` and `mistralai:mistral-small-latest` are aliases that Mistral can move to a new model and price. Pin `mistral-medium-3-5` and `mistral-small-2603` for a repeatable bake-off.

## Open questions

- Demo reset: decided 27 Oct, archive and re-key. The re-key edits `candidate_id` on the candidate's events, so the append-only wording in `docs/process-design.md` and the README gains that one exception when reset ships.
- Which Pylance `typeCheckingMode` the IDE uses. `.vscode/settings.json` sets none. The plan assumes `standard`.
- Which model wins the bake-off for the live turn, the summary and the guardrail. Decided by `docs/bakeoff.html` from a valid run. The current file is from a failed run.
- Logfire trace link format and project URL for the inspector. Needs the Logfire project to exist. Until then the inspector shows the trace id only.
- Fonts: self-host Geist, Inter and IBM Plex Mono, or load them from a CDN. A CDN fails on a call with poor network and sends visitor IPs to a third party. Self-hosting needs each font licence checked first.
- Whether the sandbox delivers the plain-text opener to a joined number with no prior inbound. Unverified. The dry run answers it. (A sandbox join lasts three days, per Twilio's sandbox docs.)
