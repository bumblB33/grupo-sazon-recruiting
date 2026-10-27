# Project status

Open work for the screening agent. The README describes the system as built. `TROUBLESHOOTING.md` holds the demo runbook and tech debt. This file tracks what is missing, what is unverified, what is deferred and what is undecided. Update it when a gap closes or a question is answered.

## Scope decision

The case study is due 27 Oct 2026 with a 5 to 10 minute video. Scope is cut to what the video needs: one WhatsApp screening from the presenter's phone, every agent decision on the recruiter candidate page with its reason, one override, and a README with every deliverable section the brief names.

Decisions taken on 27 Oct, binding:

- Web chat is dropped. There is no browser fallback if the tunnel or Twilio fails during the take. The fallback is a second take.
- The compose `sweep` service stays and covers re-engagement. The in-API scheduler is deferred.
- `screening-cli` stays. Its deletion is deferred with the console work.
- LLM choice is justified from design in the README. The failed scripted bake-off is named as is, with the provider errors, and listed first under improvements.
- Recruiter login on screen uses the real path. The login mail for the demo address is redirected to the presenter's inbox with `SCREENING_LOGIN_EMAIL_REDIRECT_TO` (dev mode only, 503 otherwise). No link on the "check your inbox" page and no dev-only listing route, because either would be a demo-only surface that the fail-closed story then has to explain. Which path runs depends on the SendGrid settings alone, not on dev mode. Runbook in `TROUBLESHOOTING.md`.
- Tunnel is the `ngrok` compose service behind the `tunnel` profile, bound to the account's fixed dev domain, so the Twilio webhook URL is pasted once. cloudflared is dropped.
- Tool exposure stays as built: every tool for a missing field from the current stage onward. The inspector shows the full exposed list, so the demo narration says this.
- Inspector shows the trace id as text. No Logfire link until a Logfire project exists.
- Fonts and shell restyle untouched.
- Demo reset, when built: archive and re-key, only for phones in a `SCREENING_DEMO_PHONES` allowlist. Design below.

## Remaining work, in order

1. WhatsApp preflight. Done: image rebuilt, compose override written outside the repo, `ngrok` service on the fixed dev domain, launcher, probes passed through the domain (200 on `/docs`, 401 on an unsigned webhook POST), login mail redirect built and proven on the stderr fallback. Pending, maintainer actions: put `SCREENING_SENDGRID_API_KEY` and a verified `SCREENING_LOGIN_EMAIL_FROM` in `.env`, paste the webhook URL into the Twilio sandbox once, join from the phone, send one message. Then one full screening. Read every reply in the inspector. Log each prose or tone fault as a persona or policy case. Fix blockers only. Commands in `TROUBLESHOOTING.md`.
2. README "Sample conversations" from the preflight transcripts, one per outcome the run produced, phone numbers replaced. Waits on the live run.
3. Record the video: phone screening beside the candidate page, the inspector on one turn with a rejected tool call or a policy fallback if the run produced one, the summary, one override.
4. Demo reset, only if time remains after the video. Then change "append-only" in `docs/process-design.md` to "append-only, except that a demo reset re-keys a candidate's events to the archive id".
5. Multi-lens adversarial review of the branch. Gates: pytest, ruff check, ruff format, pyright with no new errors.

## Requirements coverage

Against `docs/Orbio-Assignment.md`. Rubric weights: technical build 40%, process design 25%, presentation 25%, bonus 10%.

| Requirement | State | Closed by |
|---|---|---|
| Phase 1 process design | `docs/process-design.md` | none |
| Screening agent, validation, JSON output, history, storage, summary, error handling | built and tested with fakes. Stack reachable from the internet, signature check confirmed live. No live LLM turn yet | Preflight |
| Recruiter tool | built: list, funnel, detail with per-turn inspector, override | none |
| LLM choice justified | README "LLM choice": justified from design, failed bake-off named | none; re-run is the first improvement |
| Live demo ("show, don't tell") | stack up, Twilio webhook paste and sandbox join pending | Preflight |
| README: setup, architecture, key decisions, improvements | present | none |
| README: sample conversations | missing | Live run |
| Demo video, 5 to 10 minutes | missing | Video |
| Bonus: multi-language with code-switching, re-engagement, tests and evals | built | none |
| Bonus: guardrails | input classifier and live reply policy built | none |
| Bonus: sentiment | candidate tone built, untested on a live model | Bake-off |
| Bonus: analytics | partial: counts by status and stage only | deferred |
| Bonus: deployment design (deploy, monitor, scale) | compose, tracing, README "Deployment and scaling" | none |
| Bonus: voice agent | not built, optional | deferred |
| Bonus: scheduling, ATS design, RAG | not built, not planned | none |

Voice is last. Bonus features carry 10% of the rubric and the brief rewards depth over breadth. A live WhatsApp screening with auditable decisions serves the 40% build and 25% presentation weights. A half-built voice channel adds failure risk to the live call.

## Known gaps

