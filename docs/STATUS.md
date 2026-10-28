# Project status

Open work for the screening agent. The README describes the system as built. `TROUBLESHOOTING.md` holds the demo runbook and tech debt. This file tracks what is missing, what is unverified and what is undecided. Designed-but-unbuilt items, with their rationale and tradeoffs, live in `docs/process-design.md` ("Designed, not built"). Update this file when a gap closes or a question is answered.

## Scope decision

The case study is due 27 Oct 2026 with a 5 to 10 minute video. Scope is cut to what the video needs: one WhatsApp screening from the presenter's phone, every agent decision on the recruiter candidate page with its reason, one override, and a README with every deliverable section the brief names.

Decisions taken on 27 Oct, binding:

- WhatsApp is the only candidate channel. There is no browser fallback if the tunnel or Twilio fails during the take. The fallback is a second take.
- The compose `sweep` service stays and covers re-engagement. The in-API scheduler is deferred.
- `screening-cli` stays.
- LLM choice is justified from design in the README. The failed scripted bake-off is named as is, with the provider errors, and listed first under improvements.
- Recruiter login on screen uses the real path. The login mail for the demo address is redirected to the presenter's inbox with `SCREENING_LOGIN_EMAIL_REDIRECT_TO` (dev mode only, 503 otherwise). No link on the "check your inbox" page and no dev-only listing route, because either would be a demo-only surface that the fail-closed story then has to explain. Which path runs depends on the SendGrid settings alone, not on dev mode. Runbook in `TROUBLESHOOTING.md`.
- Tunnel is the `ngrok` compose service behind the `tunnel` profile, bound to the account's fixed dev domain, so the Twilio webhook URL is pasted once. cloudflared is dropped.
- Tool exposure stays as built: every tool for a missing field from the current stage onward. The inspector shows the full exposed list, so the demo narration says this.
- Inspector shows the trace id as text. No Logfire link until a Logfire project exists.
- Fonts and shell restyle untouched for the take. The console restyle question is open below.
- Demo reset is built: on the primary branch it archives and re-keys the candidate; on `guid-candidate-ids` it closes the candidate in place. Only phones in the `SCREENING_DEMO_PHONES` allowlist, set in the compose override outside the repo. Mechanism in the README "Key design decisions".
- Demo config has one owner per value. `.env` holds secrets and values shared with plain compose (`NGROK_URL`, `NGROK_AUTHTOKEN`, session secret, recruiter domains, login redirect). The override outside the repo holds demo policy only: dev mode, short silence timers, 3 s page refresh, and the public and webhook URLs derived from `NGROK_URL`. `COMPOSE_FILE` in `.env` makes plain compose load the override. Rationale: a value set in two places drifts, and an empty duplicate in `.env` once blanked the Twilio credentials. Cost: `env_file` passes `NGROK_AUTHTOKEN` into the app containers, logged as tech debt in `TROUBLESHOOTING.md`.
- SendGrid is optional for the take. The terminal login path is the fallback, so a missing key blocks nothing.

## Remaining work, in order

1. Commit the compose work. Uncommitted on the primary branch, 28 Oct, 20 files, gates green on the working tree (226 tests, ruff check, ruff format, pyright): the model writes re-asks, confirmations and the consent wait message from a code brief in a second call (`compose` node), with the templates as fallback; consent is an explicit opt-in (`agreed`, `declined`, `not_now`, `unclear`); `request_stop` closes the chat after consent with reason `stop_requested`; the opener discloses the AI, the recording, who sees it and how to stop. Unverified live: the compose call against the real model, the `consent_not_now` and `stop_after_consent` personas, and the approved WhatsApp opener template, which still carries the old wording and needs resubmitting. Next check: `python -m evals.run_evals` and one sandbox screening.

2. Record the video: phone screening beside the candidate page, the inspector on one turn with a rejected tool call or a policy fallback if the run produced one, the summary, one override, one demo reset. The live stack runs the primary tip plus the uncommitted compose work through the bind mount.

3. Merge S3 after the take. Branch `guid-candidate-ids` at `133b2a5` holds opaque candidate ids, a partial unique index on `phone` for open conversations, the in-place reset, per-phone limits on unknown-number replies and late messages, a one-time phone backfill behind a marker, and the deletion of `PLAN.md`. It already contains the primary tip `b7e0881`, and its gates are green (228 tests). Merging it changes the running API through the bind mount, so it waits for the take and for item 1, whose files overlap the branch (`flow/graph.py`, `tools.py`, `transitions.py`, `turn_record.py`, `replies.py`, `llm/turn.py`, `recruiter/views.py`, `evals/runner.py`, tests). Expect conflicts there and a modify-or-delete conflict on `PLAN.md`. After the merge: rerun the four gates, `docker compose up -d --build`, repeat the two tunnel probes in `TROUBLESHOOTING.md` section 4. The first API start runs the backfill once; the two archived copies from the 28 Oct resets become abandoned rows with their phone restored. Candidate pages are then reached from the list, not by typing the phone in the URL.

