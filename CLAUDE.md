# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Take-home case study for Orbio: an AI candidate-screening agent for Grupo Sazón (restaurant chain hiring delivery drivers in Spain and Mexico). The brief is `docs/Orbio-Assignment.md`. Read it and the README before adding code.

## Document owners

| Owns | File |
|---|---|
| Requirements | `docs/Orbio-Assignment.md` |
| Phase 1 design intent: stages, validation, outcomes, tone. Designed-not-built items with rationale and tradeoffs | `docs/process-design.md` |
| As-built: setup, architecture, design decisions, LLM choice, scaling, improvements | `README.md` |
| Open work: remaining steps, requirements coverage, known gaps, open questions, designs for planned work | `docs/STATUS.md` |
| Demo runbook, commands run, common failures, tech debt | `TROUBLESHOOTING.md` |
| Current behaviour | the code |

When the README and the code disagree, the README is stale. When `docs/process-design.md` and the code disagree, the divergence is a finding. Demo scripts and the compose override live in `~/sazon-demo/`, outside the repo.

## Current state

Working: domain, flow, CLI, storage, API with magic-link sessions, per-client API keys and webhook signature check, recruiter pages with a per-turn inspector, summary, guardrail classifier, WhatsApp opener and outbound via Twilio REST, silence sweep (`screening-nudge`), evals and bake-off runner, tests for all of it with fakes. Not built: voice channel, in-API scheduler. LangGraph owns the node graph; channels are adapters. Voice is optional and comes last.

## Commands

Interpreter is the local venv at `.venv` (Python 3.12). Dependencies are declared in `pyproject.toml`.

```bash
source .venv/bin/activate
pip install -e ".[dev]"
pytest                              # all tests, no LLM calls
pytest tests/test_flow.py::test_no_licence_is_hard_stop
ruff check . && ruff format .
pyright                             # standard mode, config in pyproject.toml
screening-cli                       # chat loop against the graph, needs PROJECT_ANTHROPIC_API_KEY or the provider's key
uvicorn screening_agent.api.app:app --reload    # needs a Mongo at SCREENING_DATABASE_URL
screening-nudge                     # silence sweep, run from cron every few minutes
screening-admin invite <email>           # also recruiters, deactivate, reactivate, create-api-key <label>, api-keys, revoke-api-key, start-from-file <path> [--dry-run] (applicants/applicants.example.json; the real file applicants/applicants.local.json is gitignored)
docker compose up --build           # api and sweep bind-mount screening_agent and api reloads on edits; --build only after pyproject.toml or Dockerfile changes; api + sweep + mongo; add --profile tunnel for the ngrok public URL (NGROK_AUTHTOKEN, NGROK_URL)
python -m evals.run_evals           # persona evals; --models a,b --judge --guardrail-models c,d --out docs for the bake-off (json, html); eval databases go to SCREENING_EVAL_DATABASE_URL, never SCREENING_DATABASE_URL
python -m evals.render_report docs/bakeoff.json   # re-render html from saved results, no LLM calls
firefox --headless --profile /tmp/ffprof --no-remote --window-size=1400,3600 --screenshot /tmp/bakeoff.png "file://$PWD/docs/bakeoff.html"   # add user_pref("ui.prefersReducedMotion", 1) (and ui.systemUsesDarkTheme) to /tmp/ffprof/user.js; no node, so no palette validator
```

## Testing notes

Tests drive the graph with a scripted fake model (`tests/conftest.py`) that records bound tool names and model inputs. One scripted AI message is consumed per candidate message. Build a fresh `ai(...)` per turn: `add_messages` assigns an id to a message on first use, so replaying the same object replaces the earlier message instead of appending. `make_engine` injects a no-op `summarizer` and a permit-all `guardrail`; pass `guardrail=` to script blocks. `conftest.classifier(category)` fakes the guardrail's `include_raw` output. `tests/test_observability.py` configures Logfire in-process with an in-memory exporter, so the rest of the session runs instrumented; nothing is sent without a token. API tests set `settings.dev_mode` via `monkeypatch`. Tests need Docker: `tests/conftest.py` starts one `mongo:7` test container per session and gives each test its own database. `SCREENING_TEST_DATABASE_URL` points the session at an existing MongoDB instead. Without either, every repository-backed test skips with a reason. An autouse fixture in conftest sets every secret and outbound Twilio setting to `None`, because settings also read `.env`. The `client` fixture is the API test client in dev mode. The `repository` fixture drops its database on teardown and the test container starts with `nofile=65536`. A run of `pymongo.errors.ServerSelectionTimeoutError` errors partway through the suite means mongod died; read `docker logs` for `Too many open files`.

Verify login changes in Docker with a throwaway `docker compose -f compose.yaml -f <override outside the repo>` that sets `SCREENING_DEV_MODE`, `SCREENING_SESSION_SECRET`, `SCREENING_PUBLIC_URL`, `SCREENING_RECRUITER_EMAIL_DOMAINS`. Do not edit `.env`.

