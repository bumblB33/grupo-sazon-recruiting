# Process design: Grupo Sazón delivery-driver screening

## Problem

Grupo Sazón receives about 1,000 delivery-driver applications a week across 45 restaurants in Spain and Mexico. Thirteen recruiters screen by phone. Six in ten candidates never answer. Eight in ten recruiter hours go to candidates who cannot be hired.

The agent takes over the first screening. Recruiters book interviews only for candidates who pass the two objective checks. They follow up on ambiguous cases the agent flags for review.

## Channel policy

WhatsApp carries the whole screening.

- First contact is a WhatsApp template sent minutes after the application.
- The template names the assistant, says it is an AI and not a person, says the conversation is recorded and only the recruiting team sees it, says the candidate can stop at any time by saying so, and asks whether they agree to continue.
- Only a clear agreement is the opt-in. "Not now" leaves the chat waiting. A clear no closes it for a recruiter. A bare "no" is asked about once: not now, or not at all? The reply also opens the 24-hour WhatsApp service window.
- After consent the candidate can stop at any time. The agent records it, closes the chat for a recruiter and sends nothing more.

The engine takes text and returns text. Another channel, such as a browser voice call, is an adapter on the same flow. No other channel is built (see the README improvements). A channel switch never restarts the flow.

## Conversation stages

Consent and the full name come first. Both hard stops (licence and zone) come before the fields only a recruiter needs: availability, shift, experience and start date.

| # | Stage | Tool exposed to the LLM | Branch |
| --- | --- | --- | --- |
| 1 | Consent | `record_consent` (agreed, declined, not_now, unclear) | Declined: close politely, `needs_recruiter_review`. Not now: wait. Unclear: ask which, twice at most |
| 2 | Full name | `record_full_name`, `confirm_name` | Invalid: re-ask once. Differs from the application name: confirm once, then `needs_recruiter_review` if denied |
| 3 | Driving licence | `record_licence` | No: `disqualified`, reason `no_licence` |
| 4 | City or zone | `record_zone`, `confirm_zone` | No match: `disqualified`, reason `outside_service_area`. Fuzzy match: confirm, then `needs_recruiter_review` if denied |
| 5 | Availability | `record_availability` | Invalid: re-ask once |
| 6 | Preferred shift | `record_schedule` | Invalid: re-ask once |
| 7 | Delivery experience | `record_experience` | 0 years is valid |
| 8 | Start date | `record_start_date` | Past date: re-ask once |
| 9 | Outcome | `flag_for_recruiter` | `qualified`: summary and interview handoff. Any flagged concern: `needs_recruiter_review`, reason `recruiter_check` |
| 10 | Wrap-up | `record_questions` | The outcome message asks for questions about the job for the recruiter. One reply is recorded, then a fixed thank-you closes the chat |

`request_stop` and `flag_for_recruiter` are exposed at every stage after consent. A stop request closes the chat with `needs_recruiter_review`, reason `stop_requested`, and skips the wrap-up. A flag records what a recruiter must check before an interview (a criminal record, a suspended, expired or unconfirmed licence, a documents question, a hedged answer); the answer is still recorded and the screening continues.

The current stage is the first required field still missing. Code exposes the tools for every missing field from the current stage onward. A candidate who answers three questions in one message therefore advances three stages.

The LLM cannot skip the licence check. Later tools do not exist until code exposes them.

## Agent personality

- Named assistant ("Sazón").
- Warm and informal-professional. Uses tú in Spanish.
- Never pretends to be human.
- One question per message.
- At most two sentences and one emoji.
- Says briefly why it asks each question.

## Data fields and validation

Rules live in code, not in prompts. Each rule is a Pydantic validator on one model, `CandidateProfile`.

| Field | Validation | On failure |
| --- | --- | --- |
| Full name | Two or more alphabetic words. When the application carries a name, similarity of 0.8 or more (token set, case and accent insensitive): accept. Below: confirm | Re-ask with an example. Confirm denied: recruiter review, reason `name_mismatch` |
| Driving licence | Yes or no | No: disqualify |
| City or zone | Exact match on a service area name or alias (case and accent insensitive): accept. Fuzzy score of 70 or more: confirm. Score below 70: out | Out: disqualify. Confirm denied: recruiter review |
| Availability | One or more of full-time, part-time, weekends | Re-ask with options |
| Preferred shift | One of morning, afternoon, evening, flexible | Re-ask with options |
| Experience | Years 0 to 40. Platforms as a list, which may be empty | Re-ask |
| Start date | ISO date, today or later. The LLM resolves relative phrases against today's date | Re-ask with a date example |

The structured output is the JSON dump of `CandidateProfile`.

## Edge cases

