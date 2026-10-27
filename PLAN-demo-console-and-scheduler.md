# Demo day: WhatsApp screening, turn inspector, README

Design and implementation plan for the last build day. `docs/STATUS.md` keeps the project-wide state and is patched when each step lands. Code owns current behaviour.

## Goal

A recorded 5 to 10 minute demo: one WhatsApp screening from the presenter's phone, every agent decision on the recruiter candidate page with its reason, one override. The README carries every deliverable section the brief names.

Brief coverage (`docs/Orbio-Assignment.md`): conversational agent run live, recruiter tool, structured JSON, validation, summary, error handling, README (setup, architecture, key decisions, improvements, sample conversations), demo video. Bonus already built: multi-language, guardrails, sentiment, re-engagement (compose `sweep` service), tests and evals.

## Decisions

Taken by the maintainer on 27 Oct 2026. Binding.

- Scope for today: turn inspector on the candidate page, WhatsApp preflight, README deliverables, demo video. Demo reset last, only if time allows.
- Web chat is dropped. There is no browser fallback if the tunnel or Twilio fails on the day; the fallback is a second take.
- Deferred, recorded in STATUS: in-API scheduler, lease and nudge claims, pause toggle, ops panel, how-it-works page, rules table, analytics series, shell restyle, start form, `screening-cli` deletion. The compose `sweep` service stays and covers re-engagement.
- LLM choice is justified from design in the README. The failed scripted bake-off is named as is, with the provider errors, and listed under improvements.
- Demo reset, when built: archive and re-key, only phones in `SCREENING_DEMO_PHONES`. Reset re-keys the candidate's events. `docs/process-design.md` and the README change from "append-only" to "append-only, except that a demo reset re-keys a candidate's events to the archive id".
- Inspector shows the trace id as text. No Logfire link.
- Tunnel: ngrok's free dev domain pins the Twilio webhook URL, so it is pasted once. cloudflared quick tunnel is the fallback and changes URL on every start. A named Cloudflare tunnel needs a domain and is not used. Twilio's sandbox webhook is console-only, so no script can set it.
- Tool exposure stays as built (every missing field from the current stage onward). README and CLAUDE.md corrected to match. Narrate it in the video rather than change behaviour on demo day.
- Candidate page refreshes with a meta tag only while the conversation is in progress.
- Fonts and shell restyle untouched today.

Routine calls, stated so they are reviewable:

- The inspector reads `TurnRecord` from the inbound transcript entry (`flow/turn_record.py`). No new storage.
- A transcript entry with no `turn` (opener, nudge, a message on a closed candidate) renders with no inspector.
- The newest turn renders expanded, older turns collapsed with `<details>`. No JavaScript.
- Meta refresh interval is a setting, `SCREENING_CANDIDATE_PAGE_REFRESH_SECONDS`, default 5. Zero disables it.
- Preflight sets short silence thresholds through `SCREENING_*_HOURS` in a compose override outside the repo, never in `.env`.

## Module map

| Module | Owns |
|---|---|
| `recruiter/views.py` | `TurnView`, `MessageView`, `transcript_views`, `REPLY_SOURCE_LABELS`. Pure. |
| `recruiter/templates/_turn.html` | One inspector block per answered inbound message. |
| `recruiter/templates/_transcript.html` | Transcript with inspector blocks, included by `candidate.html`. |

Modified: `config.py` (refresh seconds), `recruiter/router.py` (view model into the candidate page), `recruiter/templates/base.html` (`{% block head %}`), `recruiter/templates/candidate.html`, `README.md`, `CLAUDE.md`, `docs/STATUS.md`, `.env.example`, `tests/test_recruiter.py`.

Reset, if time allows: `demo.py`, `storage/repository.py` (`archive_candidate`, `_LIVE` filters on `list_candidates` and `open_conversations`), `flow/engine.py` (`archive_candidate` under the candidate lock), `storage/models.py` (`archived_at` on `Candidate`), `recruiter/router.py` (`POST /candidates/{id}/reset`), `config.py` (`demo_phones`), `docs/process-design.md`, `README.md`, new `tests/test_demo.py`.

## Inspector

`TurnView.from_record(TurnRecord)` maps: stage before and after, status after, guardrail category, tone, tools exposed, tool calls with accepted flag and validator message, reply source label, raw model text when replaced, violated rules, usage rows (call, model, tokens, latency), total latency, candidate hash, trace id.

`REPLY_SOURCE_LABELS` covers every `ReplySource` member. A test asserts that.

`candidate.html` includes `_transcript.html` in place of the current transcript markup. Pinned strings kept: `<pre>summary</pre>`, the CSRF hidden input shape, `class="done"` and `class="here"`.

## Demo reset (if time allows)

