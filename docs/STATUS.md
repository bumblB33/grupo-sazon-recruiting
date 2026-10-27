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
- Live reply policy and candidate tone detection.
- In-API silence scheduler with a sweep lease and per-nudge claims.
- Type checking. Pyright `standard` reports 49 errors and no checker runs in the dev loop.
- Voice channel (Pipecat, Deepgram STT, ElevenLabs TTS) on the same engine.

## Requirements coverage

Against `docs/Orbio-Assignment.md`. Rubric weights: technical build 40%, process design 25%, presentation 25%, bonus 10%.

| Requirement | State | Closed by |
|---|---|---|
| Phase 1 process design | `docs/process-design.md` | none |
| Screening agent, validation, JSON output, history, storage, summary, error handling | built and tested with fakes, never run live | Reply policy, live preflight |
| Recruiter tool | built: list, funnel, detail, override | Console restyle, web chat, console pages |
| LLM choice justified | not done: the bake-off has no valid run | Bake-off, model defaults, README |
| Live demo ("show, don't tell") | not possible: no live run, no web chat, mocked data | Everything up to the live preflight |
| README: setup, architecture, key decisions | present | README |
| README: potential improvements, sample conversations | missing | README |
| Demo video, 5-10 minutes | missing | Demo video |
| Bonus: multi-language with code-switching, re-engagement, tests and evals | built | none |
| Bonus: guardrails | input classifier built. Model replies are unchecked live. | Reply policy |
| Bonus: sentiment | not built | Reply policy (candidate tone) |
| Bonus: analytics | partial: counts by status and stage only | Console pages |
| Bonus: deployment design (deploy, monitor, scale) | partial: compose only | Tracing, scheduler, README |
| Bonus: voice agent | not built, optional | Voice |
| Bonus: scheduling, ATS design, RAG | not built, not planned | none |

Voice is last in this plan. Bonus features carry 10% of the rubric, and the brief rewards depth over breadth. A live WhatsApp screening with auditable decisions serves the 40% build and 25% presentation weights. A half-built voice channel adds failure risk to the live call.

## Live reply quality

Today the model's text goes to the candidate unchecked whenever no fixed template wins (`_choose_reply` in `flow/graph.py`). The tone checks exist only offline, in `evals/graders.py: style_failures`. Live interactions need them on the send path.

- One owner for the prose rules: move `style_failures` and its limits into `screening_agent` (reply policy module). Evals import it from there.
- Live rules, all deterministic and already proven offline: at most one question, at most one emoji, at most `MAX_REPLY_CHARS`, the candidate's language. Added: no markdown or bullet lists, no links.
- Not live rules: "claims to be human" and "asks for data outside the screening". A regex gives false positives ("dirección" is both address and direction), and each false positive turns a reply into a template. They go to the LLM judge in evals with the other semantic checks (warmth, promises about pay or hiring, invented job facts).
- Language check: the detector is a stopword vote, so a short reply or a proper name can misread. Only a confident mismatch fails the check. A tie passes.
- AI disclosure needs no live rule. Every channel starts with the fixed opener (`replies.opener`), which discloses the AI and the recording. The web chat starts through `start_conversation` like WhatsApp.
- On a violation the candidate gets the fixed question for the stage after this turn's patch, the same text as the last branch of `_choose_reply`. The engine records the violated rules in the turn record. The inspector and the trace show them. No second LLM call, so no added latency.
- Evals and the bake-off grade the raw model text and report the fallback rate per model. Grading the sent reply would grade the templates and hide model quality.
- Candidate tone: the guardrail call also returns `neutral`, `confused` or `frustrated` in the same structured output, so no extra call. A confused or frustrated candidate gets a simpler, calmer instruction in the turn prompt for that turn. A failed classifier means `neutral`. This changes the guardrail eval contract: add tone cases to `evals/guardrail_cases.py` and a tone gate, and check the category accuracy does not drop.
- Prompt review: rewrite `build_prompt` against `docs/process-design.md` tone rules, then confirm with the live persona run and the judge.

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