- **Silence.**
  - No reply to the opener: one template retry at about 24 hours, then `abandoned` at stage `consent`.
  - Silence after a reply: a free-form nudge at 2 hours and a last one at about 23 hours, both inside the window. Then `abandoned`, with the stage recorded.
- **Invalid or ambiguous answer.** The validator rejects the tool call. The model sees the rejection and its reason and asks again in its own words with an example; a fixed re-ask is the fallback. After two rejections on the same stage, the candidate goes to `needs_recruiter_review`. The flow never loops.
- **Language switch.** Code detects the language of each message. The agent replies in that language. The language history is stored. Code-switched messages work because the tools do not depend on language.
- **Off-topic or inappropriate input.** A guardrail check runs before the turn. The agent redirects once, then closes politely to `needs_recruiter_review`.
- **Several answers in one message.** The agent calls every matching tool in one turn. The flow skips the stages already satisfied.
- **Confused or frustrated candidate.** The guardrail check also reads the candidate's tone. The agent then uses simpler, calmer wording for that turn. A failed check counts as neutral.

## Outcomes

| Status | Who decides | What the candidate hears | What the recruiter sees |
| --- | --- | --- | --- |
| `qualified` | Code, when all fields are valid and nothing is flagged | Fixed message: the answers go to a recruiter, who will be in touch about next steps | Summary, profile JSON, transcript, the candidate's questions |
| `disqualified` | Code, only on no licence or out of zone | The real reason, in their language. The application stays on file | Reason code. Override button |
| `needs_recruiter_review` | Code, on anything ambiguous or flagged | A recruiter will follow up | Reason code, flagged concerns, transcript, the candidate's questions |
| `abandoned` | Code, on silence | Nothing further | Drop-off stage |

Only the two objective criteria disqualify automatically, and only an unflagged complete profile qualifies automatically. A human decides everything that needs judgement. Every outcome except an opt-out (declined consent, stop request) is followed by one wrap-up turn: the outcome message asks for questions about the job for the recruiter, the reply is recorded for them, and a fixed thank-you closes the chat. Every outcome and override goes to an append-only event log with its reason. The one exception is the demo reset, which re-keys a candidate's events to the archive id and adds a `demo_reset` event with the actor.

## Tone and length

- Messaging style, not email.
- One to two sentences and one question per message.
- No bullet lists.
- Replies arrive within seconds.
- The agent never leaves more than two of its own messages unanswered. Silence nudges do not count toward this limit.
- Ask, do not instruct. No "yes or no" tails on a question. Acknowledge the answer in a few words before the next question.
- Code owns the opener and the closing messages, so the disclosure and opt-in are always the same and a disqualified candidate always hears the real reason. Everything else the model writes from a code brief: carry on, re-ask with this reason, confirm this city or name, or say the chat waits.

Code checks every model reply before sending it. The checks are: one question, at most one emoji, at most 280 characters, the candidate's language, no markdown, and no links. A first draft that fails is rewritten once by a second model call that sees the tool results and the broken rules. A rewrite that still fails, or an empty one, is replaced by the fixed question for the current stage. The second call runs only when the first draft cannot go out, so an ordinary accepted turn keeps one call.

## Designed, not built

Each item below has a design and no code. Each states why it is not built and what the choice costs. Settings, routes and collections named here do not exist in the code. The case study is due 27 Oct 2026, and the scope is cut to what the video needs: one WhatsApp screening, every agent decision on the recruiter page with its reason, one override, and a README.

### Silence scheduler inside the API

Why not built: the compose `sweep` service already covers re-engagement for the take.

Tradeoffs:

- One sweep process cannot overlap with itself. The in-API scheduler runs in every replica, so it needs a lease and a claim per nudge. That adds a collection and a failure model.
- A 5xx or a lost response keeps the claim, because Twilio may have sent the message. A nudge can be lost. None is sent twice. The design prefers silence to a duplicate message.
- Removing the `sweep` service removes one container to start and one place to forget it.

Design:

