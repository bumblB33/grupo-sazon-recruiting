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
- Fonts and shell restyle untouched.
- Demo reset is built: archive and re-key, only for candidate ids in the `SCREENING_DEMO_PHONES` allowlist. Mechanism in the README "Key design decisions". The allowlist is set in the compose override outside the repo.
- Demo config has one owner per value. `.env` holds secrets and values shared with plain compose (`NGROK_URL`, `NGROK_AUTHTOKEN`, session secret, recruiter domains, login redirect). The override outside the repo holds demo policy only: dev mode, short silence timers, 3 s page refresh, and the public and webhook URLs derived from `NGROK_URL`. `COMPOSE_FILE` in `.env` makes plain compose load the override. Rationale: a value set in two places drifts, and an empty duplicate in `.env` once blanked the Twilio credentials. Cost: `env_file` passes `NGROK_AUTHTOKEN` into the app containers, logged as tech debt in `TROUBLESHOOTING.md`.
- SendGrid is optional for the take. The terminal login path is the fallback, so a missing key blocks nothing.

## Remaining work, in order

1. One full screening after the prompt change (28 Oct). The two preflight screenings ran with tool-only model turns, so every reply was the fixed next question. The prompt now states the question order and the output format. Offline checks against the live model returned text with the tool call in 7 of 10 samples, but the 28 Oct live run still produced tool-only turns after the first, so the fixed next question carries most replies. Known gap, not a blocker: the conversation completes and the inspector labels every reply. Both demo phones were reset and re-seeded with openers. Reply from each phone, read every reply in the inspector, log each prose or tone fault as a persona or policy case, fix blockers only.

2. Record the video: phone screening beside the candidate page, the inspector on one turn with a rejected tool call or a policy fallback if the run produced one, the summary, one override, one demo reset.

3. Rotate the Twilio API key whose secret was printed into a session transcript. Optional: SendGrid trial, a verified single sender and an API key with Mail Send, into `SCREENING_SENDGRID_API_KEY` and `SCREENING_LOGIN_EMAIL_FROM`. Without them `demo-login.sh` is the login path.

Done on 27 and 28 Oct: image rebuilt from the branch tip, both tunnel probes pass (200 on `/docs`, 401 on an unsigned webhook POST), Twilio credentials non-empty in `api` and `sweep`, both phones joined to the sandbox, two preflight screenings completed (one disqualified, one qualified) and copied into the README "Sample conversations", a high-effort adversarial review of the reset, unknown-number and applicant-name slices applied, gates green (pytest, ruff check, ruff format, pyright).

## Requirements coverage

Against `docs/Orbio-Assignment.md`. Rubric weights: technical build 40%, process design 25%, presentation 25%, bonus 10%.

| Requirement | State | Closed by |
|---|---|---|
| Phase 1 process design | `docs/process-design.md` | none |
| Screening agent, validation, JSON output, history, storage, summary, error handling | built and tested with fakes: 183 tests pass, ruff check and format clean, pyright 0 errors (27 Oct, working tree). Stack reachable from the internet, signature check confirmed live. No live LLM turn yet | Preflight |
| Recruiter tool | built: list, funnel, detail with per-turn inspector, override | none |
| LLM choice justified | README "LLM choice": justified from design, failed bake-off named | none.
- Re-run is the first improvement |
| Live demo ("show, don't tell") | stack up, Twilio webhook paste and sandbox join pending | Preflight |
| README: setup, architecture, key decisions, improvements | present | none |
| README: sample conversations | present, from the two preflight screenings | none |
| Demo video, 5 to 10 minutes | missing | Video |
| Bonus: multi-language with code-switching, re-engagement, tests and evals | built | none |
| Bonus: guardrails | input classifier and live reply policy built | none |
| Bonus: sentiment | candidate tone built, untested on a live model | Bake-off |
| Bonus: analytics | partial: counts by status and stage only | deferred |
| Bonus: deployment design (deploy, monitor, scale) | compose, tracing, README "Deployment and scaling" | none |
| Bonus: voice agent | not built, optional | deferred |
| Bonus: scheduling, ATS design, RAG | not built, not planned | none |

## Known gaps

- The live webpage serves old code. See remaining item 1. The README and `docs/process-design.md` describe the source, not the running image, until it is rebuilt.