## Code invariants

The README "Architecture" and "Key design decisions" sections describe the system. These are the rules that bite when editing and are not obvious from the README.

- Code owns the node graph and the tools, the LLM owns the turn. Validation rules live in Pydantic validators on `CandidateProfile`, never in prompts. Current stage is "first required field still missing."
- `flow/tools.py: tools_for` exposes tools for every missing field from the current stage onward. Gating is enforced again in `apply_tools`; a call to an unexposed tool re-asks and is not a candidate strike. Only validator rejections count toward `reask_limit`.
- `qualify_if_complete` in `flow/transitions.py` is the only place that sets `qualified`. It runs after every accepted patch.
- The model writes the candidate-facing text; code decides what it must say. Terminal statuses are fixed templates in `flow/replies.py`. For everything else `graph.py: _choose_reply` picks a fallback template plus a guidance line, and the `compose` node runs a second model call with the tool results and that guidance (the stage's tools stay bound because Anthropic rejects a history with tool_use blocks and no tools; any tool call it makes is ignored) (`llm/turn.py: GUIDANCE_*`). The compose call is skipped when the first-pass text is usable: all tools accepted, no confirmation pending, passes `flow/reply_policy.py: style_failures`. The template goes out only when the composed text is empty, breaks a style rule, misses the pending question (or asks one in the consent wait message) or the call fails; the turn record keeps the replaced draft in `model_text`. Evals grade `model_text` or a model-sourced reply, never the template.
- Consent is an explicit opt-in: `record_consent(decision)` with `agreed`, `declined`, `not_now`, `unclear`. Only `agreed` sets `consent`. `not_now` changes nothing. `unclear` counts as a rejected answer, so two unclear answers go to review. `request_stop` is exposed after consent and routes to `needs_recruiter_review` with `stop_requested`, which is what makes the opener's "you can stop whenever you want" true.
- Never an automated no on a judgement call. Anything ambiguous goes to `needs_recruiter_review`.
- Every channel calls `ScreeningEngine.handle(candidate_id, text, channel, external_id)`. When `HandleResult.terminal` is true the channel calls `engine.summarize_outcome` after replying, outside the lock. The graph passes the `TurnRecord` through a transient `turn` state key that the engine pops before saving; tone travels the same way.
- A turn is one conditional `update_one` on the candidate document, keyed on `version` and a `$ne` on the transcript external id. A stale version raises `StaleStateError` (`handle` re-runs once, the sweep skips); a lost dedupe race raises `DuplicateMessageError` from the write itself. No multi-document transactions.
- At most `settings.max_unanswered_agent_messages` agent messages go unanswered, and silence nudges do not count. `Repository._commit` enforces it for any outbound-only write through `_enforce_unanswered_limit` and raises `UnansweredLimitError`. Transcript entries carry `MessageKind` (`reply`, `opener`, `nudge`); a stored `out` entry without a kind counts. No current path can trip it.
- Rate limits and claims use a single atomic Mongo write (`find_one_and_update` with upsert, or an upsert that collides on `_id`), never count-then-insert.
- Never put an email, phone, candidate id, IP, message text or login link in a log line or an exception message. The root logger feeds Logfire, and Logfire never scrubs `logfire.msg`, `exception.message`, `exception.stacktrace` or URL attributes. Candidate ids are rewritten out of URL attributes twice: a span processor at `on_start` and the FastAPI `server_request_hook`. `configure_observability` resets `app.middleware_stack` because Starlette builds it before the lifespan runs; the no-PII test pins the processor order.
- Never build an emailed or redirect URL from the request `Host` header; take it from settings and fail closed (503) when unset outside dev mode (`deps.login_base_url`). `SCREENING_LOGIN_EMAIL_REDIRECT_TO` is honoured in dev mode only and answers 503 otherwise.
- Dates are judged in the candidate's calendar day: `domain/clock.py: candidate_today(zone)`.
- Model construction goes through `llm/models.py: chat_model(model_id)`. Provider keys come from settings (`PROJECT_ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `MISTRAL_API_KEY`; an org-level Anthropic key also needs `PROJECT_ANTHROPIC_WORKSPACE_ID`). Settings ignore empty env assignments. Never read `ANTHROPIC_API_KEY`; Claude Code in the same terminal uses that name.
- Recruiter login strings live in `recruiter/i18n.py: STRINGS`, one flat key set per locale (`es-MX`, `es-ES`, `en-US`). Authenticated pages stay English.
- Candidate-facing text: Spanish or English per message, informal tú, one question per message, 1 to 2 sentences, at most one emoji, ask rather than instruct and no "yes or no" tails. The opener is longer by design: it discloses the AI, the recording, who sees it and how to stop, then asks for agreement.

Layout: `screening_agent/{domain,flow,llm,channels,storage,api,recruiter}`, plus top-level `evals/` and `tests/`.