4. Rotate the Twilio API key whose secret was printed into a session transcript. Optional: SendGrid trial, a verified single sender and an API key with Mail Send, into `SCREENING_SENDGRID_API_KEY` and `SCREENING_LOGIN_EMAIL_FROM`. Without them `demo-login.sh` is the login path.

5. Remove `todo.md` (`git rm`). It is a scratch file with a chat answer about SendGrid keys and a superseded sandbox checklist; this file owns open work.

Done on 27 and 28 Oct, all on the primary branch unless noted: S0 unanswered-agent-message limit (`ecb6b4a`); SR demo reset (`fa74e41`); S1 fixed reply for an unknown number (`9071b79`); S2 applicant name with opener personalisation and mismatch confirmation (`9b26f09`); high-effort adversarial review of those three slices, nine findings applied (`d45d63b`); prompt states the question order and the output format (`10b9256`); S4 applicant file and `screening-admin start-from-file` (`011794f`); S3 opaque ids built, reviewed with ten findings applied, merged with the primary tip, on `guid-candidate-ids` (`987af48`, `133b2a5`). Image rebuilt from the branch tip; tunnel probes 200 on `/docs` and 401 on an unsigned webhook POST; Twilio credentials non-empty in `api` and `sweep`; both phones joined to the sandbox; both demo phones reset through the new route and re-seeded with named openers; two preflight screenings (one disqualified, one qualified) copied into the README "Sample conversations"; one full screening with the applicant name set on the `…9756` phone: greeting by first name, a model-written answer to "How'd you know my name?", "Donald Gandalf Portsmith" matched "Donald Portsmith" with no confirm turn, licence recorded, "suburbs of Toledo" disqualified as outside the 16-city fixture, summary written. Turns two to five of that run were tool-only, so the fixed questions carried them.

## Requirements coverage

Against `docs/Orbio-Assignment.md`. Rubric weights: technical build 40%, process design 25%, presentation 25%, bonus 10%.

| Requirement | State | Closed by |
|---|---|---|
| Phase 1 process design | `docs/process-design.md` | none |
| Screening agent, validation, JSON output, history, storage, summary, error handling | built and tested with fakes: 226 tests pass on the working tree, ruff check and format clean, pyright 0 errors (28 Oct). Three live screenings completed on the sandbox | none |
| Recruiter tool | built: list, funnel, detail with per-turn inspector, override | none |
| LLM choice justified | README "LLM choice": justified from design, failed bake-off named | none.
- Re-run is the first improvement |
| Live demo ("show, don't tell") | stack up, webhook saved, both phones joined, three screenings run end to end | none |
| README: setup, architecture, key decisions, improvements | present | none |
| README: sample conversations | present, from the two preflight screenings | none |
| Demo video, 5 to 10 minutes | missing | Video |
| Bonus: multi-language with code-switching, re-engagement, tests and evals | built | none |
| Bonus: guardrails | input classifier and live reply policy built | none |
| Bonus: sentiment | candidate tone built, untested on a live model beyond the three screenings | Bake-off |
| Bonus: analytics | partial: counts by status and stage only | deferred |
| Bonus: deployment design (deploy, monitor, scale) | compose, tracing, README "Deployment and scaling" | none |
| Bonus: voice agent | not built, optional | deferred |
| Bonus: scheduling, ATS design, RAG | not built, not planned | none |

## Known gaps

- Live model turns are mostly tool-only. In every live screening so far the model returned its tool call with no text on most turns, so the reply was the fixed next question (reply source `next_question`). The prompt now states the question order and the output format; offline checks returned text in 7 of 10 samples, the live run did not improve. The compose work in remaining item 1 is the structural answer: a second call writes the text from a code brief. Unverified live.

- Closed conversations are silent. A candidate who corrects the city after a hard stop, or writes "Hello?" afterwards, gets no reply. Recorded in the transcript only. Open question below.