- An asyncio task in the API lifespan runs `sweep_silence` in a worker thread every `SCREENING_SWEEP_INTERVAL_SECONDS` when `SCREENING_SWEEP_ENABLED` is set. The lifespan warns when it is off. `api` and `mongo` get `restart: unless-stopped`.
- The task uses the cached `get_engine()` instance that serves the webhook, taken on the first tick, so the API still starts without a model key. Per-candidate locks belong to an engine instance, so a second instance would not serialise the sweep against an inbound message. A failed tick is logged without candidate data and the loop continues.
- One sweep per interval across workers: a `sweep` lease in a `leases` collection, taken with a single-write upsert like the login cooldown. `held_until` stops two sweeps from overlapping. The TTL field `expires_at` is the later of `held_until` and the last start plus the interval. `screening-nudge` and a "Run sweep now" button check `held_until` only. Release filters on the owner and sets `held_until` to now.
- A claim is written before each send. The key is per silence episode, `nudge:{candidate}:{last_inbound_at or opened_at}:{n}`, because `nudge_count` resets on every inbound. A claim expires at the episode's abandon time plus a margin.
- A 4xx (429 included) and a refused or timed-out connection release the claim, and the next tick retries. A 5xx, a read timeout, a lost response, a crash mid-send or any unclassified exception keeps the claim and records `nudge_unknown`. Twilio documents only 429 as not processed, so the other 4xx cases are an inference.
- `TwilioWhatsAppSender` raises `DeliveryRefusedError` or `DeliveryUnknownError`. The failed-send test needs its fake sender to raise `DeliveryRefusedError`.
- On shutdown the lifespan sets a stop flag, which the sweep checks between candidates, then awaits the task. A worker thread cannot be cancelled.

### Recruiter console

Goal: every feature reachable in the browser, every agent decision on screen with a reason, every trace and architectural rule checkable against the running code.

Why not built: the recruiter tool the brief asks for exists (list, funnel, detail with per-turn inspector, override). The 27 Oct scope decision leaves fonts and the shell restyle untouched.

Tradeoffs:

- Server-rendered pages with a form post and a redirect per action need no front-end build and no node. They give a plainer interface than a single-page app.
- Self-hosted fonts work on a call with poor network and send no visitor IP to a third party. They need each font licence checked, a `StaticFiles` mount and a package-data glob in `pyproject.toml`. Package data covers only `templates/*.html` today.
- The ops panel shows recruiters and API keys as counts only. Every recruiter has the same rights, so a list would let any of them read every email and key id.
- The how-it-works page lists only facts the code can produce at request time. That blocks hand-written rule text from drifting, and it limits the page to what the code can introspect.

Design:

- Start a WhatsApp screening from the console: a form over the same path as `POST /candidates` (E.164 phone, language), with the CSRF check of `require_recruiter_write`.
- How-it-works page: stage order from `Stage`, tools exposed per stage, `reask_limit`, `OFF_TOPIC_STRIKE_LIMIT`, silence thresholds, configured models, the reply-policy rules and the guardrail fail-open rule. Validation rules appear only if the validators read them from a declared table the page also reads. Links to the README for the prose.
- Ops panel: scheduler state (enabled or not, lease holder, last run, nudged, abandoned, failed), "Run sweep now" through the same lease, which secrets and integrations are configured (names only, never values), Logfire on or off.
- Visual identity: Orbio product chrome, Grupo Sazón shown as the tenant. Tokens from the `--ui-*` set on orbioai.co/platform: background `#edefe8`, panel `#fcfdf9`, surface `#fff`, text `#1e2418` / `#555c4a` / `#858c78`, border `#dde0d4` / `#b8bda8`, agent accent `#b8e636` on `#f0f7d8`, brand `#2f3f22`, status success `#3d7254`, warning `#7a5f17`, error `#b83232`, info `#316692`. Fonts: Geist (display), Inter (body), IBM Plex Mono (data). The layout is original.
- Tokens live in one CSS block in `base.html` and no page sets a raw colour. Status mapping: qualified to success, disqualified to error, needs_recruiter_review to warning, abandoned to text-3, in_progress to info.
- Analytics series: completion rate, drop-off stage and average duration, from timestamps the documents already carry. Needs an index on events `(kind, created_at)`.
- `screening-cli`, `screening-admin` and `screening-nudge` stay as they are.

### Names and data

Grupo Sazón is fictional, so every name, location and persona is ours to define.

Why not built: one live screening does not need the full service-area list or realistic personas. The 16-city fixture and the clean scripted personas are enough for the build.

Tradeoffs:

- Realistic personas make the evals and the demo dataset credible. They cost live model calls and authoring time.
- Seeded conversations finish in seconds and would distort duration and drop-off. Analytics exclude the `seed-` prefix or show it as a separate series.
- The seed command takes the database URL as a required argument with no default. It does not reuse `SCREENING_EVAL_DATABASE_URL`, so evals still never write to the app database. The cost is one more argument to type.

Design:

- Author the 45 service areas across Spain and Mexico, with local aliases and IANA timezones, in `domain/service_areas.py`. This replaces the 16-city fixture.
- The assistant name (`SCREENING_ASSISTANT_NAME`, now `Sazón`) can be changed for the demo.
- Rewrite the eval personas as realistic candidates: typos, slang from both countries, one-word answers, voice-note style run-ons, questions back to the agent, code-switching, a frustrated candidate and a confused one.
- Demo dataset: run the personas live through the engine into the demo database as `cli` candidates with a `seed-` id prefix. Before the live seed, inventory what is in the demo database and where it came from. Delete only after approval.