- `configure_observability(service_name)` runs only from the API lifespan and `screening-nudge`. Tests and evals never configure it. `send_to_logfire="if-token-present"`.
- The Logfire token is a `SecretStr` settings field passed to `configure(token=...)`. Logfire reads `LOGFIRE_TOKEN` from the process environment only, and pydantic-settings does not export `.env`, so without the field a local `uvicorn` run sends nothing and says nothing.
- Spans: `handle`, `guardrail`, `turn`, `summary`, `sweep`, `nudge`. Plus FastAPI, pymongo and httpx instrumentation with no bodies, headers or endpoint arguments.
- Metadata only leaves the service: keyed candidate hash, stage, outcome, model, token counts, latency. No message text, prompts, replies, phone numbers or emails.
- The candidate hash is an HMAC with a dedicated secret setting. A plain hash of a phone number can be reversed by enumerating the number space.
- HTTP spans carry the candidate id in URL paths (`/candidates/{id}`, `/recruiter/candidates/{id}`, the chat URL). A span processor rewrites URL attributes to the route template, and Logfire scrubbing gets an E.164 pattern. The exact OTel attribute names in the installed instrumentation are unverified. The no-PII test finds them.
- `/recruiter/login/.*` is excluded from FastAPI tracing, because the path holds a live login token.
- Existing log lines carry PII and, once a root handler sends them to Logfire, would leak it: the throttle warning logs the email and client IP, the send failure logs the email, and `LoggingEmailSender` logs the full login body with the link. Redact them at the call site in the tracing work. Logfire's default scrubbing patterns do not match emails.
- `uvicorn.access` does not propagate to the root logger (uvicorn's `LOGGING_CONFIG`), so access-log paths stay on stdout and out of Logfire.
- Token counts come from LangChain `usage_metadata`. The turn and the summary return an `AIMessage` that carries it. The guardrail's structured output returns a Pydantic object with no usage, so it uses `include_raw=True`.
- The no-PII test covers every span, including the HTTP, Mongo and httpx ones, and every log record.
- Monitoring alerts are not built. The README scaling section names what to alert on: guardrail failure rate, policy fallback rate, failed and unknown nudges, sweep lag.

### Silence scheduler

- An asyncio task in the API lifespan runs `sweep_silence` in a worker thread every `SCREENING_SWEEP_INTERVAL_SECONDS`, when `SCREENING_SWEEP_ENABLED` is set. The lifespan warns when it is off and the ops panel shows the state. The compose `sweep` service is removed. `api` and `mongo` get `restart: unless-stopped`.
- The task uses the cached `get_engine()` instance that serves the webhook. Per-candidate locks belong to an engine instance, so a second instance would not serialise the sweep against an inbound message in the same process.
- One sweep per interval across workers: a `sweep` lease in a `leases` collection, taken with the same single-write upsert as the login cooldown, with a TTL index on `expires_at`. `screening-nudge` and "Run sweep now" take the same lease, so a manual sweep never runs beside the scheduled one.
- At most one send per nudge: a claim is written before the send. The key is per silence episode, `nudge:{candidate}:{last_inbound_at or opened_at}:{n}`, because `nudge_count` resets to 0 on every inbound and a key on the count alone would block every nudge after the first episode. Claims carry a TTL index.
- A definite failure before Twilio accepts the message (a 4xx answer, a refused connection) releases the claim, and the next tick retries. A timeout or a lost response keeps the claim and records `nudge_unknown`, because Twilio may have sent it. A crash mid-send keeps the claim.
- Silence thresholds are wall-clock hours. A laptop that sleeps between the dry run and the call abandons in-progress candidates on the first tick after it wakes. The preflight sets short demo thresholds or runs the dry run inside the window.

## Remaining work, in order

Precondition: commit the `compose.yaml` `FORWARDED_ALLOW_IPS` change, then branch from it.

1. Type checking: add `[tool.pyright]` in `standard` mode to `pyproject.toml` and pyright to the dev dependencies. Fix the root causes first. Helpers typed `dict[str, Any]` take `ScreeningState`, a `TypedDict` with `total=False`, which is not a `dict` subtype (about 17 errors). Code reads keys that are not required, such as `state["messages"]` (about 10). Structured-output return types need narrowing (`guardrail.py`, `evals/judge.py`). Upserted `find_one_and_update` results are `Optional` to the checker. `graph.py` appends an `AIMessage` to a `list[ToolMessage]`. `tests/test_models.py` reads provider attributes off `BaseChatModel`. The `evals/results.py` mean-over-`None` report is a false positive behind an `any(... is None)` guard. The tracing and reply-policy work edits `engine.py` and `graph.py`, which hold 22 of the 49, so this comes first.
2. Tracing and the turn record, test first with `logfire.testing`. See "Tracing".
3. Reply policy and candidate tone, test first. See "Live reply quality".
4. Service areas: author the 45 locations and their aliases. See "Names and data".
5. Persona review: rewrite the eval personas as realistic candidates. See "Names and data".
6. Run the live bake-off with `--out docs`. It needs the three provider keys and a Mongo on `localhost:27017` (the compose `mongo` service does not publish a host port). It writes `docs/bakeoff.json` and `bakeoff.html`. The current files are from a failed run: both Anthropic models hit the missing `anthropic-workspace-id` header, and every OpenAI call errored. Only Mistral produced results, so they do not support a model choice. The bake-off grades raw model text and reports the policy fallback rate per model. It runs before the console work, because it closes a core requirement and the reply policy and personas change its inputs.
7. Set the `Settings` defaults for `live_model`, `summary_model` and `guardrail_model` in `screening_agent/config.py` to the winners. The current defaults are placeholders.
8. Seed the demo database with the persona run on the chosen models. See "Names and data".
9. Silence scheduler, lease and nudge claims, test first. See "Silence scheduler".
10. Console shell restyle with the Orbio tokens across every existing page.
11. Web chat and turn inspector. Delete `screening-cli`.
12. How-it-works page, ops panel, start-screening form and demo reset. Add completion rate, drop-off stage and average duration to the funnel, from `opened_at`, `updated_at` and the outcome event.
13. Live preflight on the laptop: provider keys and workspace id in `.env`, `docker compose up --build` before the call, seeded personas plus one hand-typed conversation per outcome through the web chat, Logfire token set and one trace opened from the inspector link. The `mongo-data` volume keeps these conversations between runs. Never run `docker compose down -v` before the call. Short silence thresholds or a dry run inside the window. WhatsApp leg: Twilio account and API key in `.env`, presenter's phone joined to the sandbox and in `SCREENING_DEMO_PHONES`, tunnel up, Twilio console webhook and `SCREENING_TWILIO_WEBHOOK_URL` set to `<tunnel>/webhook/whatsapp`, one full screening from the phone, then a demo reset. Read every live reply in the inspector and log each prose or tone fault as a persona or policy case before the call.
14. README deliverable sections that are missing: "Sample conversations" from live transcripts, "LLM choice" justified from `bakeoff.html`, "Potential improvements", and "Deployment and scaling" (monitoring and alerts through Logfire, the path to 10K candidates a week, the process-local lock as the first limit). Update README and CLAUDE.md for the console, tracing, reply policy and scheduler. Move the as-built parts of "Demo design" out of this file into the README.
15. Multi-lens adversarial review of the branch. Gates: pytest, ruff, pyright with no new errors.
16. Record the 5-10 minute demo video from the console: one WhatsApp screening from the phone, the turn inspector, a trace, the how-it-works page, an override.
17. Voice channel, only if time remains after the video.

## Known gaps

- Login links appear in access and proxy logs until used or expired. The token is still single use and short lived.
- Every recruiter and API key has the same rights. There are no roles or scopes.
- The bake-off cost column counts the turn model only. Guardrail, summary and judge tokens are not included.
- The guardrail latency gate default (p95 at most 2.5s) is a first guess set before any live run. Adjust from the first `bakeoff.json`.
- `llm_timeout_seconds` is a float. `langchain-mistralai` types its timeout as int. Keep it whole-numbered for Mistral runs.
- `mistralai:mistral-medium-latest` and `mistralai:mistral-small-latest` are aliases that Mistral can move to a new model and price. Pin `mistral-medium-3-5` and `mistral-small-2603` for a repeatable bake-off.

## Open questions

- Demo reset: hard delete or archive and re-key. A delete breaks the append-only event log that `docs/process-design.md` promises. Archive and re-key keeps the history under a new id and frees the phone for a new run.
- Which Pylance `typeCheckingMode` the IDE uses. `.vscode/settings.json` sets none. The plan assumes `standard`.
- Which model wins the bake-off for the live turn, the summary and the guardrail. Decided by `docs/bakeoff.html` from a valid run. The current file is from a failed run.
- Logfire trace link format and project URL for the inspector. Needs the Logfire project to exist. Until then the inspector shows the trace id only.
- Fonts: self-host Geist, Inter and IBM Plex Mono, or load them from a CDN. A CDN fails on a call with poor network and sends visitor IPs to a third party. Self-hosting needs each font licence checked first.
- Which tunnel exposes the laptop to Twilio (cloudflared or ngrok), and whether its URL is stable across restarts. A changed URL means updating the Twilio console and `SCREENING_TWILIO_WEBHOOK_URL` before the call.
- How long a Twilio sandbox join lasts, and whether the sandbox delivers the plain-text opener to a joined number with no prior inbound. Unverified. The dry run answers both.
