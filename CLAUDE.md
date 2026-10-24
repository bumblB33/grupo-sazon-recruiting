# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Take-home case study for Orbio: an AI candidate-screening agent for Grupo Sazón (restaurant chain hiring delivery drivers in Spain and Mexico). The brief is `docs/Orbio-Assignment.md`. The process design is `docs/process-design.md` (Phase 1 deliverable). Read both before adding code.

## Current state

Scaffold stage. Decisions taken 23 Oct that override the outline where they differ:
- LangGraph owns the node graph. Channels (CLI, WhatsApp via Twilio, voice) are adapters. Pipecat is a voice adapter only, added on the voice day.
- Build order is core first: domain, graph, turn, CLI, storage, summary, minimal recruiter table, then browser voice, then evals and README.
- Layout is `screening_agent/` per the outline. The old `src/` tree is deleted.
- The design outline is private prep material and lives outside the repo. The shippable Phase 1 deliverable is `docs/process-design.md`.

Working: domain, flow, CLI, storage, API with key auth and webhook signature check, summary, flow and API tests. Stubs with TODO: `llm/guardrail.py`, `channels/whatsapp.py` outbound. Not started: model bake-off (`evals/`), recruiter UI, silence timers that set `abandoned`, Logfire. Service areas in `domain/service_areas.py` are fixture data keyed by bare city name, not the client's 45 locations.

## Commands

Interpreter is the local venv at `.venv` (Python 3.12). Dependencies are declared in `pyproject.toml`.

```bash
source .venv/bin/activate
pip install -e ".[dev]"
pytest                              # all tests, no LLM calls
pytest tests/test_flow.py::test_no_licence_is_hard_stop
ruff check . && ruff format .
screening-cli                       # chat loop against the graph, needs a provider API key
uvicorn screening_agent.api.app:app --reload
python -m evals.run_evals           # persona evals against the live model
```

Tests drive the graph with a scripted fake model (`tests/conftest.py`) that records bound tool names and model inputs. One scripted AI message is consumed per candidate message. Build a fresh `ai(...)` per turn: `add_messages` assigns an id to a message on first use, so replaying the same object replaces the earlier message instead of appending. Pass a no-op `summarizer` to `ScreeningEngine` in tests. API tests set `settings.dev_mode` via `monkeypatch`.

## Architecture

Governing decision: code owns the node graph and the tools, the LLM owns the turn.

- Screening is an explicit node graph in Python: stages, transitions, validators. Stage order is cheapest disqualifier first: consent, name, licence (hard stop), zone (hard stop), availability, schedule, experience, start date, outcome.
- Each node exposes only the tools for fields still missing. One LLM call per turn: it records data by calling a tool and its text goes to the candidate. Code validates tool args with Pydantic, advances the node, swaps the tool set. The LLM cannot skip a stage because the tool does not exist until code exposes it.
- `CandidateProfile` is the single Pydantic model. Current stage is "first required field still missing." Validation rules live in code, not prompts. `CandidateProfile.model_dump()` is the structured JSON output.
- Every channel calls `ScreeningEngine.handle(candidate_id, text, channel, external_id)` in `flow/engine.py`. It returns a `HandleResult` with outcome `replied`, `duplicate` or `closed` and a `terminal` flag. Inbound message, state and reply are saved in one transaction. A process-local lock serialises one candidate. When `terminal` is true the channel calls `engine.summarize_outcome(candidate_id)` after replying (FastAPI uses `BackgroundTasks`, CLI and evals call it inline), so the summary LLM call never delays the reply or holds the lock.
- Tool gating is enforced in `apply_tools`. Allowed tools are recomputed after each accepted call in the turn, so consent plus name in one message both land. A call to a tool still not exposed is rejected, re-asks the current stage, and is not counted as a candidate strike (model fault, not candidate fault). Only validator rejections count toward `reask_limit`.
- `qualify_if_complete` in `flow/transitions.py` is the only place that sets `qualified`. It runs after every accepted patch, so tool order within a turn does not matter.
- Replies for re-ask, zone confirmation and every terminal status are fixed templates in `flow/replies.py`, not model output. Priority: terminal, then re-ask, then zone confirm, then model text, then the next stage's question. The reply actually sent is appended to history as an AI message when it differs from the model's text.
- Graph per message: `turn` (one LLM call with the stage's tools bound) then `apply_tools` (validate, transition, pick reply). No checkpointer; `storage/repository.py` persists the full state as JSON.
- Never an automated no on a judgement call. Anything ambiguous goes to `needs_recruiter_review`.
- Dates are judged in the candidate's calendar day, not the server's. `domain/clock.py: candidate_today(zone)` uses the service area's IANA timezone, falling back to `SCREENING_DEFAULT_TIMEZONE`. The start-date validator and the prompt's "today" both use it.
- API auth fails closed. Recruiter routes need `SCREENING_RECRUITER_API_KEY`; the Twilio webhook needs `SCREENING_TWILIO_AUTH_TOKEN` (`X-Twilio-Signature`, HMAC-SHA1 over the webhook URL plus sorted form params, base64). Set `SCREENING_TWILIO_WEBHOOK_URL` when a proxy rewrites the URL Twilio signed. The webhook answers with TwiML, which is how the reply reaches the candidate. Without them the routes return 503 unless `SCREENING_DEV_MODE=true`.
- Stack: Pydantic, LangGraph, FastAPI, SQLite via SQLModel, Pydantic Logfire. Voice day adds Pipecat, Deepgram STT, ElevenLabs TTS. Primary LLM chosen by a scripted bake-off, not assumed.
- Terminal statuses: `qualified`, `disqualified` (objective criteria only, with reason code, recruiter can override), `needs_recruiter_review`, `abandoned`.

Layout: `screening_agent/{domain,flow,llm,channels,storage,api}`, plus top-level `evals/` and `tests/`. The recruiter UI gets its own package when it is built.

## Conventions

- Candidate-facing text: Spanish or English per message, informal tú, one question per message, 1-2 sentences, at most one emoji. Agent discloses it is an AI.
- Graders in `evals/` score the final JSON and outcome, not the transcript.