### Voice channel

Why not built: bonus features carry 10% of the rubric and the brief rewards depth over breadth. A live WhatsApp screening with auditable decisions serves the build and presentation weights. A half-built voice channel adds failure risk to the live call.

Tradeoffs:

- The engine takes text and returns text, so a voice adapter changes no screening logic. It adds three vendors and a real-time audio path.

Design: Pipecat as a voice adapter on the same engine, with Deepgram for speech-to-text and ElevenLabs for text-to-speech.

### Intake page

Why not built: the page existed to pass an SMS campaign review. The brief does not need it, and a stable public host is unresolved (the free ngrok domain shows a browser interstitial to a first-time visitor).

Tradeoffs:

- Collecting name, phone and consent before the first message gives the agent the applicant name for the mismatch check and a consent record. It adds a public surface that needs rate limits, privacy and terms pages and a legal review.
- Recruiter-initiated starts through the authenticated `POST /candidates` stay available, so the page is an addition, not a replacement.
- Whether the flow handles a stop request is unverified. The page must not promise one until it does.

Design:

- `GET /apply` serves a form with name, phone, language and an unchecked consent box. The consent text names Grupo Sazon, says messages are recruiting-related and sent by an AI assistant on WhatsApp, gives the frequency from the nudge settings, says how to stop, and states consent is not a condition of employment.
- `POST /apply` refuses an unchecked box and rate limits per client IP and per phone, one atomic Mongo write each, like the login throttles. It then runs the same path as `POST /candidates`.
- The candidate document stores `consent_given_at` and the consent text version. It does not store the IP.
- The in-flow consent stage is the second opt-in. The candidate still agrees in the first reply before any question.
- `GET /privacy` and `GET /terms` are server-rendered. The maintainer reviews the wording. It is not legal advice.

### Async worker for many concurrent conversations

Why not built: the README "Deployment and scaling" section holds the design and the queue comparison, and the demo load does not need a broker. The built system has one known limit. The model call runs inside the webhook request, and Twilio gives up on a response after 15 seconds. A slower turn loses its reply and is not retried.

Tradeoffs:

- Correctness across several api replicas already holds through the Mongo `version` conditional update and the `$ne` on the transcript external id. The worker adds speed of acknowledgement and per-candidate ordering, not correctness.
- The worker adds Redis, a broker client, a lease and an outbox relay. Each is a new failure mode.
- Celery with Redis is mature and documents long-task settings. It gives no per-key ordering, so a Mongo lease supplies the order. A Mongo inbox with a lease needs no new infrastructure and needs its own polling and backoff code. Dramatiq, Arq and Temporal are covered in the README. The ordering claims for them are reasoning, not a primary source.

Facts from sources:

- Twilio defaults are a 5 s connect timeout, 15 s read timeout, 15 s total, one retry, and retry only on connect failures (`rp=ct`). The total budget `tt` accepts 100 to 15000 ms and includes retries. A Twilio-side retry cannot give a slow turn more time. The fix is to answer fast.
- `config.py` sets `llm_timeout_seconds = 15.0` and `llm_max_retries = 2` per model call. A turn makes a guardrail call and a turn call, so a slow provider can pass 15 s. Each stored turn record carries `latency_ms`, which sizes the problem before any build.
- Celery recommends idempotent tasks. With `acks_late` a crash can run a task twice. For long tasks it recommends `worker_prefetch_multiplier = 1` with `task_acks_late = True`. It states no per-key ordering or locking.

Design:

1. The webhook verifies the signature, dedupes on `MessageSid`, stores the inbound message and returns empty TwiML.
2. A stored inbox row per inbound message is the source of truth. A worker claims a candidate with an atomic Mongo lease (a `processing_until` field set by `find_one_and_update`), runs the turn, replies through the REST sender, and releases. The queue only wakes a worker. A repeated task finds the message processed and exits.
3. The reply is stored with `outbound_status = pending` in the same single-document write as the turn. A relay sends and marks it `sent`. A crash between write and send resends at most once, keyed by the stored reply id.
4. Worker concurrency is the global cap on in-flight model calls. Back off on provider 429.
5. Tests: a fake model that sleeps past 15 s while the webhook answers in under a second and the reply arrives through the REST sender. A repeated `MessageSid` runs one turn. A worker crash between turn and send resends at most once.

### SMS channel (dropped)

Why dropped: the WhatsApp path works and is sufficient.

Tradeoffs:

- WhatsApp is the only channel, so a candidate without WhatsApp cannot be screened.
- Twilio blocks sends from a US 10DLC number to US numbers until an A2P campaign is approved (error 30034). The error page ties the block to a US destination. Candidates are in Spain and Mexico, so an SMS sender for them needs its own setup, which has not been researched.