- Recruiter console visual identity is not built. `base.html` still carries the warm paper palette (Cooper Black display, chile and marigold). The Orbio token set in `docs/process-design.md` ("Recruiter console") is applied nowhere. The maintainer's side UI and UX planning is not in the repository: `git status` shows no matching file, there is no stash, and `evals-review-fixes` and `main` hold no `--ui-` tokens. `harden-recruiter-api-auth` mentions them only in its `STATUS.md`. Until the work is located, nothing on the webpage can show it.

- The bake-off report restyle is uncommitted: `evals/templates/bakeoff.html` and the regenerated `docs/bakeoff.html` (Fraunces, Inter and JetBrains Mono, teal accent, loaded from Google Fonts). `docs/bakeoff.json` is unchanged and still the failed run. The palette and fonts differ from the console token set in `docs/process-design.md`, and the CDN load is the case the fonts question below argues against.

- `todo.md` is an untracked scratch file holding a chat answer about SendGrid keys. This file owns open work, so `todo.md` can go.

- The mailbox login path is unverified end to end. `.env` has no `SCREENING_SENDGRID_API_KEY` or `SCREENING_LOGIN_EMAIL_FROM`, so the redirect was proven only on the stderr fallback. Until a SendGrid key and a verified sender are in `.env`, the terminal path is the demo path.

- No live LLM turn has happened. The first WhatsApp message is the first. The org key needs `PROJECT_ANTHROPIC_WORKSPACE_ID`, set in `.env`.

- No trace has been sent to a real Logfire project. The no-PII test uses an in-memory exporter.

- The guardrail tone prompt and the tone cases are untested on a live model. Category accuracy after the tone change is unverified until the bake-off runs.

- The service-area list is a 16-city fixture, not the client's 45 locations. 

- Every recruiter and API key has the same rights. There are no roles or scopes.

- Monitoring alerts are not built. README "Deployment and scaling" names what to alert on.

- Prompt review is open: rewrite `build_prompt` against the tone rules in `docs/process-design.md`, then confirm with the live persona run and the judge.

- Observed: two sandbox joins from one number produced no webhook request. The ngrok inspector was empty and the API log has no `/webhook` line. The sandbox consumes the join message, so a join cannot trigger the opener.

- Unverified: whether the plain-text opener reaches a joined number with no prior inbound. The preflight answers it.

## Next session

1. Build from `PLAN.md` in its order of work. The slow-webhook worker is designed, not built: see `docs/process-design.md` ("Async worker").

## Open questions

- Which model wins the bake-off for the live turn, the summary and the guardrail. Decided by `docs/bakeoff.html` from a valid run. The current file is from a failed run.
- Logfire trace link format and project URL for the inspector. Needs the Logfire project to exist.
- Whether the console restyle is back in scope. The 27 Oct decision says fonts and shell restyle stay untouched, and the maintainer has since done side UI and UX work. If it is back in scope, which palette wins: the Orbio tokens under "Recruiter console" or the bake-off report restyle. The token set is in `docs/process-design.md` ("Recruiter console").
- Fonts for the console restyle: self-host Geist, Inter and IBM Plex Mono, or load from a CDN. A CDN fails on a call with poor network and sends visitor IPs to a third party. Self-hosting needs each font licence checked first.

## Deferred past the deadline

Not built, by decision, with the rationale and tradeoffs in `docs/process-design.md` ("Designed, not built"):

- Intake page: a public form for name, phone, language and consent that runs the same path as `POST /candidates`. It existed to pass an SMS campaign review and the brief does not need it. The applicant file (`screening-admin start-from-file`) seeds the demo instead.
- Async worker for many concurrent conversations: acknowledge the webhook fast, run the turn in a worker with a Mongo lease, reply through the REST sender. Twilio drops a reply slower than 15 s. Measure `latency_ms` from stored turn records before building it.

## Planned designs

Designs for work in `PLAN.md` that is not built yet. Settings, routes and collections named in this section do not exist in the code. Designs with no plan to build them are in `docs/process-design.md` ("Designed, not built").

### Live bake-off

Re-run `python -m evals.run_evals` with the workspace header fixed, then set the model defaults in `config.py` from the result. Adjust the guardrail latency gate default (p95 at most 2.5 s, a first guess) from the first valid `bakeoff.json`.