- The mailbox login path is unverified end to end. `.env` has no `SCREENING_SENDGRID_API_KEY` or `SCREENING_LOGIN_EMAIL_FROM`, so the redirect was proven only on the stderr fallback. Until a SendGrid key and a verified sender are in `.env`, the terminal path is the demo path.
- No live LLM turn has happened. The first WhatsApp message is the first. The org key needs `PROJECT_ANTHROPIC_WORKSPACE_ID`, set in `.env`.
- No trace has been sent to a real Logfire project. The no-PII test uses an in-memory exporter.
- The guardrail tone prompt and the tone cases are untested on a live model. Category accuracy after the tone change is unverified until the bake-off runs.
- The service-area list is a 16-city fixture, not the client's 45 locations.
- Every recruiter and API key has the same rights. There are no roles or scopes.
- Monitoring alerts are not built. README "Deployment and scaling" names what to alert on.
- Prompt review is open: rewrite `build_prompt` against the tone rules in `docs/process-design.md`, then confirm with the live persona run and the judge.
- Unverified: whether the Twilio sandbox delivers the plain-text opener to a joined number with no prior inbound. The preflight answers it. If not, the candidate sends the first message. The webhook handles an unknown number as a new conversation at the consent stage (`Repository.load_state` returns `initial_state`), so the demo still runs, without the fixed opener and the AI disclosure it carries.

## Open questions

- Which model wins the bake-off for the live turn, the summary and the guardrail. Decided by `docs/bakeoff.html` from a valid run. The current file is from a failed run.
- Logfire trace link format and project URL for the inspector. Needs the Logfire project to exist.
- Fonts for the console restyle: self-host Geist, Inter and IBM Plex Mono, or load from a CDN. A CDN fails on a call with poor network and sends visitor IPs to a third party. Self-hosting needs each font licence checked first.

## Deferred past the deadline

Designs kept here so they are not re-derived. None of this is built. Settings, routes and collections named in this section do not exist in the code yet.

### Demo reset

`DemoResetService.reset(candidate_id, actor)` checks a `SCREENING_DEMO_PHONES` allowlist first, separate from any other demo flag so no real candidate can be reset, then calls `engine.archive_candidate`, which takes the per-candidate lock and calls `Repository.archive_candidate`. Standalone Mongo has no transactions, so the sequence is fenced, version-guarded and resumable:

1. Fence: pipeline `find_one_and_update` setting `archive_id` with `$ifNull` and incrementing `version`. Returns the fenced document and its version `v`. None means not found.
2. Copy: `replace_one({_id: archive_id}, copy, upsert=True)`. Copy has `archived_at`, `archived_by` and `state.candidate_id` re-keyed. The re-key is mandatory because `_commit` writes to `state["candidate_id"]`.
3. Events: `update_many({candidate_id}, {$set: {candidate_id: archive_id}})`.
4. Actor event: upsert `demo_reset` keyed on archive id and kind, `$setOnInsert` payload with the actor.
5. Delete: `delete_one({_id: candidate_id, archive_id, version: v})`. Zero matched means a writer committed after the fence. Repeat from step 1, at most twice, then raise `StaleStateError`.

A `_LIVE = {"archived_at": {"$exists": False}}` filter applies in `list_candidates` and `open_conversations`. Route `POST /candidates/{id}/reset` verifies CSRF, maps `NotResettableError` to 403, and redirects to the archived page, which shows a banner. The reset button appears only for allowlisted, unarchived candidates. The reset is not atomic: a crash between steps leaves the phone occupied until reset is pressed again. The actor is recorded and the phone stays out of logs and traces.

Without the reset, `POST /candidates` answers 409 on the second run for the same phone. The recorded take then uses a second phone number joined to the sandbox.

### Silence scheduler inside the API

- An asyncio task in the API lifespan runs `sweep_silence` in a worker thread every `SCREENING_SWEEP_INTERVAL_SECONDS` when `SCREENING_SWEEP_ENABLED` is set. The lifespan warns when it is off. The compose `sweep` service goes away. `api` and `mongo` get `restart: unless-stopped`.
- The task uses the cached `get_engine()` instance that serves the webhook, taken on the first tick, not at startup, so the API still starts without a model key. Per-candidate locks belong to an engine instance, so a second instance would not serialise the sweep against an inbound message in the same process. A failed tick is logged without candidate data and the loop continues.
- One sweep per interval across workers: a `sweep` lease in a `leases` collection, taken with the same single-write upsert as the login cooldown. The record holds two times. `held_until` stops two sweeps from overlapping. `expires_at`, the TTL field, is the later of `held_until` and the last start plus the interval, so a scheduled sweep runs at most once per interval. `screening-nudge` and a "Run sweep now" button check `held_until` only, so a manual sweep never runs beside the scheduled one. Release filters on the owner and sets `held_until` to now.
- At most one send per nudge: a claim is written before the send. The key is per silence episode, `nudge:{candidate}:{last_inbound_at or opened_at}:{n}`, because `nudge_count` resets to 0 on every inbound and a key on the count alone would block every nudge after the first episode. A claim expires at the episode's abandon time plus a margin.
- Any 4xx (429 included) and a refused or timed-out connection release the claim, and the next tick retries. A 5xx, a read timeout, a lost response or any unclassified exception keeps the claim and records `nudge_unknown`, because Twilio may have sent it. A crash mid-send keeps the claim. Twilio documents only 429 as not processed; the other 4xx cases are an inference. `TwilioWhatsAppSender` raises `DeliveryRefusedError` or `DeliveryUnknownError` for the engine to tell them apart. The existing failed-send test needs its fake sender to raise `DeliveryRefusedError`; a plain exception will count as unknown.
- On shutdown the lifespan sets a stop flag, which the sweep checks between candidates, then awaits the task. A worker thread cannot be cancelled.