- Recruiter console visual identity is not built. `base.html` still carries the warm paper palette (Cooper Black display, chile and marigold). The Orbio `--ui-*` token set in `docs/process-design.md` ("Recruiter console") is applied in no template on any branch (`git grep` across all six branches: hits only in `STATUS.md` and `process-design.md`). The maintainer's side visual UI and UX planning is not located: not in the repository, not on any branch or stash, not in `~/Desktop/Orbio/notes` (which holds `design-outline.md`, a 23 Oct project design outline, and `subprocessors.odt`). Until it is located, nothing on the webpage can show it. Action: the maintainer points at the file or link.

- The bake-off report restyle (`evals/templates/bakeoff.html`, `docs/bakeoff.html`: Fraunces, Inter and JetBrains Mono, teal accent, loaded from Google Fonts) is committed in `0b6fd50`. Its palette and fonts differ from the console token set, and the CDN load is the case the fonts question below argues against. `docs/bakeoff.json` is still the failed run.

- The approved WhatsApp opener template still carries the pre-compose wording. The sandbox sends plain text, so the demo is unaffected; a production send would use the old text until the template is resubmitted.

- The mailbox login path is unverified end to end. `.env` has no `SCREENING_SENDGRID_API_KEY` or `SCREENING_LOGIN_EMAIL_FROM`, so the redirect was proven only on the stderr fallback. Until a SendGrid key and a verified sender are in `.env`, the terminal path is the demo path.

- No trace has been sent to a real Logfire project. The no-PII test uses an in-memory exporter.

- The guardrail tone prompt and the tone cases are untested on a live model beyond the three screenings. Category accuracy after the tone change is unverified until the bake-off runs.

- The service-area list is a 16-city fixture, not the client's 45 locations. Toledo is not in it, which disqualified the 28 Oct screening.

- Every recruiter and API key has the same rights. There are no roles or scopes.

- Monitoring alerts are not built. README "Deployment and scaling" names what to alert on.

- Prompt review is open: rewrite `build_prompt` against the tone rules in `docs/process-design.md`, then confirm with the live persona run and the judge.

- Persona cases from the live runs not yet in the evals: a correction after the hard stop; a follow-up "Hello?" to a closed conversation; a location given as a suburb plus a side of town; a candidate asking how the agent knows their name.

- Observed: two sandbox joins from one number produced no webhook request. The sandbox consumes the join message, so a join cannot trigger the opener.

## Next session

1. Items 1 to 3 of "Remaining work", in that order: commit the compose work, record, merge S3.
2. Run `python -m evals.run_evals` against the live models with the new personas, then the bake-off with the workspace header fixed.
3. Locate the side visual UI and UX planning and decide the console restyle question.

## Open questions

- Which model wins the bake-off for the live turn, the summary and the guardrail. Decided by `docs/bakeoff.html` from a valid run. The current file is from a failed run.
- Logfire trace link format and project URL for the inspector. Needs the Logfire project to exist.
- Whether the console restyle is back in scope. The 27 Oct decision says fonts and shell restyle stay untouched, and the maintainer has since done side visual UI and UX work that is not yet located (known gap above). If it is back in scope, which palette wins: the Orbio tokens under "Recruiter console", the bake-off report restyle, or the side plan.
- Whether a closed conversation should answer once that a recruiter will read late messages. Today it stores the message and stays silent.
- Whether the fixed questions keep the one-question rule. The rewritten availability question in `flow/replies.py` asks two questions in one message, which `docs/process-design.md` forbids.
- Fonts for the console restyle: self-host Geist, Inter and IBM Plex Mono, or load from a CDN. A CDN fails on a call with poor network and sends visitor IPs to a third party. Self-hosting needs each font licence checked first.

## Deferred past the deadline

Not built, by decision, with the rationale and tradeoffs in `docs/process-design.md` ("Designed, not built"):

- Intake page: a public form for name, phone, language and consent that runs the same path as `POST /candidates`. It existed to pass an SMS campaign review and the brief does not need it. The applicant file (`screening-admin start-from-file`) seeds the demo instead.
- Async worker for many concurrent conversations: acknowledge the webhook fast, run the turn in a worker with a Mongo lease, reply through the REST sender. Twilio drops a reply slower than 15 s. Measure `latency_ms` from stored turn records before building it.

## Planned designs

Designs for planned work that is not built yet. Settings, routes and collections named in this section do not exist in the code. Designs with no plan to build them are in `docs/process-design.md` ("Designed, not built").

### Live bake-off

Re-run `python -m evals.run_evals` with the workspace header fixed, then set the model defaults in `config.py` from the result. Adjust the guardrail latency gate default (p95 at most 2.5 s, a first guess) from the first valid `bakeoff.json`.