`DemoResetService.reset(candidate_id, actor)` checks the allowlist first, then calls `engine.archive_candidate`, which takes the per-candidate lock and calls `Repository.archive_candidate`. Standalone Mongo has no transactions, so the sequence is fenced, version-guarded and resumable:

1. Fence: pipeline `find_one_and_update` setting `archive_id` with `$ifNull` and incrementing `version`. Returns the fenced document and its version `v`. None means not found.
2. Copy: `replace_one({_id: archive_id}, copy, upsert=True)`. Copy has `archived_at`, `archived_by` and `state.candidate_id` re-keyed. The re-key is mandatory because `_commit` writes to `state["candidate_id"]`.
3. Events: `update_many({candidate_id}, {$set: {candidate_id: archive_id}})`.
4. Actor event: upsert `demo_reset` keyed on archive id and kind, `$setOnInsert` payload with the actor.
5. Delete: `delete_one({_id: candidate_id, archive_id, version: v})`. Zero matched means a writer committed after the fence. Repeat from step 1, at most twice, then raise `StaleStateError`.

`_LIVE = {"archived_at": {"$exists": False}}` is applied in `list_candidates` and `open_conversations`. Route `POST /candidates/{id}/reset` verifies CSRF, maps `NotResettableError` to 403, and redirects to the archived page, which shows a banner. The reset button appears only for allowlisted, unarchived candidates.

If reset is not built, the recorded take uses a second phone number joined to the sandbox, or the dry run is the take.

## README sections

- "LLM choice": tool use reliability, Spanish quality, latency, cost. States that the scripted bake-off in `evals/` errored on provider configuration (Anthropic workspace header, OpenAI calls) and only Mistral completed, so the defaults in `config.py` are a design choice, not a measured one. Re-running the bake-off is the first improvement.
- "Sample conversations": from the live transcripts of the preflight, one per outcome where the run produced one. Phone numbers replaced.
- "Potential improvements": bake-off, in-API scheduler with lease and claims (link the STATUS design), voice, analytics series, ATS spec, RAG over an FAQ.
- "Deployment and scaling": compose today, Logfire monitoring and what to alert on, the process-local lock as the first limit, the path to 10K candidates a week.
- Update the process table and the diagrams only where the build changed them (no `screening-cli` deletion today, so the row stays).

## Build sequence

Each step leaves the suite green.

1. Done (`53c0e0d`). Inspector: `views.py`, the two partials, candidate page, refresh setting, `base.html` head block. Tests in `test_views.py` and `test_recruiter.py`. Gates green: pytest 177, ruff, pyright.
2. In progress. Done: image rebuilt, override at `~/sazon-demo/compose.demo.yaml` (dev mode on so the login link prints; the Twilio signature check stays on because the auth token is set), launcher, tunnel probes passed (200 on `/docs`, 401 on an unsigned webhook POST). Maintainer: install ngrok and add the authtoken, re-run `demo-up.sh`, paste the webhook URL into the Twilio sandbox once, join from the phone. Then one full screening from the phone. Read every reply in the inspector. Log each prose or tone fault as a persona or policy case. Fix blockers only.
3. Done except "Sample conversations", which waits for the live run (`ce30d1a`, `00b6300`, `2c00758`). README has LLM choice, deployment and scaling, improvements. CLAUDE.md and STATUS patched. `TROUBLESHOOTING.md` added.
4. Record the video: phone screening on screen beside the candidate page, the inspector on one turn with a rejected tool call or a policy fallback if the run produced one, the summary, one override.
5. Demo reset, only if time remains after the video is recorded. Then the process-design and README wording change.
6. Multi-lens adversarial review of the branch. Gates: pytest, ruff check, ruff format, pyright.

## Risks

- No live LLM turn has happened yet. The first WhatsApp message is the first. Budget for provider surprises (the org key needs `PROJECT_ANTHROPIC_WORKSPACE_ID`, set in `.env`) before the sample conversations can be written.
- No browser fallback. A tunnel or Twilio failure during the take means a second take, not a different channel.
- Silence thresholds are wall-clock. The preflight override sets short thresholds, so a paused take is abandoned by the `sweep` service. Keep the take moving or stop the `sweep` service for the recording.
- Twilio sandbox: unverified whether a joined number receives the plain-text opener with no prior inbound. The preflight answers it. If not, the candidate sends the first message: the webhook handles an unknown number as a new conversation at the consent stage (`Repository.load_state` returns `initial_state`), so the demo still runs, without the fixed opener and the AI disclosure it carries.
- Meta refresh discards an unsaved override note while in progress. Write the note after the outcome.
- Reset is not atomic. A crash between steps leaves the phone occupied until reset is pressed again.
- The launcher's ngrok branch is untested until ngrok is installed on this machine.
- A sandbox join lasts three days. Rejoin before the recording if the join is older.