### Recruiter console

Goal: every feature reachable in the browser, every agent decision on screen with a reason, every trace and architectural rule checkable against the running code.

- Web chat (`/recruiter/chat`, enabled by `SCREENING_DEMO_CHAT`). Start a new web candidate through `start_conversation` with the fixed opener, or resume one. A web candidate id is `web-` plus a random id, because there is no phone. The web outbound sender sends nothing: the page reads the opener and replies from the transcript. The sweep gets no sender for `web`, so a silent web candidate is only abandoned. Each form carries a CSRF token and a fresh `external_id`, so a resubmit dedupes through `handle`. A terminal turn queues `summarize_outcome`. Candidates whose channel is not `web` are refused, so a recruiter cannot type into a WhatsApp conversation. Web candidates appear in the candidate list with a `web` tag. The chat page never auto-refreshes, because a refresh would wipe the message being typed. A turn blocks the form post for the LLM call, with no progress indicator.
- Start a WhatsApp screening from the console: a form over the same path as `POST /candidates` (E.164 phone, language), with the CSRF check of `require_recruiter_write`, so the opener goes out from the browser, not curl.
- How-it-works page. It shows only facts the code can list at request time: stage order from `Stage`, tools exposed per stage, `reask_limit`, `OFF_TOPIC_STRIKE_LIMIT`, silence thresholds, configured models, the reply-policy rules and the guardrail fail-open rule. Validation rules appear only if the validators read them from a declared table the page also reads. No hand-written rule text in the template. Links to the README for the prose.
- Ops panel. Scheduler state (enabled or not, lease holder, last run, nudged, abandoned, failed), "Run sweep now" through the same lease, which secrets and integrations are configured (names only, never values), Logfire on or off. Recruiters and API keys show as counts only, because every recruiter has the same rights and could otherwise read every email and key id.
- Visual identity: Orbio product chrome, Grupo Sazón shown as the tenant. Tokens from the `--ui-*` set on orbioai.co/platform: background `#edefe8`, panel `#fcfdf9`, surface `#fff`, text `#1e2418` / `#555c4a` / `#858c78`, border `#dde0d4` / `#b8bda8`, agent accent `#b8e636` on `#f0f7d8`, brand `#2f3f22`, status success `#3d7254`, warning `#7a5f17`, error `#b83232`, info `#316692`. Fonts: Geist (display), Inter (body), IBM Plex Mono (data). The layout is original; only the tokens are shared. Tokens live in one CSS block in `base.html`, no page sets a raw colour. Status mapping: qualified to success, disqualified to error, needs_recruiter_review to warning, abandoned to text-3, in_progress to info. Self-hosted fonts and any other static files need a `StaticFiles` mount and a package-data glob in `pyproject.toml`; today package data covers only `templates/*.html`.
- Pages stay server-rendered. Each action is a form post followed by a redirect.
- `screening-cli` is deleted once the web chat exists. `screening-admin` stays for invites and API keys. `screening-nudge` stays as a manual one-shot trigger.
- Analytics series: completion rate, drop-off stage and average duration, from timestamps the documents already carry. Needs an index on events `(kind, created_at)`.

### Names and data

Grupo Sazón is fictional, so every name, location and persona is ours to define.

- Author the 45 service areas across Spain and Mexico, with local aliases and IANA timezones, in `domain/service_areas.py`. This replaces the 16-city fixture.
- The assistant name (`SCREENING_ASSISTANT_NAME`, now `Sazón`) can be changed for the demo.
- Rewrite the eval personas as realistic candidates: typos, slang from both countries, one-word answers, voice-note style run-ons, questions back to the agent, code-switching, a frustrated candidate and a confused one.
- Demo dataset: run the personas live through the engine into the demo database as `web` candidates with a `seed-` id prefix. The command takes the database URL as a required argument with no default. It does not reuse `SCREENING_EVAL_DATABASE_URL`, and evals still never write to the app database. Seeded conversations finish in seconds, so analytics exclude the `seed-` prefix from duration and drop-off, or show it as a separate series. Before the live seed, inventory what is in the demo database and where it came from. Delete only after approval.

### Live bake-off

Re-run `python -m evals.run_evals` with the workspace header fixed, then set the model defaults in `config.py` from the result. Adjust the guardrail latency gate default (p95 at most 2.5 s, a first guess) from the first valid `bakeoff.json`.

### Voice

Pipecat as a voice adapter on the same engine, with Deepgram STT and ElevenLabs TTS. The engine takes text and returns text, so no screening logic changes.
