# Project status

Moving state for the screening agent. The README describes the system as built. This file tracks what is done, what is missing, what is unverified and what is undecided. Update it when a gap closes or a question is answered.

## Built and tested

- Domain validators and `CandidateProfile`.
- LangGraph flow: tool gating, transitions, fixed replies, single qualify rule.
- CLI chat channel.
- MongoDB storage: one document per candidate, append-only events, database-level dedupe, version check across processes.
- FastAPI routes with magic-link sessions, per-client API keys and Twilio webhook signature check.
- Recruiter pages with filters, funnel and override. Invite-only login, session revocation on deactivate, confirm-button login links, CSRF on the override form.
- Post-outcome summary as a background task.
- Guardrail classifier that fails open.
- WhatsApp opener and nudges via Twilio REST.
- Silence sweep (`screening-nudge`) that nudges, then sets `abandoned`.
- Evals and bake-off runner.
- Tests with fakes for all of the above. The full suite, including the Mongo-backed tests, passes with no LLM calls.

## Not built

- Voice channel (Pipecat, Deepgram STT, ElevenLabs TTS) on the same engine.
- Logfire tracing.

## Remaining work, in order

1. Run the live bake-off with `--out docs`. It needs the three provider keys and a Mongo on `localhost:27017` (the compose `mongo` service does not publish a host port). It writes `docs/bakeoff.json` and `bakeoff.html`. The current files are from a failed run: both Anthropic models hit the missing `anthropic-workspace-id` header, and every OpenAI call errored. Only Mistral produced results, so they do not support a model choice.
2. Set the `Settings` defaults for `live_model`, `summary_model` and `guardrail_model` in `screening_agent/config.py` to the winners. The current defaults are placeholders.
3. Add a "Sample conversations" section to the README from the bake-off transcripts.
4. Build the voice channel.
5. Add Logfire tracing.

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
